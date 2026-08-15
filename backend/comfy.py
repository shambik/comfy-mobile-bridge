import asyncio
import ctypes
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import websockets

from .config import (COMFY_CODE, COMFY_HOST, COMFY_PORT, COMFY_PYTHON,
                     COMFY_URL, INPUT, LOGS, MODELS, OUTPUT, TEMP, USER)


class ComfyClient:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.log_handle = None

    async def ready(self) -> bool:
        try:
            # /object_info and /models can be very slow while custom nodes or
            # large H3 models are loading.  Health reporting must answer a
            # simple question: is the ComfyUI server responsive?
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(COMFY_URL + "/system_stats")
                response.raise_for_status()
            return True
        except Exception:
            return False

    async def ensure_started(self):
        if await self.ready():
            return
        if not COMFY_PYTHON.exists() or not (COMFY_CODE / "main.py").exists():
            raise RuntimeError("ComfyUI installation is missing")
        self.log_handle = open(LOGS / "comfy-8190.log", "a", encoding="utf-8", buffering=1)
        command = [
            str(COMFY_PYTHON), "-u", str(COMFY_CODE / "main.py"),
            "--listen", COMFY_HOST, "--port", str(COMFY_PORT),
            "--base-directory", str(COMFY_CODE),
            "--models-directory", str(MODELS),
            "--input-directory", str(INPUT),
            "--output-directory", str(OUTPUT),
            "--temp-directory", str(TEMP),
            "--user-directory", str(USER),
            "--database-url", "sqlite:///" + str((USER / "comfyui.db").resolve()).replace("\\", "/"),
            "--disable-auto-launch", "--disable-api-nodes",
            "--reserve-vram", "0.9", "--enable-dynamic-vram", "--async-offload", "2",
            "--preview-method", "none",
            "--log-stdout",
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        child_env = os.environ.copy()
        # ComfyUI custom nodes may emit Unicode (including emoji) while
        # loading. Windows can otherwise inherit the user's legacy code page
        # and crash the child while writing its own diagnostic log.
        child_env.setdefault("PYTHONUTF8", "1")
        child_env.setdefault("PYTHONIOENCODING", "utf-8")
        self.process = subprocess.Popen(
            command, cwd=COMFY_CODE, stdout=self.log_handle, stderr=subprocess.STDOUT,
            creationflags=flags, env=child_env,
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"ComfyUI 8190 exited with code {self.process.returncode}; see state/logs/comfy-8190.log")
            if await self.ready():
                return
            await asyncio.sleep(2)
        raise RuntimeError("ComfyUI 8190 did not become ready within 180 seconds")

    async def object_info(self):
        async with httpx.AsyncClient(timeout=30) as client:
            return (await client.get(COMFY_URL + "/object_info")).raise_for_status().json()

    async def submit(self, workflow: dict, client_id: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(COMFY_URL + "/prompt", json={"prompt": workflow, "client_id": client_id})
            if response.status_code >= 400:
                raise RuntimeError(f"ComfyUI rejected workflow: {response.text[:4000]}")
            payload = response.json()
            if payload.get("node_errors"):
                raise RuntimeError("Workflow validation failed: " + json.dumps(payload["node_errors"], ensure_ascii=False)[:4000])
            return payload["prompt_id"]

    async def history(self, prompt_id: str):
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{COMFY_URL}/history/{prompt_id}")
            response.raise_for_status()
            return response.json().get(prompt_id)

    async def monitor_progress(self, client_id: str, on_message, ready: asyncio.Event, stop: asyncio.Event):
        """Forward ComfyUI WebSocket execution events until the job is done."""
        parsed = urlsplit(COMFY_URL)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        websocket_url = urlunsplit((scheme, parsed.netloc, "/ws", f"clientId={quote(client_id)}", ""))

        while not stop.is_set():
            try:
                async with websockets.connect(
                    websocket_url,
                    open_timeout=10,
                    close_timeout=2,
                    ping_interval=20,
                    max_size=None,
                ) as socket:
                    ready.set()
                    while not stop.is_set():
                        receive_task = asyncio.create_task(socket.recv())
                        stop_task = asyncio.create_task(stop.wait())
                        done, pending = await asyncio.wait(
                            {receive_task, stop_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if stop_task in done:
                            receive_task.cancel()
                            await asyncio.gather(receive_task, return_exceptions=True)
                            return
                        stop_task.cancel()
                        await asyncio.gather(stop_task, return_exceptions=True)
                        raw = receive_task.result()
                        if isinstance(raw, bytes):
                            continue
                        try:
                            message = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await on_message(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                # History polling remains the completion fallback. Reconnect so
                # a short local WebSocket interruption does not lose progress.
                ready.set()

            if not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass

    async def queue(self):
        async with httpx.AsyncClient(timeout=20) as client:
            return (await client.get(COMFY_URL + "/queue")).raise_for_status().json()

    async def cancel(self, prompt_id: str | None):
        async with httpx.AsyncClient(timeout=20) as client:
            await client.post(COMFY_URL + "/interrupt")
            if prompt_id:
                await client.post(COMFY_URL + "/queue", json={"delete": [prompt_id]})

    async def free_models(self):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                await client.post(COMFY_URL + "/free", json={"unload_models": True, "free_memory": True})
        except Exception:
            pass

    async def shutdown(self):
        process = self.process
        self.process = None
        try:
            if process and process.poll() is None:
                if os.name == "nt":
                    # ComfyUI/custom nodes can create a child process that owns
                    # the HTTP listener.  Terminating only the tracked parent
                    # leaves that child alive and makes the next start attach
                    # to the wrong instance.  /T is scoped to this exact PID.
                    await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        timeout=20,
                        check=False,
                    )
                else:
                    process.terminate()
                    try:
                        await asyncio.to_thread(process.wait, 15)
                    except subprocess.TimeoutExpired:
                        process.kill()
            if process and process.poll() is None:
                await asyncio.to_thread(process.wait, 5)
        finally:
            if self.log_handle:
                self.log_handle.close()
                self.log_handle = None


def find_video(prefix: str) -> Path | None:
    candidates = sorted(OUTPUT.rglob(f"{prefix}*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def media_probe(path: Path, require_audio: bool = True) -> dict:
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        raise RuntimeError("ffprobe/ffmpeg are required for output validation")
    probe = subprocess.run([
        ffprobe, "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json", str(path),
    ], capture_output=True, text=True, timeout=60)
    if probe.returncode:
        raise RuntimeError("ffprobe failed: " + probe.stderr[-1000:])
    payload = json.loads(probe.stdout)
    streams = payload.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams):
        raise RuntimeError("Output has no video stream")
    if require_audio and not any(s.get("codec_type") == "audio" for s in streams):
        raise RuntimeError("Output has no audio stream")
    decode = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, timeout=300)
    if decode.returncode:
        raise RuntimeError("Full media decode failed: " + decode.stderr[-1500:])
    return payload


def gpu_sample() -> dict:
    try:
        result = subprocess.run([
            "nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ], capture_output=True, text=True, timeout=10)
        used, total, util, temp = [int(x.strip()) for x in result.stdout.strip().split(",")]
        sample = {"vram_used_mib": used, "vram_total_mib": total, "gpu_util_percent": util, "gpu_temp_c": temp}
        if os.name == "nt":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                            ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                            ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                            ("avail_extended", ctypes.c_ulonglong)]
            status = MemoryStatus(); status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                sample["ram_used_mib"] = round((status.total_phys - status.avail_phys) / 1024 / 1024)
                sample["ram_total_mib"] = round(status.total_phys / 1024 / 1024)
        return sample
    except Exception:
        return {}
