"""Edit a finished or uploaded video with the H3 edit LoRAs (issue #54), as a post job (engine "post", method "h3edit").

Graph (pixaroma Ep41 workflows 04/07/08/09, rebuilt and measured in the lab, D:/h3-omnilab/tests/h3_detail_pass): H3
Ref2VA int8 + Kijai's DMAD 4-step speed LoRA + one Alissonerdx edit LoRA (each 1.0), SigmaShift 12/3, comfy kitchen
attention; MiniMaxH3ReferenceToVideo with the prompt (and the photos), MiniMaxH3AddGuide with the source video and its
sound from frame 0; KSampler 4 steps euler simple CFG 1; the source's own sound on the result.

Only what the lab measured on the RTX 3080 10 GB (2026-11-11, project "Edit LoRAs test") is allowed:
- 480x864, 5 s (124 frames): all four tasks good, ~130 s, 9.5 GB.  10 s (243 frames): good, 286 s.
- 704x1280, 5 s: text edit, style and head swap good, ~5.5 min, up to 9.9 GB. Outfit from photos made NO change at 704
  (2 seeds) and only the cap at 576, so it stays at 480. 704 at 10 s failed in the sampler ("CUDA error: device not
  ready"), so 10 s stays at 480.
- Landscape sizes are the same sizes turned (864x480, 1280x704).

Motion transfer (issue #56, pixaroma workflow 06; lab 2026-11-11, project "Motion transfer test"): the moves of the
video (RT-DETR v4 person box -> SDPose whole-body stick figure -> the Comfy-Org H3 Fun ControlNet Union pose patch,
strength 1) drive a character from a sheet (Ref2VA <Picture 1>) in a new place; DMAD at 0.7, 8 steps. Tai chi and
dance clips with a pixaroma sheet and two app library characters followed the moves: 704x1280 388-397 s (peak
9.96 GB), 480x864 204-210 s (~9 GB). Only 5 s (124 frames) was run, so 10 s is refused.
"""
from __future__ import annotations

import re
from pathlib import Path

from .config import AUDIO_VAE, FUSED_VIDEO_VAE, MODELS, REF2VA_MODEL, TEXT_ENCODER

H3_EDIT = "h3edit"
EDIT_FPS = 24
EDIT_FRAMES = {5: 124, 10: 243}           # H3 takes 17n+5 frames: 5.2 s and 10.1 s at 24 fps
EDIT_MAX_PAD_FRAMES = 12                  # a source up to 0.5 s short is finished by holding its last frame
EDIT_SIZES = {"480": (480, 864), "704": (704, 1280)}   # portrait; a landscape source gets them turned
EDIT_DEFAULT_SIZE = "480"
EDIT_LORA_DIR = "h3_edit"
DMAD_LORA = "minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors"
EDIT_SEED_MOD = 2 ** 50
MAX_PROMPT = 1200
MAX_FACE = 400

# task -> LoRA, trigger, photos (min, max), sizes, lengths (seconds)
EDIT_TASKS = {
    "vfx": {"label": "Text edit", "lora": "minimax_h3_vfx_edit_v1.0_r128.safetensors", "trigger": "vfx_edit:",
            "photos": (0, 0), "sizes": ("480", "704"), "seconds": (5, 10)},
    "outfit": {"label": "Outfit from photos", "lora": "minimax_h3_vfx_edit_v1.0_r128.safetensors", "trigger": "vfx_edit:",
               "photos": (1, 2), "sizes": ("480",), "seconds": (5, 10)},
    "style": {"label": "Style", "lora": "minimax_h3_style_transfer_v1.0_r64.safetensors", "trigger": "style_transfer:",
              "photos": (0, 0), "sizes": ("480", "704"), "seconds": (5, 10)},
    "head": {"label": "Head swap", "lora": "minimax_h3_head_swap_v1.0_r32.safetensors", "trigger": "head_swap:",
             "photos": (1, 1), "sizes": ("480", "704"), "seconds": (5, 10)},
    "motion": {"label": "Motion transfer", "lora": None, "trigger": None,
               "photos": (1, 1), "sizes": ("480", "704"), "seconds": (5,)},
}
MOTION_CONTROLNET = "minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors"   # models/model_patches
MOTION_SDPOSE = "sdpose_wholebody_fp16.safetensors"                                    # models/checkpoints
MOTION_RTDETR = "rt_detr_v4-x-hgnet_fp16.safetensors"                                   # models/diffusion_models
MOTION_DMAD_STRENGTH = 0.7
MOTION_STEPS = 8
MOTION_TEMPLATE = ("The {character}, the person shown in the character sheet <Picture 1>, {action} in {place}. "
                   "The character follows the moves exactly. The camera stays still at chest height, framing the "
                   "character from the knees up. Calm ambient music.")
