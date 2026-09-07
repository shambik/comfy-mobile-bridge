from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import requests


BASE = "http://127.0.0.1:8787"
ROOT = Path(r"D:\repository\state\productions\shadow_on_the_block_20260901")
OUTPUT = ROOT / "pilot_outputs"
ASSEMBLY = ROOT / "assembly"
SONG = Path(r"D:\Shadow On The Block.mp3")
SONG_DURATION = 157.44


# Every lip-sync job has a five-second raw window and a one-second lead-in.
# The visible duration is allowed to be shorter at an instrumental transition,
# but the generated window remains exactly five integer seconds.
JOBS = [
    ("P04", "6eaaf380e48d4a37b7c34de16d211683", 46, "lip"),
    ("P05", "b3c1b9130652482a8984c078e9263a93", 50, "lip"),
    ("P06", "3861f316f88c471ba9c569880ecb3c62", 54, "lip"),
    ("P07", "bbd6a03cbf1f471f9c272606a9fd80b7", 58, "lip"),
    ("P08", "d563f954bf46462b8682415b20dc1ca1", 62, "lip"),
    ("P09", "0ffa60b8cfc845b7b5a6e42c7397008d", 66, "lip"),
    ("P10", "0647dd02c4504350861b6175244e7d90", 70, "lip"),
    ("P11", "083b14ed2a464b9ba64e7f26cafda55a", 74, "lip"),
    ("P12", "bfc35b4d93ad42058db8962e31a90ccf", 78, "lip"),
    ("P13", "5106ce68b17944c6abc242b6aa9d2a83", 87, "regular"),
    ("P14", "8603f45ea86f403abb71d1b03d0ed8fe", 92, "regular"),
    ("P15", "642189947f884f2eacf5087900d6a74c", 94, "lip"),
    ("P16", "fe9062f0ab394558b0020b7d2c86db3f", 98, "lip"),
    ("P17", "1877d4ff4bf6463583020ed14fe33f2b", 102, "lip"),
    ("P18", "feddc4285a194aeb87d15e7d106d3df9", 106, "lip"),
    ("P19", "c1804cd331bd46508bf40115e98954ec", 110, "lip"),
    ("P20", "ff8550e4fd164fea96d259289d390dfc", 114, "lip"),
    ("P21", "81e2d5955fe84c1da63c35a4c28c4735", 118, "lip"),
    ("P22", "fe15e7732486439397ee7ef492f27082", 122, "lip"),
    ("P23", "00f7ca31545c4006b5bf8c35adce96d2", 126, "lip"),
    ("P24", "6837fd02b4bc485badd7c01725418cae", 130, "lip"),
    ("P25", "9573aaa6287f4afdaa9ad1334562b896", 134, "lip"),
    ("P26", "da56efbc8aac440c86092d8f2d3f349c", 138, "regular"),
    ("P27", "ffee19a8c3d645e883ee8b56787bea3d", 139, "lip"),
    ("P28", "fcfa7187b3d14816b9bebfffb9b5cd61", 143, "lip"),
    ("P29", "6d0a44f711c74879bf3bb926d8fd70cf", 147, "lip"),
    ("P30", "f108b4f215a149328da5699834d4a77b", 152, "regular"),
    ("P31", "c1f304889f404675a13d9cb1df9899e7", 0, "regular"),
    ("P32", "3aa694243970401888f1856a073a0c79", 5, "regular"),
    ("P33", "c36dada907b1475fa842dbb920c2c92f", 10, "regular"),
    ("P34", "4d075679078e428aa3d5d5fa85e7161c", 15, "regular"),
    ("P35", "1aa35aeac2e84d0f9d2801de0f0ecade", 20, "regular"),
    ("P36", "1cccfed8526540ed839d0cead7f9aa0d", 21, "lip"),
    ("P37", "d97e377674934088a1a4733a29ebeb27", 25, "lip"),
    ("P38", "d1095af2c2294ac68a61fdf55cd9e55d", 29, "lip"),
    ("P39", "7330c8a371674e33b37f77139f6ad13f", 33, "lip"),
]


