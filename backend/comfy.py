import asyncio
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import websockets

from .config import (COMFY_CODE, COMFY_HOST, COMFY_PORT, COMFY_PYTHON,
                     COMFY_URL, INPUT, LOGS, MODELS, OUTPUT, TEMP, USER)


class ComfyCancellationError(RuntimeError):
    """Raised when ComfyUI still owns a prompt after cancellation was requested."""


class ComfyClient:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.log_handle = None
        self.last_command: list[str] | None = None

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

    async def system_stats(self) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(COMFY_URL + "/system_stats")
            response.raise_for_status()
            return response.json()

    def _git_metadata(self, root: Path | None = None) -> dict:
        root = root or COMFY_CODE
        result = {}
        for key, args in (
            ("commit", ["rev-parse", "HEAD"]),
            ("branch", ["symbolic-ref", "--short", "-q", "HEAD"]),
        ):
            try:
                value = subprocess.run(
                    ["git", "-C", str(root), *args],
                    capture_output=True, text=True, timeout=5, check=False,
                ).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                value = ""
            if value:
                result[key] = value
        try:
            result["dirty"] = bool(subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
        return result

    @staticmethod
    def _argv_value(argv: list[str], flag: str) -> str | None:
        try:
            index = argv.index(flag)
        except ValueError:
            return None
        return str(argv[index + 1]) if index + 1 < len(argv) else None

    @staticmethod
    def _runtime_root(argv: list[str]) -> Path:
        base_directory = ComfyClient._argv_value(argv, "--base-directory")
        if base_directory:
            return Path(base_directory).resolve()
        if argv:
            main_path = Path(str(argv[0]))
            if main_path.name.lower() == "main.py":
                return main_path.parent.resolve()
        return COMFY_CODE

    def _listening_pid(self) -> int | None:
        """Return the process owning the configured ComfyUI port on Windows."""
        if os.name != "nt":
            return None
        script = (
            f"Get-NetTCPConnection -LocalPort {COMFY_PORT} -State Listen "
            "-ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty OwningProcess"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=5, check=False,
            )
            for line in result.stdout.splitlines():
                if line.strip().isdigit():
                    return int(line.strip())
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        return None

    @staticmethod
    def _process_executable(pid: int | None) -> str | None:
        if os.name != "nt" or not pid:
            return None
        script = (
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}' "
            "-ErrorAction SilentlyContinue).ExecutablePath"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=5, check=False,
            )
            value = result.stdout.strip()
            return value or None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _runtime_matches_config(self, stats: dict) -> bool:
        system = stats.get("system") or {}
        argv = [str(item) for item in (system.get("argv") or [])]
        if self._runtime_root(argv) != COMFY_CODE.resolve():
            return False
        configured_models = MODELS.resolve()
        server_models = self._argv_value(argv, "--models-directory")
        if server_models and Path(server_models).resolve() != configured_models:
            return False
        pid = self.discovered_pid() or self._listening_pid()
        executable = self._process_executable(pid)
        if executable and Path(executable).resolve() != COMFY_PYTHON.resolve():
            return False
        return True

    async def runtime_metadata(self, stats: dict | None = None) -> dict:
        """Capture the exact ComfyUI runtime used by a generation.

        The server's own /system_stats argv is authoritative when ComfyUI was
        started outside the bridge. This prevents the card from claiming the
        configured interpreter when a stale process answered on the port.
        """
        try:
            payload = stats or await self.system_stats()
        except Exception as exc:
            return {"capture_error": str(exc), "captured_at": datetime.now(timezone.utc).isoformat()}
        system = payload.get("system") or {}
        pytorch = str(system.get("pytorch_version") or "")
        match = re.search(r"\+cu(\d+)", pytorch)
        cuda_digits = match.group(1) if match else ""
        cuda = f"{cuda_digits[:-1]}.{cuda_digits[-1]}" if len(cuda_digits) >= 3 else (cuda_digits or None)
        argv = system.get("argv") or self.last_command or []
        root = self._runtime_root([str(item) for item in argv])
        pid = self.discovered_pid() or self._listening_pid()
        executable = self._process_executable(pid)
        command_argv = [str(item) for item in argv]
        command_line = ([executable] + command_argv) if executable else command_argv
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "bridge": {"python": sys.executable, "pid": os.getpid()},
            "comfy": {
                "version": system.get("comfyui_version"),
                "commit": self._git_metadata(root),
                "root": str(root),
                "pid": pid,
                "python": executable or self._python_from_argv(argv) or str(COMFY_PYTHON),
                "python_version": system.get("python_version"),
                "pytorch": pytorch,
                "cuda": cuda,
                "host": COMFY_HOST,
                "port": COMFY_PORT,
                "argv": command_argv,
                "command_line": subprocess.list2cmdline(command_line) if command_line else None,
                "packages": system.get("comfy_package_versions") or [],
                "log_file": str(LOGS / "comfy-8190.log"),
                "paths": {
                    flag.lstrip("-").replace("-", "_"): self._argv_value(command_argv, flag)
                    for flag in ("--base-directory", "--models-directory", "--input-directory", "--output-directory", "--temp-directory", "--user-directory", "--database-url")
                    if self._argv_value(command_argv, flag)
                },
            },
            "devices": payload.get("devices") or [],
        }

    @staticmethod
    def _python_from_argv(argv: list[str]) -> str | None:
        if not argv:
            return None
        first = str(argv[0])
        return first if first.lower().endswith(("python.exe", "python")) else None

    def _windows_process_ids(self) -> list[int]:
        """Find ComfyUI processes even when this app lost its Popen handle."""
        if os.name != "nt":
            return []
        code = str(COMFY_CODE).replace("'", "''")
        script = (
            "$needle = '" + code + "\\main.py'; "
            "$port = '--port " + str(COMFY_PORT) + "'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -and "
            "$_.Name -match '^python(\.exe)?$' -and "
            "$_.CommandLine -like ('*' + $needle + '*') -and "
            "$_.CommandLine -like ('*' + $port + '*') } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=5, check=False,
            )
            return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return []

    def discovered_pid(self) -> int | None:
        if self.process and self.process.poll() is None:
            return self.process.pid
        pids = self._windows_process_ids()
        return pids[0] if pids else None

    async def ensure_started(self):
        if await self.ready():
            stats = await self.system_stats()
            if self._runtime_matches_config(stats):
                return
            actual_root = self._runtime_root([str(item) for item in (stats.get("system") or {}).get("argv", [])])
            raise RuntimeError(
                "ComfyUI is already responding on the configured port, but it is not the configured runtime: "
                f"{actual_root}. Stop that instance before starting {COMFY_CODE}."
            )
        if not COMFY_PYTHON.exists() or not (COMFY_CODE / "main.py").exists():
            raise RuntimeError("ComfyUI installation is missing")

        # The bridge can lose its Popen handle while a previous ComfyUI
        # process tree remains alive. Starting another instance then causes
        # port 8190 and ComfyUI's SQLite database to be locked. Remove only
        # stale processes matching this exact installation and port.
        if self._windows_process_ids():
            await self.shutdown()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if not self._windows_process_ids():
                    break
                await asyncio.sleep(0.5)

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
        self.last_command = command
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

    async def delete_queued(self, prompt_ids: list[str]):
        """Delete pending prompts without interrupting the GPU job."""
        ids = [str(prompt_id) for prompt_id in prompt_ids if prompt_id]
        if not ids:
            return
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(COMFY_URL + "/queue", json={"delete": ids})
            response.raise_for_status()

    @staticmethod
    def _queue_contains_prompt(payload: dict, prompt_id: str) -> bool:
        """Handle ComfyUI's tuple-shaped queue entries and newer dict entries."""
        for queue_name in ("queue_running", "queue_pending"):
            for item in payload.get(queue_name) or []:
                if isinstance(item, (list, tuple)) and len(item) > 1:
                    if str(item[1]) == prompt_id:
                        return True
                elif isinstance(item, dict) and str(item.get("prompt_id")) == prompt_id:
                    return True
        return False

    async def wait_for_prompt_clear(self, prompt_id: str, timeout: float = 20.0) -> bool:
        """Wait until a canceled prompt is absent from both ComfyUI queues.

        Interrupting a prompt is asynchronous.  In particular, a heavy model
        forward can remain in ``queue_running`` for several seconds after the
        interrupt request.  The bridge must not dequeue another job during
        that interval.  If the server has already gone away, the prompt
        cannot continue using the GPU and is therefore considered cleared.
        """
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                payload = await self.queue()
                last_error = None
                if not self._queue_contains_prompt(payload, prompt_id):
                    return True
            except Exception as exc:
                last_error = exc
                # A manually stopped or crashed ComfyUI cannot keep executing
                # the prompt.  Let the worker's restart gate recover it.
                if not await self.ready():
                    return True
            await asyncio.sleep(0.5)

        detail = f" ({last_error})" if last_error else ""
        raise ComfyCancellationError(
            f"ComfyUI did not clear canceled prompt {prompt_id} within {int(timeout)} seconds{detail}"
        )

    async def cancel(self, prompt_id: str | None):
        async with httpx.AsyncClient(timeout=20) as client:
            (await client.post(COMFY_URL + "/interrupt")).raise_for_status()
            if prompt_id:
                (await client.post(
                    COMFY_URL + "/queue", json={"delete": [prompt_id]}
                )).raise_for_status()
        if prompt_id:
            await self.wait_for_prompt_clear(prompt_id)

    async def free_models(self):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                await client.post(COMFY_URL + "/free", json={"unload_models": True, "free_memory": True})
        except Exception:
            pass

    async def shutdown(self):
        process = self.process
        self.process = None
        discovered = [] if process and process.poll() is None else self._windows_process_ids()
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
            elif discovered:
                # The app may have restarted while ComfyUI remained alive,
                # leaving no Popen handle. Kill only matching ComfyUI trees.
                for pid in discovered:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        timeout=20,
                        check=False,
                    )
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
