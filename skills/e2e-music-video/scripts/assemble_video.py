from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Concatenate approved silent clips and add the original song")
    parser.add_argument("song", type=Path)
    parser.add_argument("clips", nargs="+", type=Path)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1120)
    parser.add_argument("--height", type=int, default=640)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    normalized = args.output_dir / "normalized_clips"
    normalized.mkdir(exist_ok=True)
    normalized_clips = []
    for index, clip in enumerate(args.clips, 1):
        target = normalized / f"clip_{index:03d}.mp4"
        run(
            "-i", str(clip), "-map", "0:v:0", "-an",
            "-vf", f"scale={args.width}:{args.height}:force_original_aspect_ratio=decrease,pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
        )
        normalized_clips.append(target)
    concat = args.output_dir / "concat.txt"
    concat.write_text("\n".join(f"file '{clip.resolve().as_posix()}'" for clip in normalized_clips) + "\n", encoding="utf-8")
    silent = args.output_dir / "silent_master.mp4"
    final = args.output_dir / "final_music_video.mp4"
    run("-f", "concat", "-safe", "0", "-i", str(concat), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(silent))
    run("-i", str(silent), "-i", str(args.song), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "256k", "-t", str(args.duration), "-movflags", "+faststart", str(final))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(final)], check=True, capture_output=True, text=True)
    report = {"silent_master": str(silent), "final": str(final), "probe": json.loads(probe.stdout)}
    (args.output_dir / "technical_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