# Final editorial order. Values are (shot id, raw trim offset, visible seconds).
# Raw trim offset is one for lip-sync and zero for silent instrumental shots.
EDIT = [
    ("P31", 0, 5), ("P32", 0, 5), ("P33", 0, 5), ("P34", 0, 5),
    ("P35", 0, 2), ("P36", 1, 4), ("P37", 1, 4), ("P38", 1, 4),
    ("P39", 1, 4), ("P01", 0, 5), ("P02", 1, 4), ("P04", 1, 4),
    ("P05", 1, 4), ("P06", 1, 4), ("P07", 1, 4), ("P08", 1, 4),
    ("P09", 1, 4), ("P10", 1, 4), ("P11", 1, 4), ("P12", 1, 3),
    ("P03", 0, 5), ("P13", 0, 5), ("P14", 0, 3), ("P15", 1, 4),
    ("P16", 1, 4), ("P17", 1, 4), ("P18", 1, 4), ("P19", 1, 4),
    ("P20", 1, 4), ("P21", 1, 4), ("P22", 1, 4), ("P23", 1, 4),
    ("P24", 1, 4), ("P25", 1, 3), ("P26", 0, 2), ("P27", 1, 4),
    ("P28", 1, 4), ("P29", 1, 4), ("P30", 0, 5),
]


def run_ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def raw_path(shot_id: str, start: int, kind: str) -> Path:
    suffix = "lipsync" if kind == "lip" else "regular_turbo_silent"
    return OUTPUT / f"shadow_on_the_block_{shot_id}_raw_{start}-{start + 5}_{suffix}.mp4"


def preview_path(shot_id: str, duration: int, kind: str, start: int) -> Path:
    end = start + duration
    suffix = "overlap1s" if kind == "lip" else "silent"
    return OUTPUT / f"shadow_on_the_block_{shot_id}_edit_{start}-{end}_{suffix}.mp4"


def make_preview(source: Path, destination: Path, trim: int, duration: int, with_audio: bool) -> None:
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    args = ["-ss", str(trim), "-i", str(source), "-t", str(duration), "-map", "0:v:0"]
    if with_audio:
        args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k", "-af", "aresample=async=1:first_pts=0"]
    else:
        args += ["-an"]
    args += ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination)]
    run_ffmpeg(*args)


def get_jobs(session: requests.Session) -> dict[str, dict]:
    response = session.get(f"{BASE}/api/jobs?limit=100&include_library=false&include_sequences=false", timeout=30)
    response.raise_for_status()
    return {item["id"]: item for item in response.json()["jobs"]}


def download_completed(session: requests.Session, shot_id: str, job_id: str, start: int, kind: str, job: dict) -> Path:
    destination = raw_path(shot_id, start, kind)
    if not destination.exists():
        response = session.get(f"{BASE}{job['video_url']}", timeout=300)
        response.raise_for_status()
        destination.write_bytes(response.content)
    return destination


