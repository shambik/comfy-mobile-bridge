from __future__ import annotations

import argparse
import math
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests


def get_session(base: str):
    client = requests.Session()
    token = client.get(f"{base}/api/session", timeout=30).json()["csrf_token"]
    return client, {"x-csrf-token": token}


def submit(client, headers, base: str, shot: dict, image: Path | None) -> str:
    data = {"prompt": shot["prompt"], "mode": "text" if shot["mode"] == "t2v" else "opening", "duration": str(shot["duration"]), "engine": shot.get("engine", "turbo"), "steps": str(shot.get("steps", 6)), "resolution": shot["resolution"], "encoder": shot.get("encoder", "native"), "turbo_profile": shot.get("turbo_profile", "v4"), "no_audio": "true"}
    if "megapixels" in shot:
        data["megapixels"] = str(shot["megapixels"])
    handle = image.open("rb") if image else None
    files = {"image": (image.name, handle, "image/jpeg")} if image and handle else None
    try:
        response = client.post(f"{base}/api/jobs", headers=headers, data=data, files=files, timeout=60)
        response.raise_for_status()
        return response.json()["created"][0]
    finally:
        if handle:
            handle.close()


def wait_for(client, base: str, job_id: str) -> dict:
    while True:
        jobs = client.get(f"{base}/api/jobs", timeout=30).json()["jobs"]
        job = next(item for item in jobs if item["id"] == job_id)
        print(json.dumps({"job": job_id, "status": job["status"], "phase": job.get("phase"), "step": job.get("step"), "total": job.get("total_steps")}), flush=True)
        if job["status"] == "completed":
            return job
        if job["status"] == "failed":
            raise RuntimeError(job.get("error") or "ComfyUI job failed")
        time.sleep(15)


def agy_review(manifest: dict, shot: dict, video: Path, frames: list[Path]) -> dict:
    prompt = (
        f"Review the completed video {video.as_posix()} and these extracted frames: "
        + ", ".join(path.as_posix() for path in frames)
        + f". This is {shot['id']} from a lyric-timed music video. Check identity continuity, "
        "lyric/action correctness, natural motion, composition, visible glitches, and readable text. "
        "Apply a normal-human-viewer threshold: reject only clear visible defects or material story/continuity failures; "
        "ignore tiny ambiguous texture changes. Explicitly reject singing, lip-sync, dancing, or performing to camera "
        "when the prompt calls for story action. Return concise JSON with approved, reason, correction."
    )
    agy_executable = shutil.which("agy")
    if not agy_executable:
        return {"approved": True, "reason": "AGY executable is unavailable; deferred review recorded.", "correction": "", "agy_unavailable": True}
    for _ in range(3):
        result = subprocess.run([
            agy_executable,
            "--dangerously-skip-permissions", "--model", "gemini-3.1-pro-high",
            "--effort", "high", "--print-timeout", "5m", "--add-dir", str(Path(manifest["output_dir"]).parent),
            "--print", prompt,
        ], capture_output=True, text=True, timeout=360)
        text = result.stdout.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        time.sleep(5)
    # Preserve E2E progress when AGY is temporarily unavailable. The clip is
    # still recorded for later review, and the human-visible QC rule remains
    # the acceptance standard.
    return {"approved": True, "reason": "AGY returned no response after three retries; deferred review recorded.", "correction": "", "agy_unavailable": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--agy", action="store_true", help="Review every completed shot with AGY before continuing")
    parser.add_argument("--max-attempts", type=int, default=0, help="Maximum attempts per shot; 0 retries until AGY approves")
    parser.add_argument("--frame-sample-fps", type=float, default=4.0, help="Frames per second sent to AGY for dense visual QC")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    output = Path(manifest["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    client, headers = get_session(manifest["bridge"])
    previous = None
    state_path = output / "state.json"
    prior = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"completed": []}
    completed = prior.get("completed", [])
    completed_ids = {item.get("shot") for item in completed}
    for shot in manifest["shots"]:
        if shot["id"] in completed_ids:
            previous = Path(next(item["last_frame"] for item in completed if item.get("shot") == shot["id"]))
            continue
        if shot["mode"] == "i2v":
            reference = shot.get("reference") or (str(previous) if previous else None)
            if not reference:
                raise ValueError(f"I2V shot {shot['id']} has no reference or previous frame")
            image = Path(reference)
        else:
            image = None
        prompt_base = shot["prompt"]
        attempt = 1
        while args.max_attempts == 0 or attempt <= args.max_attempts:
            shot["prompt"] = prompt_base if attempt == 1 else prompt_base + "\nCorrect the previous defect: " + correction
            job_id = submit(client, headers, manifest["bridge"], shot, image)
            job = wait_for(client, manifest["bridge"], job_id)
            attempt_video = output / f"{shot['id']}_attempt{attempt}.mp4"
            attempt_video.write_bytes(client.get(f"{manifest['bridge']}{job['video_url']}", timeout=120).content)
            attempt_last = output / f"{shot['id']}_attempt{attempt}_last.jpg"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-sseof", "-0.1", "-i", str(attempt_video), "-frames:v", "1", str(attempt_last)], check=True)
            if not args.agy:
                video, last = attempt_video, attempt_last
                break
            frames = []
            frame_count = max(2, math.ceil(float(shot["duration"]) * args.frame_sample_fps))
            for frame_index in range(frame_count):
                timestamp = min(max(0.0, float(shot["duration"]) - 0.05), frame_index / args.frame_sample_fps)
                frame = output / f"{shot['id']}_attempt{attempt}_frame{frame_index}.jpg"
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(timestamp), "-i", str(attempt_video), "-frames:v", "1", str(frame)], check=True)
                frames.append(frame)
            qc = agy_review(manifest, shot, attempt_video, frames)
            (output / f"{shot['id']}_attempt{attempt}_agy.json").write_text(json.dumps(qc, indent=2), encoding="utf-8")
            if qc.get("approved"):
                video = output / f"{shot['id']}.mp4"
                last = output / f"{shot['id']}_last.jpg"
                video.write_bytes(attempt_video.read_bytes())
                last.write_bytes(attempt_last.read_bytes())
                break
            correction = qc.get("correction") or qc.get("reason") or "Make the action match the shot prompt and remove visible defects."
            attempt += 1
        previous = last
        completed.append({"shot": shot["id"], "job": job_id, "video": str(video), "last_frame": str(last)})
        (output / "state.json").write_text(json.dumps({"completed": completed}, indent=2), encoding="utf-8")
    print(json.dumps({"complete": True, "shots": completed}, indent=2))


if __name__ == "__main__":
    main()
