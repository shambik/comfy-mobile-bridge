from copy import deepcopy

from .config import (AUDIO_VAE, CLIPPROJ_PROJECTION, CLIPPROJ_TEXT_ENCODER,
                     FL2VA_MODEL, REF2VA_MODEL, REF2VA_TURBO_LORA, TEXT_ENCODER, TURBO_LORAS,
                     VIDEO_VAE)

FPS = 24
H3_DURATION_EXPRESSION = "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17"
H3_ASPECT_RATIOS = {
    "1:1 (Square)": 1.0,
    "16:9 (Widescreen)": 16 / 9,
    "9:16 (Portrait Widescreen)": 9 / 16,
    "4:3 (Standard)": 4 / 3,
    "3:4 (Portrait Standard)": 3 / 4,
}


def h3_frame_count(duration: float) -> int:
    """Round requested seconds up to H3's 17k+5 frame grid."""
    frames = max(5, round(duration * FPS))
    return frames + (5 - frames % 17) % 17


def _resolution_selector(
    width: int,
    height: int,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
) -> dict:
    # New jobs pass the user/skill megapixel value directly. The node owns the
    # final width/height calculation. Width/height fallback is for legacy
    # callers and old saved jobs only.
    ratio = width / height
    aspect = aspect_ratio or min(H3_ASPECT_RATIOS, key=lambda item: abs(H3_ASPECT_RATIOS[item] - ratio))
    aspect = {
        "1:1": "1:1 (Square)",
        "16:9": "16:9 (Widescreen)",
        "9:16": "9:16 (Portrait Widescreen)",
        "4:3": "4:3 (Standard)",
        "3:4": "3:4 (Portrait Standard)",
    }.get(aspect, aspect)
    node_megapixels = megapixels if megapixels is not None else width * height / (1024 * 1024)
    return {
        "7": {"class_type": "ResolutionSelector", "inputs": {
            "aspect_ratio": aspect, "megapixels": node_megapixels, "multiple": 32,
        }},
    }


def _duration_selector(duration: float) -> dict:
    return {
        "105": {"class_type": "PrimitiveFloat", "inputs": {"value": duration}},
        "106": {"class_type": "ComfyMathExpression", "inputs": {
            "values.a": ["105", 0], "expression": H3_DURATION_EXPRESSION,
        }},
    }


def _clip_loader(encoder: str, reference: bool = False) -> dict:
    if encoder == "clipproj":
        return {
            "class_type": "ClipProjLoader",
            "inputs": {
                "clip_name": CLIPPROJ_TEXT_ENCODER,
                "type": "auto",
                "projection": CLIPPROJ_PROJECTION,
                "device": "cuda:0",
                # The official node requires resident mode when image tokens
                # are used by ref2va. Dynamic mode lets ComfyUI offload the
                # encoder before the large diffusion model runs on an 8GB GPU.
                "mode": "resident" if reference else "dynamic",
            },
        }
    return {"class_type": "CLIPLoader", "inputs": {
        "clip_name": TEXT_ENCODER, "type": "minimax", "device": "default",
    }}


def _common_decode(
    condition_node: str,
    model_node: str,
    sampler_node: dict,
    seed: int,
    prefix: str,
    encoder: str = "native",
    reference: bool = False,
    include_audio: bool = True,
):
    nodes = {
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "13": _clip_loader(encoder, reference=reference),
        "15": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "16": {"class_type": "BasicGuider", "inputs": {"model": [model_node, 0], "conditioning": [condition_node, 0]}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["11", 0]}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["15", 0], "guider": ["16", 0], "sampler": [sampler_node["id"], 0],
            "sigmas": [sampler_node["scheduler"], 0], "latent_image": [condition_node, 1]}},
        "91": {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "fps": FPS, "bit_depth": 8}},
        "92": {"class_type": "SaveVideo", "inputs": {"video": ["91", 0], "filename_prefix": prefix, "format": "mp4", "codec": "auto"}},
    }
    if include_audio or reference:
        nodes["24"] = {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}}
    if include_audio:
        nodes["23"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["14", 0], "vae": ["24", 0]}}
        nodes["91"]["inputs"]["audio"] = ["23", 0]
    return nodes


