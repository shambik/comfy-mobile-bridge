"""Upscale or interpolate a finished video as its own job (engine "post").

Only what was measured in the lab on the RTX 3080 10 GB (issue #37, D:/h3-omnilab/tests: Missed Bus, The Package
remake, The Last Fold, Pirate & Inventor) is allowed:

- Interpolation 2x (24 -> 48 fps) with RIFE 4.26 (~21 s per 5 s shot at 1632x928, ~1.6 GB) or FILM (~77 s, ~7 GB).
- Upscale with Lanczos (~31-36 s per shot to 2560x1456, also run on 247-frame 48 fps clips) or Real-ESRGAN x2plus
  then a Lanczos fit (~235 s per shot to 2560x1456, ~4 GB).
- RIFE, FILM and Real-ESRGAN: whole clips of up to 150 frames (5 s at 30 fps). RIFE and Real-ESRGAN up to 1080p
  (1920x1080 30 fps uploads: RIFE 31 s / 2.5 GB, Real-ESRGAN 378 s / 6.1 GB, 2026-11-08). FILM stays at 1632x928:
  at 1080p it peaked at 9.77 GB, the edge where this card spills. Lanczos: up to 300 frames (a 5 s 60 fps clip, 73 s).
  Smoothing takes sources up to 30 fps. FILM at 2560x1456 spilled past 10 GB (12+ min per window).
- Longer clips (issue #44): one run of the 18 s, 432-frame 736x1280 clip worked for every method; longer or bigger
  clips are processed in chunks inside one job (see CHUNKED_METHODS); Visual Enhancer is never chunked.
- Visual Enhancer v22.0 (issue #39, lab 2026-11-08/09), run through the user's own VE_CLI.exe, not ComfyUI:
  RTX Video Super Resolution upscale (11-13 s per shot to 2560 wide, ~1.5 GB; 1920 wide 7 s) and FSR 3 frame
  generation x2 (5-7.5 s, <1 GB). Tested on 1632x928 24 fps (124 frames) and 1920x1080 / 1080x1920 30 fps
  (150 frames); as app jobs, with the crop and encode, 6-18 s and 0.9-1.7 GB. Its
  license forbids redistribution, so the app never ships it: `visual_enhancer_cli` in config.local.json points at it.
"""
from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from .config import AUDIO_VAE, FL2VA_MODEL, FUSED_VIDEO_VAE, MODELS, PIKA_FL2VA_LORA, SKIN_MODELS, TEXT_ENCODER, TURBO_LORAS

INTERPOLATION_MODELS = {"rife": "rife_v4.26.safetensors", "film": "film_net_fp16.safetensors"}
UPSCALE_MODELS = {"gan": "RealESRGAN_x2plus.pth"}
METHODS = {"interpolate": ("rife", "film", "fsr3"), "upscale": ("lanczos", "gan", "rtx")}
METHOD_LABELS = {"rife": "RIFE 4.26", "film": "FILM", "lanczos": "Lanczos", "gan": "Real-ESRGAN x2",
                 "rtx": "RTX Video Super Resolution", "fsr3": "FSR 3 frame generation",
                 "h3detail": "RTX VSR + H3 detail"}
# Methods the worker runs through Visual Enhancer's VE_CLI.exe instead of a ComfyUI graph.
VISUAL_ENHANCER_METHODS = ("rtx", "fsr3")
VISUAL_ENHANCER_TIMEOUT_SECONDS = 15 * 60  # the lab runs took 5-19 s; a hung run must not hold the queue

# RIFE and FSR 3 also smooth upscaled clips (issue #41): whole 2560x1440 shots in the lab took RIFE 37-47 s at 2.3 GB
# and FSR 3 13-16 s at 1.5 GB. FILM stays at 1632x928 (at 2560x1456 it used 9.8 GB plus 4 GB of shared memory).
SMOOTH_UPSCALED_MAX = (2560 * 1456, "2560x1456")
MAX_SOURCE = {"rife": SMOOTH_UPSCALED_MAX, "gan": (1920 * 1080, "1920x1080"),
              "rtx": (1920 * 1080, "1920x1080"), "fsr3": SMOOTH_UPSCALED_MAX,
              "film": (1632 * 928, "1632x928 (1.5 MP); at 1080p it nearly fills the 10 GB card, use RIFE")}