MAX_MOTION_FIELD = 400
# Styles the LoRA's guide and the pixaroma tests name as working (drawn styles with lines; watercolor barely changes).
EDIT_STYLES = {
    "anime": "a 2D anime style with clean black line art, flat cel shading, soft gradients and vibrant colours",
    "comic": "a comic book illustration with bold black ink outlines, halftone shading and saturated flat colours",
    "manga": "a black and white manga drawing with crisp ink lines, screentone shading and no colour",
    "cel": "a cel-shaded cartoon with thick clean outlines, flat bright colours and simple hard-edged shadows",
}
NODE_CLASSES = {
    "LoadVideo", "GetVideoComponents", "VAELoader", "CLIPLoader", "UNETLoader", "LoraLoaderModelOnly",
    "MiniMaxH3SigmaShift", "ModelAttentionBackend", "MiniMaxH3ReferenceToVideo", "MiniMaxH3AddGuide",
    "ConditioningZeroOut", "KSampler", "VAEDecode", "CreateVideo", "SaveVideo",
}
NODE_CLASSES_WITH_PHOTOS = NODE_CLASSES | {"LoadImage"}
MOTION_NODE_CLASSES = {
    "LoadVideo", "GetVideoComponents", "VAELoader", "CLIPLoader", "UNETLoader", "LoraLoaderModelOnly",
    "MiniMaxH3SigmaShift", "ModelPatchLoader", "CheckpointLoaderSimple", "RTDETR_detect", "SDPoseKeypointExtractor",
    "SDPoseDrawKeypoints", "MiniMaxH3FunControlNetApply", "ModelAttentionBackend", "LoadImage",
    "MiniMaxH3ReferenceToVideo", "ConditioningZeroOut", "KSampler", "VAEDecode", "CreateVideo", "SaveVideo",
}

# The head swap LoRA's prompt template (Alissonerdx/Minimax-H3-ComfyUI docs/head-swap.md, as the lab ran it); the
# user's short description of the face photo goes in {face}.
HEAD_SWAP_TEMPLATE = """head_swap:

subject_definitions:

<Subject 1> is the reference head identity from <Picture 1>, including the complete head, facial identity, facial structure, head shape, hairstyle, hairline, skin appearance, proportions, and all distinctive visual features.

Facial details of <Subject 1>:
{face}

<Subject 2> is the original person in <Video 1>, whose body, neck, clothing, pose, physical proportions below the head, actions, motion, timing, and interaction with the environment must remain unchanged.

<Video 1> is the source video for the target video edit, providing the original body performance, motion, camera movement, framing, timing, lighting, environment, scene composition, and temporal structure.

summary:

[video editing + reference generation]

The target video is an edited version of <Video 1>. Replace only the entire head of <Subject 2> with the reference head identity defined by <Subject 1> from <Picture 1>. Preserve the source video's body, clothing, performance, motion, camera behavior, environment, lighting, timing, and composition.

retention_analysis:

<Subject 1> (appears throughout the target video): attribute_transfer - the complete head identity from <Picture 1>, including facial identity, facial structure, hairstyle, head shape, proportions, skin appearance, and distinctive features, is transferred consistently onto the body of <Subject 2>.

<Subject 2> (appears throughout the target video): partially_preserved - the original body, neck position, clothing, pose, motion, gestures, actions, and physical performance are preserved, while only the original head is replaced.

<Video 1> (entire target timeline): partially_preserved - the original video timing, body motion, camera movement, framing, lighting, background, environment, scene composition, and temporal structure are preserved; only the subject's head appearance is modified.

detailed_description:

Preserve <Video 1> as the complete temporal and compositional foundation of the target video. <Subject 2> retains the exact original body, clothing, pose, body proportions, movement, gestures, actions, speed, timing, and interaction with the environment.

Replace only the entire original head of <Subject 2> with <Subject 1>, the reference head identity from <Picture 1>. Preserve the complete recognizable identity of <Subject 1>, including facial structure, skull and head shape, hairstyle, hairline, skin appearance, facial proportions, eyes, eyebrows, nose, mouth, jawline, ears, and distinctive identifying features.

The transferred head follows the original head motion and performance of <Subject 2> throughout <Video 1>, including head rotation, tilt, pitch, yaw, natural translation, facial orientation, gaze direction, and perspective changes. Maintain anatomically correct head scale and a seamless connection between the transferred head and the original neck.

Preserve the lighting conditions of <Video 1> on the transferred head. The head naturally responds to changes in illumination, shadows, highlights, color temperature, exposure, depth of field, motion blur, occlusion, camera angle, and perspective while continuously maintaining the identity established by <Picture 1>.

Maintain strong temporal consistency across every frame. The identity, facial geometry, hairstyle, head size, skin appearance, and distinguishing features of <Subject 1> remain stable during motion and viewpoint changes. Prevent identity drift, facial morphing, hairstyle changes, head-size fluctuations, geometry instability, texture crawling, temporal flickering, frame-to-frame inconsistency, or sudden changes in facial appearance.

Do not alter the body, clothing, hands, pose, gestures, action, background, objects, environment, camera trajectory, framing, lens behavior, scene timing, or composition inherited from <Video 1>. The final result should appear as though <Subject 1>'s head naturally belonged to <Subject 2>'s body during the original recorded performance.

overall_soundscape:

Preserve the original audiovisual timing and visible action structure of <Video 1>. No visual modifications are made outside the head replacement.

non_diegetic_music:
N/A"""


