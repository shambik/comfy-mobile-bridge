from __future__ import annotations

import shutil
import subprocess
import json
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


def extract_review_frames(video: Path, target_dir: Path, fps: float = 1.0, limit: int = 48) -> list[Path]:
    """Extract a dense, bounded visual sample for agent quality review."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to extract review frames")
    target_dir.mkdir(parents=True, exist_ok=True)
    pattern = target_dir / "frame_%04d.jpg"
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-vf", f"fps={max(0.25, min(fps, 4.0))}", "-frames:v", str(limit),
        "-q:v", "2", "-y", str(pattern),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    frames = sorted(target_dir.glob("frame_*.jpg"))
    if result.returncode or not frames:
        raise RuntimeError("Could not extract review frames: " + result.stderr[-1200:])
    return frames


def prepare_audio_segment(source: Path, target: Path, start: float, duration: float) -> Path:
    """Create an exact, ComfyUI-readable WAV segment for a production shot.

    Production lip-sync uses a different song interval for each shot.  The
    generated clip may contain audio for Native AudioLock, but the final
    production soundtrack is still muxed separately from the original song.
    Padding makes a short source segment deterministic at the requested shot
    duration instead of allowing ffmpeg/ComfyUI to infer a different length.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to prepare production lip-sync audio")
    if not source.is_file():
        raise RuntimeError(f"Lip-sync audio source is missing: {source}")
    if start < 0 or duration < 0.5:
        raise ValueError("Lip-sync audio start must be non-negative and duration at least 0.5 seconds")
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.6f}", "-i", str(source),
            "-af", "apad", "-t", f"{duration:.6f}",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(target),
        ],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise RuntimeError("Could not prepare production lip-sync audio: " + result.stderr[-1200:])
    return target


def probe_audio_metadata(path: Path) -> dict:
    """Read basic audio metadata without asking an agent to run a shell command."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required for audio metadata")
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,sample_rate,channels,bit_rate",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError("ffprobe failed: " + result.stderr[-1000:])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe returned invalid audio metadata") from exc
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "audio"), None)
    if not stream:
        raise RuntimeError("The song has no audio stream")
    try:
        duration = float(payload.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration_seconds": duration,
        "size_bytes": int(payload.get("format", {}).get("size") or 0),
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "bit_rate": int(stream.get("bit_rate") or 0),
    }


def is_audio_only_media(path: Path) -> bool:
    """Return True when a media file has audio but no video stream."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.is_file():
        return False
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        return False
    try:
        streams = json.loads(result.stdout).get("streams", [])
    except json.JSONDecodeError:
        return False
    kinds = {str(stream.get("codec_type")) for stream in streams if isinstance(stream, dict)}
    return "audio" in kinds and "video" not in kinds


def prepare_agent_audio_carrier(source: Path, target: Path, duration_seconds: float | None = None) -> Path:
    """Wrap source audio in a tiny MP4 so multimodal agents can inspect it.

    The current AGY ``view_file`` transport terminates provider turns for
    audio-only WAV/MP3 files, while the same provider successfully decodes the
    audio track of an MP4.  Keep the original song untouched and create a
    deterministic black, one-frame-per-second visual carrier exclusively for
    analysis.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to prepare the AGY audio carrier")
    if not source.is_file():
        raise RuntimeError(f"Song source is missing: {source}")
    duration = float(duration_seconds or probe_audio_metadata(source)["duration_seconds"])
    if duration <= 0:
        raise RuntimeError("The source song has no valid duration")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=640x360:r=1",
            "-i", str(source), "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-t", f"{duration:.6f}", "-movflags", "+faststart", "-f", "mp4", str(temporary),
        ],
        capture_output=True, text=True, timeout=900,
    )
    if result.returncode or not temporary.exists() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Could not prepare the AGY audio carrier: " + result.stderr[-1200:])
    temporary.replace(target)
    return target


def attach_song(video: Path, song: Path, output: Path) -> dict:
    """Mux the original song over a silent assembled master."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to attach the song")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video), "-i", str(song),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
        "-shortest", "-movflags", "+faststart", "-y", str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    if result.returncode or not output.exists():
        raise RuntimeError("Could not attach the original song: " + result.stderr[-3000:])
    return {"output": str(output), "ffprobe": media_probe(output, require_audio=True)}


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