TESTED_MAX_FRAMES = 150             # one 5 s clip at 30 fps, whole-clip jobs
GAN_SMOOTHED_MAX_FRAMES = 248       # Real-ESRGAN on a smoothed 48 fps shot up to 1632x928: 247 frames in one pass,
GAN_SMOOTHED_MAX_PIXELS = 1632 * 928  # 454 s, 6.8 GB VRAM, 31 GB ComfyUI RAM (3 lab windows of 83 frames: ~470 s)
LANCZOS_MAX_FRAMES = 300            # a 5 s 60 fps clip, or a smoothed 30 fps clip (299 frames)
INTERPOLATE_MAX_FPS = 30.0          # 24 and 30 fps sources were tested; smoothing a 48/60 fps clip is not
UPSCALE_LONG_SIDES = (1920, 2560)   # 2560 = the measured 2560x1456 target class
UPSCALE_MAX_PIXELS = 2560 * 1456
# Near-16:9 and near-9:16 sources (the app's sizes are 1.75-1.83, not exactly 1.78) go to the standard delivery
# sizes, 1920x1080 / 2560x1440 and the portrait pair, with a small center crop. Other shapes keep their own.
STANDARD_RATIO_TOLERANCE = 0.04


# Long clips (issue #44): # a clip longer than the flow was tested on in ONE run is cut into chunks inside one job, each chunk is processed like
# a short clip, and the results are joined in order with the source's sound. Smoothing chunks borrow the next chunk's
# first frame so the midpoint at every seam is still made. Whole-clip test on the 18 s swap clip (432 frames, 736x1280,
# tests/post_full_clip): RIFE 42 s / 1.5 GB, FILM 143 s / 4.7 GB, Lanczos 110 s / 1.1 GB, Real-ESRGAN x2 to 1472x2560
# 530 s / 6.8 GB, all in one run. The ComfyUI methods hold the whole clip in RAM, so their single-run limit is that
# many frame-pixels (bigger frames: fewer frames per run). Visual Enhancer (RTX VSR 48 s, FSR 3 14 s on the same clip)
# streams frame by frame and is never chunked.
WHOLE_RUN_PIXEL_FRAMES = 432 * 736 * 1280
CHUNKED_METHODS = ("rife", "film", "gan", "lanczos")


