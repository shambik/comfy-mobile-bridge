"""Generate Fluffies Scooter Race opening frames using OpenAI Codex image_gen.

Executes Codex in focused batches (Batch 1: S01-S05, Batch 2: S06-S10, Batch 3: S11-S13)
with `mcp_servers.runpod.enabled=false`. Copies results directly to
`state/fluffies_ep04_scooter_race/frames/<ID>.png`.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EP_DIR = ROOT / 'state' / 'fluffies_ep04_scooter_race'
FRAMES_DIR = EP_DIR / 'frames'
FRAMES_DIR.mkdir(parents=True, exist_ok=True)
CODEX_CMD = r"C:\Users\David Shambik\AppData\Roaming\npm\codex.cmd"
CODEX_HOME = Path.home() / ".codex"
GEN_DIR = CODEX_HOME / "generated_images"

BATCHES = {
    1: ['S01', 'S02', 'S03', 'S04', 'S05'],
    2: ['S06', 'S07', 'S08', 'S09', 'S10'],
    3: ['S11', 'S12', 'S13']
}


def run_batch(batch_num: int):
    shot_ids = BATCHES[batch_num]
    print(f"\n=======================================================")
    print(f"Starting Codex Image Generation - Batch {batch_num}: {shot_ids}")
    print(f"=======================================================")

    prompt = f"""You are the production artist for Fluffies — The Big Scooter Race.
Read D:/repository/state/fluffies_ep04_scooter_race/manifest.json.
Your task is to generate the 16:9 cinematic landscape opening frames for these exact shots: {', '.join(shot_ids)}.

For EACH shot in {shot_ids}:
1. Inspect the shot specification from manifest.json (`shot.image_prompt`, `shot.cast`, `shot.emotion`).
2. Add this strict instruction to the prompt:
   "Reference images supply character, prop, and vehicle identity ONLY. Create ONE finished cinematic 16:9 landscape film still caught DURING motion as described. Show ONLY the characters listed for this shot, no duplicates, no extra characters, no text, no watermarks."
3. Use your built-in `image_gen` tool to generate the still.
   Pass these exact reference image paths appropriate to the shot's cast:
   - Always include: D:/repository/state/fluffies_ep04_scooter_race/refs/vehicles-sheet.png
   - If Bobo, Lulu, or Zuzu: D:/repository/state/fluffies_ep04_scooter_race/refs/blue-pink-purple-lineup-v1.png
   - If Pebble or Numi: D:/repository/state/fluffies_ep04_scooter_race/refs/white-charcoal-lineup-v2.png
   - If Bobo & Lulu together: D:/repository/state/fluffies_ep04_scooter_race/refs/selected-opener-cast.png
4. Copy the generated image from your session output directly to:
   D:/repository/state/fluffies_ep04_scooter_race/frames/<ID>.png
   (so for example {shot_ids[0]}.png, etc.)

Do not touch any running ComfyUI or video processes.
Proceed through all shots in {shot_ids} in order now.
"""

    cmd = [
        CODEX_CMD,
        "exec",
        "-c", "mcp_servers.runpod.enabled=false",
        "-c", "model_reasoning_effort=\"low\"",
        "--sandbox", "danger-full-access",
        "--skip-git-repo-check",
        "-"
    ]

    log_file = EP_DIR / f"codex_batch{batch_num}.log"
    print(f"Executing Codex (log: {log_file})...")

    with log_file.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8"
        )
        stdout, _ = proc.communicate(input=prompt)
        log.write(stdout or "")
        print(stdout)

    print(f"Batch {batch_num} completed with exit code {proc.returncode}")

    # Check which frames exist
    for sid in shot_ids:
        dest = FRAMES_DIR / f"{sid}.png"
        if dest.exists():
            print(f"  [OK] {sid}.png exists ({dest.stat().st_size} bytes)")
        else:
            print(f"  [MISSING] {sid}.png MISSING!")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=int, choices=[1, 2, 3], help="Run specific batch (1, 2, or 3)")
    args = parser.parse_args()

    if args.batch:
        run_batch(args.batch)
    else:
        for b in [1, 2, 3]:
            run_batch(b)