def turbo_workflow(
    prompt: str,
    duration: int,
    seed: int,
    prefix: str,
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    steps: int = 4,
    width: int = 736,
    height: int = 416,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
    encoder: str = "native",
    turbo_profile: str = "v1",
    include_audio: bool = True,
):
    length = h3_frame_count(duration)
    nodes = _common_decode("104", "17", {"id": "19", "scheduler": "9"}, seed, prefix, encoder, include_audio=include_audio)
    nodes.update({
        **_resolution_selector(width, height, megapixels, aspect_ratio),
        **_duration_selector(duration),
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": FL2VA_MODEL, "weight_dtype": "default"}},
        "18": {"class_type": "MiniMaxH3TurboLoRA", "inputs": {"model": ["6", 0], "lora_name": TURBO_LORAS[turbo_profile], "strength": 1.0, "low_vram": True}},
        "17": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["18", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "19": {"class_type": "MiniMaxH3TurboSampler", "inputs": {}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["17", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0], "prompt": prompt, "width": ["7", 0], "height": ["7", 1], "length": ["106", 1]}},
    })
    if first_frame_name:
        nodes["200"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        nodes["104"]["inputs"]["first_frame"] = ["200", 0]
    if last_frame_name:
        nodes["201"] = {"class_type": "LoadImage", "inputs": {"image": last_frame_name}}
        nodes["104"]["inputs"]["last_frame"] = ["201", 0]
    return deepcopy(nodes)


def standard_workflow(
    prompt: str,
    duration: int,
    seed: int,
    prefix: str,
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    steps: int = 20,
    width: int = 736,
    height: int = 416,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
    encoder: str = "native",
    include_audio: bool = True,
):
    length = h3_frame_count(duration)
    nodes = _common_decode("104", "6", {"id": "17", "scheduler": "9"}, seed, prefix, encoder, include_audio=include_audio)
    nodes.update({
        **_resolution_selector(width, height, megapixels, aspect_ratio),
        **_duration_selector(duration),
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": FL2VA_MODEL, "weight_dtype": "default"}},
        "17": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["6", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0], "prompt": prompt, "width": ["7", 0], "height": ["7", 1], "length": ["106", 1]}},
    })
    if first_frame_name:
        nodes["200"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        nodes["104"]["inputs"]["first_frame"] = ["200", 0]
    if last_frame_name:
        nodes["201"] = {"class_type": "LoadImage", "inputs": {"image": last_frame_name}}
        nodes["104"]["inputs"]["last_frame"] = ["201", 0]
    return deepcopy(nodes)


def native_audio_lock_workflow(
    prompt: str,
    duration: int,
    seed: int,
    prefix: str,
    audio_name: str,
    first_frame_name: str | None = None,
    steps: int = 20,
    width: int = 736,
    height: int = 416,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
    encoder: str = "native",
):
    """Native H3 video with an uploaded audio track locked into the AV latent."""
    nodes = _common_decode(
        "104", "18", {"id": "17", "scheduler": "9"},
        seed, prefix, encoder, include_audio=False,
    )
    nodes.update({
        **_resolution_selector(width, height, megapixels, aspect_ratio),
        **_duration_selector(duration),
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": FL2VA_MODEL, "weight_dtype": "default"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["18", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "17": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "18": {"class_type": "MiniMaxH3NativeAudioLock", "inputs": {
            "model": ["6", 0], "av_latent": ["104", 1],
            "audio_vae": ["24", 0], "audio": ["23", 0],
        }},
        "23": {"class_type": "LoadAudio", "inputs": {"audio": audio_name}},
        "24": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["13", 0], "vae": ["11", 0], "prompt": prompt,
            "width": ["7", 0], "height": ["7", 1], "length": ["106", 1],
        }},
    })
    nodes["14"]["inputs"]["latent_image"] = ["18", 1]
    nodes["91"]["inputs"]["audio"] = ["18", 2]
    if first_frame_name:
        nodes["200"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        nodes["104"]["inputs"]["first_frame"] = ["200", 0]
    return deepcopy(nodes)


def spectrum_workflow(
    prompt: str,
    duration: int,
    seed: int,
    prefix: str,
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    steps: int = 16,
    width: int = 736,
    height: int = 416,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
    encoder: str = "native",
    include_audio: bool = True,
):
    """Native H3 with the optional Spectrum v0.2.5 acceleration node.

    Spectrum is deliberately kept separate from the Turbo sampler. It wraps
    the native model after the H3 sigma-shift node and uses RES multistep,
    which is one of Spectrum's supported sampler paths.
    """
    length = h3_frame_count(duration)
    nodes = _common_decode("104", "18", {"id": "19", "scheduler": "9"}, seed, prefix, encoder, include_audio=include_audio)
    nodes.update({
        **_resolution_selector(width, height, megapixels, aspect_ratio),
        **_duration_selector(duration),
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": FL2VA_MODEL, "weight_dtype": "default"}},
        "17": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["6", 0], "shift_video": 12.0, "shift_audio": 3.0,
        }},
        "18": {"class_type": "SpectrumApplyMiniMaxH3", "inputs": {
            "model": ["17", 0], "enabled": True,
            "blend_weight": 0.50, "degree": 1, "ridge_lambda": 0.10,
            "window_size": 2.0, "flex_window": 0.75,
            "warmup_steps": 1, "tail_actual_steps": 1, "max_history": 8,
            "debug": True, "history_storage": "system_ram",
            "offline_archive_storage": "system_ram",
            "bootstrap_first_forecast": True,
            "anchor_residual_feedback": False,
            "selective_rollback_correction": False,
            "offline_smoothing_replay": True,
            "audio_blend_weight": 0.0,
        }},
        "19": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["18", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0], "prompt": prompt, "width": ["7", 0], "height": ["7", 1], "length": ["106", 1]}},
    })
    if first_frame_name:
        nodes["200"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        nodes["104"]["inputs"]["first_frame"] = ["200", 0]
    if last_frame_name:
        nodes["201"] = {"class_type": "LoadImage", "inputs": {"image": last_frame_name}}
        nodes["104"]["inputs"]["last_frame"] = ["201", 0]
    return deepcopy(nodes)


def reference_workflow(
    prompt: str,
    duration: int,
    seed: int,
    prefix: str,
    image_name: str,
    audio_name: str | None = None,
    steps: int = 20,
    width: int = 736,
    height: int = 416,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
    spectrum: bool = False,
    encoder: str = "native",
    turbo: bool = False,
    image_names: list[str] | None = None,
    video_names: list[str] | None = None,
    include_audio: bool = True,
):
    length = h3_frame_count(duration)
    image_names = image_names or ([image_name] if image_name else [])
    video_names = video_names or []
    turbo = bool(turbo)
    model_node = "129" if turbo else ("129" if spectrum else "127")
    sampler_node = "130" if turbo else ("130" if spectrum else "123")
    nodes = _common_decode(
        "136", model_node, {"id": sampler_node, "scheduler": "124"},
        seed, prefix, encoder, reference=True, include_audio=include_audio,
    )
    nodes.update({
        **_resolution_selector(width, height, megapixels, aspect_ratio),
        **_duration_selector(duration),
        "127": {"class_type": "UNETLoader", "inputs": {"unet_name": REF2VA_MODEL, "weight_dtype": "default"}},
        "124": {"class_type": "BasicScheduler", "inputs": {"model": [model_node, 0], "scheduler": "beta" if turbo else "simple", "steps": steps, "denoise": 1.0}},
        "136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["13", 0], "vae": ["11", 0], "audio_vae": ["24", 0], "prompt": prompt,
            "width": ["7", 0], "height": ["7", 1], "length": ["106", 1], "ref_image_size": "match",
             "ref_images": {}}},
    })
    for index, name in enumerate(image_names[:9]):
        node_id = str(137 + index)
        nodes[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        nodes["136"]["inputs"]["ref_images"][f"ref_image_{index}"] = [node_id, 0]
    for index, name in enumerate(video_names[:3]):
        load_id = str(150 + index * 2)
        component_id = str(151 + index * 2)
        nodes[load_id] = {"class_type": "LoadVideo", "inputs": {"file": name}}
        nodes[component_id] = {"class_type": "GetVideoComponents", "inputs": {"video": [load_id, 0]}}
        nodes["136"]["inputs"].setdefault("ref_videos", {})[f"ref_video_{index}"] = [component_id, 0]
        if include_audio:
            nodes["136"]["inputs"].setdefault("ref_video_audios", {})[f"ref_video_audio_{index}"] = [component_id, 1]
    if audio_name:
        # Keep the standalone audio loader away from the image reference
        # range (137-145).  Reusing node 138 silently replaced image 2 and
        # wired both ref_image_1 and ref_audio_0 to LoadAudio.
        nodes["180"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_name}}
        nodes["136"]["inputs"]["ref_audios"] = {"ref_audio_0": ["180", 0]}
    if turbo:
        nodes.update({
            "128": {"class_type": "MiniMaxH3TurboLoRA", "inputs": {
                "model": ["127", 0], "lora_name": REF2VA_TURBO_LORA,
                "strength": 1.0, "low_vram": True,
            }},
            "129": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
                "model": ["128", 0], "shift_video": 12.0, "shift_audio": 3.0,
            }},
            "130": {"class_type": "MiniMaxH3TurboSampler", "inputs": {}},
        })
    elif spectrum:
        nodes.update({
            "128": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
                "model": ["127", 0], "shift_video": 12.0, "shift_audio": 3.0,
            }},
            "129": {"class_type": "SpectrumApplyMiniMaxH3", "inputs": {
                "model": ["128", 0], "enabled": True,
                "blend_weight": 0.50, "degree": 1, "ridge_lambda": 0.10,
                "window_size": 2.0, "flex_window": 0.75,
                "warmup_steps": 1, "tail_actual_steps": 1, "max_history": 8,
                "debug": True, "history_storage": "system_ram",
                "offline_archive_storage": "system_ram",
                "bootstrap_first_forecast": True,
                "anchor_residual_feedback": False,
                "selective_rollback_correction": False,
                "offline_smoothing_replay": True,
                "audio_blend_weight": 0.0,
            }},
            "130": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        })
    else:
        nodes["123"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    return deepcopy(nodes)