def single_run_frames(method: str, width: int, height: int) -> int | None:
    """The most frames one run of this method was tested on at this frame size (None: no limit, never chunked)."""
    if method not in CHUNKED_METHODS:
        return None
    return max(TESTED_MAX_FRAMES, WHOLE_RUN_PIXEL_FRAMES // (width * height))


def chunk_plan(method: str, operation: str, frames: int, width: int = 736, height: int = 1280) -> list[dict]:
    """The chunks of a long clip ({start, count, borrow}); empty when one run covers it."""
    size = single_run_frames(method, width, height)
    if size is None or frames <= size:
        return []
    if operation == "interpolate":
        size -= 1                                   # a chunk also reads the next chunk's first frame
    pieces = -(-frames // size)                     # as few chunks as possible, of even length
    even = -(-frames // pieces)
    chunks, start = [], 0
    while start < frames:
        count = min(even, frames - start)
        chunks.append({"start": start, "count": count,
                       "borrow": operation == "interpolate" and start + count < frames})
        start += count
    return chunks


def chunk_keep(options: dict, chunk: dict) -> int:
    """How many output frames of a chunk go into the joined clip.

    Upscale: one per input frame. RIFE/FILM give 2n-1 frames for n inputs: a chunk that borrowed the next frame keeps
    2n (through the seam midpoint), the last chunk keeps all 2n-1. FSR 3 gives 2n (it also adds one after the last
    frame): keep 2n, so the whole clip ends like a single FSR 3 run."""
    n = chunk["count"]
    if options["operation"] == "upscale" or options["method"] == "fsr3":
        return n if options["operation"] == "upscale" else 2 * n
    return 2 * n if chunk["borrow"] else 2 * n - 1


def probe_video(path: Path) -> dict:
    """Width, height, frame count, frame rate, duration and whether there is sound."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,width,height,r_frame_rate,nb_frames:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise ValueError("The source video could not be read")
    data = json.loads(out.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("The source has no video stream")
    fps = float(Fraction(video.get("r_frame_rate") or "0/1")) if video.get("r_frame_rate") else 0.0
    duration = float(data.get("format", {}).get("duration") or 0)
    frames = int(video.get("nb_frames") or round(duration * fps))
    return {"width": int(video["width"]), "height": int(video["height"]), "fps": fps, "frames": frames,
            "duration": duration, "audio": any(s.get("codec_type") == "audio" for s in data.get("streams", []))}


def upscale_size(width: int, height: int, long_side: int) -> tuple[int, int]:
    """Standard 16:9 / 9:16 size when the source is close to it; otherwise its own shape on multiples of 16."""
    landscape = width >= height
    standard = 16 / 9 if landscape else 9 / 16
    if abs((width / height) / standard - 1) <= STANDARD_RATIO_TOLERANCE:
        short = long_side * 9 // 16
        return (long_side, short) if landscape else (short, long_side)
    scale = long_side / max(width, height)
    return (round(width * scale / 16) * 16, round(height * scale / 16) * 16)


def crop_percent(width: int, height: int, target_width: int, target_height: int) -> float:
    """How much of the source the center crop removes to reach the target's shape."""
    ratio = (width / height) / (target_width / target_height)
    return round((1 - min(ratio, 1 / ratio)) * 100, 1)


def plan_post_process(source: dict, operation: str, method: str, long_side: int | None = None) -> dict:
    """Check the request against the tested limits and return the stored options (raises ValueError)."""
    if operation not in METHODS:
        raise ValueError("Choose upscale or interpolate")
    if method not in METHODS[operation]:
        raise ValueError(f"{operation.capitalize()} supports: " + ", ".join(METHOD_LABELS[m] for m in METHODS[operation]))
    width, height, frames, fps = source["width"], source["height"], source["frames"], source["fps"]
    pixels = width * height
    if method in MAX_SOURCE:
        max_pixels, max_label = MAX_SOURCE[method]
        if pixels > max_pixels:
            raise ValueError(f"{METHOD_LABELS[method]} was tested on sources up to {max_label}; this one is {width}x{height}")
        if method == "rtx" and fps > INTERPOLATE_MAX_FPS:   # tested on 24 and 30 fps originals, never after smoothing
            raise ValueError(f"RTX Video Super Resolution runs on original clips (24 or 30 fps), not on smoothed ones; "
                             f"this one is {fps:g} fps")
    options = {"operation": operation, "method": method, "source_width": width, "source_height": height,
               "source_frames": frames, "source_fps": round(fps, 3), "source_duration": round(source["duration"], 3),
               "audio": bool(source["audio"])}
    chunks = chunk_plan(method, operation, frames, width, height)
    if chunks:
        options["chunks"] = chunks
    if operation == "interpolate":
        if fps <= 0 or fps > INTERPOLATE_MAX_FPS:
            raise ValueError(f"Smoothing was tested on sources up to 30 fps; this one is {fps:g} fps")
        # FrameInterpolate adds a frame between each pair; FSR 3 also generates one after the last frame.
        options.update(width=width, height=height, fps=round(fps * 2, 3),
                       frames=frames * 2 if method == "fsr3" else frames * 2 - 1)
    else:
        if long_side not in UPSCALE_LONG_SIDES:
            raise ValueError("Upscale targets: long side 1920 or 2560")
        target = upscale_size(width, height, long_side)
        if target[0] * target[1] > UPSCALE_MAX_PIXELS:
            raise ValueError("The target is larger than the tested 2560x1456")
        if target[0] <= width or target[1] <= height:
            raise ValueError(f"The source ({width}x{height}) is already at least that size")
        options.update(width=target[0], height=target[1], fps=round(fps, 3), frames=frames, long_side=long_side,
                       crop_percent=crop_percent(width, height, *target))
    return options


def chunk_cut_command(options: dict, chunk: dict, source: Path, out: Path) -> list[str]:
    """FFmpeg command for one chunk's frames (plus the next chunk's first frame when it borrows one), at the source's
    own frame rate. Without the explicit rate FFmpeg fell back to 25 fps and duplicated frames (145 -> 150), so the
    smoothed chunks drifted away from the source (2026-11-09)."""
    fps = f"{float(options['source_fps']):g}"
    end = chunk["start"] + chunk["count"] + int(chunk["borrow"])
    return ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-an", "-vf",
            f"trim=start_frame={chunk['start']}:end_frame={end},setpts=N/({fps})/TB", "-r", fps,
            "-fps_mode", "cfr", "-c:v", "libx264", "-crf", "10", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            str(out)]


def chunk_join_command(options: dict, parts: list[Path], source: Path, output: Path) -> list[str]:
    """FFmpeg command that joins processed chunks: each chunk's kept frames in order, at the target frame rate,
    cropped to the target for RTX VSR (VE renders at the source's shape), with the source's own sound."""
    fps = float(options["fps"])
    keeps = [chunk_keep(options, chunk) for chunk in options["chunks"]]
    crop = ""
    if options["method"] == "rtx":
        width, height = options["width"], options["height"]
        crop = f",crop={width}:{height}:(iw-{width})/2:(ih-{height})/2,setsar=1"
    graph = [f"[{i}:v]trim=start_frame=0:end_frame={keep},setpts=PTS-STARTPTS[v{i}]" for i, keep in enumerate(keeps)]
    graph.append("".join(f"[v{i}]" for i in range(len(parts)))
                 + f"concat=n={len(parts)}:v=1:a=0,setpts=N/({fps})/TB{crop}[v]")
    command = ["ffmpeg", "-v", "error", "-y"]
    for part in parts:
        command += ["-i", str(part)]
    if options.get("audio"):
        command += ["-i", str(source)]
    command += ["-filter_complex", ";".join(graph), "-map", "[v]", "-r", f"{fps:g}", "-fps_mode", "cfr",
                "-c:v", "libx264", "-crf", "12", "-preset", "medium", "-pix_fmt", "yuv420p"]
    if options.get("audio"):
        command += ["-map", f"{len(parts)}:a:0", "-c:a", "copy", "-t", f"{sum(keeps) / fps:.4f}"]
    return [*command, "-movflags", "+faststart", str(output)]


def uses_visual_enhancer(options: dict) -> bool:
    return options.get("method") in VISUAL_ENHANCER_METHODS


def visual_enhancer_size(options: dict) -> tuple[int, int]:
    """RTX VSR output size with the source's own shape.

    VE stretches to whatever --size it gets, so it renders at the source's shape and the finishing FFmpeg pass
    center-crops to the target, the same way the ComfyUI upscalers do (ImageScale crop=center).
    """
    width, height = options["source_width"], options["source_height"]
    scale = max(options["width"] / width, options["height"] / height)
    return (max(options["width"], round(width * scale / 2) * 2), max(options["height"], round(height * scale / 2) * 2))


def visual_enhancer_command(cli: Path, options: dict, source: Path, output: Path) -> list[str]:
    """VE_CLI arguments for one job (the lab runs used exactly these engines and flags)."""
    if options["method"] == "rtx":
        width, height = visual_enhancer_size(options)
        action = ["upscale", str(source), "--engine", "rtx", "--size", f"{width}x{height}"]
    elif options["method"] == "fsr3":
        action = ["interpolate", str(source), "--interpolator", "fsr3", "--multiplier", "2"]
    else:
        raise ValueError(f"{options['method']} is not a Visual Enhancer method")
    # "best" is visually lossless and a third of "max"; the finishing pass re-encodes at the app's CRF 12 anyway.
    return [str(cli), *action, "-o", str(output), "--codec", "h264", "--container", "mp4", "--quality", "best",
            "--json"]


def visual_enhancer_finish_command(options: dict, rendered: Path, source: Path, output: Path) -> list[str]:
    """Crop to the target size, encode like SaveVideo (H.264 CRF 12) and copy the source's original sound.

    VE re-encodes the sound at a lower bitrate, so its audio track is dropped in favour of the source's.
    """
    width, height = options["width"], options["height"]
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(rendered)]
    if options.get("audio"):
        command += ["-i", str(source)]
    command += ["-map", "0:v:0", "-vf", f"crop={width}:{height}:(iw-{width})/2:(ih-{height})/2,setsar=1",
                "-c:v", "libx264", "-crf", "12", "-preset", "medium", "-pix_fmt", "yuv420p"]
    if options.get("audio"):
        command += ["-map", "1:a:0", "-c:a", "copy", "-shortest"]
    return [*command, "-movflags", "+faststart", str(output)]


def post_node_classes(options: dict) -> set[str]:
    if options["method"] == H3_DETAIL:
        lora_node = "LoraLoaderModelOnly" if options["chain"] == "pika" else "MiniMaxH3TurboLoRA"
        return H3_DETAIL_NODE_CLASSES | {lora_node}
    classes = {"LoadVideo", "GetVideoComponents", "CreateVideo", "SaveVideo"}
    if options["method"] in INTERPOLATION_MODELS:
        classes |= {"FrameInterpolationModelLoader", "FrameInterpolate"}
    else:
        classes.add("ImageScale")
        if options["method"] == "gan":
            classes |= {"UpscaleModelLoader", "ImageUpscaleWithModel"}
    return classes


def post_model_files(options: dict) -> list[tuple[str, str]]:
    """(models subfolder, filename) the job needs."""
    if options["method"] in INTERPOLATION_MODELS:
        return [("frame_interpolation", INTERPOLATION_MODELS[options["method"]])]
    if options["method"] in UPSCALE_MODELS:
        return [("upscale_models", UPSCALE_MODELS[options["method"]])]
    return []


def post_process_workflow(options: dict, video_name: str, prefix: str) -> dict:
    """The ComfyUI graph for one post-process job, saved under the job's prefix with the source's sound."""
    g = {"1": {"class_type": "LoadVideo", "inputs": {"file": video_name}},
         "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}}}
    frames, fps = ["2", 0], ["2", 2]
    method = options["method"]
    if method in INTERPOLATION_MODELS:
        g["10"] = {"class_type": "FrameInterpolationModelLoader", "inputs": {"model_name": INTERPOLATION_MODELS[method]}}
        g["11"] = {"class_type": "FrameInterpolate", "inputs": {"interp_model": ["10", 0], "images": frames, "multiplier": 2}}
        frames, fps = ["11", 0], float(options["fps"])
    else:
        if method == "gan":
            g["10"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALE_MODELS["gan"]}}
            g["11"] = {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["10", 0], "image": frames}}
            frames = ["11", 0]
        g["12"] = {"class_type": "ImageScale", "inputs": {"image": frames, "upscale_method": "lanczos",
                                                         "width": options["width"], "height": options["height"],
                                                         "crop": "center"}}
        frames = ["12", 0]
    g["30"] = {"class_type": "CreateVideo", "inputs": {"images": frames, "fps": fps}}
    if options.get("audio"):
        g["30"]["inputs"]["audio"] = ["2", 1]
    g["31"] = {"class_type": "SaveVideo", "inputs": {"video": ["30", 0], "filename_prefix": prefix, "format": "mp4",
                                                     "format.codec": "h264", "format.codec.encoding": "re-encode",
                                                     "format.codec.encoding.crf": 12.0}}
    return g


