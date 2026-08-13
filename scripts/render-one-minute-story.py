"""Render the six-shot local H3 story plan without touching the app queue.

This script intentionally renders one shot at a time. Each completed shot is
validated, its last frame is extracted into ComfyUI's input directory, and that
frame becomes the first-frame input for the next shot.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from backend.comfy import ComfyClient, find_video, media_probe
from backend.config import INPUT, OUTPUT, STATE
from backend.workflows import spectrum_workflow, standard_workflow, turbo_workflow


CONTINUITY = (
    "Continuity block: a young woman in her late twenties with short dark-brown hair, "
    "a mustard-yellow raincoat, dark trousers, and brown boots; one small cobalt-blue "
    "metal lantern with warm amber light; the same old glass greenhouse after rain, "
    "wet stone, fogged glass, green plants, pale blue evening sky; cinematic "
    "naturalistic look, soft handheld camera, realistic motion, no cuts inside the shot, "
    "no other people, no text, no logos, preserve the same face, clothing, lantern, "
    "table, and greenhouse layout. Ambient natural sound only. "
)

SHOT_ACTIONS = [
    "At blue hour she pushes open the greenhouse door and steps inside holding the unlit lantern. Rain beads on the glass. The camera follows from behind and eases to her left side. She stops beside a wooden potting table and looks at the dark plants. Door creak and soft footsteps.",
    "She places the lantern on the wet wooden table and lights it. The warm glow reveals one small wilted seedling in a clay pot. She gently turns the pot toward the light and studies it. Keep the camera close and slow.",
    "She takes a small metal watering can from the table and gives the seedling one careful pour. Water drops sparkle in the lantern light and the leaves lift slightly. The lantern stays in the same place while the camera makes one slow push-in.",
    "The seedling slowly straightens and produces one fresh green leaf while the woman watches without moving her hands. She leans closer with a small surprised smile. Keep the growth subtle and believable, with no fast time-lapse and no new plants suddenly appearing.",
    "She lifts the lantern and walks three slow steps along the greenhouse path. Warm light travels across wet leaves and fogged glass while the camera tracks beside her. She turns back toward the small pot, which remains visible behind her. Footsteps and a soft wind rise gently.",
    "She returns the lantern beside the pot and opens the greenhouse door. Pale morning light enters, revealing the same seedling with one healthy leaf. She looks back at it, smiles, and leaves the door slightly open as rain stops. End on the lantern and seedling glowing together, with soft birds replacing the rain.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("turbo", "standard", "spectrum"), default="turbo")
    parser.add_argument("--encoder", choices=("native", "clipproj"), default="native")
    parser.add_argument("--steps", type=int, help="Override the engine default for every shot")
    parser.add_argument("--shots", type=int, choices=range(1, 7), default=6)
    parser.add_argument("--duration", type=int, choices=(5, 10), default=10)
    parser.add_argument("--width", type=int, default=736)
    parser.add_argument("--height", type=int, default=416)
    parser.add_argument("--seed", type=int, default=184731)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--no-assemble", action="store_true")
    return parser.parse_args()


def default_steps(engine: str) -> int:
    return {"turbo": 4, "standard": 20, "spectrum": 16}[engine]


def required_nodes(engine: str, encoder: str) -> set[str]:
    nodes = {"UNETLoader", "VAELoader", "MiniMaxH3ImageToVideo", "CreateVideo", "SaveVideo"}
    nodes.add("ClipProjLoader" if encoder == "clipproj" else "CLIPLoader")
    if engine == "turbo":
        nodes |= {"MiniMaxH3TurboLoRA", "MiniMaxH3TurboSampler"}
    else:
        nodes.add("KSamplerSelect")
    if engine == "spectrum":
        nodes |= {"MiniMaxH3SigmaShift", "SpectrumApplyMiniMaxH3"}
    return nodes


def build_workflow(args: argparse.Namespace, prompt: str, seed: int, prefix: str, first_frame: str | None):
    steps = args.steps or default_steps(args.engine)
    builder = {"turbo": turbo_workflow, "standard": standard_workflow, "spectrum": spectrum_workflow}[args.engine]
    return builder(
        prompt,
        args.duration,
        seed,
        prefix,
        first_frame_name=first_frame,
        steps=steps,
        width=args.width,
        height=args.height,
        encoder=args.encoder,
    )


def stream_duration(probe: dict) -> float:
    try:
        return float(probe.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        return 0.0


def extract_last_frame(video: Path, target: Path, width: int, height: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to extract continuity frames")
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-sseof", "-0.20", "-i", str(video),
        "-frames:v", "1", "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-y", str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode or not target.exists():
        raise RuntimeError("Could not extract the last continuity frame: " + result.stderr[-1200:])


def safe_copy(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


async def wait_for_result(client: ComfyClient, workflow: dict, label: str) -> tuple[Path, dict, dict]:
    client_id = str(uuid.uuid4())
    websocket_ready = asyncio.Event()
    stop = asyncio.Event()
    prompt_id: str | None = None
    last_progress = -1

    async def on_message(message: dict):
        nonlocal last_progress
        data = message.get("data") or {}
        if not prompt_id or data.get("prompt_id") != prompt_id:
            return
        if message.get("type") == "progress":
            try:
                value = int(float(data.get("value", 0)))
                total = int(float(data.get("max", 0)))
            except (TypeError, ValueError):
                return
            if total and value != last_progress:
                last_progress = value
                print(f"[{label}] sampling {value}/{total}", flush=True)

    monitor = asyncio.create_task(client.monitor_progress(client_id, on_message, websocket_ready, stop))
    try:
        try:
            await asyncio.wait_for(websocket_ready.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        prompt_id = await client.submit(workflow, client_id)
        started = time.monotonic()
        while True:
            history = await client.history(prompt_id)
            if history:
                status = history.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError("ComfyUI execution error: " + json.dumps(status.get("messages", [])[-2:], ensure_ascii=False)[:6000])
                if status.get("completed"):
                    break
            elapsed = round(time.monotonic() - started)
            print(f"[{label}] waiting ({elapsed}s)", flush=True)
            await asyncio.sleep(5)
        return prompt_id, history, {"seconds": round(time.monotonic() - started, 1)}
    finally:
        stop.set()
        try:
            await asyncio.wait_for(monitor, timeout=3)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)


def assemble(clips: list[Path], output: Path) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for final assembly")
    durations = []
    for clip in clips:
        probe = media_probe(clip)
        durations.append(stream_duration(probe))
    if not all(durations):
        raise RuntimeError("Could not read all clip durations for assembly")

    inputs: list[str] = []
    filters: list[str] = []
    for index, (clip, duration) in enumerate(zip(clips, durations)):
        inputs += ["-i", str(clip)]
        filters.append(
            f"[{index}:v]fps=24,trim=duration={duration:.6f},settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[v{index}]"
        )
        filters.append(
            f"[{index}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{index}]"
        )

    concat_inputs = "".join(f"[v{index}][a{index}]" for index in range(len(clips)))
    filters.append(f"{concat_inputs}concat=n={len(clips)}:v=1:a=1[vout][aout]")

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-y", str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode:
        raise RuntimeError("Final xfade assembly failed: " + result.stderr[-3000:])
    final_probe = media_probe(output)
    return {"durations": durations, "output": str(output), "probe": final_probe}


async def render(args: argparse.Namespace) -> int:
    if args.width != 736 or args.height != 416:
        print("Warning: the validated long-form profile is 736x416", flush=True)
    steps = args.steps or default_steps(args.engine)
    if args.engine == "turbo" and not 4 <= steps <= 12:
        raise ValueError("Turbo steps must be between 4 and 12")
    if args.engine != "turbo" and not 8 <= steps <= 30:
        raise ValueError(f"{args.engine.capitalize()} steps must be between 8 and 30")

    run_id = args.run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    run_dir = STATE / "long-form" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = run_dir / "manifest.json"
    client = ComfyClient()
    await client.ensure_started()
    info = await client.object_info()
    missing = sorted(required_nodes(args.engine, args.encoder) - set(info))
    if missing:
        raise RuntimeError("8190 is missing node classes: " + ", ".join(missing) + ". Restart 8190 after installing Spectrum.")

    continuity_frame: str | None = None
    clips: list[Path] = []
    records = []
    for shot_number in range(1, args.shots + 1):
        prompt = CONTINUITY + SHOT_ACTIONS[shot_number - 1]
        seed = args.seed + shot_number - 1
        prefix = f"h3_story_{run_id}_shot{shot_number:02d}"
        print(f"\n=== Shot {shot_number}/{args.shots} | {args.engine} | {args.encoder} | {steps} steps ===", flush=True)
        workflow = build_workflow(args, prompt, seed, prefix, continuity_frame)
        prompt_id, history, timing = await wait_for_result(client, workflow, f"shot {shot_number}")
        video = find_video(prefix)
        if not video:
            raise RuntimeError(f"Shot {shot_number} completed but no MP4 matched {prefix}")
        probe = media_probe(video)
        local_clip = safe_copy(video, run_dir / f"shot-{shot_number:02d}.mp4")
        frame_path = INPUT / f"{run_id}_shot{shot_number:02d}_last.png"
        extract_last_frame(video, frame_path, args.width, args.height)
        continuity_frame = frame_path.name
        clips.append(local_clip)
        records.append({
            "shot": shot_number,
            "prompt_id": prompt_id,
            "seed": seed,
            "engine": args.engine,
            "encoder": args.encoder,
            "steps": steps,
            "source_output": str(video),
            "clip": str(local_clip),
            "last_frame": str(frame_path),
            "generation": timing,
            "probe": probe,
            "history_status": history.get("status", {}),
        })
        manifest_path.write_text(json.dumps({"run_id": run_id, "records": records}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[shot {shot_number}] validated: {local_clip}", flush=True)

    assembly = None
    if not args.no_assemble and len(clips) > 1:
        print("\n=== Assembling final video ===", flush=True)
        assembly = assemble(clips, run_dir / "the-blue-lantern-final.mp4")
        print(f"Final validated video: {assembly['output']}", flush=True)
    manifest_path.write_text(json.dumps({"run_id": run_id, "records": records, "assembly": assembly}, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(render(parse_args())))
    except KeyboardInterrupt:
        raise SystemExit(130)