def edit_lora_name(filename: str) -> str:
    """The name ComfyUI lists for a LoRA in models/loras/h3_edit (Windows separator, as the other LoRA subfolders)."""
    return f"{EDIT_LORA_DIR}\\{filename}"


def edit_size(size: str, source_width: int, source_height: int) -> tuple[int, int]:
    width, height = EDIT_SIZES[size]
    return (height, width) if source_width > source_height else (width, height)


def build_motion_prompt(character: str, action: str, place: str) -> str:
    """Pixaroma's motion transfer prompt with the three boxes filled (raises ValueError with the reason)."""
    values = {key: re.sub(r"\s+", " ", value or "").strip().rstrip(".")
              for key, value in (("character", character), ("action", action), ("place", place))}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise ValueError("Fill in " + ", ".join({"character": "the character", "action": "what they do",
                                                  "place": "the new place"}[key] for key in missing))
    if any(len(value) > MAX_MOTION_FIELD for value in values.values()):
        raise ValueError(f"Keep each box under {MAX_MOTION_FIELD} characters")
    return MOTION_TEMPLATE.format(**values)


def build_edit_prompt(task: str, prompt: str, style: str, face: str, photos: int) -> str:
    """The prompt the LoRA expects (raises ValueError with the reason)."""
    prompt = re.sub(r"\s+", " ", prompt or "").strip()
    face = re.sub(r"\s+", " ", face or "").strip()
    trigger = EDIT_TASKS[task]["trigger"]
    if task == "head":
        if not face:
            raise ValueError("Describe the face photo in a few words (for example: male, oval face, short blond hair, "
                             "trimmed beard)")
        if len(face) > MAX_FACE:
            raise ValueError(f"Keep the face description under {MAX_FACE} characters")
        return HEAD_SWAP_TEMPLATE.replace("{face}", face)
    if task == "style":
        if style == "custom":
            if not prompt:
                raise ValueError("Describe the style in one sentence")
            body = prompt
        elif style in EDIT_STYLES:
            body = f"Transform this video into {EDIT_STYLES[style]}."
        else:
            raise ValueError("Choose a style: " + ", ".join([*EDIT_STYLES, "custom"]))
    else:
        if not prompt:
            raise ValueError("Write the change in one sentence: change X into Y, while preserving Z")
        body = prompt
        if task == "outfit":
            used = {int(n) for n in re.findall(r"@([1-9])", body)}
            if used - set(range(1, photos + 1)):
                raise ValueError(f"The sentence names a photo that is not attached (attached: {photos})")
            if not used:
                raise ValueError("Name the photos in the sentence: @1 for the first photo, @2 for the second")
            body = re.sub(r"@([1-9])", r"<Picture \1>", body)
    if body.lower().startswith(trigger):
        body = body[len(trigger):].strip()
    if len(body) > MAX_PROMPT:
        raise ValueError(f"Keep the sentence under {MAX_PROMPT} characters")
    return f"{trigger} {body}"


