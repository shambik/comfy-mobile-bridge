from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import requests


BASE = "http://127.0.0.1:8787"
STATE = Path(r"D:\repository\state\e2e_belly_of_the_beast")
SONG = Path(r"C:\Users\David Shambik\Downloads\Belly of the Beast.wav")
INITIAL = Path(r"C:\Users\David Shambik\.gemini\antigravity-cli\brain\6d1f99b8-97eb-43dc-9f14-75721d52b4d5\shot_rover_standoff_1786802504223.jpg")

SHOTS = [
    (10, "wide Kingston night establishing shot, dark tinted Rover entering a wet concrete street, two distinct Rastafari men in deep shadow, amber streetlights and teal shadows, slow lateral camera move"),
    (15, "Kofi alone walking beside shuttered shops and concrete walls, long dreadlocks and subtle sunglasses, low-angle side tracking shot, reveal the neighborhood and his controlled swagger"),
    (10, "tight lyrical tension insert: Kofi notices the dark Rover, eyes shift toward it, hand moves beneath his shirt and grips a concealed handgun without drawing it, restrained close-up, no firing"),
    (15, "Zion alone scanning the street from a different corner, navy windbreaker and long dreadlocks, over-the-shoulder view into traffic, handheld documentary movement, blue police reflections beginning"),
    (10, "the dark Rover passes close to camera, chrome and tinted glass catching red and amber light, Kofi reflected in the window, dynamic low tracking shot, aggressive chorus energy"),
    (15, "Kofi and Zion move in opposite directions through the block, wide composition with depth and silhouettes, pedestrians and Caribbean storefront details, rhythmic camera drift, never a static portrait"),
    (10, "Gaza Jay enters from a separate alley, distinct Jamaican man with shorter dreads, bright red-and-gold jacket and round sunglasses, confident solo introduction, whip-pan into a medium shot"),
    (15, "blue police lights flood the street, the Rover accelerates away and leaves wet tire marks, Kofi turns but does not chase, fast lateral camera movement followed by a wide aftermath"),
    (10, "bridge scene at the same block after the commotion: Kofi kneels and pours white rum onto the pavement for the lost, candlelight and smoke, intimate slow push-in, solemn expression"),
    (15, "final chorus dawn movement: Kofi leads the group through the neighborhood, distinct silhouettes, vibrant red, gold and green wardrobe accents, crane-like rise from street level to a wider view"),
    (10, "performance-style close-ups cut within one continuous shot: Kofi faces camera with calm authority, Zion crosses behind him, sun breaks over rooftops, strong lens flare and saturated dancehall color"),
    (15, "the characters separate into the waking neighborhood, Rover gone, empty street and long shadows, slow pullback revealing Kingston rooftops, resilient victorious mood"),
    (4.64, "instrumental tail: empty wet street at sunrise, fading red tail lights in the distance, reggae guitar atmosphere, slow locked-off hold and gentle light change"),
]


def run_ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    token = session.get(f"{BASE}/api/session", timeout=30).json()["csrf_token"]
    headers = {"x-csrf-token": token}
    previous = INITIAL
    video_files: list[Path] = []

    for index, (duration, direction) in enumerate(SHOTS, 1):
        mp = "0.7 MP" if duration == 10 else "0.5 MP"
        resolution = "1120x640" if duration == 10 else "960x544"
        prompt = (
            "Professional cinematic Jamaican hip-hop/dancehall music video. "
            f"This is shot {index} of a continuous lyric-timed sequence. "
            f"{direction}. Duration target {duration:g} seconds at approximately {mp}. "
            "Use the input image as the exact starting frame and preserve continuity of faces, wardrobe, geography, "
            "and lighting only where appropriate; deliberately change framing, subject focus, camera movement, and "
            "composition so this shot does not look like a repeated portrait. Realistic motion, vibrant but gritty "
            "cinematic grade, 35mm lens language, no text, no logos, no audio."
        )
        data = {
            "prompt": prompt,
            "mode": "opening",
            "duration": str(duration),
            "engine": "turbo",
            "steps": "6",
            "resolution": resolution,
            "encoder": "native",
            "turbo_profile": "v4",
            "no_audio": "true",
        }
        with previous.open("rb") as image:
            response = session.post(
                f"{BASE}/api/jobs",
                headers=headers,
                data=data,
                files={"image": (previous.name, image, "image/jpeg")},
                timeout=60,
            )
        response.raise_for_status()
        job_id = response.json()["created"][0]
        print(json.dumps({"shot": index, "job": job_id, "duration": duration, "resolution": resolution}), flush=True)

        while True:
            jobs = session.get(f"{BASE}/api/jobs", timeout=30).json()["jobs"]
            job = next(item for item in jobs if item["id"] == job_id)
            print(json.dumps({"shot": index, "status": job["status"], "phase": job.get("phase"), "step": job.get("step"), "total": job.get("total_steps")}), flush=True)
            if job["status"] == "completed":
                break
            if job["status"] == "failed":
                raise RuntimeError(job.get("error") or f"shot {index} failed")
            time.sleep(15)

        video = STATE / f"shot_{index:02d}.mp4"
        video.write_bytes(session.get(f"{BASE}{job['video_url']}", timeout=120).content)
        last_frame = STATE / f"shot_{index:02d}_last.jpg"
        run_ffmpeg("-sseof", "-0.1", "-i", str(video), "-frames:v", "1", str(last_frame))
        video_files.append(video)
        previous = last_frame

    concat = STATE / "concat.txt"
    concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in video_files) + "\n", encoding="utf-8")
    silent = STATE / "belly_of_the_beast_silent.mp4"
    final = STATE / "belly_of_the_beast_final.mp4"
    run_ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(silent))
    run_ffmpeg("-i", str(silent), "-i", str(SONG), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "256k", "-t", "154.64", "-movflags", "+faststart", str(final))
    print(json.dumps({"complete": True, "silent": str(silent), "final": str(final)}), flush=True)


if __name__ == "__main__":
    main()