# --- RTX VSR + H3 detail (issue #50) -----------------------------------------------------------------------------
# A short second H3 pass over an RTX VSR 1920 clip redraws real detail (fabric, skin, eyes, hair, background) with the
# source clip's own prompt and model, through bbaudio-2025/Comfyui-MMH3-UltimateUpscale (time chunks, audio carried
# through). Lab A/B on the RTX 3080 10 GB, 2026-11-10 (D:/h3-omnilab/tests/h3_detail_pass/RESULTS.md); the user rated
# every one of these good: Missed Bus face and The Package rooftop jump (Singularity Pika flow, 1632x928, 124 frames,
# ~332 s), The Last Fold (Pika flow, 1024x576 -> 1920x1080, two hard cuts, 345 frames, ~900 s, peak RAM 61 GB) and a
# Turbo v4 lip-sync clip (928x1632 -> 1080x1920, 107 frames, ~275 s). Peak VRAM 9.5-9.7 GB in every run.
H3_DETAIL = "h3detail"
# Explicit sigmas (er_sde): a BasicScheduler "denoise" at shift 6 starts much higher (0.40 -> 0.774), which redrew mouths.
H3_DETAIL_LEVELS = {
    "s30": ("0.3, 0.15, 0.0", "light, 0.30"),
    "s45": ("0.45, 0.2, 0.0", "medium, 0.45"),
    "s60": ("0.6, 0.3, 0.0", "strong, 0.60"),
    "s60x3": ("0.6, 0.4, 0.2, 0.0", "strong, 0.60, 3 steps"),
    "s75x3": ("0.75, 0.5, 0.25, 0.0", "strongest, 0.75, 3 steps"),   # painted patterns start to change
}
H3_DETAIL_SIZES = ((1920, 1080), (1080, 1920))   # the RTX VSR 1920 outputs that were tested
H3_DETAIL_FPS = 24.0
H3_DETAIL_MIN_FRAMES = 107                       # the shortest tested clip (4.5 s)
H3_DETAIL_MAX_FRAMES = 362                       # The Last Fold, 15 s (peak RAM 61 GB of 64)
H3_DETAIL_CHUNK = (68, 17, 0.99)                 # time chunk, overlap (frames), frame-0 anchor strength
H3_DETAIL_SEED_MOD = 2 ** 50


