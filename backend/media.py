from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .comfy import media_probe


def _duration(probe: dict) -> float:
    try:
        return float(probe.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        return 0.0


def _video_stream(probe: dict) -> dict:
    return next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"),
        {},
    )


def extract_last_frame(video: Path, target: Path, width: int, height: int) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to extract continuity frames")
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-sseof", "-0.20",
        "-i", str(video), "-frames:v", "1", "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-y", str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode or not target.exists():
        raise RuntimeError("Could not extract the last continuity frame: " + result.stderr[-1200:])
    return target


def assemble_clips(clips: list[Path], output: Path) -> dict:
    """Normalize and join validated H3 clips with deterministic hard cuts.

    The first selected clip defines the output frame size. Every input is
    decoded, normalized to 24fps/stereo 48kHz, and re-encoded so history items
    with different H3 resolution presets can still be joined safely.
    """
    if len(clips) < 2:
        raise ValueError("At least two clips are required for assembly")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for final assembly")

    probes = [media_probe(path, require_audio=False) for path in clips]
    durations = [_duration(probe) for probe in probes]
    first_stream = _video_stream(probes[0])
    width = int(first_stream.get("width") or 0)
    height = int(first_stream.get("height") or 0)
    if not all(durations) or width <= 0 or height <= 0:
        raise RuntimeError("Could not read all clip durations and dimensions for assembly")

    inputs: list[str] = []
    filters: list[str] = []
    has_any_audio = any(
        any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))
        for probe in probes
    )
    for index, (clip, duration) in enumerate(zip(clips, durations)):
        inputs += ["-i", str(clip)]
        filters.append(
            f"[{index}:v]fps=24,trim=duration={duration:.6f},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[v{index}]"
        )
        if has_any_audio:
            has_audio = any(stream.get("codec_type") == "audio" for stream in probes[index].get("streams", []))
            audio_source = f"[{index}:a]" if has_audio else f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.6f},"
            filters.append(
                f"{audio_source}aresample=48000,"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )

    if has_any_audio:
        concat_inputs = "".join(f"[v{index}][a{index}]" for index in range(len(clips)))
        filters.append(f"{concat_inputs}concat=n={len(clips)}:v=1:a=1[vout][aout]")
    else:
        concat_inputs = "".join(f"[v{index}]" for index in range(len(clips)))
        filters.append(f"{concat_inputs}concat=n={len(clips)}:v=1:a=0[vout]")

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-y", str(output),
    ]
    if has_any_audio:
        command[command.index("-movflags"):command.index("-movflags")] = ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    if result.returncode:
        raise RuntimeError("Final video assembly failed: " + result.stderr[-3000:])

    final_probe = media_probe(output, require_audio=False)
    return {
        "source_count": len(clips),
        "source_durations": durations,
        "output": str(output),
        "ffprobe": final_probe,
    }
