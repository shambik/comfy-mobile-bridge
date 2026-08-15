from __future__ import annotations

import argparse
import json
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    output = Path(manifest["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    client, headers = get_session(manifest["bridge"])
    previous = None
    completed = []
    for shot in manifest["shots"]:
        if shot["mode"] == "i2v":
            reference = shot.get("reference") or (str(previous) if previous else None)
            if not reference:
                raise ValueError(f"I2V shot {shot['id']} has no reference or previous frame")
            image = Path(reference)
        else:
            image = None
        job_id = submit(client, headers, manifest["bridge"], shot, image)
        job = wait_for(client, manifest["bridge"], job_id)
        video = output / f"{shot['id']}.mp4"
        video.write_bytes(client.get(f"{manifest['bridge']}{job['video_url']}", timeout=120).content)
        last = output / f"{shot['id']}_last.jpg"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-sseof", "-0.1", "-i", str(video), "-frames:v", "1", str(last)], check=True)
        previous = last
        completed.append({"shot": shot["id"], "job": job_id, "video": str(video), "last_frame": str(last)})
        (output / "state.json").write_text(json.dumps({"completed": completed}, indent=2), encoding="utf-8")
    print(json.dumps({"complete": True, "shots": completed}, indent=2))


if __name__ == "__main__":
    main()