def h3_detail_chain(source: dict) -> tuple[str | None, str]:
    """The model chain the H3 detail pass uses for this source clip, or None and why it is not offered.

    Only what the lab ran: the Pika flow (FL2VA int8 + Pika Flex LoRA: the Pika engine, or Singularity with the Pika
    speed LoRA on the base model) on opening-frame clips, and Turbo v4 on lip-sync clips."""
    engine, mode = source.get("engine"), source.get("mode")
    try:
        skin = json.loads(source.get("skin_options_json") or "{}")
    except json.JSONDecodeError:
        skin = {}
    pika = (engine == "pika" and source.get("workflow_variant") != "turbo4") or (
        engine == "singularity" and skin.get("speed_lora") == "pika" and skin.get("model") == "base")
    if pika:
        if mode == "opening":
            return "pika", ""
        return None, "H3 detail was tested on Pika-flow opening-frame clips only"
    if engine == "turbo" and (source.get("turbo_profile") or "v1") == "v4":
        if mode == "lip_sync":
            return "turbo_v4", ""
        return None, "H3 detail was tested on Turbo v4 lip-sync clips only"
    return None, ("H3 detail was tested on Pika-flow opening-frame clips and Turbo v4 lip-sync clips; "
                  "this clip comes from another engine")


def h3_detail_frames(frames: int) -> int:
    """H3 needs 17n+5 frames: the most such frames that fit (the end of the clip is trimmed)."""
    return (frames - 5) // 17 * 17 + 5 if frames >= 5 else 0


