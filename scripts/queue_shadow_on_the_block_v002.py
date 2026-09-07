"""Queue the repaired Shadow On The Block shots through the local H3 bridge.

The script is deliberately small and explicit: Whisper-derived five-second
audio windows are uploaded as pretrimmed files, each lip-sync take receives a
one-second lead-in, and every submission gets an independently random seed.
It queues one shot by default so the resulting motion can be reviewed before
the remaining repairs are submitted.
"""

from __future__ import annotations

import argparse
import json
import secrets
import time
from pathlib import Path

import requests


BASE = "http://127.0.0.1:8787"
ROOT = Path(r"D:\repository\state\productions\shadow_on_the_block_20260901")
APPROVED = ROOT / "references" / "approved_opening_frames_v002"
AUDIO_DIR = ROOT / "analysis" / "whisper"


IDENTITY_LOCK = (
    "Preserve the exact established singer from the uploaded opening frame: a dark-skinned, muscular adult male, "
    "same face and proportions, short beard, vivid geometric neon face paint, extremely long blue-teal dreadlocks "
    "with the same silhouette, braid thickness and fluorescent beads, black neon rave styling, layered beads and "
    "triangle pendant, fluorescent arm wraps, and unmistakable saturated natural blue irises with normal black pupils, "
    "white sclera and realistic catchlights in every frame. The eyes must never become black, gray, glowing or "
    "cybernetic. No eye-color drift, hair drift, wardrobe drift, face drift or age drift."
)
REALISM_LOCK = (
    "Photorealistic live-action music-video footage with believable human biomechanics. Keep both feet grounded, "
    "preserve balance and weight transfer, use natural knee flexion, shoulder/chest rhythm and one or two restrained "
    "hand gestures that follow the beat. Hands, fingers, elbows, joints, fabric, hair and jewelry move with realistic "
    "inertia and contact; no rubber limbs, teleporting, frozen poses, repeated loops, body morphing, extra fingers or "
    "impossible choreography."
)
CAMERA_LOCK = (
    "The physical camera stays in the opening-frame position for the entire raw take. Allow only subtle handheld "
    "micro-vibration, breathing motion and tiny operator drift; no dolly, pan, tilt, zoom, orbit, reframe, lens jump, "
    "scene change or hidden cut."
)


