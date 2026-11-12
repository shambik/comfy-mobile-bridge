"""Character swap: replace people in a finished job or an uploaded video with characters from a library (#46).

Engines:
- Viggle Remake (default), any length. The clip is rendered in ~5 s windows (up to 124 frames); each window opens
  with the previous window's last 17 frames locked (Remake Prefix), so the joins are seamless. Up to 4 windows run
  in one job (~18 s, measured 2026-11-09: 34 min, 9.5 GB); longer clips run as a chain of such jobs, each opening
  with the previous job's last frames, and a final job joins them with the source sound (one job must keep all its
  frames in RAM, so a single job for a long clip would not fit).
- akatz Character Swap V1.5: one person per render; its own graph loops 124-frame windows over the clip (up to its
  own 149 s limit). It finds the person by the description on every frame, so when they leave the shot it can
  pick someone else who matches (2026-11-09 stage clip): the sheet says so, nothing stops it (user, 2026-11-09).
- Openjutsu (D3voz, issue #58): 1-3 people per render, from the character pictures alone; SAM 3.1 + a Qwen3-VL 8B
  describer find the person per 6 s piece, H3 redraws only their mask from a grey mannequin. Pieces without them keep
  the source (bridge patch); an optional hair eraser for characters whose hair differs. Tested up to 15.1 s at
  480p and 736p (backend/openjutsu.py).

The flow:
1. create   - a finished job's video or an upload is converted to 24 fps; hard cuts are found (issue #43 rule,
              isolated jumps only); the clip is split into parts = one shot inside one ~5 s window, one frame each.
2. marks    - the user taps people on a part's frame, picks a character and describes who it is; later parts of the
              same shot carry those marks over unless the user marks them again or says nobody is there. No AI
              picks or describes people (user, 2026-11-09).
3. mode "reference" - the character images are Viggle's references (no pins).
   mode "painted"   - every part with someone to swap gets a painted frame (the user's own, or Codex's), pinned at
              that part's key frame.
4. render   - swap jobs (engine "swap") queued like any other job; the worker runs their graph and moves long
              clips from one job to the next (follow()).

Settings are the ones the user chose after the A/B on 2026-11-09 (1 MP, int8 attention, default keyframe hold).
"""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import openjutsu
from . import codex_guard
from .config import CODEX_COMMAND, CODEX_GENERATED_IMAGES, COMFY_CODE, INPUT, STATE

SWAPS = STATE / "swaps"
CHARACTERS = STATE / "characters"
CHARACTERS_FILE = CHARACTERS / "characters.json"
VIGGLE_MODEL = "viggle_remake_swap_pruned_int8_convrot.safetensors"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
MAX_FRAMES, MIN_FRAMES = 124, 90          # one window at 1 MP on the 10 GB card; Viggle's minimum
SHORT_EDGE = 736                           # ~1 MP (1280x736 / 736x1280)
CODEX_MODEL, CODEX_EFFORT = "gpt-6-luna", "medium"   # used only when the app has no Codex agent settings
CODEX_TIMEOUT = 1800
MAX_PEOPLE = 4                             # tested: 1-4 people in one render
SEGMENT_WINDOWS = 4                        # windows per job: 4 = ~18 s, ran in 34 min at 9.5 GB (2026-11-09)
AKATZ_MAX_SECONDS = 149                    # H3 Relay's PrepareSource limit (149.66 s)
LOCK = 17                                  # Remake Prefix: frames of the previous window that open the next one
ENGINES = ("viggle", "akatz", "openjutsu")
# akatz's own API graph ships with the H3 Relay node pack (GPL-3.0), so it is read from there, not copied here
AKATZ_GRAPH = COMFY_CODE / "custom_nodes" / "h3-relay" / "example_workflows" / "toolkit" / "H3-Character-Swap.api.json"
AKATZ_MODEL = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
VIDEO_VAE, AUDIO_VAE = "minimax_h3_video_vae_fp16.safetensors", "minimax_h3_audio_vae_fp32.safetensors"
# Viggle Remake's sampling schedule (6 steps) and keyframe hold, as in its official ComfyUI graph
VIGGLE_SIGMAS = "1.0, 0.990476, 0.965243, 0.923077, 0.8, 0.631579, 0.0"


def viggle_base_graph() -> dict:
    """The Viggle Remake swap graph (nodes 1-20): the int8 swap model, the source video and two pictures into
    RemakeConditioning, Viggle's noise and 6-step schedule, decode and save. Built here; every value the swap sets is
    overwritten per job."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": VIGGLE_MODEL, "weight_dtype": "default"}},
        "3": {"class_type": "RemakeKeyframeUntil", "inputs": {"model": ["1", 0], "keyframe_until": 0.9}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "7": {"class_type": "LoadVideo", "inputs": {"file": ""}},
        "8": {"class_type": "GetVideoComponents", "inputs": {"video": ["7", 0]}},
        "9": {"class_type": "LoadImage", "inputs": {"image": ""}},
        "10": {"class_type": "LoadImage", "inputs": {"image": ""}},
        "11": {"class_type": "RemakeConditioning", "inputs": {
            "clip": ["4", 0], "vae": ["5", 0], "audio_vae": ["6", 0], "source": ["8", 0], "audio": ["8", 1],
            "prompt": "", "ref_1": ["9", 0], "ref_2": ["10", 0], "pins": "", "frames": MAX_FRAMES,
            "short_edge": SHORT_EDGE}},
        "12": {"class_type": "RemakeNoise", "inputs": {"positive": ["11", 0], "seed": 0}},
        "13": {"class_type": "BasicGuider", "inputs": {"model": ["3", 0], "conditioning": ["11", 0]}},
        "14": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "15": {"class_type": "ManualSigmas", "inputs": {"sigmas": VIGGLE_SIGMAS}},
        "16": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["12", 0], "guider": ["13", 0], "sampler": ["14", 0], "sigmas": ["15", 0],
            "latent_image": ["11", 1]}},
        "17": {"class_type": "VAEDecode", "inputs": {"samples": ["16", 0], "vae": ["5", 0]}},
        "18": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["16", 0], "vae": ["6", 0]}},
        "19": {"class_type": "CreateVideo", "inputs": {"images": ["17", 0], "audio": ["18", 0], "fps": 24.0}},
        "20": {"class_type": "SaveVideo", "inputs": {"video": ["19", 0], "filename_prefix": "swap", "format": "mp4",
                                                     "codec": "h264"}},
    }


PASSTHROUGH_GRAPH = {  # LoadVideo -> SaveVideo: an already joined clip becomes a job (stream copy, no re-encode)
    "1": {"class_type": "LoadVideo", "inputs": {"file": ""}},
    "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0], "filename_prefix": "swap", "format": "mp4",
                                                "codec": "h264"}},
}
VIGGLE_MODELS = [("diffusion_models", "viggle_remake_swap_pruned_int8_convrot.safetensors"),
                 ("text_encoders", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")]


def codex_settings() -> tuple[str, str]:
    """The app's Codex model and effort (agent settings), or the lab defaults."""
    try:
        from .production_db import get_agent_settings
        settings = get_agent_settings()
        return (settings.get("codex_model") or CODEX_MODEL), (settings.get("codex_effort") or CODEX_EFFORT)
    except Exception:
        return CODEX_MODEL, CODEX_EFFORT
AKATZ_TURBO = r"character_swap\minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"
AKATZ_ADAPTER = r"character_swap\h3_character_swap_v1.5.safetensors"
AKATZ_RESOLUTION = "480"                   # tested: 512x928 ~355 s per 5 s; "768" ran 900 s at the 10 GB edge
AKATZ_MEMORY_GIB = 6.0                     # the working-memory reserve used in the akatz tests
AKATZ_MODELS = [("diffusion_models", AKATZ_MODEL), ("text_encoders", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
                ("loras", AKATZ_TURBO), ("loras", AKATZ_ADAPTER), ("checkpoints", "sam3.1_multiplex_fp16.safetensors")]
IMAGE_LOCK = threading.Lock()              # Codex images are found as "the newest file": one image job at a time
_STATE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------------------------------------------
# Small helpers

def _ffprobe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v",
                          "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate", "-of", "json",
                          str(path)], capture_output=True, text=True, timeout=300)
    stream = json.loads(out.stdout)["streams"][0]
    return {"width": int(stream["width"]), "height": int(stream["height"]),
            "frames": int(stream.get("nb_read_frames") or 0)}


def window_frames(available: int) -> int:
    """Viggle renders 17n+5 frames: the largest that fits the clip and one 1 MP window, or 0 when too short."""
    n = (min(available, MAX_FRAMES) - 5) // 17
    frames = 17 * n + 5
    return frames if frames >= MIN_FRAMES else 0


def plan_windows(total: int) -> list[tuple[int, int]]:
    """Viggle windows over the clip as (start, frames). Up to 124 frames: one window (the tail past the last 17n+5,
    under 0.7 s, is dropped). Longer: 124-frame windows, each starting 17 frames before the previous one ends; the
    last one is sized (90/107/124) to end exactly on the clip's last frame."""
    if total <= MAX_FRAMES:
        frames = window_frames(total)
        return [(0, frames)] if frames else []
    windows, end = [(0, MAX_FRAMES)], MAX_FRAMES
    while end < total:
        need = total - (end - LOCK)
        if need <= MAX_FRAMES:
            frames = next(f for f in (90, 107, 124) if f >= need)
            windows.append((total - frames, frames))
            end = total
        else:
            windows.append((end - LOCK, MAX_FRAMES))
            end += MAX_FRAMES - LOCK
    return windows