def plan_h3_detail(rtx: dict, original: dict, level: str | None) -> dict:
    """Check an RTX VSR clip and its original H3 clip against the tested limits; return the stored options.

    `rtx` is the probe of the RTX VSR output, `original` the job row the RTX VSR job was made from (raises ValueError).
    """
    if level not in H3_DETAIL_LEVELS:
        raise ValueError("Choose a detail strength: " + ", ".join(label for _, label in H3_DETAIL_LEVELS.values()))
    chain, why = h3_detail_chain(original)
    if not chain:
        raise ValueError(why)
    width, height, fps, frames = rtx["width"], rtx["height"], rtx["fps"], rtx["frames"]
    if (width, height) not in H3_DETAIL_SIZES:
        raise ValueError(f"H3 detail runs on RTX VSR 1920 clips (1920x1080 or 1080x1920); this one is {width}x{height}")
    if abs(fps - H3_DETAIL_FPS) > 0.01:
        raise ValueError(f"H3 detail was tested on 24 fps clips; this one is {fps:g} fps")
    keep = h3_detail_frames(frames)
    if keep < H3_DETAIL_MIN_FRAMES:
        raise ValueError(f"H3 detail was tested on clips of {H3_DETAIL_MIN_FRAMES} frames or more; this one has {frames}")
    if keep > H3_DETAIL_MAX_FRAMES:
        raise ValueError(f"H3 detail was tested on clips of up to {H3_DETAIL_MAX_FRAMES} frames (15 s); "
                         f"this one has {frames}")
    sigmas, label = H3_DETAIL_LEVELS[level]
    return {"operation": "upscale", "method": H3_DETAIL, "detail": level, "detail_label": label, "sigmas": sigmas,
            "chain": chain, "prompt": original.get("prompt") or "", "original_job_id": original["id"],
            "source_width": width, "source_height": height, "source_frames": frames, "source_fps": round(fps, 3),
            "source_duration": round(rtx["duration"], 3), "audio": bool(rtx["audio"]),
            "width": width, "height": height, "fps": round(fps, 3), "frames": keep, "trimmed_frames": frames - keep,
            "long_side": max(width, height), "crop_percent": 0.0}