def local_existing_raw(shot_id: str) -> Path | None:
    candidates = sorted(OUTPUT.glob(f"shadow_on_the_block_{shot_id}_raw_*.mp4"))
    if not candidates and shot_id == "P01":
        candidate = OUTPUT / "shadow_on_the_block_P01_38-43_regular_turbo_silent.mp4"
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def assemble(session: requests.Session, spec_by_id: dict[str, tuple[str, int, str]]) -> None:
    segment_dir = ASSEMBLY / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    assembly_rows: list[str] = []

    for index, (shot_id, trim, duration) in enumerate(EDIT, start=1):
        source = local_existing_raw(shot_id)
        if source is None and shot_id == "P01":
            source = OUTPUT / "shadow_on_the_block_P01_38-43_regular_turbo_silent.mp4"
        if source is None and shot_id == "P02":
            source = OUTPUT / "shadow_on_the_block_P02_raw_42-47_lipsync.mp4"
        if source is None and shot_id == "P03":
            source = OUTPUT / "shadow_on_the_block_P03_raw_82-87_regular_turbo_silent.mp4"
        if source is None or not source.exists():
            raise FileNotFoundError(f"Missing raw artifact for {shot_id}")

        segment = segment_dir / f"{index:02d}_{shot_id}_video_only.mp4"
        if not segment.exists():
            run_ffmpeg(
                "-ss", str(trim), "-i", str(source), "-t", str(duration),
                "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "fast",
                "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(segment),
            )
        segment_paths.append(segment)
        raw_start = spec_by_id.get(shot_id, (shot_id, 0, "regular"))[1]
        assembly_rows.append(f"{index:02d}. {shot_id}: raw trim {trim}s, visible {duration}s, source start {raw_start}s -> {segment.name}")

    concat = ASSEMBLY / "concat_video_only.txt"
    concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in segment_paths) + "\n", encoding="utf-8")
    silent = ASSEMBLY / "shadow_on_the_block_silent_timeline.mp4"
    if not silent.exists():
        run_ffmpeg(
            "-f", "concat", "-safe", "0", "-i", str(concat), "-an",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-r", "24", "-movflags", "+faststart", str(silent),
        )

    padded = ASSEMBLY / "shadow_on_the_block_silent_padded.mp4"
    if not padded.exists():
        run_ffmpeg(
            "-i", str(silent), "-vf", "tpad=stop_mode=clone:stop_duration=0.44",
            "-t", str(SONG_DURATION), "-an", "-c:v", "libx264", "-preset", "fast",
            "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(padded),
        )

    final = ASSEMBLY / "shadow_on_the_block_full_1.5mp_9x16.mp4"
    if not final.exists():
        run_ffmpeg(
            "-i", str(padded), "-i", str(SONG), "-map", "0:v:0", "-map", "1:a:0",
            "-t", str(SONG_DURATION), "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
            "-movflags", "+faststart", str(final),
        )

    (ASSEMBLY / "assembly_manifest_v001.md").write_text(
        "# Shadow On The Block — assembly manifest\n\n"
        "Whisper is the timing authority. Every lip-sync raw take is 5 integer seconds with a 1-second lead-in; regular instrumental generations are silent. The final master uses the original MP3 as the only audio track.\n\n"
        + "\n".join(assembly_rows) + "\n\n"
        f"Final master: `{final.name}`\nSong duration target: {SONG_DURATION:.2f}s\n",
        encoding="utf-8",
    )
    print(json.dumps({"complete": True, "final": str(final), "silent": str(silent), "segments": len(segment_paths)}), flush=True)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    ASSEMBLY.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.get(f"{BASE}/api/session", timeout=30).raise_for_status()
    spec_by_id = {shot_id: (kind, start, kind) for shot_id, _job, start, kind in JOBS}
    pending = {job_id: (shot_id, start, kind) for shot_id, job_id, start, kind in JOBS}
    last_status: dict[str, str] = {}

    while pending:
        jobs = get_jobs(session)
        finished: list[str] = []
        for job_id, (shot_id, start, kind) in pending.items():
            existing = local_existing_raw(shot_id)
            if existing is not None:
                finished.append(job_id)
                continue
            job = jobs.get(job_id)
            if job is None:
                print(json.dumps({"shot": shot_id, "status": "not_returned"}), flush=True)
                continue
            status = job.get("status", "unknown")
            marker = f"{status}:{job.get('phase')}:{job.get('step')}/{job.get('total_steps')}"
            if last_status.get(job_id) != marker:
                print(json.dumps({"shot": shot_id, "job": job_id, "status": status, "phase": job.get("phase"), "step": job.get("step"), "total": job.get("total_steps"), "eta": job.get("eta_seconds")}), flush=True)
                last_status[job_id] = marker
            if status == "completed":
                download_completed(session, shot_id, job_id, start, kind, job)
                finished.append(job_id)
            elif status in {"failed", "canceled", "cancelled"}:
                raise RuntimeError(f"{shot_id} ({job_id}) {status}: {job.get('error') or 'no error supplied'}")
        for job_id in finished:
            pending.pop(job_id, None)
        if pending:
            print(json.dumps({"remaining": len(pending), "completed_or_local": len(JOBS) - len(pending)}), flush=True)
            time.sleep(20)

    for shot_id, _trim, _duration in EDIT:
        source = local_existing_raw(shot_id)
        if source is None:
            raise FileNotFoundError(f"No raw source for {shot_id}")
        kind, start, _ = spec_by_id.get(shot_id, ("regular", 0, "regular"))
        duration = next(item[2] for item in EDIT if item[0] == shot_id)
        trim = next(item[1] for item in EDIT if item[0] == shot_id)
        make_preview(source, preview_path(shot_id, duration, kind, start + trim), trim, duration, kind == "lip")

    assemble(session, spec_by_id)


if __name__ == "__main__":
    main()
