"""Upscale or interpolate a finished video as its own job (engine "post").

Only what was measured in the lab on the RTX 3080 10 GB (issue #37, D:/h3-omnilab/tests: Missed Bus, The Package
remake, The Last Fold, Pirate & Inventor) is allowed:

- Interpolation 2x (24 -> 48 fps) with RIFE 4.26 (~21 s per 5 s shot at 1632x928, ~1.6 GB) or FILM (~77 s, ~7 GB).
- Upscale with Lanczos (~31-36 s per shot to 2560x1456, also run on 247-frame 48 fps clips) or Real-ESRGAN x2plus
  then a Lanczos fit (~235 s per shot to 2560x1456, ~4 GB).
- RIFE, FILM and Real-ESRGAN: whole clips of up to 150 frames (5 s at 30 fps). RIFE and Real-ESRGAN up to 1080p
  (1920x1080 30 fps uploads: RIFE 31 s / 2.5 GB, Real-ESRGAN 378 s / 6.1 GB, 2026-11-08). FILM stays at 1632x928:
  at 1080p it peaked at 9.77 GB, the edge where this card spills. Lanczos: up to 300 frames (a 5 s 60 fps clip, 73 s).
  Smoothing takes sources up to 30 fps. Longer clips are refused until they are tested; FILM at 2560x1456 spilled
  past 10 GB (12+ min per window).
"""
from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

INTERPOLATION_MODELS = {"rife": "rife_v4.26.safetensors", "film": "film_net_fp16.safetensors"}
UPSCALE_MODELS = {"gan": "RealESRGAN_x2plus.pth"}
METHODS = {"interpolate": ("rife", "film"), "upscale": ("lanczos", "gan")}
METHOD_LABELS = {"rife": "RIFE 4.26", "film": "FILM", "lanczos": "Lanczos", "gan": "Real-ESRGAN x2"}

MAX_SOURCE = {"rife": (1920 * 1080, "1920x1080"), "gan": (1920 * 1080, "1920x1080"),
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
        max_frames = (GAN_SMOOTHED_MAX_FRAMES if method == "gan" and pixels <= GAN_SMOOTHED_MAX_PIXELS
                      else TESTED_MAX_FRAMES)
        if frames > max_frames:
            raise ValueError(f"{METHOD_LABELS[method]} was tested on clips of up to {max_frames} frames at this size "
                             f"(5 s, or a smoothed 5 s shot for Real-ESRGAN up to 1632x928); this clip has {frames}")
    elif frames > LANCZOS_MAX_FRAMES:
        raise ValueError(f"Lanczos was tested up to 300 frames (5 s at 60 fps); this clip has {frames}")
    options = {"operation": operation, "method": method, "source_width": width, "source_height": height,
               "source_frames": frames, "source_fps": round(fps, 3), "source_duration": round(source["duration"], 3),
               "audio": bool(source["audio"])}
    if operation == "interpolate":
        if fps <= 0 or fps > INTERPOLATE_MAX_FPS:
            raise ValueError(f"Smoothing was tested on sources up to 30 fps; this one is {fps:g} fps")
        options.update(width=width, height=height, fps=round(fps * 2, 3), frames=frames * 2 - 1)
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


def post_node_classes(options: dict) -> set[str]:
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


def post_title(options: dict, source_prompt: str) -> str:
    label = METHOD_LABELS[options["method"]]
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
