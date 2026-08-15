from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path)
    parser.add_argument("--frames", type=Path)
    args = parser.parse_args()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(args.media)], check=True, capture_output=True, text=True)
    info = json.loads(probe.stdout)
    output = {"path": str(args.media), "probe": info}
    if args.frames:
        args.frames.mkdir(parents=True, exist_ok=True)
        duration = float(info.get("format", {}).get("duration", 0) or 0)
        files = []
        for label, seconds in (("first", 0.05), ("middle", max(0.05, duration / 2)), ("last", max(0.05, duration - 0.1))):
            target = args.frames / f"{args.media.stem}_{label}.jpg"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(seconds), "-i", str(args.media), "-frames:v", "1", str(target)], check=True)
            files.append(str(target))
        output["frames"] = files
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