SHOTS = {
    "P01": {
        "mode": "opening",
        "start": 38,
        "frame": "P01_instrumental_cypher_blue_eye_opening_v001.png",
        "prompt": (
            "P01 instrumental dance take in the cold concrete performance space. The singer is not singing: keep his "
            "mouth naturally closed and relaxed with no lip movement. He performs a restrained, beat-accurate groove "
            "in place, shifting weight once between the feet, bending the knees naturally and letting the shoulders "
            "and forearms follow the rhythm. A few distinct background ravers can move independently in soft focus. "
            "No microphone."
        ),
    },
    "P03": {
        "mode": "opening",
        "start": 82,
        "frame": "P03_rooftop_dance_blue_eye_opening_v001.png",
        "prompt": (
            "P03 instrumental rooftop cypher take. The singer does not sing: mouth closed and neutral, absolutely no "
            "lip-sync or talking. He dances with grounded, controlled footwork, a low knee bounce, relaxed shoulder "
            "groove and one clean arm accent on the beat; nearby ravers respond with different natural movements and "
            "do not clone his face, hair or outfit. No microphone."
        ),
    },
    "P09": {
        "mode": "lip_sync",
        "start": 66,
        "frame": "P09_warehouse_blue_eye_opening_v002.png",
        "audio": "audio_66_71_P09.wav",
        "prompt": (
            "P09 raw overlap performance in the wet warehouse. The true editorial cut is at raw second 1; the singer "
            "is already in a restrained performance groove at raw time zero, so do not restart his body or face at the "
            "cut. He delivers only the uploaded song vocal with precise natural lip-sync: clean consonants, jaw motion, "
            "vowel shaping and subtle facial emphasis. Use a controlled chest pulse, one small weight shift and one "
            "deliberate hand gesture, then settle. No microphone."
        ),
    },
    "P15": {
        "mode": "lip_sync",
        "start": 94,
        "frame": "P15_reflective_courtyard_blue_eye_opening_v001.png",
        "audio": "audio_94_99_P15.wav",
        "prompt": (
            "P15 raw overlap performance in the reflective courtyard. The true editorial cut is at raw second 1; "
            "begin already mid-groove. Perform only the uploaded song vocal with clean, restrained lip-sync and natural "
            "jaw, lips and eyes. Let the torso ride the rhythm, shift weight once and make one low, controlled hand "
            "gesture that respects the frame. No microphone and no exaggerated dancing."
        ),
    },
    "P19": {
        "mode": "lip_sync",
        "start": 110,
        "frame": "P19_storm_code_blue_eye_opening_v001.png",
        "audio": "audio_110_115_P19.wav",
        "prompt": (
            "P19 raw overlap performance in the storm-code warehouse. The true editorial cut is at raw second 1; "
            "the performer is already moving before the visible cut. He delivers only the uploaded song vocal with "
            "accurate rhythmic lip-sync, then punctuates the phrase with one controlled forward hand accent and a "
            "natural shoulder hit. Keep movement powerful but physically plausible, never frantic or rubbery. No microphone."
        ),
    },
    "P23": {
        "mode": "lip_sync",
        "start": 126,
        "frame": "P23_neon_crowd_blue_eye_opening_v001.png",
        "audio": "audio_126_131_P23.wav",
        "prompt": (
            "P23 raw overlap performance in the neon crowd. The true editorial cut is at raw second 1, so the singer "
            "must already be in motion and already be inside the vocal phrase at raw time zero. He delivers only the "
            "uploaded song vocal with exact natural lip-sync: realistic mouth shapes, consonants, vowels, jaw and "
            "facial timing. Use a grounded rhythmic bounce, a believable left-to-right weight transfer, subtle shoulder "
            "and chest pulses, and one controlled hand gesture toward the lens before settling. Background ravers move "
            "independently with varied realistic timing and never duplicate the singer. No microphone."
        ),
    },
    "P27": {
        "mode": "lip_sync",
        "start": 139,
        "frame": "P27_warm_outro_blue_eye_opening_v001.png",
        "audio": "audio_139_144_P27.wav",
        "prompt": (
            "P27 raw overlap performance in the warm amber exit space. The true editorial cut is at raw second 1; "
            "start in a living mid-performance pose, not a reset. Deliver only the uploaded song vocal with accurate "
            "natural lip-sync. Use a subtle grounded sway, one slow shoulder roll and a small open-palm gesture, then "
            "hold a believable breathing stance. No microphone, no frozen pose and no theatrical overacting."
        ),
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shot", choices=sorted(SHOTS), default="P23")
    parser.add_argument("--all", action="store_true", help="queue all seven repaired shots")
    parser.add_argument("--wait", action="store_true", help="wait for queued jobs and download completed videos")
    return parser.parse_args()


def submit(session: requests.Session, token: str, shot_id: str) -> str:
    spec = SHOTS[shot_id]
    frame = APPROVED / spec["frame"]
    if not frame.is_file():
        raise FileNotFoundError(frame)

    prompt = (
        "Professional photorealistic live-action rap music-video shot, expensive real cinematography, not an "
        "illustration, not a fashion still, no text, logos, watermark or border. "
        f"{IDENTITY_LOCK} {REALISM_LOCK} {CAMERA_LOCK} {spec['prompt']} "
        "Preserve realistic skin, facial detail, hair strands, beads, fabric, jewelry, lighting, reflections and "
        "physical contact. The uploaded opening frame is the identity and composition anchor; do not redesign it."
    )
    data = {
        "prompt": prompt,
        "mode": spec["mode"],
        "duration": "5",
        "engine": "turbo",
        "steps": "6",
        "megapixels": "1.5",
        "aspect_ratio": "9:16",
        "encoder": "native",
        "turbo_profile": "v4",
        "no_audio": "true" if spec["mode"] != "lip_sync" else "false",
        "seed": str(secrets.randbits(64)),
    }
    files: dict[str, tuple[str, object, str]] = {
        "image" if spec["mode"] != "lip_sync" else "first_frame": (
            frame.name,
            frame.open("rb"),
            "image/png",
        )
    }
    audio_handle = None
    if spec["mode"] == "lip_sync":
        audio_path = AUDIO_DIR / str(spec["audio"])
        if not audio_path.is_file():
            raise FileNotFoundError(audio_path)
        audio_handle = audio_path.open("rb")
        files["audio"] = (audio_path.name, audio_handle, "audio/wav")
        data.update(
            {
                "audio_start": "0",
                "audio_duration": "5",
                "audio_pretrimmed": "true",
                "audio_original_start": str(spec["start"]),
            }
        )
    try:
        response = session.post(
            f"{BASE}/api/jobs",
            headers={"X-CSRF-Token": token},
            data=data,
            files=files,
            timeout=90,
        )
        response.raise_for_status()
        job_id = response.json()["created"][0]
        print(
            json.dumps(
                {
                    "shot": shot_id,
                    "job": job_id,
                    "mode": spec["mode"],
                    "raw_window": f"{spec['start']}-{spec['start'] + 5}",
                    "editorial_trim": 1 if spec["mode"] == "lip_sync" else 0,
                    "duration": 5,
                    "megapixels": 1.5,
                    "aspect_ratio": "9:16",
                    "seed": data["seed"],
                    "frame": str(frame),
                }
            ),
            flush=True,
        )
        return job_id
    finally:
        for item in files.values():
            handle = item[1]
            if hasattr(handle, "close"):
                handle.close()
        if audio_handle and not audio_handle.closed:
            audio_handle.close()


def wait_for_jobs(session: requests.Session, jobs: dict[str, str]) -> None:
    downloaded = ROOT / "pilot_outputs" / "v002_raw"
    downloaded.mkdir(parents=True, exist_ok=True)
    pending = set(jobs.values())
    while pending:
        rows = session.get(f"{BASE}/api/jobs?limit=100&include_library=false&include_sequences=false", timeout=30).json()["jobs"]
        by_id = {row["id"]: row for row in rows}
        for shot_id, job_id in jobs.items():
            if job_id not in pending or job_id not in by_id:
                continue
            row = by_id[job_id]
            print(
                json.dumps(
                    {
                        "shot": shot_id,
                        "job": job_id,
                        "status": row.get("status"),
                        "phase": row.get("phase"),
                        "step": row.get("step"),
                        "total": row.get("total_steps"),
                    }
                ),
                flush=True,
            )
            if row.get("status") == "completed":
                response = session.get(f"{BASE}{row['video_url']}", timeout=300)
                response.raise_for_status()
                destination = downloaded / f"shadow_on_the_block_{shot_id}_P{shot_id[1:]}_raw_5s_v002.mp4"
                destination.write_bytes(response.content)
                print(json.dumps({"shot": shot_id, "downloaded": str(destination)}), flush=True)
                pending.remove(job_id)
            elif row.get("status") in {"failed", "canceled", "cancelled"}:
                raise RuntimeError(f"{shot_id} failed: {row.get('error') or row.get('status')}")
        if pending:
            time.sleep(15)


def main() -> None:
    args = parse_args()
    selected = sorted(SHOTS) if args.all else [args.shot]
    session = requests.Session()
    token = session.get(f"{BASE}/api/session", timeout=30).json()["csrf_token"]
    jobs = {shot_id: submit(session, token, shot_id) for shot_id in selected}
    if args.wait:
        wait_for_jobs(session, jobs)


if __name__ == "__main__":
    main()