def windows_of(swap: dict) -> list[tuple[int, int]]:
    return [tuple(w) for w in swap.get("windows") or [(0, swap["frames"])]]


def keep_ranges(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Which local frames of each window go into the joined clip: the first window up to the next window's locked
    frames' end; every later window from its first new frame (after the 17 locked ones)."""
    out = []
    for k, (start, frames) in enumerate(windows):
        first = 0 if k == 0 else LOCK
        last = windows[k + 1][0] + LOCK - start if k + 1 < len(windows) else frames
        out.append((first, last))
    return out


def make_parts(windows: list[tuple[int, int]], scenes: list[dict]) -> list[dict]:
    """The parts the user marks: one shot inside one window's own (new) frames, with its middle frame as the key
    frame (always after the window's locked frames, so a painted frame can be pinned there)."""
    parts = []
    for k, (first, last) in enumerate(keep_ranges(windows)):
        lo, hi = windows[k][0] + first, windows[k][0] + last
        for j, scene in enumerate(scenes):
            a, b = max(scene["start"], lo), min(scene["end"], hi)
            if a < b:
                parts.append({"index": len(parts), "start": a, "end": b, "key_frame": (a + b) // 2, "scene": j,
                              "window": k})
    return parts


def find_cuts(path: Path, frames: int) -> list[int]:
    """Hard cuts: scene score >= 0.2 and PSNR to the previous frame <= 15 (measured on the lab clips, issue #43)."""
    scene = subprocess.run(["ffmpeg", "-i", str(path), "-vf", "scale=320:-2,select='gte(scene,0)',metadata=print",
                            "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=600).stderr
    scores = [float(v) for v in re.findall(r"lavfi\.scene_score=([\d.]+)", scene)]
    psnr = subprocess.run(["ffmpeg", "-i", str(path), "-i", str(path), "-filter_complex",
                           "[0:v]scale=320:180,format=gray,trim=start_frame=1,setpts=PTS-STARTPTS[a];"
                           "[1:v]scale=320:180,format=gray,setpts=PTS-STARTPTS[b];[a][b]psnr=stats_file=-",
                           "-f", "null", "-"], capture_output=True, text=True, timeout=600).stdout
    values = [float(v) if v != "inf" else 99.0 for v in re.findall(r"psnr_avg:([\d.inf]+)", psnr)]
    found = [i for i in range(2, min(frames, len(scores), len(values) + 1)) if scores[i] >= 0.2 and values[i - 1] <= 15]
    return isolated_cuts(found, frames)


def isolated_cuts(found: list[int], frames: int, gap: int = 12) -> list[int]:
    """A hard cut is one jump; fast camera swings, flashes or low-frame-rate footage jump every few frames
    (an 18 s phone clip on 2026-11-09 gave 23 "cuts" 4 frames apart). Keep only jumps with no other jump within
    half a second, and no shot shorter than that."""
    cuts = []
    for i in found:
        if all(abs(i - other) >= gap for other in found if other != i) and gap <= i <= frames - gap                 and (not cuts or i - cuts[-1] >= gap):
            cuts.append(i)
    return cuts


def ts(frame: int) -> str:
    s = frame / 24
    return f"{int(s // 60):02d}:{s % 60:06.3f}"


def _newest_image(after: float) -> Path | None:
    found = [p for p in CODEX_GENERATED_IMAGES.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
             and p.stat().st_mtime >= after]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _codex(task: str, images: list[Path], workdir: Path, schema: dict | None = None) -> str:
    """Run Codex once; returns its last message (JSON text when a schema is given).

    Codex runs in a new empty folder with the shared image-only settings (codex_guard): read-only, no shell tool,
    none of the user's plugins, apps or MCP servers. The inputs arrive as attached images, not as files to read.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    run = workdir / f"codex_run_{uuid.uuid4().hex[:8]}"
    empty = run / "work"
    empty.mkdir(parents=True)
    last = run / "answer.txt"
    model, effort = codex_settings()
    command = [shutil.which(CODEX_COMMAND) or CODEX_COMMAND, "exec", *codex_guard.image_args(empty, model, effort),
               "-o", str(last)]
    if schema:
        schema_file = run / "schema.json"
        schema_file.write_text(json.dumps(schema), encoding="utf-8")
        command += ["--output-schema", str(schema_file)]
    for image in images:
        command += ["--image", str(image)]
    command.append("-")
    try:
        subprocess.run(command, input=task, capture_output=True, text=True, encoding="utf-8",
                       timeout=CODEX_TIMEOUT)
        return last.read_text(encoding="utf-8") if last.exists() else ""
    finally:
        shutil.rmtree(run, ignore_errors=True)


def _codex_image(task: str, images: list[Path], workdir: Path, out: Path, size: tuple[int, int]) -> None:
    with IMAGE_LOCK:
        started = time.time() - 1
        answer = _codex(task, images, workdir)
        image = _newest_image(started)
    if not image:
        # Codex's answer goes to a log next to the swap; the job card shows a short message.
        (workdir / "codex_last_answer.txt").write_text(answer, encoding="utf-8")
        raise RuntimeError("Codex returned no image (its answer is in codex_last_answer.txt in the swap folder)")
    with Image.open(image) as im:
        im.convert("RGB").resize(size, Image.LANCZOS).save(out)


# ---------------------------------------------------------------------------------------------------------------
# Character library

def list_characters() -> list[dict]:
    if not CHARACTERS_FILE.exists():
        return []
    return json.loads(CHARACTERS_FILE.read_text(encoding="utf-8"))


def _save_characters(items: list[dict]) -> None:
    CHARACTERS.mkdir(parents=True, exist_ok=True)
    tmp = CHARACTERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CHARACTERS_FILE)


def _update_character(char_id: str, **values) -> None:
    with _STATE_LOCK:
        items = list_characters()
        for item in items:
            if item["id"] == char_id:
                item.update(values)
        _save_characters(items)


def add_character(name: str, raw: bytes, look: str = "") -> dict:
    name = " ".join(name.split())[:60]
    look = " ".join(look.split())[:400]
    if not name:
        raise ValueError("Give the character a name")
    CHARACTERS.mkdir(parents=True, exist_ok=True)
    char_id = uuid.uuid4().hex[:12]
    path = CHARACTERS / f"{char_id}.png"
    tmp = CHARACTERS / f"{char_id}.upload"
    tmp.write_bytes(raw)
    try:
        with Image.open(tmp) as im:
            im = im.convert("RGB")
            if max(im.size) > 2048:
                im.thumbnail((2048, 2048), Image.LANCZOS)
            im.save(path)
    except Exception as exc:
        raise ValueError("The file is not an image") from exc
    finally:
        tmp.unlink(missing_ok=True)
    item = {"id": char_id, "name": name, "image": path.name, "look": look, "status": "ready",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with _STATE_LOCK:
        items = list_characters()
        items.append(item)
        _save_characters(items)
    return item


def update_character(char_id: str, name: str | None = None, look: str | None = None) -> dict:
    values = {}
    if name is not None and name.strip():
        values["name"] = " ".join(name.split())[:60]
    if look is not None:
        values["look"] = " ".join(look.split())[:400]
    _update_character(char_id, **values)
    item = next((c for c in list_characters() if c["id"] == char_id), None)
    if not item:
        raise KeyError("Character not found")
    return item


def delete_character(char_id: str) -> None:
    with _STATE_LOCK:
        items = list_characters()
        item = next((c for c in items if c["id"] == char_id), None)
        if not item:
            raise KeyError("Character not found")
        _save_characters([c for c in items if c["id"] != char_id])
    (CHARACTERS / item["image"]).unlink(missing_ok=True)


# ---------------------------------------------------------------------------------------------------------------
# Swaps

def _swap_dir(swap_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", swap_id):
        raise KeyError("Swap not found")
    path = SWAPS / swap_id
    if not (path / "swap.json").exists():
        raise KeyError("Swap not found")
    return path


def get_swap(swap_id: str) -> dict:
    return json.loads((_swap_dir(swap_id) / "swap.json").read_text(encoding="utf-8"))


def _save_swap(swap: dict) -> None:
    path = SWAPS / swap["id"] / "swap.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(swap, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _set(swap_id: str, **values) -> dict:
    with _STATE_LOCK:
        swap = get_swap(swap_id)
        swap.update(values)
        swap["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _save_swap(swap)
        return swap


def delete_swap(swap_id: str) -> None:
    """Remove a swap from the list: its folder (frames, marks, painted frames). A rendered job stays in the queue."""
    with _STATE_LOCK:
        folder = _swap_dir(swap_id)
        if get_swap(swap_id).get("status") == "preparing":
            raise ValueError("Codex is still painting this swap; wait for it to finish")
        shutil.rmtree(folder)


def list_swaps(limit: int = 12) -> list[dict]:
    if not SWAPS.exists():
        return []
    items = []
    for folder in SWAPS.iterdir():
        try:
            items.append(json.loads((folder / "swap.json").read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    items.sort(key=lambda s: s.get("created", ""), reverse=True)
    return items[:limit]


def create_swap(source: Path, title: str, source_job_id: str | None = None) -> dict:
    swap_id = uuid.uuid4().hex[:12]
    folder = SWAPS / swap_id
    folder.mkdir(parents=True)
    video = folder / "source.mp4"
    # 24 fps, short edge at most 736 (Viggle renders at 736 anyway; keeps RAM low)
    scale = (f"scale='if(lte(iw,ih),min(iw,{SHORT_EDGE}),-2)':'if(lte(iw,ih),-2,min(ih,{SHORT_EDGE}))',"
             "scale=trunc(iw/2)*2:trunc(ih/2)*2")
    out = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                          "-vf", f"fps=24,{scale}", "-fps_mode", "cfr", "-c:v", "libx264",
                          "-crf", "10", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                          str(video)], capture_output=True, text=True, timeout=900)
    if out.returncode:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError("The video could not be read: " + (out.stderr.strip().splitlines() or ["unknown"])[-1])
    probe = _ffprobe(video)
    duration = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                               str(source)], capture_output=True, text=True, timeout=120).stdout.strip()
    try:
        original = max(probe["frames"], round(float(duration) * 24))
    except ValueError:
        original = probe["frames"]
    windows = plan_windows(probe["frames"])
    if not windows:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError("The clip is shorter than 3.8 s (Viggle needs at least 90 frames at 24 fps)")
    frames = windows[-1][0] + windows[-1][1]
    cuts = find_cuts(video, frames)
    bounds = [0, *cuts, frames]
    scenes = [{"start": a, "end": b} for a, b in zip(bounds, bounds[1:])]
    shots = make_parts(windows, scenes)
    for part in shots:
        part["frame"] = f"shot{part['index']}_frame.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{part['key_frame'] / 24:.4f}", "-i", str(video),
                        "-frames:v", "1", str(folder / part["frame"])], check=True, timeout=300)
    swap = {"id": swap_id, "title": title[:160], "source_job_id": source_job_id, "status": "marking",
            "stage": "", "error": None, "width": probe["width"], "height": probe["height"],
            "source_frames": original, "frames": frames, "seconds": round(frames / 24, 2),
            "trimmed": original - frames > 2, "windows": windows, "scenes": scenes, "shots": shots, "marks": [],
            "job_id": None,
            "mode": "reference", "engine": "viggle", "notes": "",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save_swap(swap)
    return swap


def set_marks(swap_id: str, marks: list[dict], mode: str = "reference", notes: str = "",
              engine: str = "viggle", empty: list[int] | None = None, openjutsu_options: dict | None = None) -> dict:
    swap = get_swap(swap_id)
    if swap["status"] not in ("marking", "review", "failed", "done"):
        raise ValueError("This swap is busy")
    if mode not in ("reference", "painted"):
        raise ValueError("Mode is reference or painted")
    if engine not in ENGINES:
        raise ValueError("Engine is viggle, akatz or openjutsu")
    oj = {"resolution": "736p", "remove_hair": False, **(openjutsu_options or {})}
    if oj["resolution"] not in openjutsu.RESOLUTIONS:
        raise ValueError("Openjutsu renders at 480p or 736p")
    oj = {"resolution": oj["resolution"], "remove_hair": bool(oj["remove_hair"])}
    characters = {c["id"] for c in list_characters()}
    clean = []
    for number, mark in enumerate(marks, 1):
        shot = int(mark["shot"])
        if not 0 <= shot < len(swap["shots"]):
            raise ValueError("Unknown part")
        if mark["character_id"] not in characters:
            raise ValueError("Pick a character for every marked person")
        x, y = float(mark["x"]), float(mark["y"])
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError("Marks must be on the frame")
        description = " ".join(str(mark.get("description") or "").split())[:200]
        if not description:
            raise ValueError(f"Describe person {number} (for example: the man on the left in the grey hoodie)")
        clean.append({"shot": shot, "x": round(x, 4), "y": round(y, 4), "character_id": mark["character_id"],
                      "description": description})
    per_shot = {}
    for mark in clean:
        per_shot.setdefault(mark["shot"], []).append(mark)
    if any(len(v) > MAX_PEOPLE for v in per_shot.values()):
        raise ValueError(f"Up to {MAX_PEOPLE} people per part were tested")
    for shot_marks in per_shot.values():
        chosen = [m["character_id"] for m in shot_marks]
        if len(chosen) != len(set(chosen)):
            raise ValueError("One character can replace only one person in a part")
    if engine == "akatz" and len({m["character_id"] for m in clean}) > 1:
        raise ValueError("akatz swaps one person per render: mark one person (one character)")
    if engine == "openjutsu" and len({m["character_id"] for m in clean}) > openjutsu.MAX_CHARACTERS:
        raise ValueError(f"Openjutsu swaps up to {openjutsu.MAX_CHARACTERS} people per render (the tested counts): "
                         f"mark up to {openjutsu.MAX_CHARACTERS} characters")
    marked = {m["shot"] for m in clean}
    nobody = {int(i) for i in (empty or [])} - marked
    with _STATE_LOCK:
        swap = get_swap(swap_id)
        for part in swap["shots"]:
            part.pop("empty", None)
            if part["index"] in nobody:
                part["empty"] = True
        swap.update(marks=clean, mode=mode, engine=engine, openjutsu=oj, notes=" ".join(notes.split())[:1000], status="marking",
                    updated=time.strftime("%Y-%m-%dT%H:%M:%S"))
        _save_swap(swap)
    return swap


def _marked_image(folder: Path, shot: dict, marks: list[dict]) -> Path:
    out = folder / f"shot{shot['index']}_marked.png"
    with Image.open(folder / shot["frame"]) as im:
        im = im.convert("RGB")
        draw = ImageDraw.Draw(im)
        radius = max(18, im.width // 40)
        try:
            font = ImageFont.truetype("arialbd.ttf", radius)
        except OSError:
            font = ImageFont.load_default()
        for number, mark in enumerate(marks, 1):
            cx, cy = mark["x"] * im.width, mark["y"] * im.height
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(230, 30, 30),
                         outline=(255, 255, 255), width=max(2, radius // 6))
            draw.text((cx, cy), str(number), fill=(255, 255, 255), font=font, anchor="mm")
        im.save(out)
    return out


def start_prepare(swap_id: str) -> dict:
    swap = get_swap(swap_id)
    if swap["status"] in ("preparing", "rendering"):
        raise ValueError("This swap is already running")
    if not swap["marks"]:
        raise ValueError("Tap at least one person and pick a character")
    if swap.get("mode") != "painted":
        raise ValueError("Painting is for the painted-keyframes mode")
    swap = _set(swap_id, status="preparing", stage="Painting", error=None)
    threading.Thread(target=_prepare, args=(swap_id,), daemon=True).start()
    return swap


def _own_marks(swap: dict, part: int) -> list[dict]:
    return [m for m in swap["marks"] if m["shot"] == part]


def _shot_marks(swap: dict, part: int) -> list[dict]:
    """The people to swap in a part: its own marks, or, when it has none and is not marked "nobody here", the marks
    of the part before it in the same shot (people carry over within a shot; their tap positions are that part's)."""
    own = _own_marks(swap, part)
    parts = swap["shots"]
    if own or not 0 <= part < len(parts):
        return own
    current = parts[part]
    if current.get("empty") or "scene" not in current:
        return []
    before = next((p for p in reversed(parts[:part]) if p.get("scene") == current["scene"]), None)
    if before is None:
        return []
    return [{**m, "shot": part, "inherited": True} for m in _shot_marks(swap, before["index"])]


def _people(swap: dict) -> dict:
    """(shot, number in that shot) -> the user's description of that person."""
    out = {}
    for shot in swap["shots"]:
        for number, mark in enumerate(_shot_marks(swap, shot["index"]), 1):
            out[(shot["index"], number)] = mark["description"]
    return out


def _prepare(swap_id: str) -> None:
    """Codex paints every part that has someone to swap and no painted frame yet. Each finished part is saved at
    once; a part Codex refuses or fails is skipped and named on the sheet with Codex's reason, so the user can
    paint that one themselves (2026-11-09: Codex refuses frames it classifies as showing a public figure)."""
    try:
        swap = get_swap(swap_id)
        folder = SWAPS / swap_id
        todo = [s for s in swap["shots"] if _shot_marks(swap, s["index"]) and not s.get("painted")]
        people = _people(swap)
        characters = {c["id"]: c for c in list_characters()}
        failed = []
        for n, shot in enumerate(todo, 1):
            _set(swap_id, stage=f"Painting part {shot['index'] + 1} ({n} of {len(todo)})")
            try:
                _marked_image(folder, shot, _own_marks(swap, shot["index"]))
                name = _paint(folder, swap, shot, people, characters)
            except Exception as exc:
                failed.append(f"part {shot['index'] + 1}: {exc}"[:300])
                continue
            with _STATE_LOCK:
                current = get_swap(swap_id)
                current["shots"][shot["index"]].update(painted=name, painted_by="codex")
                current["painted_version"] = time.time()
                _save_swap(current)
        swap = get_swap(swap_id)
        complete = all(s.get("painted") for s in swap["shots"] if _shot_marks(swap, s["index"]))
        _set(swap_id, status="review" if complete and not failed else "marking", stage="",
             error=("Codex did not paint " + "; ".join(failed) + ". Paint these parts yourself (download, paint, "
                    "upload) or try Codex again.") if failed else None)
    except Exception as exc:  # the user sees the reason on the sheet
        _set(swap_id, status="failed", stage="", error=f"{type(exc).__name__}: {exc}"[:600])


def consistency_frame(swap: dict, part: int, character_id: str) -> str | None:
    """The first painted frame of an earlier part that shows this character, so every part paints the same version of
    them (2026-11-09: separately painted parts gave the same character different hats and patches, and the render
    jumped at the window join where one painted frame hands over to the next)."""
    for earlier in swap["shots"][:part]:
        if earlier.get("painted") and any(m["character_id"] == character_id for m in _shot_marks(swap, earlier["index"])):
            return earlier["painted"]
    return None


def _paint(folder: Path, swap: dict, shot: dict, people: dict, characters: dict) -> str:
    marks = _shot_marks(swap, shot["index"])
    circles = not any(m.get("inherited") for m in marks)   # carried-over marks were tapped on another frame
    images = [folder / shot["frame"]] + ([folder / f"shot{shot['index']}_marked.png"] if circles else [])
    lines = []
    for number, mark in enumerate(marks, 1):
        char = characters[mark["character_id"]]
        images.append(CHARACTERS / char["image"])
        where = f" (red circle {number} in image 2)" if circles else ""
        line = (f"- Replace the person described as {codex_guard.user_text(mark['description'])}{where} with the "
                f"character in image {len(images)}, who looks like {codex_guard.user_text(char['look'] or char['name'])}"
                ". Copy that character's face, hair and outfit exactly.")
        anchor = consistency_frame(get_swap(swap["id"]), shot["index"], mark["character_id"])
        if anchor:
            images.append(folder / anchor)
            line += (f" Image {len(images)} is an earlier frame of this video where this character is already "
                     "painted: copy their hat, face, hair, beard, glasses, outfit, patches and every accessory exactly "
                     "as there (only the pose, size and position follow the first image).")
        lines.append(line)
    guide = ("Image 2 is the same frame with red numbered circles that only show who is who: the result must have no "
             "circles or numbers.\n" if circles else "")
    task = ("Use your image generation tool to edit the FIRST image (a frame from a video) into exactly one new image, "
            "then inspect it against all the inputs and regenerate once if anything is wrong. " +
            codex_guard.DATA_NOTE + "\n" + guide +
            "Make these replacements, and nothing else:\n" + "\n".join(lines) + "\n\nEach new person keeps exactly the "
            "pose, position, size and action of the person they replace. Same camera angle, framing, lens, lighting, "
            "colour grade and aspect ratio as the first image; the background and every other person stay exactly as "
            "they are. No text, logos or watermarks. Do not run shell commands and do not modify any file.")
    out = folder / f"shot{shot['index']}_painted.png"
    with Image.open(folder / shot["frame"]) as im:
        size = im.size
    _codex_image(task, images, folder, out, size)
    return out.name


def build_prompt(swap: dict, characters: dict) -> str:
    """Viggle's six-section prompt from the user's marks, descriptions and notes (no AI).

    reference mode: <Picture N> is character N's own image (not a frame); painted mode: <Picture N> is shot N's
    painted frame, pinned at that shot's key frame.
    """
    painted = swap.get("mode") == "painted"
    pinned = True                           # every painted frame lies inside its own window, after the locked frames
    window = swap.get("window", 0)
    marked_shots = [s for s in swap["shots"] if _shot_marks(swap, s["index"])]
    if painted:                             # pieces that only continue a part from the window before carry no frame
        marked_shots = [s for s in marked_shots if s.get("painted", True)]
    subjects, replaced = [], {}
    for shot in [s for s in swap["shots"] if _shot_marks(swap, s["index"])]:
        for mark in _shot_marks(swap, shot["index"]):
            cid = mark["character_id"]
            if cid not in subjects:
                subjects.append(cid)
            replaced.setdefault(cid, []).append(mark["description"])

    def look(cid):
        char = characters[cid]
        return char["look"] or f"exactly as in {'the pictures' if painted else 'their picture'}"

    shots_seen = [s.get("scene", s["index"]) for s in swap["shots"]]
    cuts = sum(1 for a, b in zip(shots_seen, shots_seen[1:]) if a != b)
    shape = "single continuous shot with no cut" if not cuts else f"clip with {cuts + 1} shots and {cuts} hard cut(s)"
    subject_lines = [f"<Subject {i}> is {characters[c]['name']}: {look(c)}. {characters[c]['name']} replaces "
                     f"{' and '.join(dict.fromkeys(replaced[c]))} in <Video 1>." for i, c in enumerate(subjects, 1)]
    if painted and pinned:
        pictures = [f"<Picture {i}> is a frame of the target video from [Shot {s['index'] + 1}]."
                    for i, s in enumerate(marked_shots, 1)]
        retention = [f"<Picture {i}>: reference - a frame of the target video at {ts(s['key_frame'])}. Every new "
                     f"person as they appear there is taken from <Picture {i}>." for i, s in enumerate(marked_shots, 1)]
    elif painted:
        pictures = [f"<Picture {i}> is a frame of this shot from another part of the video, with the new people in "
                    f"it, for [Shot {s['index'] + 1}]." for i, s in enumerate(marked_shots, 1)]
        retention = [f"<Picture {i}>: reference - every new person's face, hair and outfit are taken from "
                     f"<Picture {i}>; its exact pose and moment are not used." for i, s in enumerate(marked_shots, 1)]
    else:
        pictures = ["Each <Picture N> is a character picture, not a frame of the target video: " +
                    ", ".join(f"<Picture {i}> shows <Subject {i}>" for i in range(1, len(subjects) + 1)) + "."]
        retention = [f"<Picture {i}>: reference - only <Subject {i}>'s face, hair and outfit are taken from "
                     f"<Picture {i}>; its background, layout and pose are not used." for i in range(1, len(subjects) + 1)]
    keep = [f"<Subject {i}>: fully_preserved - {characters[c]['name']}'s face, hair and outfit stay identical in every "
            f"frame." for i, c in enumerate(subjects, 1)]
    picture_of = {s["index"]: i for i, s in enumerate(marked_shots, 1)}
    detail = []
    for shot in swap["shots"]:
        ordered = sorted(_shot_marks(swap, shot["index"]), key=lambda m: m["x"])   # where the user tapped
        here = [f"<Subject {subjects.index(m['character_id']) + 1}> in place of {m['description']}" for m in ordered]
        who = (f" with, from left to right, {'; '.join(here)}" if len(here) > 1 else f" with {here[0]}") if here else ""
        match = f", matching <Picture {picture_of[shot['index']]}> at {ts(shot['key_frame'])}" \
            if painted and pinned and shot["index"] in picture_of else ""
        same = shot["index"] and swap["shots"][shot["index"] - 1].get("scene", -1) == shot.get("scene", -2)
        cut = "" if shot["index"] == 0 else "the same shot continues, " if same else "a hard cut, "
        carry = "continuing seamlessly from the previous take, " if window and shot["index"] == 0 else ""
        detail.append(f"[Shot {shot['index'] + 1}] At {ts(shot['start'])} {cut}{carry}the shot of <Video 1>{who}; "
                      f"everyone moves, acts and speaks exactly as in <Video 1>{match}.")
    notes = (swap.get("notes") or "").strip()
    if notes:
        notes = notes[0].upper() + notes[1:] + ("" if notes[-1] in ".!?" else ".")
    names = ", ".join(f"<Subject {i}>" for i in range(1, len(subjects) + 1))
    return f"""subject_definitions:
<Video 1> is the source video for the editing task: a {swap['seconds']:.1f} s {shape}.{' ' + notes if notes else ''}
{chr(10).join(pictures)}
{chr(10).join(subject_lines)}

summary:
[video editing + character replacement] The target video is an edited version of <Video 1> in which {len(subjects)} {"person is" if len(subjects) == 1 else "people are"} replaced: {names}, each looking exactly as in {'the pictures' if painted else 'their picture'} and doing everything the person they replace does. Everyone else, the place and the light are unchanged. The shots, the camera, the motion and the timing of <Video 1> are kept.

retention_analysis:
<Video 1> (source video editing): fully_preserved - the shot structure, every camera angle and move, the place, the light, every other person, and the motion and timing of every action and word are copied frame for frame.
{chr(10).join(retention)}
{chr(10).join(keep)}

detailed_description:
The target video is a realistic live-action video with the same place, light and look as <Video 1>.{' ' + notes if notes else ''}
{chr(10).join(detail)}
Each new person keeps their own face, hair and outfit in every frame, and none of the replaced people's faces, hair or clothes remain. Only these people change, and everything else stays as in <Video 1>.

overall_soundscape:
The source soundtrack continues throughout, unchanged.

non_diegetic_music:
N/A
"""


def start_repaint(swap_id: str, shot_index: int) -> dict:
    swap = get_swap(swap_id)
    if swap["status"] in ("preparing", "rendering"):
        raise ValueError("This swap is busy")
    if not _shot_marks(swap, shot_index):
        raise ValueError("Nothing to paint in this part")
    swap = _set(swap_id, status="preparing", stage=f"Repainting shot {shot_index + 1}")

    def work():
        try:
            current = get_swap(swap_id)
            people = _people(current)
            characters = {c["id"]: c for c in list_characters()}
            shot = current["shots"][shot_index]
            _marked_image(SWAPS / swap_id, shot, _own_marks(current, shot_index))
            _paint(SWAPS / swap_id, current, shot, people, characters)
            _set(swap_id, status="review", stage="", painted_version=time.time())
        except Exception as exc:
            _set(swap_id, status="failed", stage="", error=f"{type(exc).__name__}: {exc}"[:600])

    threading.Thread(target=work, daemon=True).start()
    return swap


SPLIT_MIN = 12                             # each half of a split part is at least 0.5 s


def split_part(swap_id: str, index: int, frame: int) -> dict:
    """Split a part in two at `frame` (inside one ~5 s window, same shot), so each half gets its own frame to mark
    and paint: for people who show at different moments of the same part. Later parts, their marks, files and
    "nobody here" flags move up by one; the split part keeps its marks (the second half carries them over) and
    loses its painted frame (its frame moved)."""
    with _STATE_LOCK:
        swap = get_swap(swap_id)
        if swap["status"] in ("preparing", "rendering"):
            raise ValueError("This swap is busy")
        parts = swap["shots"]
        if not 0 <= index < len(parts):
            raise ValueError("Unknown part")
        part = parts[index]
        if not part["start"] + SPLIT_MIN <= frame <= part["end"] - SPLIT_MIN:
            raise ValueError(f"Pick a moment between {ts(part['start'] + SPLIT_MIN)} and {ts(part['end'] - SPLIT_MIN)}")
        folder = SWAPS / swap_id
        for i in range(len(parts) - 1, index, -1):          # move later parts' files up by one, last first
            for kind in ("frame", "painted", "marked"):
                src = folder / f"shot{i}_{kind}.png"
                if src.exists():
                    src.replace(folder / f"shot{i + 1}_{kind}.png")
        for kind in ("painted", "marked"):
            (folder / f"shot{index}_{kind}.png").unlink(missing_ok=True)
        first = {k: v for k, v in part.items() if k not in ("painted", "painted_by")}
        first.update(end=frame, key_frame=(part["start"] + frame) // 2)
        second = {k: v for k, v in part.items() if k not in ("painted", "painted_by", "empty")}
        second.update(start=frame, key_frame=(frame + part["end"]) // 2)
        parts = parts[:index] + [first, second] + parts[index + 1:]
        for i, p in enumerate(parts):
            if i > index + 1 and p.get("painted"):
                p["painted"] = f"shot{i}_painted.png"
            p["index"], p["frame"] = i, f"shot{i}_frame.png"
        for i in (index, index + 1):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{parts[i]['key_frame'] / 24:.4f}", "-i",
                            str(folder / "source.mp4"), "-frames:v", "1", str(folder / parts[i]["frame"])],
                           check=True, timeout=300)
        for mark in swap["marks"]:
            if mark["shot"] > index:
                mark["shot"] += 1
        swap.update(shots=parts, status="marking", painted_version=time.time(),
                    updated=time.strftime("%Y-%m-%dT%H:%M:%S"))
        _save_swap(swap)
        return swap


def set_painted(swap_id: str, shot_index: int, raw: bytes) -> dict:
    """The user's own painted frame for a shot (painted mode): fitted to the shot frame's exact size."""
    swap = get_swap(swap_id)
    if swap["status"] in ("preparing", "rendering"):
        raise ValueError("This swap is busy")
    if not 0 <= shot_index < len(swap["shots"]):
        raise ValueError("Unknown shot")
    folder = SWAPS / swap_id
    shot = swap["shots"][shot_index]
    tmp = folder / f"shot{shot_index}_upload.tmp"
    tmp.write_bytes(raw)
    try:
        with Image.open(folder / shot["frame"]) as frame:
            size = frame.size
        with Image.open(tmp) as im:
            im = im.convert("RGB")
            scale = max(size[0] / im.width, size[1] / im.height)   # cover, then center-crop: no stretching
            im = im.resize((max(size[0], round(im.width * scale)), max(size[1], round(im.height * scale))), Image.LANCZOS)
            left, top = (im.width - size[0]) // 2, (im.height - size[1]) // 2
            im.crop((left, top, left + size[0], top + size[1])).save(folder / f"shot{shot_index}_painted.png")
    except Exception as exc:
        raise ValueError("The file is not an image") from exc
    finally:
        tmp.unlink(missing_ok=True)
    with _STATE_LOCK:
        swap = get_swap(swap_id)
        swap["shots"][shot_index]["painted"] = f"shot{shot_index}_painted.png"
        swap["shots"][shot_index]["painted_by"] = "user"
        marked = [s for s in swap["shots"] if _shot_marks(swap, s["index"])]
        if swap.get("mode") == "painted" and marked and all(s.get("painted") for s in marked):
            swap["status"] = "review"
        swap["error"] = None
        swap["painted_version"] = time.time()
        _save_swap(swap)
    return swap


def build_graph(swap: dict, names: dict, prompt: str) -> dict:
    """The Viggle swap graph spec (workflows.graph_spec_workflow): int8 swap file, int8 attention, ~1 MP."""
    refs = names["refs"]  # [(input file name, pin or None)]
    sets = {"1.unet_name": VIGGLE_MODEL, "4.clip_name": TEXT_ENCODER, "7.file": names["source"],
            "11.frames": swap["frames"], "11.short_edge": SHORT_EDGE,
            "11.pins": ", ".join(str(pin) for _, pin in refs if pin is not None), "11.prompt": prompt}
    add = {"30": {"class_type": "ModelAttentionBackend",
                  "inputs": {"model": ["1", 0], "attention": "comfy kitchen attention"}}}
    sets["3.model"] = ["30", 0]
    remove, unset = ["2"], []
    for i, (name, _) in enumerate(refs, 1):
        node = {1: "9", 2: "10"}.get(i) or str(20 + i)
        if node not in ("9", "10"):
            add[node] = {"class_type": "LoadImage", "inputs": {}}
        sets[f"{node}.image"] = name
        sets[f"11.ref_{i}"] = [node, 0]
    if len(refs) == 1:
        remove.append("10")
        unset.append("11.ref_2")
    return {"base": viggle_base_graph(), "set": sets, "add": add, "remove": remove, "unset": unset}


def window_view(swap: dict, k: int) -> dict:
    """The swap as seen by window k, counted from the window's first frame: one piece per part of this window
    (the first piece of a shot also covers the window's locked frames), and a piece for a shot that only shows in
    the locked frames, which takes its people from the part before it. Painted frames and pins come only from this
    window's parts (their key frames lie after the locked frames, so they can always be pinned)."""
    start, frames = windows_of(swap)[k]
    parts = swap["shots"]
    scenes = swap.get("scenes") or [{"start": p["start"], "end": p["end"]} for p in parts]
    pieces, marks = [], []

    def add(a, b, scene, src, own):
        index = len(pieces)
        pieces.append({"index": index, "start": a - start, "end": b - start, "scene": scene,
                       "part": src["index"] if src else None,
                       "key_frame": own["key_frame"] - start if own else None,
                       "painted": own.get("painted") if own else None})
        if src:
            marks.extend({**m, "shot": index} for m in _shot_marks(swap, src["index"]))

    for j, scene in enumerate(scenes):
        a, b = max(scene["start"], start), min(scene["end"], start + frames)
        if a >= b:
            continue
        own = sorted((p for p in parts if p.get("window", 0) == k and p.get("scene", p["index"]) == j),
                     key=lambda p: p["start"])
        if not own:
            before = next((p for p in reversed(parts) if p.get("window", 0) < k and p.get("scene", p["index"]) == j),
                          None)
            add(a, b, j, before, None)
            continue
        for n, part in enumerate(own):
            add(a if n == 0 else part["start"], b if n == len(own) - 1 else part["end"], j, part, part)
    return {**swap, "shots": pieces, "scenes": None, "marks": marks, "frames": frames,
            "seconds": round(frames / 24, 2), "window": k, "start": start}


def multi_window_graph(windows: list[dict], seed: int, source: str, keeps: list[tuple[int, int]] | None = None,
                       prefix: dict | None = None, audio: tuple[float, float] | None = None) -> dict:
    """Chained Viggle windows in one graph. windows[k] = {start (frame in `source`), frames, refs: [(input name,
    pin)], prompt}.

    Window 0 is the shipped graph (nodes 11-17) fed a slice of the source; each later window adds the same chain
    with Remake Prefix taking the previous window's decoded frames; the kept frames of every window are joined and
    saved with the source sound. Every window has its own seed (job seed + k). A later part of a long clip passes
    `prefix` ({file, at}: the previous part's video and the frame its last window starts at), so its first window
    opens with the previous part's frames, and `keeps`/`audio` for its own frame range."""
    starts = [(w["start"], w["frames"]) for w in windows]
    keeps = keeps or keep_ranges(starts)
    sets = {"1.unet_name": VIGGLE_MODEL, "4.clip_name": TEXT_ENCODER, "3.model": ["30", 0], "12.seed": seed,
            "7.file": source}
    add = {"30": {"class_type": "ModelAttentionBackend",
                  "inputs": {"model": ["1", 0], "attention": "comfy kitchen attention"}}}
    remove, unset = ["2", "18"], []
    image_node: dict[str, str] = {}
    for w in windows:
        for name, _ in w["refs"]:
            if name not in image_node:
                node = {0: "9", 1: "10"}.get(len(image_node)) or f"img{len(image_node)}"
                image_node[name] = node
                if node not in ("9", "10"):
                    add[node] = {"class_type": "LoadImage", "inputs": {}}
                sets[f"{node}.image"] = name
    if len(image_node) == 1:
        remove.append("10")
    if prefix:
        add["p_load"] = {"class_type": "LoadVideo", "inputs": {"file": prefix["file"]}}
        add["p_parts"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["p_load", 0]}}
        add["w0_prefix"] = {"class_type": "RemakePrefix", "inputs": {
            "vae": ["5", 0], "latent": ["11", 1], "prefix": ["p_parts", 0], "prefix_frames": LOCK,
            "prefix_at": prefix["at"]}}
        sets["16.latent_image"] = ["w0_prefix", 0]
    decode_prev = None
    keep_nodes = []
    for k, w in enumerate(windows):
        src, aud = f"w{k}_src", f"w{k}_aud"
        add[src] = {"class_type": "ImageFromBatch", "inputs": {"image": ["8", 0], "batch_index": w["start"],
                                                               "length": w["frames"]}}
        add[aud] = {"class_type": "TrimAudioDuration", "inputs": {"audio": ["8", 1], "start_index": w["start"] / 24,
                                                                  "duration": w["frames"] / 24}}
        cond_inputs = {"clip": ["4", 0], "vae": ["5", 0], "audio_vae": ["6", 0], "source": [src, 0],
                       "audio": [aud, 0], "prompt": w["prompt"], "frames": w["frames"], "short_edge": SHORT_EDGE,
                       "pins": ", ".join(str(p) for _, p in w["refs"] if p is not None)}
        for i, (name, _) in enumerate(w["refs"], 1):
            cond_inputs[f"ref_{i}"] = [image_node[name], 0]
        if k == 0:
            cond, decode = "11", "17"
            for field, value in cond_inputs.items():
                sets[f"11.{field}"] = value
            if len(w["refs"]) < 2:
                unset.append("11.ref_2")
        else:
            cond, decode = f"w{k}_cond", f"w{k}_decode"
            add[cond] = {"class_type": "RemakeConditioning", "inputs": cond_inputs}
            add[f"w{k}_noise"] = {"class_type": "RemakeNoise", "inputs": {"positive": [cond, 0],
                                                                          "seed": (seed + k) % 2 ** 63}}
            add[f"w{k}_guider"] = {"class_type": "BasicGuider", "inputs": {"model": ["3", 0], "conditioning": [cond, 0]}}
            add[f"w{k}_prefix"] = {"class_type": "RemakePrefix", "inputs": {
                "vae": ["5", 0], "latent": [cond, 1], "prefix": [decode_prev, 0], "prefix_frames": LOCK,
                "prefix_at": w["start"] - windows[k - 1]["start"]}}
            add[f"w{k}_sample"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
                "noise": [f"w{k}_noise", 0], "guider": [f"w{k}_guider", 0], "sampler": ["14", 0],
                "sigmas": ["15", 0], "latent_image": [f"w{k}_prefix", 0]}}
            add[decode] = {"class_type": "VAEDecode", "inputs": {"samples": [f"w{k}_sample", 0], "vae": ["5", 0]}}
        first, last = keeps[k]
        add[f"w{k}_keep"] = {"class_type": "ImageFromBatch", "inputs": {"image": [decode, 0], "batch_index": first,
                                                                        "length": last - first}}
        keep_nodes.append(f"w{k}_keep")
        decode_prev = decode
    joined = keep_nodes[0]
    for k, node in enumerate(keep_nodes[1:], 1):
        add[f"join{k}"] = {"class_type": "ImageBatch", "inputs": {"image1": [joined, 0], "image2": [node, 0]}}
        joined = f"join{k}"
    if audio is None:
        total = windows[-1]["start"] + windows[-1]["frames"]
        audio = (0.0, total / 24)
    add["final_aud"] = {"class_type": "TrimAudioDuration", "inputs": {"audio": ["8", 1], "start_index": audio[0],
                                                                     "duration": audio[1]}}
    sets["19.images"] = [joined, 0]
    sets["19.audio"] = ["final_aud", 0]
    return {"base": viggle_base_graph(), "set": sets, "add": add, "remove": remove, "unset": unset}


def plan_segments(windows: list[tuple[int, int]], first_window: int = 0) -> list[dict]:
    """Long clips run as several jobs ("parts of the render") of up to SEGMENT_WINDOWS windows: one job keeps all
    its frames in RAM, so a single job for a long clip would not fit. Each job's video covers `keep` (no overlap);
    its source slice `src` runs from its first window's start to its last window's end."""
    keeps = keep_ranges(windows)
    out = []
    for first in range(first_window, len(windows), SEGMENT_WINDOWS):
        ids = list(range(first, min(len(windows), first + SEGMENT_WINDOWS)))
        out.append({"windows": ids,
                    "src": [windows[ids[0]][0], windows[ids[-1]][0] + windows[ids[-1]][1]],
                    "keep": [windows[ids[0]][0] + keeps[ids[0]][0], windows[ids[-1]][0] + keeps[ids[-1]][1]],
                    "job_id": None, "output": None})
    return out


def akatz_windows(count: int, window: int = 124, history: int = 18) -> int:
    """How many windows akatz's H3RelayWindowPlan (adaptive, 124 + 18 history) renders for `count` frames:
    the first window has no history; each later one starts on the last delivered frame."""
    sizes = range(22, 363, 17)
    windows, covered = 0, 0
    while covered < count:
        hist = history if windows else 0
        start = covered - (1 if hist else 0)
        size = next(v for v in sizes if v >= min(count - start, window) and v > hist)
        covered = min(count, start + size)
        windows += 1
    return windows


def akatz_prompt(mark: dict, character: dict) -> str:
    look = character["look"] or "face, hair and outfit"
    return (f"Replace {mark['description']} in <Video 1> with the character in <Picture 1>. Keep the reference "
            f"character's {look}. Follow the source performance's pose, gaze, expression, mouth movement and "
            "movement. Preserve the scene, the shots and the cuts, and everyone else.")


def akatz_graph(names: dict, mark: dict, prompt: str, seed: int, seconds: float) -> dict:
    """akatz V1.5 as tested on 2026-11-09 (int8 Ref2VA + swap LoRA + Turbo 8, SAM 3.1 mask, 480 setting)."""
    sets = {"source.file": names["source"], "reference.image": names["ref"], "turbo.lora_name": AKATZ_TURBO,
            "adapter.lora_name": AKATZ_ADAPTER, "prepare.resolution": AKATZ_RESOLUTION,
            "prepare.duration_seconds": round(seconds, 2), "sampling_memory.activation_memory_gib": AKATZ_MEMORY_GIB,
            "subject.text": mark.get("subject") or mark["description"], "select.selection": mark.get("pick", "largest"),
            "reference_conditioning.prompt": prompt, "plan.seed": seed % 2 ** 31}
    return {"file": str(AKATZ_GRAPH), "set": sets, "remove": ["mask_preview"]}


def _pick(x: float) -> str:
    """Which SAM match akatz keeps, from where the user tapped: a person on the left or right third is the
    leftmost/rightmost match; in the middle, the largest."""
    return "leftmost" if x < 1 / 3 else "rightmost" if x > 2 / 3 else "largest"


def _window_spec(swap: dict, k: int, painted: bool, characters_by_id: dict) -> dict:
    """Window k's pictures (copied into ComfyUI's input folder) and prompt."""
    folder = SWAPS / swap["id"]
    view = window_view(swap, k)
    start, frames = windows_of(swap)[k]
    if not view["marks"]:
        raise ValueError(f"Nobody to swap in {ts(start)}-{ts(start + frames)}: every ~5 s part needs at least one "
                         "person marked (or carried over from the part before)")
    refs = []
    if painted:
        for piece in view["shots"]:
            if piece.get("painted") and any(m["shot"] == piece["index"] for m in view["marks"]):
                name = f"swap_{swap['id']}_part{piece['part']}.png"
                shutil.copyfile(folder / piece["painted"], INPUT / name)
                refs.append((name, piece["key_frame"]))
    else:
        for cid in dict.fromkeys(m["character_id"] for m in view["marks"]):
            name = f"swap_char_{cid}.png"
            shutil.copyfile(CHARACTERS / characters_by_id[cid]["image"], INPUT / name)
            refs.append((name, None))
    if len(refs) > MAX_PEOPLE:
        raise ValueError(f"Up to {MAX_PEOPLE} pictures per ~5 s part ({ts(start)}-{ts(start + frames)})")
    return {"start": start, "frames": frames, "refs": refs, "prompt": build_prompt(view, characters_by_id)}


def render(swap_id: str, folder_ref: tuple[str, str] | None) -> dict:
    """Submit the swap as swap jobs (engine "swap", workflows.graph_spec_workflow): one job for
    up to SEGMENT_WINDOWS windows; longer clips as a chain of such jobs and a final joining job (follow())."""
    swap = get_swap(swap_id)
    engine = swap.get("engine") or "viggle"
    painted = swap.get("mode") == "painted" and engine == "viggle"
    if swap["status"] not in ("marking", "failed", "done", "review"):
        raise ValueError("This swap is busy")
    if not swap["marks"]:
        raise ValueError("Tap at least one person and pick a character")
    unpainted = [p["index"] + 1 for p in swap["shots"] if _shot_marks(swap, p["index"]) and not p.get("painted")]
    if painted and unpainted:
        raise ValueError(f"Part {', '.join(map(str, unpainted))} needs a painted frame")
    folder = SWAPS / swap_id
    characters_by_id = {c["id"]: c for c in list_characters()}
    if {m["character_id"] for m in swap["marks"]} - set(characters_by_id):
        raise ValueError("A chosen character was deleted; pick another")
    who = sorted({characters_by_id[m["character_id"]]["name"] for m in swap["marks"]})
    swap = _set(swap_id, folder_ref=list(folder_ref) if folder_ref else None, segments=None, built=None,
                final_job=None, error=None, head=None, tail=None)
    source = f"swap_{swap_id}_source.mp4"
    shutil.copyfile(folder / "source.mp4", INPUT / source)
    seed = str(random.getrandbits(63))
    windows = windows_of(swap)
    mode_tag = f"Mode: {'painted frames' if painted else 'character image only'}"
    if engine == "akatz":
        if swap["seconds"] > AKATZ_MAX_SECONDS:
            raise ValueError(f"akatz handles up to {AKATZ_MAX_SECONDS} s (its own limit); use Viggle or a shorter clip")
        mark = swap["marks"][0]
        char = characters_by_id[mark["character_id"]]
        names = {"source": source, "ref": f"swap_char_{char['id']}.png"}
        shutil.copyfile(CHARACTERS / char["image"], INPUT / names["ref"])
        prompt = akatz_prompt(mark, char)
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        graph = akatz_graph(names, {**mark, "pick": _pick(mark["x"])}, prompt, int(seed), swap["frames"] / 24)
        card = {"kind": "Character swap", "tags": ["akatz Character Swap V1.5",
                                                   "Model: H3 Ref2VA int8 + swap LoRA + Turbo 8 LoRA",
                                                   "Attention: int8 (kitchen)", f"Resolution setting {AKATZ_RESOLUTION}",
                                                   "8 steps", f"{swap['frames']} frames ({swap['seconds']} s), "
                                                   "124-frame windows inside the graph",
                                                   f"Who to replace (SAM mask, {_pick(mark['x'])} match): {mark['description']}",
                                                   "Characters: " + ", ".join(who)],
                "windows": akatz_windows(swap["frames"]), "steps": 8, "variant": "akatz"}
        return _submit(swap_id, graph, card, seed)
    if engine == "openjutsu":
        return _render_openjutsu(swap_id, swap, source, seed, characters_by_id)
    built = [_window_spec(swap, k, painted, characters_by_id) for k in range(len(windows))]
    (folder / "prompt.txt").write_text("\n\n".join(
        f"[Window {k + 1}: {ts(w['start'])}-{ts(w['start'] + w['frames'])}]\n{w['prompt']}" for k, w in enumerate(built)),
        encoding="utf-8")
    if len(windows) == 1:          # the shipped single-window graph, as tested
        graph = build_graph(swap, {"source": source, "refs": built[0]["refs"]}, built[0]["prompt"])
        graph["set"]["12.seed"] = int(seed)
        tags = [f"{swap['frames']} frames", f"{len(built[0]['refs'])} picture(s)" + (", pinned" if painted else "")]
    elif len(windows) <= SEGMENT_WINDOWS:
        graph = multi_window_graph(built, int(seed), source)
        tags = [f"{swap['frames']} frames ({swap['seconds']} s) in {len(windows)} chained windows, {LOCK} frames "
                "locked at each join"]
    else:
        segments = plan_segments(windows)
        _set(swap_id, built=built, segments=segments)
        return _submit_segment(swap_id, 0)
    card = {"kind": "Character swap", "tags": ["Viggle Remake", mode_tag, "Model: Viggle swap int8",
                                               "Attention: int8 (kitchen)", *tags, "Short edge 736",
                                               "6 steps per window", "Characters: " + ", ".join(who)],
            "windows": len(windows), "steps": 6, "variant": "viggle"}
    return _submit(swap_id, graph, card, seed)


OPENJUTSU_PATCH = COMFY_CODE / "custom_nodes" / "ComfyUI-Fantastic-MiniMaxH3-PromptBuilder" / "video_edit.py"
OPENJUTSU_PATCH_MARK = "comfy-mobile-bridge #58"


def _render_openjutsu(swap_id: str, swap: dict, source: str, seed: str, characters_by_id: dict) -> dict:
    if swap["frames"] / 24 > openjutsu.MAX_SECONDS:
        raise ValueError(f"Openjutsu was tested up to {openjutsu.MAX_SECONDS:g} s; use Viggle for longer clips")
    try:
        patched = OPENJUTSU_PATCH_MARK in OPENJUTSU_PATCH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        patched = False
    if not patched:
        raise ValueError("Openjutsu needs the Fantastic PromptBuilder pack with the bridge patch "
                         "(patches/fantastic-promptbuilder-empty-mask.patch) in ComfyUI")
    settings = swap.get("openjutsu") or {"resolution": "736p", "remove_hair": False}
    first = {}                                     # one picture and role per character: its first mark's description
    for mark in swap["marks"]:
        first.setdefault(mark["character_id"], mark)
    people, chars = [], []
    whos = openjutsu.positions([m["x"] for m in first.values()])
    for (cid, mark), who in zip(first.items(), whos):
        char = characters_by_id[cid]
        picture = f"swap_char_{char['id']}.png"
        shutil.copyfile(CHARACTERS / char["image"], INPUT / picture)
        people.append((picture, openjutsu.role_text(mark["description"], who)))
        chars.append((char, mark))
    (SWAPS / swap_id / "prompt.txt").write_text(
        "\n".join(f"Openjutsu role {k}: {role}" for k, (_p, role) in enumerate(people, 1)), encoding="utf-8")
    graph = {"base": openjutsu.build_graph(source, people, int(seed), settings["resolution"],
                                           settings["remove_hair"])}
    width, height = openjutsu.canvas(swap["width"], swap["height"], settings["resolution"])
    card = {"kind": "Character swap", "tags": [
        "Openjutsu (D3voz) Advanced swap", "Model: H3 Ref2VA int8 + DMAD LoRA, 6 steps, kitchen attention",
        f"{settings['resolution']} ({width}x{height}), 6 s pieces with 39 frames of overlap (Context Loop)",
        "SAM 3.1 mask + Qwen3-VL 8B describer; grey-mannequin motion reference",
        *[f"Picture {k} ({char['name']}) replaces: {mark['description']}" for k, (char, mark) in enumerate(chars, 1)],
        "Hair eraser on (source hair removed from the mannequin)" if settings["remove_hair"] else "Hair eraser off",
        "Pieces without the people keep the source"],
        "windows": max(1, -(-swap["frames"] // (openjutsu.CLIP_SECONDS * 24))), "steps": openjutsu.STEPS,
        "variant": "openjutsu"}
    return _submit(swap_id, graph, card, seed)


def rerender_from(swap_id: str, part: int, folder_ref: tuple[str, str] | None = None, only: bool = False) -> dict:
    """Re-render only from a part's window onward (after a repaint or new marks there): the finished video before that
    window is kept, the rest is rendered opening with the finished video's last frames (Remake Prefix, as at every
    window join), and the two are stitched. Every later window has to follow, since each opens with the frames of
    the one before; earlier windows stay as they are (user, 2026-11-09). `only`: render just that one window and keep
    the old video after it too (user: "render only window 2 and restitch it"); the next window was rendered from the
    old frames, so the hand-over to it may show a small change."""
    swap = get_swap(swap_id)
    if swap["status"] not in ("done", "marking", "review", "failed") or (swap.get("engine") or "viggle") != "viggle":
        raise ValueError("Re-rendering a part needs a finished Viggle swap")
    previous = swap.get("last_output")
    if not previous or not Path(previous).is_file():
        raise ValueError("There is no finished render of this swap to keep")
    if not 0 <= part < len(swap["shots"]):
        raise ValueError("Unknown part")
    painted = swap.get("mode") == "painted"
    unpainted = [p["index"] + 1 for p in swap["shots"] if _shot_marks(swap, p["index"]) and not p.get("painted")]
    if painted and unpainted:
        raise ValueError(f"Part {', '.join(map(str, unpainted))} needs a painted frame")
    windows = windows_of(swap)
    first = swap["shots"][part].get("window", 0)
    if first == 0:
        return render(swap_id, folder_ref or (tuple(swap["folder_ref"]) if swap.get("folder_ref") else None))
    kept = SWAPS / swap_id / "previous.mp4"
    shutil.copyfile(previous, kept)
    characters_by_id = {c["id"]: c for c in list_characters()}
    built = [_window_spec(swap, k, painted, characters_by_id) if k >= first else None for k in range(len(windows))]
    segments = plan_segments(windows, first)
    tail = None
    if only:
        segments = segments[:1]
        segments[0]["windows"] = [first]
        start, frames = windows[first]
        keep = keep_ranges(windows)[first]
        segments[0]["src"] = [start, start + frames]
        segments[0]["keep"] = [start + keep[0], start + keep[1]]
        if first + 1 < len(windows):
            tail = {"path": str(kept), "from": start + keep[1]}
    segments[0]["prefix"] = {"path": str(kept), "at": windows[first][0]}
    _set(swap_id, built=built, segments=segments, final_job=None, error=None, tail=tail,
         head={"path": str(kept), "frames": windows[first][0] + LOCK},
         folder_ref=list(folder_ref) if folder_ref else swap.get("folder_ref"))
    return _submit_segment(swap_id, 0)


def _cut(source: Path, start: int, end: int, out: Path) -> None:
    """Frames [start, end) of the 24 fps source, with their sound, as their own file."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-vf",
                    f"trim=start_frame={start}:end_frame={end},setpts=N/24/TB", "-af",
                    f"atrim=start={start / 24}:end={end / 24},asetpts=PTS-STARTPTS", "-r", "24", "-fps_mode", "cfr",
                    "-c:v", "libx264", "-crf", "10", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", str(out)], check=True, capture_output=True, timeout=1800)


def _submit_segment(swap_id: str, k: int) -> dict:
    swap = get_swap(swap_id)
    segments, built, windows = swap["segments"], swap["built"], windows_of(swap)
    seg = segments[k]
    a, b = seg["src"]
    source = f"swap_{swap_id}_part{k}_source.mp4"
    _cut(SWAPS / swap_id / "source.mp4", a, b, INPUT / source)
    keeps_all = keep_ranges(windows)
    wins = [{**built[i], "start": built[i]["start"] - a} for i in seg["windows"]]
    prefix = None
    if k == 0 and seg.get("prefix"):              # re-render from a part: open with the finished video's frames
        name = f"swap_{swap_id}_previous.mp4"
        shutil.copyfile(seg["prefix"]["path"], INPUT / name)
        prefix = {"file": name, "at": seg["prefix"]["at"]}
    elif k:
        previous = segments[k - 1]
        name = f"swap_{swap_id}_part{k - 1}_out.mp4"
        shutil.copyfile(previous["output"], INPUT / name)
        prefix = {"file": name, "at": windows[seg["windows"][0]][0] - previous["keep"][0]}
    ka, kb = seg["keep"]
    seed = str(random.getrandbits(63))
    graph = multi_window_graph(wins, int(seed), source, [keeps_all[i] for i in seg["windows"]], prefix,
                               ((ka - a) / 24, (kb - ka) / 24))
    characters = {c["id"]: c["name"] for c in list_characters()}
    who = sorted({characters.get(m["character_id"], "?") for m in swap["marks"]})
    painted = swap.get("mode") == "painted"
    card = {"kind": "Character swap", "tags": [
        "Viggle Remake", f"Mode: {'painted frames' if painted else 'character image only'}",
        (f"Re-render from {ts(ka)}: opens with the previous render's frames" if swap.get("head") and k == 0 else
         f"Render part {k + 1} of {len(segments)}: {ts(ka)}-{ts(kb)} of {swap['seconds']} s"),
        f"{len(wins)} chained windows" + (", opens with the previous part's last frames" if k else ""),
        "Model: Viggle swap int8", "Attention: int8 (kitchen)", "Short edge 736", "6 steps per window",
        "Characters: " + ", ".join(who)], "windows": len(wins), "steps": 6, "variant": "viggle"}
    out = _submit(swap_id, graph, card, seed, f" · part {k + 1}/{len(segments)}")
    segments = get_swap(swap_id)["segments"]
    segments[k]["job_id"] = out["job_id"]
    return _set(swap_id, segments=segments, stage=f"Render part {k + 1} of {len(segments)}")


def _finish(swap_id: str) -> dict:
    """All parts rendered: join them (no overlap, same encoding: stream copy) with the source sound, then show the
    full clip in the bridge as its own job."""
    swap = get_swap(swap_id)
    folder = SWAPS / swap_id
    name = f"swap_{swap_id}_full.mp4"
    head = swap.get("head")
    if head:                                       # re-render from a part: the kept start + the new rest
        tail = swap.get("tail")
        inputs = ["-i", head["path"]] + [arg for s in swap["segments"] for arg in ("-i", s["output"])]
        n = len(swap["segments"]) + 1
        labels = "[h]" + "".join(f"[s{i}]" for i in range(1, n))
        graph = (f"[0:v]trim=end_frame={head['frames']},setpts=PTS-STARTPTS[h];"
                 + "".join(f"[{i}:v]setpts=PTS-STARTPTS[s{i}];" for i in range(1, n)))
        if tail:                                   # the old video after the re-rendered window
            inputs += ["-i", tail["path"]]
            graph += f"[{n}:v]trim=start_frame={tail['from']},setpts=PTS-STARTPTS[t];"
            labels += "[t]"
            n += 1
        graph += labels + f"concat=n={n}:v=1:a=0,setpts=N/24/TB[v]"
        subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-i", str(folder / "source.mp4"),
                        "-filter_complex", graph, "-map", "[v]", "-map", f"{n}:a:0?", "-r", "24", "-fps_mode", "cfr",
                        "-c:v", "libx264", "-crf", "12", "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-t", f"{swap['frames'] / 24:.4f}", str(INPUT / name)],
                       check=True, capture_output=True, timeout=1800)
    else:
        listing = folder / "parts.txt"
        listing.write_text("".join(f"file '{Path(s['output']).as_posix()}'\n" for s in swap["segments"]),
                           encoding="utf-8")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-i", str(folder / "source.mp4"), "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-t", f"{swap['frames'] / 24:.4f}", str(INPUT / name)],
                       check=True, capture_output=True, timeout=1800)
    graph = {"base": PASSTHROUGH_GRAPH, "set": {"1.file": name}}
    who = sorted({c["name"] for c in list_characters() if c["id"] in {m["character_id"] for m in swap["marks"]}})
    tail = swap.get("tail")
    joined = (f"Re-rendered {ts(head['frames'])}-{ts(tail['from'])}, the rest kept from the previous render" if head and tail
              else f"Kept 0-{ts(head['frames'])} of the previous render + re-rendered the rest" if head
              else f"Full clip: {len(swap['segments'])} render parts joined")
    card = {"kind": "Character swap", "tags": ["Viggle Remake", joined,
                                               f"{swap['frames']} frames ({swap['seconds']} s)", "Source sound",
                                               "Characters: " + ", ".join(who)], "windows": 1, "steps": 0,
            "variant": "swap_join"}
    out = _submit(swap_id, graph, card, str(random.getrandbits(63)), " · full clip")
    return _set(swap_id, final_job=out["job_id"], stage="Joining the parts")


_FOLLOW_LOCK = threading.Lock()


def follow(get_job) -> None:
    """Move rendering swaps along: a finished part starts the next part, the last part starts the joining job, and
    the joining job (or a single job) finishes the swap. Runs in the watcher thread, so bridge restarts resume."""
    with _FOLLOW_LOCK:
        for swap in list_swaps(limit=100000):
            if swap.get("status") != "rendering" or not swap.get("job_id"):
                continue
            try:
                job = get_job(swap["job_id"], public=False)
                if not job or job["status"] not in ("completed", "failed", "canceled"):
                    continue
                if job["status"] != "completed":
                    _set(swap["id"], status="failed", stage="", error=(job.get("error") or job["status"])[:600])
                    continue
                segments = swap.get("segments")
                if not segments or swap.get("final_job") == swap["job_id"]:
                    _set(swap["id"], status="done", stage="", error=None, last_output=job.get("output_path"))
                    continue
                k = next(i for i, s in enumerate(segments) if s["job_id"] == swap["job_id"])
                segments[k]["output"] = job["output_path"]
                _set(swap["id"], segments=segments)
                if k + 1 < len(segments):
                    _submit_segment(swap["id"], k + 1)
                else:
                    _finish(swap["id"])
            except Exception as exc:  # the user sees why on the sheet
                _set(swap["id"], status="failed", stage="", error=f"{type(exc).__name__}: {exc}"[:600])


_QUEUE = None


def set_job_queue(queue) -> None:
    """main.py hands in the function that inserts a swap job row (backend.main._queue_swap_job)."""
    global _QUEUE
    _QUEUE = queue


def output_size(swap: dict, variant: str) -> tuple[int, int]:
    """The job's expected video size (the file's own size is in its ffprobe metrics). Viggle renders on its
    1280x736 / 736x1280 canvas; akatz at its "480" setting measured 512x928 for a 9:16 clip."""
    portrait = swap["height"] > swap["width"]
    if variant == "openjutsu":
        return openjutsu.canvas(swap["width"], swap["height"], (swap.get("openjutsu") or {}).get("resolution", "736p"))
    if variant == "akatz":
        return (512, 928) if portrait else (928, 512)
    return (736, 1280) if portrait else (1280, 736)


def _submit(swap_id: str, graph: dict, card: dict, seed: str, label_suffix: str = "") -> dict:
    if _QUEUE is None:
        raise RuntimeError("The swap job queue is not set up")
    swap = get_swap(swap_id)
    variant = card.get("variant", "viggle")
    width, height = output_size(swap, variant)
    models = (AKATZ_MODELS if variant == "akatz" else VIGGLE_MODELS if variant == "viggle"
              else openjutsu.MODELS if variant == "openjutsu" else [])
    options = {"swap_id": swap_id, "graph": graph, "card": card, "windows": card.get("windows", 1),
               "steps": card.get("steps", 0), "models": models}
    job_id = _QUEUE(title=f"Character swap · {swap['title'][:80]}{label_suffix}", variant=variant,
                    steps=card.get("steps") or 1, width=width, height=height, duration=swap["frames"] / 24,
                    portrait=swap["height"] > swap["width"], seed=seed, options=options,
                    folder_ref=swap.get("folder_ref"), source_job_id=swap.get("source_job_id"))
    return _set(swap_id, status="rendering", job_id=job_id, seed=seed)