def plan_edit(source: dict, task: str, size: str | None, seconds: int | None, prompt: str, style: str, face: str,
              photos: int, character: str = "", action: str = "", place: str = "") -> dict:
    """Check the request and the source probe against the tested limits; return the stored post options."""
    if task not in EDIT_TASKS:
        raise ValueError("Choose an edit: " + ", ".join(EDIT_TASKS))
    spec = EDIT_TASKS[task]
    size = size or EDIT_DEFAULT_SIZE
    seconds = int(seconds or 5)
    if size not in EDIT_SIZES:
        raise ValueError("Choose a size: 480 or 704")
    if size not in spec["sizes"]:
        raise ValueError(f"{spec['label']} was tested at 480x864 only: at 576 and 704 the photo clothes did not appear")
    if seconds not in EDIT_FRAMES or seconds not in spec["seconds"]:
        if task == "motion":
            raise ValueError("Motion transfer was tested on 5 second clips only")
        raise ValueError("Choose 5 or 10 seconds")
    if seconds == 10 and size != "480":
        raise ValueError("10 seconds runs at 480x864 only: at 704x1280 it ran out of graphics memory on this card")
    low, high = spec["photos"]
    if not low <= photos <= high:
        raise ValueError(f"{spec['label']} takes {low if low == high else f'{low}-{high}'} photo(s); {photos} attached")
    frames = EDIT_FRAMES[seconds]
    available = int(source["duration"] * EDIT_FPS + 1e-6)
    if available < frames - EDIT_MAX_PAD_FRAMES:
        need = (frames - EDIT_MAX_PAD_FRAMES) / EDIT_FPS
        raise ValueError(f"The clip is {source['duration']:.1f} s; {seconds} s needs at least {need:.1f} s")
    width, height = edit_size(size, source["width"], source["height"])
    if task == "motion":
        final = build_motion_prompt(character, action, place)
    else:
        final = build_edit_prompt(task, prompt, style, face, photos)
    return {"operation": "edit", "method": H3_EDIT, "task": task, "task_label": spec["label"], "size": size,
            "style": style if task == "style" else None, "user_prompt": (prompt or "").strip()[:MAX_PROMPT],
            "face": (face or "").strip()[:MAX_FACE] if task == "head" else None, "prompt": final,
            "motion": {"character": character.strip(), "action": action.strip(), "place": place.strip()}
            if task == "motion" else None,
            "source_width": source["width"], "source_height": source["height"], "source_fps": source["fps"],
            "source_frames": source["frames"], "source_duration": round(source["duration"], 3),
            "audio": bool(source["audio"]), "width": width, "height": height, "fps": EDIT_FPS, "frames": frames,
            "seconds": seconds, "output_duration": round(frames / EDIT_FPS, 3), "pad_frames": max(0, frames - available), "long_side": max(width, height),
            "crop_percent": _crop_percent(source["width"], source["height"], width, height), "photos": []}


def _crop_percent(width: int, height: int, target_width: int, target_height: int) -> float:
    ratio = (width / height) / (target_width / target_height)
    return round((1 - min(ratio, 1 / ratio)) * 100, 1)


def edit_input_command(options: dict, source: Path, out: Path) -> list[str]:
    """Scale and centre-crop the source to the edit size at 24 fps, first `frames` frames (the last one held when the
    clip is a little short), with its sound cut to the same length (silence when it has none)."""
    width, height, frames = options["width"], options["height"], options["frames"]
    seconds = f"{frames / EDIT_FPS:.6f}"
    video = (f"fps={EDIT_FPS},scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
             f"crop={width}:{height},setsar=1,tpad=stop_mode=clone:stop={EDIT_MAX_PAD_FRAMES + 12}")
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(source)]
    if options.get("audio"):
        command += ["-filter_complex", f"[0:v]{video}[v];[0:a]apad[a]", "-map", "[v]", "-map", "[a]"]
    else:
        command += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-filter_complex", f"[0:v]{video}[v]", "-map", "[v]", "-map", "1:a"]
    return [*command, "-frames:v", str(frames), "-t", seconds, "-c:v", "libx264", "-crf", "10", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(out)]