def h3_detail_input_command(options: dict, source: Path, out: Path) -> list[str]:
    """Copy the RTX VSR clip for the job, trimmed to the 17n+5 frames H3 takes (sound cut to the same length)."""
    frames, fps = options["frames"], float(options["fps"])
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-frames:v", str(frames), "-t", f"{frames / fps:.6f}",
               "-c:v", "libx264", "-crf", "8", "-preset", "medium", "-pix_fmt", "yuv420p"]
    command += ["-c:a", "aac", "-b:a", "320k"] if options.get("audio") else ["-an"]
    return [*command, "-movflags", "+faststart", str(out)]


def h3_detail_prompt(options: dict) -> str:
    """The source prompt, without the People LoRA trigger line (that LoRA is not part of the pass)."""
    lines = (options.get("prompt") or "").strip().splitlines()
    while lines and lines[0].strip().lower() == "r34l1sm":
        lines.pop(0)
    return "\n".join(lines).strip()


def h3_detail_workflow(options: dict, video_name: str, prefix: str, seed: int) -> dict:
    """The lab graph: RTX clip -> 32-px grid -> H3 video/audio encode -> MMH3 Ultimate Upscale with the source's prompt
    and model (int8 kitchen attention, frame 0 as the first frame, er_sde, explicit sigmas, time chunks) -> tiled
    decode -> back to the RTX size, with the clip's own sound, CRF 12."""
    out_w, out_h, frames = options["width"], options["height"], options["frames"]
    w, h = -(-out_w // 32) * 32, -(-out_h // 32) * 32
    chunk, overlap, anchor = H3_DETAIL_CHUNK
    g = {"1": {"class_type": "LoadVideo", "inputs": {"file": video_name}},
         "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
         "3": {"class_type": "ImageScale", "inputs": {"image": ["2", 0], "upscale_method": "lanczos", "width": w,
                                                      "height": h, "crop": "disabled"}},
         "4": {"class_type": "VAELoader", "inputs": {"vae_name": FUSED_VIDEO_VAE}},
         "5": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
         "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["3", 0], "vae": ["4", 0]}},
         "7": {"class_type": "VAEEncodeAudio", "inputs": {"audio": ["2", 1], "vae": ["5", 0]}},
         "8": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["6", 0], "audio_latent": ["7", 0]}},
         "9": {"class_type": "ImageFromBatch", "inputs": {"image": ["3", 0], "batch_index": 0, "length": 1}},
         "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"}},
         "11": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
             "clip": ["10", 0], "vae": ["4", 0], "prompt": h3_detail_prompt(options), "width": w, "height": h,
             "length": frames, "first_frame": ["9", 0]}},
         "20": {"class_type": "UNETLoader", "inputs": {"unet_name": FL2VA_MODEL, "weight_dtype": "default"}}}
    if options["chain"] == "pika":
        g["21"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["20", 0], "lora_name": PIKA_FL2VA_LORA,
                                                                   "strength_model": 1.0}}
    else:
        g["21"] = {"class_type": "MiniMaxH3TurboLoRA", "inputs": {"model": ["20", 0], "lora_name": TURBO_LORAS["v4"],
                                                                  "strength": 1.0, "low_vram": True}}
    g["22"] = {"class_type": "ModelAttentionBackend", "inputs": {"model": ["21", 0], "attention": "comfy kitchen attention"}}
    g["30"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed) % H3_DETAIL_SEED_MOD}}
    g["31"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "er_sde"}}
    g["32"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": options["sigmas"]}}
    g["33"] = {"class_type": "MMH3TemporalSplitParams", "inputs": {"chunk_length": chunk, "temporal_overlap": overlap,
                                                                   "anchor_strength": anchor}}
    g["40"] = {"class_type": "MMH3UltimateUpscale", "inputs": {
        "model": ["22", 0], "conditioning": ["11", 0], "latent": ["8", 0], "noise": ["30", 0], "sampler": ["31", 0],
        "sigmas": ["32", 0], "cfg": 1.0, "temporal_split_param": ["33", 0]}}
    g["41"] = {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["40", 0], "vae": ["4", 0], "tile_size": 512,
                                                          "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}}
    g["42"] = {"class_type": "ImageScale", "inputs": {"image": ["41", 0], "upscale_method": "lanczos", "width": out_w,
                                                      "height": out_h, "crop": "disabled"}}
    g["43"] = {"class_type": "CreateVideo", "inputs": {"images": ["42", 0], "fps": float(options["fps"])}}
    if options.get("audio"):
        g["43"]["inputs"]["audio"] = ["2", 1]
    g["44"] = {"class_type": "SaveVideo", "inputs": {"video": ["43", 0], "filename_prefix": prefix, "format": "mp4",
                                                     "format.codec": "h264", "format.codec.encoding": "re-encode",
                                                     "format.codec.encoding.crf": 12.0}}
    return g


H3_DETAIL_NODE_CLASSES = {
    "LoadVideo", "GetVideoComponents", "ImageScale", "VAELoader", "VAEEncode", "VAEEncodeAudio", "LTXVConcatAVLatent",
    "ImageFromBatch", "CLIPLoader", "MiniMaxH3ImageToVideo", "UNETLoader", "ModelAttentionBackend", "RandomNoise",
    "KSamplerSelect", "ManualSigmas", "MMH3TemporalSplitParams", "MMH3UltimateUpscale", "VAEDecodeTiled",
    "CreateVideo", "SaveVideo",
}


def post_required_files(options: dict) -> list[Path]:
    """Every model file the job needs, as full paths."""
    if options["method"] == H3_DETAIL:
        lora = (SKIN_MODELS / "loras" / PIKA_FL2VA_LORA if options["chain"] == "pika"
                else MODELS / "loras" / TURBO_LORAS["v4"])
        return [MODELS / "diffusion_models" / FL2VA_MODEL, lora, MODELS / "text_encoders" / TEXT_ENCODER,
                MODELS / "vae" / FUSED_VIDEO_VAE, MODELS / "vae" / AUDIO_VAE]
    return [MODELS / folder / name for folder, name in post_model_files(options)]


def post_title(options: dict, source_prompt: str) -> str:
    label = METHOD_LABELS[options["method"]]
    if options["method"] == H3_DETAIL:
        head = f"{label} ({options['detail_label']}) · {options['width']}x{options['height']}"
        return f"{head} · {source_prompt.strip()[:160]}"
    if options["operation"] == "interpolate":
        head = f"{label} 2x · {options['source_fps']:g} -> {options['fps']:g} fps"
    else:
        head = f"{label} upscale · {options['source_width']}x{options['source_height']} -> {options['width']}x{options['height']}"
    return f"{head} · {source_prompt.strip()[:160]}"


UPLOAD_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm", "video/x-matroska": ".mkv"}
UPLOAD_MAX_BYTES = 500 * 1024 * 1024
UPLOAD_MAX_SECONDS = 60.0


def prepare_upload(raw: Path, target: Path) -> dict:
    """Re-encode an uploaded video to what LoadVideo reads reliably and probe it.

    Phone clips often carry a rotation flag, a variable frame rate or HEVC; FFmpeg applies the rotation, makes the
    frame rate constant and writes near-lossless H.264 (CRF 10) with AAC sound, so the job sees what the user sees.
    """
    first = probe_video(raw)
    if first["duration"] > UPLOAD_MAX_SECONDS:
        raise ValueError(f"The video is {first['duration']:.0f} s; upload clips of up to {UPLOAD_MAX_SECONDS:.0f} s")
    out = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-map", "0:v:0", "-map", "0:a:0?",
                          "-c:v", "libx264", "-crf", "10", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                          "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-fps_mode", "cfr",
                          "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(target)],
                         capture_output=True, text=True, timeout=600)
    if out.returncode:
        target.unlink(missing_ok=True)
        raise ValueError("The video could not be converted: " + (out.stderr.strip().splitlines() or ["unknown error"])[-1])
    return probe_video(target)


def aspect_label(width: int, height: int) -> str:
    ratio = width / height
    return min(("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0), ("4:3", 4 / 3), ("3:4", 3 / 4),
               key=lambda item: abs(item[1] - ratio))[0]
