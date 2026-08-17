from __future__ import annotations

import json
import argparse
import subprocess
import time
from pathlib import Path

import requests


BASE = "http://127.0.0.1:8787"
STATE = Path(r"D:\repository\state\e2e_music_video_belly_fresh_05")
SONG = Path(r"C:\Users\David Shambik\Downloads\Belly of the Beast.wav")
INITIAL = Path(r"D:\repository\state\e2e_music_video_belly_fresh_04\review_opening\opening_frame_fresh_04b.png")
ROVER = Path(r"D:\repository\state\e2e_music_video_belly_fresh_04\references\rover_anchor_fresh_01.png")

SHOTS = [
    (5, "INTRO: restrained opening at a hot concrete corner at night. Kairo and Mally stand low in deep shade, alert and silent, subtle heat haze and distant street atmosphere. No car yet, no weapon, no police action."),
    (10, "VERSE 1: Kairo and Mally observe the block while an ordinary dark tinted civilian Rover rolls slowly into the far background. Keep the car unmarked, blank plate, no logos, no police lights. Slow side-track, controlled tension."),
    (15, "VERSE 1: the civilian Rover passes the corner and Kairo follows it with his eyes while Mally scans the opposite direction. Long dreads and sunglasses remain consistent. Slow tracking movement, no confrontation."),
    (10, "VERSE 1 around 0:30: restrained close-up of Kairo's torso and hand moving beneath his shirt to grip concealed steel, never drawing or firing. Mally remains a blurred lookout in the background. No blood, no performance, deliberate realistic motion."),
    (15, "PRE-CHORUS: distant siren atmosphere makes both men look toward the end of the street. The civilian Rover continues away through wet amber light. No visible police vehicle and no blue lights yet; camera slowly arcs around the men."),
    (15, "CHORUS: wider west-side block montage inside one continuous I2V shot: Kairo and Mally move through separate layers of the concrete street, checking corners and keeping low, the neighborhood feels crowded and difficult. No dancing or singing, purposeful movement throughout."),
    (15, "VERSE 2: the ordinary civilian Rover pulls up and stops at the intersection; its tinted side window rolls down slightly, interior remains in deep shadow. Kairo and Mally hold position. Slow push toward the window, no police identity."),
    (15, "VERSE 2: sudden blue police lights flash from off-screen, reflecting on the civilian Rover and wet asphalt; the Rover accelerates away and leaves a short tire mark. The lights are environmental only; no police car enters frame. Fast but controlled pan."),
    (12, "VERSE 2 aftermath: the men remain alive and unhurt as the Rover disappears, Kairo releases the concealed grip and Mally watches the empty street. Handheld breathing space, blue reflections fade, no extra action."),
    (12, "BRIDGE: solemn close-up of Kairo's hands pouring white rum onto the street for the lost. Same wet concrete location, low light, realistic liquid and reflections, no bottle label or text, no singing or dancing."),
    (10, "FINAL CHORUS: Kairo and Mally walk the block with controlled resolve, checking the street and helping a frightened neighbor move behind a doorway. Story action only, no performance, vibrant teal and amber night cinematography."),
    (10, "FINAL CHORUS: the men hold the corner until the first gray morning light, long dreads moving in the breeze, empty civilian street after the Rover has gone. Slow pullback, resilient but restrained."),
    (10.67, "OUTRO: empty wet street and concrete corner at first light, distant tail lights vanish, the neighborhood settles after the night. Very slow locked-off hold, no text, no logos, no gibberish."),
]


def run_ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    token = session.get(f"{BASE}/api/session", timeout=30).json()["csrf_token"]
    headers = {"x-csrf-token": token}
    existing = sorted(STATE.glob("shot_*.mp4")) if args.resume else []
    completed_count = len(existing)
    previous = STATE / f"shot_{completed_count:02d}_last.jpg" if completed_count else INITIAL
    video_files: list[Path] = existing.copy()

    for index in range(completed_count + 1, len(SHOTS) + 1):
        duration, direction = SHOTS[index - 1]
        mp = 1.5 if duration == 5 else 1.0 if duration <= 8 else 0.7 if duration <= 10 else 0.5
        source = ROVER if index in {2, 3, 7, 8} else previous
        if not source.exists():
            raise FileNotFoundError(f"Missing I2V source for shot {index}: {source}")
        prompt = (
            "Professional cinematic Jamaican hip-hop/dancehall music video. "
            f"This is shot {index} of a continuous lyric-timed sequence. "
            f"{direction}. Duration target {duration:g} seconds at approximately {mp:.2f} MP. "
            "Use the input image as the exact starting frame and preserve continuity of faces, wardrobe, geography, "
            "and lighting only where appropriate; deliberately change framing, subject focus, camera movement, and "
            "composition so this shot does not look like a repeated portrait. Realistic motion, vibrant but gritty "
            "cinematic grade, 35mm lens language. I2V only, silent output. No singing, dancing, lip-sync, performance, "
            "readable text, logos, signs, labels, plates, or gibberish. The Rover is an ordinary unmarked civilian car, "
            "never a police car; use a blank featureless plate and preserve its geometry."
        )
        data = {
            "prompt": prompt,
            "mode": "opening",
            "duration": str(duration),
            "engine": "turbo",
            "steps": "6",
            "megapixels": str(mp),
            "aspect_ratio": "16:9",
            "encoder": "native",
            "turbo_profile": "v4",
            "no_audio": "true",
        }
        with source.open("rb") as image:
            response = session.post(
                f"{BASE}/api/jobs",
                headers=headers,
                data=data,
                files={"image": (source.name, image, "image/png" if source.suffix.lower() == ".png" else "image/jpeg")},
                timeout=60,
            )
        response.raise_for_status()
        job_id = response.json()["created"][0]
        print(json.dumps({"shot": index, "job": job_id, "duration": duration, "megapixels": mp, "source": str(source)}), flush=True)

        while True:
            jobs = session.get(f"{BASE}/api/jobs", timeout=30).json()["jobs"]
            job = next(item for item in jobs if item["id"] == job_id)
            print(json.dumps({"shot": index, "status": job["status"], "phase": job.get("phase"), "step": job.get("step"), "total": job.get("total_steps")}), flush=True)
            if job["status"] == "completed":
                break
            if job["status"] in {"failed", "canceled", "cancelled"}:
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
    run_ffmpeg("-i", str(silent), "-i", str(SONG), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "256k", "-t", "154.67", "-movflags", "+faststart", str(final))
    print(json.dumps({"complete": True, "silent": str(silent), "final": str(final)}), flush=True)


if __name__ == "__main__":
    main()