def motion_workflow(options: dict, video_name: str, prefix: str, seed: int) -> dict:
    """Pixaroma workflow 06 as the lab ran it: pose stick figure from the moves clip -> Fun ControlNet pose patch on
    Ref2VA + DMAD 0.7 -> the character sheet as <Picture 1> -> 8 steps; the moves clip's sound on the result."""
    g = {"1": {"class_type": "LoadVideo", "inputs": {"file": video_name}},
         "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
         "4": {"class_type": "VAELoader", "inputs": {"vae_name": FUSED_VIDEO_VAE}},
         "5": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
         "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"}},
         "20": {"class_type": "UNETLoader", "inputs": {"unet_name": REF2VA_MODEL, "weight_dtype": "default"}},
         "21": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["20", 0], "lora_name": edit_lora_name(DMAD_LORA),
                                                                "strength_model": MOTION_DMAD_STRENGTH}},
         "23": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["21", 0], "shift_video": 12.0, "shift_audio": 3.0}},
         "60": {"class_type": "ModelPatchLoader", "inputs": {"name": MOTION_CONTROLNET}},
         "61": {"class_type": "UNETLoader", "inputs": {"unet_name": MOTION_RTDETR, "weight_dtype": "default"}},
         "62": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": MOTION_SDPOSE}},
         "63": {"class_type": "RTDETR_detect", "inputs": {"model": ["61", 0], "image": ["2", 0], "threshold": 0.5,
                                                          "class_name": "person", "max_detections": 2}},
         "64": {"class_type": "SDPoseKeypointExtractor", "inputs": {"model": ["62", 0], "vae": ["62", 2], "image": ["2", 0],
                                                                    "batch_size": 16, "bboxes": ["63", 0]}},
         "65": {"class_type": "SDPoseDrawKeypoints", "inputs": {"keypoints": ["64", 0], "draw_body": True,
                                                                "draw_hands": True, "draw_face": True, "draw_feet": True,
                                                                "stick_width": 4, "face_point_size": 2,
                                                                "score_threshold": 0.5, "draw_head": True}},
         "66": {"class_type": "MiniMaxH3FunControlNetApply", "inputs": {"model": ["23", 0], "model_patch": ["60", 0],
                                                                        "vae": ["4", 0], "strength": 1.0,
                                                                        "start_percent": 0.0, "end_percent": 1.0,
                                                                        "control_video": ["65", 0]}},
         "24": {"class_type": "ModelAttentionBackend", "inputs": {"model": ["66", 0], "attention": "comfy kitchen attention"}},
         "50": {"class_type": "LoadImage", "inputs": {"image": options["photos"][0]}},
         "13": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
             "clip": ["10", 0], "vae": ["4", 0], "audio_vae": ["5", 0], "prompt": options["prompt"],
             "width": options["width"], "height": options["height"], "length": options["frames"],
             "ref_image_size": "match", "ref_images.ref_image_0": ["50", 0]}},
         "15": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["13", 0]}},
         "30": {"class_type": "KSampler", "inputs": {"model": ["24", 0], "seed": int(seed) % EDIT_SEED_MOD,
                                                     "steps": MOTION_STEPS, "cfg": 1.0, "sampler_name": "euler",
                                                     "scheduler": "simple", "positive": ["13", 0], "negative": ["15", 0],
                                                     "latent_image": ["13", 1], "denoise": 1.0}},
         "41": {"class_type": "VAEDecode", "inputs": {"samples": ["30", 0], "vae": ["4", 0]}},
         "43": {"class_type": "CreateVideo", "inputs": {"images": ["41", 0], "fps": float(EDIT_FPS)}},
         "44": {"class_type": "SaveVideo", "inputs": {"filename_prefix": prefix, "video": ["43", 0], "format": "mp4",
                                                      "format.codec": "h264", "format.codec.encoding": "re-encode",
                                                      "format.codec.encoding.crf": 12.0}}}
    if options.get("audio"):
        g["43"]["inputs"]["audio"] = ["2", 1]
    return g


def edit_workflow(options: dict, video_name: str, prefix: str, seed: int) -> dict:
    if options["task"] == "motion":
        return motion_workflow(options, video_name, prefix, seed)
    task = EDIT_TASKS[options["task"]]
    g = {"1": {"class_type": "LoadVideo", "inputs": {"file": video_name}},
         "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
         "4": {"class_type": "VAELoader", "inputs": {"vae_name": FUSED_VIDEO_VAE}},
         "5": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
         "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"}},
         "20": {"class_type": "UNETLoader", "inputs": {"unet_name": REF2VA_MODEL, "weight_dtype": "default"}},
         "21": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["20", 0], "lora_name": edit_lora_name(DMAD_LORA),
                                                                "strength_model": 1.0}},
         "22": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["21", 0],
                                                                "lora_name": edit_lora_name(task["lora"]),
                                                                "strength_model": 1.0}},
         "23": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["22", 0], "shift_video": 12.0, "shift_audio": 3.0}},
         "24": {"class_type": "ModelAttentionBackend", "inputs": {"model": ["23", 0], "attention": "comfy kitchen attention"}}}
    rtv = {"clip": ["10", 0], "vae": ["4", 0], "audio_vae": ["5", 0], "prompt": options["prompt"],
           "width": options["width"], "height": options["height"], "length": options["frames"], "ref_image_size": "match"}
    for index, photo in enumerate(options.get("photos") or []):
        g[str(50 + index)] = {"class_type": "LoadImage", "inputs": {"image": photo}}
        rtv[f"ref_images.ref_image_{index}"] = [str(50 + index), 0]   # flat key: ComfyUI drops nested ref inputs
    g["13"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": rtv}
    g["14"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": ["13", 0], "latent": ["13", 1], "frame_idx": 0,
                                                             "vae": ["4", 0], "audio_vae": ["5", 0], "image": ["2", 0],
                                                             "audio": ["2", 1]}}
    g["15"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["14", 0]}}
    g["30"] = {"class_type": "KSampler", "inputs": {"model": ["24", 0], "seed": int(seed) % EDIT_SEED_MOD, "steps": 4,
                                                    "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                                                    "positive": ["14", 0], "negative": ["15", 0],
                                                    "latent_image": ["13", 1], "denoise": 1.0}}
    g["41"] = {"class_type": "VAEDecode", "inputs": {"samples": ["30", 0], "vae": ["4", 0]}}
    g["43"] = {"class_type": "CreateVideo", "inputs": {"images": ["41", 0], "fps": float(EDIT_FPS)}}
    if options.get("audio"):
        g["43"]["inputs"]["audio"] = ["2", 1]
    g["44"] = {"class_type": "SaveVideo", "inputs": {"video": ["43", 0], "filename_prefix": prefix, "format": "mp4",
                                                     "format.codec": "h264", "format.codec.encoding": "re-encode",
                                                     "format.codec.encoding.crf": 12.0}}
    return g


def edit_node_classes(options: dict) -> set[str]:
    if options["task"] == "motion":
        return MOTION_NODE_CLASSES
    return NODE_CLASSES_WITH_PHOTOS if options.get("photos") else NODE_CLASSES


def edit_required_files(options: dict) -> list[Path]:
    loras = MODELS / "loras" / EDIT_LORA_DIR
    if options["task"] == "motion":
        return [MODELS / "diffusion_models" / REF2VA_MODEL, loras / DMAD_LORA,
                MODELS / "model_patches" / MOTION_CONTROLNET, MODELS / "checkpoints" / MOTION_SDPOSE,
                MODELS / "diffusion_models" / MOTION_RTDETR, MODELS / "text_encoders" / TEXT_ENCODER,
                MODELS / "vae" / FUSED_VIDEO_VAE, MODELS / "vae" / AUDIO_VAE]
    return [MODELS / "diffusion_models" / REF2VA_MODEL, loras / DMAD_LORA, loras / EDIT_TASKS[options["task"]]["lora"],
            MODELS / "text_encoders" / TEXT_ENCODER, MODELS / "vae" / FUSED_VIDEO_VAE, MODELS / "vae" / AUDIO_VAE]


def edit_title(options: dict, source_prompt: str) -> str:
    motion = options.get("motion") or {}
    what = (f"{motion['action']} in {motion['place']}" if motion else
            options.get("user_prompt") or options.get("face") or EDIT_STYLES.get(options.get("style") or "", ""))
    head = f"H3 edit · {options['task_label']} · {options['width']}x{options['height']} · {options['seconds']} s"
    return f"{head} · {(what or source_prompt).strip()[:160]}"
