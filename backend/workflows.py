import json
from pathlib import Path
from copy import deepcopy

from .config import (OFFICIAL_LTX_TEMPLATES, OMNI_MODEL, PIKA_FL2VA_LORA, PIKA_REF2VA_LORA, PIKA_SIGMAS, PIKA_TURBO4_FL2VA_LORA, AUDIO_VAE, CLIPPROJ_PROJECTION, CLIPPROJ_TEXT_ENCODER,
                     FL2VA_MODEL, FUSED_MOTION_ADAPTER, FUSED_SLA_MODEL,
                     FUSED_VIDEO_VAE, FUSED_WORKFLOW_FILES, LTX23_CHECKPOINT,
                     LTX23_DISTILLED_LORA, LTX23_INGREDIENTS_LORA,
                     LTX23_LATENT_UPSCALER, LTX23_TEXT_ENCODER,
                     LTX25_INGREDIENTS_LORA, LTX25_LATENT_UPSCALER, LTX_AUDIO_VAE,
                     LTX_TEXT_ENCODER, LTX_TRANSFORMER,
                     LTX_VIDEO_VAE, LTX_WORKFLOW,
                     REF2VA_MODEL, REF2VA_TURBO_LORA, SINGULARITY_FULL_MODEL, SINGULARITY_MODEL,
                     SKIN_PEOPLE_LORA, SKIN_REF2V_8STEP_LORA, TEXT_ENCODER,
                     TURBO_LORAS, VIDEO_VAE)

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


def fused_sla_workflow(
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
    include_audio: bool = True,
):
    """Low VRAM fused ref-delta H3 with the official SLA attention chain.

    The model is already a fused turbo checkpoint, so this path does not
    attach a Turbo LoRA.  Four steps is the default; the model also supports
    the measured 6–8 step single-pass ladder. The KJNodes feed-forward
    chunker keeps the sequence memory within reach of a 10 GB card before the
    SLA attention patch runs.
    """
    nodes = _common_decode(
        "104", "17", {"id": "20", "scheduler": "9"},
        seed, prefix, encoder="native", include_audio=include_audio,
    )
    nodes.update({
        **_resolution_selector(width, height, megapixels, aspect_ratio),
        **_duration_selector(duration),
        "6": {"class_type": "UNETLoader", "inputs": {
            "unet_name": FUSED_SLA_MODEL, "weight_dtype": "default",
        }},
        "18": {"class_type": "MiniMaxChunkFeedForward", "inputs": {
            "model": ["6", 0], "chunks": 4, "seq_threshold": 4096,
        }},
        "19": {"class_type": "H3SLAAttention", "inputs": {
            "model": ["18", 0], "sparsity_ratio": 0.90,
            "block_size": "64", "min_seq_len": 8192,
            "dense_last_steps": 0, "protect_audio": True, "enabled": True,
        }},
        "17": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["19", 0], "shift_video": 12.0, "shift_audio": 3.0,
        }},
        "20": {"class_type": "KSamplerSelect", "inputs": {
            "sampler_name": "res_multistep",
        }},
        "9": {"class_type": "BasicScheduler", "inputs": {
            "model": ["17", 0], "scheduler": "simple", "steps": steps,
            "denoise": 1.0,
        }},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["13", 0], "vae": ["11", 0], "prompt": prompt,
            "width": ["7", 0], "height": ["7", 1], "length": ["106", 1],
        }},
    })
    if first_frame_name:
        nodes["200"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        nodes["104"]["inputs"]["first_frame"] = ["200", 0]
    if last_frame_name:
        nodes["201"] = {"class_type": "LoadImage", "inputs": {"image": last_frame_name}}
        nodes["104"]["inputs"]["last_frame"] = ["201", 0]
    # The fused workflow uses the INT8 video VAE while retaining the existing
    # audio VAE from the native H3 installation.
    nodes["11"] = {"class_type": "VAELoader", "inputs": {"vae_name": FUSED_VIDEO_VAE}}
    return deepcopy(nodes)


def _official_workflow(variant: str) -> dict:
    path = FUSED_WORKFLOW_FILES.get(variant)
    if path is None:
        raise ValueError(f"Unknown official Fused workflow: {variant}")
    if not path.exists():
        raise RuntimeError(f"Official Fused workflow is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read official Fused workflow: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Official Fused workflow is not an API graph: {path}")
    return deepcopy(payload)


def _official_aspect(aspect_ratio: str | None, width: int, height: int) -> str:
    aspect = aspect_ratio or min(
        H3_ASPECT_RATIOS,
        key=lambda item: abs(H3_ASPECT_RATIOS[item] - width / height),
    )
    return {
        "1:1": "1:1 (Square)",
        "16:9": "16:9 (Widescreen)",
        "9:16": "9:16 (Portrait Widescreen)",
        "4:3": "4:3 (Standard)",
        "3:4": "3:4 (Portrait Standard)",
    }.get(aspect, aspect)


def official_fused_workflow(
    variant: str,
    prompt: str,
    duration: float,
    seed: int,
    prefix: str,
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    reference_image_name: str | None = None,
    reference_image_names: list[str] | None = None,
    reference_video_names: list[str] | None = None,
    reference_audio_name: str | None = None,
    steps: int = 4,
    width: int = 736,
    height: int = 416,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
    include_audio: bool = True,
) -> dict:
    """Return one of the downloaded official low-VRAM H3 API graphs.

    The graph topology stays upstream-owned. Only request-specific values and
    uploaded filenames are filled in here so the bridge can run the same
    workflows from the phone UI and from ComfyUI directly.
    """
    nodes = _official_workflow(variant)
    prompt_node = nodes.get("1")
    if prompt_node:
        prompt_node.setdefault("inputs", {})["value"] = prompt
    resolution_node = nodes.get("115")
    if resolution_node:
        resolution_node.setdefault("inputs", {}).update({
            "aspect_ratio": _official_aspect(aspect_ratio, width, height),
            "megapixels": megapixels if megapixels is not None else width * height / 1_000_000,
            "multiple": 32,
        })
    duration_node = nodes.get("133")
    if duration_node:
        duration_node.setdefault("inputs", {})["value"] = duration
    scheduler = nodes.get("124")
    if scheduler:
        scheduler.setdefault("inputs", {})["steps"] = steps
    for node_id, node in nodes.items():
        if node.get("class_type") == "RandomNoise":
            node.setdefault("inputs", {})["noise_seed"] = seed if node_id == "129" else seed + 1

    def add_frame(node_id: str, input_name: str, filename: str | None, load_id: str) -> None:
        if not filename:
            return
        nodes[load_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        if node_id in nodes:
            nodes[node_id].setdefault("inputs", {})[input_name] = [load_id, 0]

    if variant in {"direct", "i2v_fl2v", "derope", "dyrope"}:
        add_frame("131", "first_frame", first_frame_name, "903")
        add_frame("131", "last_frame", last_frame_name, "904")
        if variant in {"derope", "dyrope"}:
            add_frame("206", "first_frame", first_frame_name, "905")
            add_frame("206", "last_frame", last_frame_name, "906")
    if variant == "ref2va":
        if not reference_image_name:
            raise ValueError("The official Ref2VA workflow requires a reference image")
        nodes.setdefault("901", {"class_type": "LoadImage", "inputs": {}})
        nodes["901"].setdefault("inputs", {})["image"] = reference_image_name
    if variant == "ref2va_multiref":
        # The official graph contains one static reference slot. The same
        # MiniMaxH3ReferenceToVideo node exposes COMFY_AUTOGROW_V3 inputs,
        # so expand those slots here while leaving the fused sampler chain
        # and model topology unchanged.
        image_names = [name for name in (reference_image_names or []) if name]
        if reference_image_name and reference_image_name not in image_names:
            image_names.insert(0, reference_image_name)
        video_names = [name for name in (reference_video_names or []) if name]
        if not image_names and not video_names:
            raise ValueError("The Fused Ref2VA Multi-reference workflow requires at least one image or video")
        reference_node = nodes.get("131")
        if not reference_node or reference_node.get("class_type") != "MiniMaxH3ReferenceToVideo":
            raise RuntimeError("The official Ref2VA graph has no reference video node")
        inputs = reference_node.setdefault("inputs", {})
        for key in list(inputs):
            if key.startswith(("ref_images.", "ref_videos.", "ref_video_audios.", "ref_audios.")):
                inputs.pop(key, None)
        if nodes.get("901", {}).get("class_type") == "LoadImage":
            nodes.pop("901", None)
        for index, name in enumerate(image_names[:9]):
            load_id = str(1000 + index)
            nodes[load_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
            inputs[f"ref_images.ref_image_{index}"] = [load_id, 0]
        for index, name in enumerate(video_names[:3]):
            load_id = str(1020 + index * 2)
            component_id = str(1021 + index * 2)
            nodes[load_id] = {"class_type": "LoadVideo", "inputs": {"file": name}}
            nodes[component_id] = {"class_type": "GetVideoComponents", "inputs": {"video": [load_id, 0]}}
            inputs[f"ref_videos.ref_video_{index}"] = [component_id, 0]
            if include_audio:
                inputs[f"ref_video_audios.ref_video_audio_{index}"] = [component_id, 1]
        if reference_audio_name:
            audio_id = "1040"
            nodes[audio_id] = {"class_type": "LoadAudio", "inputs": {"audio": reference_audio_name}}
            inputs["ref_audios.ref_audio_0"] = [audio_id, 0]
    if variant == "dyrope":
        nodes["902"].setdefault("inputs", {})["lora_name"] = FUSED_MOTION_ADAPTER

    save_nodes = [
        (node_id, node) for node_id, node in nodes.items()
        if node.get("class_type") == "SaveVideo"
    ]
    for node_id, node in save_nodes:
        node.setdefault("inputs", {})["filename_prefix"] = f"{prefix}_{variant}_{node_id}"
    final_save = nodes.get("215") if variant in {"derope", "dyrope"} else nodes.get("92")
    if final_save and final_save.get("class_type") == "SaveVideo":
        final_save.setdefault("inputs", {})["filename_prefix"] = prefix
    for node in nodes.values():
        if node.get("class_type") == "H3SaveHoldMap":
            node.setdefault("inputs", {})["filename_prefix"] = f"{prefix}_holdmap"

    if not include_audio:
        for node in nodes.values():
            if node.get("class_type") == "CreateVideo":
                node.setdefault("inputs", {}).pop("audio", None)
    return nodes


def native_audio_lock_workflow(
    prompt: str,
    duration: int,
    seed: int,
    prefix: str,
    audio_name: str,
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    steps: int = 20,
    width: int = 736,
    height: int = 416,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
    encoder: str = "native",
    turbo: bool = False,
    turbo_profile: str = "v1",
):
    """Native H3 video with an uploaded audio track locked into the AV latent."""
    model_node = "20" if turbo else "18"
    sampler_node = {"id": "21", "scheduler": "9"} if turbo else {"id": "17", "scheduler": "9"}
    nodes = _common_decode(
        "104", model_node, sampler_node,
        seed, prefix, encoder, include_audio=False,
    )
    nodes.update({
        **_resolution_selector(width, height, megapixels, aspect_ratio),
        **_duration_selector(duration),
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": FL2VA_MODEL, "weight_dtype": "default"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": [model_node, 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
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
    if turbo:
        nodes["18"] = {"class_type": "MiniMaxH3TurboLoRA", "inputs": {
            "model": ["6", 0], "lora_name": TURBO_LORAS[turbo_profile],
            "strength": 1.0, "low_vram": True,
        }}
        nodes["19"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["18", 0], "shift_video": 12.0, "shift_audio": 3.0,
        }}
        nodes["20"] = {"class_type": "MiniMaxH3NativeAudioLock", "inputs": {
            "model": ["19", 0], "av_latent": ["104", 1],
            "audio_vae": ["24", 0], "audio": ["23", 0],
        }}
        nodes["21"] = {"class_type": "MiniMaxH3TurboSampler", "inputs": {}}
        nodes["14"]["inputs"]["sampler"] = ["21", 0]
        nodes["14"]["inputs"]["latent_image"] = ["20", 1]
        nodes["91"]["inputs"]["audio"] = ["20", 2]
    else:
        nodes["14"]["inputs"]["latent_image"] = ["18", 1]
        nodes["91"]["inputs"]["audio"] = ["18", 2]
    if first_frame_name:
        nodes["200"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        nodes["104"]["inputs"]["first_frame"] = ["200", 0]
    if last_frame_name:
        nodes["201"] = {"class_type": "LoadImage", "inputs": {"image": last_frame_name}}
        nodes["104"]["inputs"]["last_frame"] = ["201", 0]
    return deepcopy(nodes)


def fused_sla_audio_lock_workflow(
    prompt: str,
    duration: int,
    seed: int,
    prefix: str,
    audio_name: str,
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    steps: int = 4,
    width: int = 736,
    height: int = 416,
    megapixels: float | None = None,
    aspect_ratio: str | None = None,
):
    """Fused INT8 H3 lip-sync with an exact user-supplied audio track."""
    nodes = _common_decode(
        "104", "21", {"id": "22", "scheduler": "9"},
        seed, prefix, encoder="native", include_audio=False,
    )
    nodes.update({
        **_resolution_selector(width, height, megapixels, aspect_ratio),
        **_duration_selector(duration),
        "6": {"class_type": "UNETLoader", "inputs": {
            "unet_name": FUSED_SLA_MODEL, "weight_dtype": "default",
        }},
        "18": {"class_type": "MiniMaxChunkFeedForward", "inputs": {
            "model": ["6", 0], "chunks": 4, "seq_threshold": 4096,
        }},
        "19": {"class_type": "H3SLAAttention", "inputs": {
            "model": ["18", 0], "sparsity_ratio": 0.90,
            "block_size": "64", "min_seq_len": 8192,
            "dense_last_steps": 0, "protect_audio": True, "enabled": True,
        }},
        "20": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["19", 0], "shift_video": 12.0, "shift_audio": 3.0,
        }},
        "21": {"class_type": "MiniMaxH3NativeAudioLock", "inputs": {
            "model": ["20", 0], "av_latent": ["104", 1],
            "audio_vae": ["24", 0], "audio": ["23", 0],
        }},
        "22": {"class_type": "KSamplerSelect", "inputs": {
            "sampler_name": "res_multistep",
        }},
        "9": {"class_type": "BasicScheduler", "inputs": {
            "model": ["21", 0], "scheduler": "simple", "steps": steps,
            "denoise": 1.0,
        }},
        "23": {"class_type": "LoadAudio", "inputs": {"audio": audio_name}},
        "24": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["13", 0], "vae": ["11", 0], "prompt": prompt,
            "width": ["7", 0], "height": ["7", 1], "length": ["106", 1],
        }},
    })
    nodes["11"] = {"class_type": "VAELoader", "inputs": {"vae_name": FUSED_VIDEO_VAE}}
    nodes["14"]["inputs"]["latent_image"] = ["21", 1]
    nodes["91"]["inputs"]["audio"] = ["21", 2]
    if first_frame_name:
        nodes["200"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        nodes["104"]["inputs"]["first_frame"] = ["200", 0]
    if last_frame_name:
        nodes["201"] = {"class_type": "LoadImage", "inputs": {"image": last_frame_name}}
        nodes["104"]["inputs"]["last_frame"] = ["201", 0]
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


def reference_input(inputs: dict, group: str, index: int, link: list) -> None:
    """Wire one MiniMaxH3ReferenceToVideo autogrow slot, e.g. ("ref_images", 0) -> "ref_images.ref_image_0".

    ComfyUI reads autogrow inputs only as flat dotted keys. A nested
    {"ref_images": {"ref_image_0": ...}} dict is dropped without an error and
    the node then runs on the prompt alone.
    """
    inputs[f"{group}.{group.removesuffix('s')}_{index}"] = link


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
        "124": {"class_type": "BasicScheduler", "inputs": {"model": [model_node, 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["13", 0], "vae": ["11", 0], "audio_vae": ["24", 0], "prompt": prompt,
            "width": ["7", 0], "height": ["7", 1], "length": ["106", 1], "ref_image_size": "match"}},
    })
    for index, name in enumerate(image_names[:9]):
        node_id = str(137 + index)
        nodes[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        reference_input(nodes["136"]["inputs"], "ref_images", index, [node_id, 0])
    for index, name in enumerate(video_names[:3]):
        load_id = str(150 + index * 2)
        component_id = str(151 + index * 2)
        nodes[load_id] = {"class_type": "LoadVideo", "inputs": {"file": name}}
        nodes[component_id] = {"class_type": "GetVideoComponents", "inputs": {"video": [load_id, 0]}}
        reference_input(nodes["136"]["inputs"], "ref_videos", index, [component_id, 0])
        if include_audio:
            reference_input(nodes["136"]["inputs"], "ref_video_audios", index, [component_id, 1])
    if audio_name:
        # Keep the standalone audio loader away from the image reference
        # range (137-145).  Reusing node 138 silently replaced image 2 and
        # wired both ref_image_1 and ref_audio_0 to LoadAudio.
        nodes["180"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_name}}
        reference_input(nodes["136"]["inputs"], "ref_audios", 0, ["180", 0])
    if turbo:
        # Lightx2v/ModelTC's Ref2V Turbo LoRA is in ComfyUI's standard key format, so it loads with
        # LoraLoaderModelOnly (larryvrh's MiniMaxH3TurboLoRA patched 0 weights). The chain follows ModelTC's
        # own graph, example_workflows/video_minimax_h3_ref2v_lightx2v_turbo.json: shift 12/3, euler, simple.
        nodes.update({
            "128": {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": ["127", 0], "lora_name": REF2VA_TURBO_LORA, "strength_model": 1.0,
            }},
            "129": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
                "model": ["128", 0], "shift_video": 12.0, "shift_audio": 3.0,
            }},
            "130": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
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


# Singularity skin tiers: the LoRA stack for each (one speed LoRA at a time).
# The People LoRA only works when the prompt starts with its trigger word.
SKIN_TRIGGER = "r34l1sm"
SKIN_TIER_LORAS = {
    "skin_god": (SKIN_PEOPLE_LORA, TURBO_LORAS["v4"]),
    "skin_balanced": (SKIN_PEOPLE_LORA, SKIN_REF2V_8STEP_LORA),
    "skin_max": (SKIN_REF2V_8STEP_LORA,),
    "skin_app": (SKIN_PEOPLE_LORA,),
}


SKIN_SPEED_LORAS = {
    "pika": PIKA_REF2VA_LORA,
    "ema600": TURBO_LORAS["v4"],
    "ref8": SKIN_REF2V_8STEP_LORA,
    "ref_v01": REF2VA_TURBO_LORA,
}
SKIN_DEFAULT_OPTIONS = {
    "model": "pruned", "speed_lora": "tier", "speed_strength": 1.0, "people_strength": 1.0,
    "shift_video": 12.0, "shift_audio": 3.0, "scheduler": "beta", "tail_steps": 0,
    "flow": "t8", "ref_size": "max",
}


def skin_loras(tier: str, options: dict, mode: str = "reference") -> list[tuple[str, float]]:
    """The (LoRA, strength) stack for a tier after the per-job overrides."""
    tier_loras = SKIN_TIER_LORAS[tier]
    people = SKIN_PEOPLE_LORA in tier_loras and options["people_strength"] > 0
    if options["speed_lora"] == "tier":
        speed = [lora for lora in tier_loras if lora != SKIN_PEOPLE_LORA]
    elif options["speed_lora"] == "none":
        speed = []
    else:
        # Frame and lip-sync modes run on the FL2VA base, so they take the FL2VA file.
        # Pika Turbo has no reference file: the engine refuses Turbo in reference mode.
        fl2va = {"pika": PIKA_FL2VA_LORA, "pika_turbo4": PIKA_TURBO4_FL2VA_LORA}
        speed = [fl2va[options["speed_lora"]] if options["speed_lora"] in fl2va and mode != "reference"
                 else SKIN_SPEED_LORAS[options["speed_lora"]]]
    return ([(SKIN_PEOPLE_LORA, options["people_strength"])] if people else []) + \
        [(lora, options["speed_strength"]) for lora in speed]


def skin_prompt(prompt: str, people: bool) -> str:
    """Put the People LoRA trigger on its own first line, or remove it when the People LoRA is off."""
    lines = prompt.strip().splitlines()
    while lines and lines[0].strip().lower() == SKIN_TRIGGER:
        lines.pop(0)
    body = "\n".join(lines).strip()
    return f"{SKIN_TRIGGER}\n\n{body}" if people else body


def _skin_model(options: dict, mode: str = "reference") -> str:
    if options["model"] == "base":
        return REF2VA_MODEL if mode == "reference" else FL2VA_MODEL
    return SINGULARITY_FULL_MODEL if options["model"] == "full" else SINGULARITY_MODEL


def singularity_workflow(
    prompt: str,
    duration: float,
    seed: int,
    prefix: str,
    tier: str,
    width: int,
    height: int,
    image_names: list[str],
    mode: str = "reference",
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    video_names: list[str] | None = None,
    audio_name: str | None = None,
    include_audio: bool = True,
    steps: int = 8,
    options: dict | None = None,
):
    """One pass of the Prompt Mastery "Most Realistic Skin" setup (8 steps by default), in any H3 mode.

    Singularity -> tier LoRAs -> T8 Dual-Clock sampler (shift 12 video / 3 audio,
    dual_clock_euler, beta). Reference mode conditions through Reference-to-Video
    (refs at 'max' size), the pack's own graph. Text and frame modes use
    Image-to-Video, and lip-sync locks the uploaded audio with Native AudioLock,
    as the app's Turbo flows do. The video decode is tiled with the 10 GB settings.
    """
    lip_sync = mode == "lip_sync"
    condition = "136" if mode == "reference" else "104"
    nodes = _common_decode(condition, "130", {"id": "130", "scheduler": "130"}, seed, prefix,
                           reference=True, include_audio=include_audio and not lip_sync)
    options = {**SKIN_DEFAULT_OPTIONS, **(options or {})}
    nodes["11"]["inputs"]["vae_name"] = FUSED_VIDEO_VAE
    nodes["10"] = {"class_type": "VAEDecodeTiled", "inputs": {
        "samples": ["14", 0], "vae": ["11", 0],
        "tile_size": 512, "overlap": 64, "temporal_size": 64, "temporal_overlap": 16,
    }}
    loras = skin_loras(tier, options, mode)
    people = any(lora == SKIN_PEOPLE_LORA for lora, _ in loras)
    nodes["14"]["inputs"].update(sampler=["130", 1], sigmas=["130", 2])
    if options["tail_steps"]:
        nodes["131"] = {"class_type": "MiniMaxH3AVTailDetailScheduleT8Advanced", "inputs": {
            "sigmas": ["130", 2], "extra_tail_steps": options["tail_steps"], "spacing": "video_sigma_linear",
            "shift_video": options["shift_video"], "shift_audio": options["shift_audio"], "profile": "custom_strict"}}
        nodes["14"]["inputs"]["sigmas"] = ["131", 0]
    nodes["127"] = {"class_type": "UNETLoader", "inputs": {"unet_name": _skin_model(options, mode), "weight_dtype": "default"}}
    model = ["127", 0]
    for index, (lora, strength) in enumerate(loras):
        node_id = str(160 + index)
        if lora == TURBO_LORAS["v4"]:
            # EMA-600 has unprefixed keys and adaln updates that the pruned base
            # folds into its curves; ComfyUI 0.33's LoRA loader skips all 518 keys.
            # The app's Turbo LoRA node applies it (same settings as the app).
            nodes[node_id] = {"class_type": "MiniMaxH3TurboLoRA", "inputs": {
                "model": model, "lora_name": lora, "strength": strength, "low_vram": True}}
        else:
            nodes[node_id] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": model, "lora_name": lora, "strength_model": strength}}
        model = [node_id, 0]
    latent = [condition, 1]
    if lip_sync:
        nodes["23"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_name}}
        nodes["170"] = {"class_type": "MiniMaxH3NativeAudioLock", "inputs": {
            "model": model, "av_latent": [condition, 1], "audio_vae": ["24", 0], "audio": ["23", 0]}}
        model, latent = ["170", 0], ["170", 1]
        nodes["91"]["inputs"]["audio"] = ["170", 2]
    nodes["14"]["inputs"]["latent_image"] = latent
    nodes["130"] = {"class_type": "MiniMaxH3DualClockSamplerT8", "inputs": {
        "model": model, "av_latent": latent, "steps": steps, "shift_video": options["shift_video"],
        "shift_audio": options["shift_audio"], "sampler_name": "dual_clock_euler", "scheduler": options["scheduler"],
    }}
    if options["flow"] == "pika":
        # Pika H3 Flex release contract (as in Comfy-Org's Pika templates): fixed knots, lcm sampler.
        nodes["130"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "lcm"}}
        nodes["132"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": PIKA_SIGMAS}}
        nodes["14"]["inputs"].update(sampler=["130", 0], sigmas=["132", 0])
        nodes["16"]["inputs"]["model"] = model
    if mode != "reference":
        nodes["104"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["13", 0], "vae": ["11", 0], "prompt": skin_prompt(prompt, people),
            "width": width, "height": height, "length": h3_frame_count(duration)}}
        if first_frame_name:
            nodes["200"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
            nodes["104"]["inputs"]["first_frame"] = ["200", 0]
        if last_frame_name:
            nodes["201"] = {"class_type": "LoadImage", "inputs": {"image": last_frame_name}}
            nodes["104"]["inputs"]["last_frame"] = ["201", 0]
        return deepcopy(nodes)
    nodes["136"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
        "clip": ["13", 0], "vae": ["11", 0], "audio_vae": ["24", 0], "prompt": skin_prompt(prompt, people),
        "width": width, "height": height, "length": h3_frame_count(duration), "ref_image_size": options["ref_size"]}}
    for index, name in enumerate(image_names[:9]):
        node_id = str(137 + index)
        nodes[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        reference_input(nodes["136"]["inputs"], "ref_images", index, [node_id, 0])
    for index, name in enumerate((video_names or [])[:3]):
        load_id = str(150 + index * 2)
        component_id = str(151 + index * 2)
        nodes[load_id] = {"class_type": "LoadVideo", "inputs": {"file": name}}
        nodes[component_id] = {"class_type": "GetVideoComponents", "inputs": {"video": [load_id, 0]}}
        reference_input(nodes["136"]["inputs"], "ref_videos", index, [component_id, 0])
        if include_audio:
            reference_input(nodes["136"]["inputs"], "ref_video_audios", index, [component_id, 1])
    if audio_name:
        nodes["180"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_name}}
        reference_input(nodes["136"]["inputs"], "ref_audios", 0, ["180", 0])
    return deepcopy(nodes)



def omni_workflow(
    prompt: str,
    duration: float,
    seed: int,
    prefix: str,
    width: int,
    height: int,
    image_names: list[str],
    video_names: list[str] | None = None,
    audio_name: str | None = None,
    include_audio: bool = True,
):
    """FastH3 OmniRef 8-step, as Comfy-Org's video_fasth3_ominiref_r2v template: euler + simple, 8 steps, CFG 1
    (BasicGuider), shift 12 video / 3 audio, Comfy Kitchen INT8 attention and VSA sparse attention keeping 10 %.

    Reference videos go in for motion and camera only. Their soundtrack is not passed in: in the lab it made
    Omni invent a new lip-sync performance instead of keeping the moves."""
    nodes = {
        "119": {"class_type": "VAELoader", "inputs": {"vae_name": FUSED_VIDEO_VAE}},
        "120": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "127": {"class_type": "UNETLoader", "inputs": {"unet_name": OMNI_MODEL, "weight_dtype": "default"}},
        "128": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"}},
        "141": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["127", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "142": {"class_type": "ModelAttentionBackend", "inputs": {"model": ["141", 0], "attention": "comfy kitchen attention"}},
        "143": {"class_type": "BlockSparseAttention", "inputs": {
            "model": ["142", 0], "selection": "vsa", "selection.keep_percent": 10.0, "start_percent": 0.0,
            "end_percent": 1.0, "dense_blocks": "", "min_tokens": 12288, "extra_tokens": 256,
            "sink_conditioning": "exact_kv_and_rows", "verbose": False}},
        "136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["128", 0], "vae": ["119", 0], "audio_vae": ["120", 0], "prompt": prompt,
            "width": width, "height": height, "length": h3_frame_count(duration), "ref_image_size": "match"}},
        "123": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "124": {"class_type": "BasicScheduler", "inputs": {"model": ["143", 0], "scheduler": "simple", "steps": 8, "denoise": 1.0}},
        "126": {"class_type": "BasicGuider", "inputs": {"model": ["143", 0], "conditioning": ["136", 0]}},
        "129": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "125": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["129", 0], "guider": ["126", 0], "sampler": ["123", 0], "sigmas": ["124", 0],
            "latent_image": ["136", 1]}},
        "122": {"class_type": "VAEDecode", "inputs": {"samples": ["125", 0], "vae": ["119", 0]}},
    }
    if include_audio:
        nodes["121"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["125", 0], "vae": ["120", 0]}}
        nodes["130"] = {"class_type": "CreateVideo", "inputs": {"images": ["122", 0], "audio": ["121", 0], "fps": float(FPS)}}
    else:
        nodes["130"] = {"class_type": "CreateVideo", "inputs": {"images": ["122", 0], "fps": float(FPS)}}
    nodes["92"] = {"class_type": "SaveVideo", "inputs": {"video": ["130", 0], "filename_prefix": prefix,
                                                        "format": "mp4", "codec": "auto"}}
    # ComfyUI reads autogrow inputs only as flat "group.slot" keys; a nested {"ref_images": {...}} dict is
    # dropped without an error, and the node then runs on the prompt alone.
    reference = nodes["136"]["inputs"]
    for index, name in enumerate(image_names[:9]):
        node_id = str(137 + index)
        nodes[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        reference[f"ref_images.ref_image_{index}"] = [node_id, 0]
    for index, name in enumerate((video_names or [])[:3]):
        load_id = str(150 + index * 2)
        component_id = str(151 + index * 2)
        nodes[load_id] = {"class_type": "LoadVideo", "inputs": {"file": name}}
        nodes[component_id] = {"class_type": "GetVideoComponents", "inputs": {"video": [load_id, 0]}}
        reference[f"ref_videos.ref_video_{index}"] = [component_id, 0]
    if audio_name:
        nodes["180"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_name}}
        reference["ref_audios.ref_audio_0"] = ["180", 0]
    return deepcopy(nodes)


def singularity_app_workflow(
    prompt: str,
    duration: float,
    seed: int,
    prefix: str,
    mode: str,
    width: int,
    height: int,
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    audio_name: str | None = None,
    include_audio: bool = True,
    steps: int = 8,
    options: dict | None = None,
):
    """The app's own Turbo v4 graph (8 steps by default) with Singularity as the model and the People LoRA added.

    Lip-sync is native_audio_lock_workflow and the other modes are turbo_workflow, so
    everything but the model and the extra LoRA matches the app's tested 1.5 MP jobs.
    The People LoRA goes in through the standard loader, the same add_patches merge the
    Turbo LoRA node uses with low_vram on.
    """
    options = {**SKIN_DEFAULT_OPTIONS, **(options or {})}
    people = options["people_strength"] > 0
    if mode == "lip_sync":
        nodes = native_audio_lock_workflow(
            skin_prompt(prompt, people), duration, seed, prefix, audio_name=audio_name,
            first_frame_name=first_frame_name, last_frame_name=last_frame_name, steps=steps,
            width=width, height=height, turbo=True, turbo_profile="v4")
    else:
        nodes = turbo_workflow(
            skin_prompt(prompt, people), duration, seed, prefix, first_frame_name=first_frame_name,
            last_frame_name=last_frame_name, steps=steps, width=width, height=height,
            turbo_profile="v4", include_audio=include_audio)
    # Exact size, as in the lab tests, instead of the megapixel selector.
    nodes["104"]["inputs"].update(width=width, height=height)
    nodes["6"]["inputs"]["unet_name"] = _skin_model(options)
    for node in nodes.values():
        if node["class_type"] == "MiniMaxH3SigmaShift":
            node["inputs"].update(shift_video=options["shift_video"], shift_audio=options["shift_audio"])
    if people:
        nodes["165"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["6", 0], "lora_name": SKIN_PEOPLE_LORA, "strength_model": options["people_strength"]}}
        nodes["18"]["inputs"]["model"] = ["165", 0]
    return nodes


SAGE_ATTENTION_NODE = "PathchSageAttentionKJ"
STEADY_MEMORY_NODE = "H3SteadyMemory"
SLA_ATTENTION_NODE = "H3SLAAttention"
# Same settings as the Fused SLA chain, measured on the Turbo flows in the
# speed lab (sparsity 0.90, 64x64 blocks, dense below 8192 tokens).
SLA_ATTENTION_INPUTS = {
    "sparsity_ratio": 0.90, "block_size": "64", "min_seq_len": 8192,
    "dense_last_steps": 0, "protect_audio": True, "enabled": True,
}


INT8_ATTENTION_NODE = "ModelAttentionBackend"
INT8_ATTENTION_INPUTS = {"attention": "comfy kitchen attention"}


def attention_node_classes(attention_mode: str) -> set[str]:
    """ComfyUI node classes an attention mode adds to a workflow."""
    classes = set()
    if attention_mode == "int8":
        classes.add(INT8_ATTENTION_NODE)
    if attention_mode in {"sage", "sage_sla"}:
        classes.add(SAGE_ATTENTION_NODE)
    if attention_mode in {"sla", "sage_sla"}:
        classes.add(SLA_ATTENTION_NODE)
    return classes


def steady_memory_needed(engine: str, attention_mode: str) -> bool:
    """Pika with Sage peaks near the card's spill point; Singularity stays well below it and runs faster without
    the waits. See docs/HARDWARE_AND_VRAM.md."""
    return engine == "pika" and attention_mode == "sage"


def _insert_model_patch(nodes: dict, source: str, class_type: str, inputs: dict) -> str:
    """Insert a MODEL->MODEL node after `source` and rewire its MODEL consumers."""
    node_id = str(max(int(key) for key in nodes if key.isdigit()) + 1)
    for node in nodes.values():
        for key, value in node["inputs"].items():
            if key == "model" and value == [source, 0]:
                node["inputs"][key] = [node_id, 0]
    nodes[node_id] = {"class_type": class_type, "inputs": {"model": [source, 0], **inputs}}
    return node_id


def apply_attention_mode(workflow: dict, attention_mode: str) -> dict:
    """Return a copy of `workflow` with the requested per-job attention patch.

    "standard" returns the workflow unchanged. Sage is applied through the
    KJNodes per-model patch, so it never needs a ComfyUI restart or a global
    --use-sage-attention flag. In graphs that already run H3SLAAttention
    (Fused SLA), Sage is inserted just before it so SLA's dense fallback uses
    Sage. Otherwise the patches go after the Turbo LoRA, or after the UNET
    loader when there is no LoRA: Sage first, then SLA.
    """
    if attention_mode == "standard":
        return workflow
    if attention_mode not in {"sage", "sla", "sage_sla", "int8"}:
        raise ValueError(f"Unknown attention mode: {attention_mode}")
    nodes = deepcopy(workflow)
    sage_inputs = {"sage_attention": "auto", "allow_compile": False}
    existing_sla = [key for key, node in nodes.items() if node["class_type"] == SLA_ATTENTION_NODE]
    if existing_sla:
        if attention_mode == "int8":
            raise ValueError("int8 attention is not offered on graphs that already run sparse attention")
        if attention_mode != "sage":
            raise ValueError("This workflow already uses sparse attention; only Sage can be added")
        upstream = nodes[existing_sla[0]]["inputs"]["model"][0]
        _insert_model_patch(nodes, upstream, SAGE_ATTENTION_NODE, sage_inputs)
        return nodes
    anchor = next(
        (key for class_type in ("MiniMaxH3TurboLoRA", "UNETLoader")
         for key, node in nodes.items() if node["class_type"] == class_type),
        None,
    )
    if anchor is None:
        raise ValueError("Workflow has no model loader to patch")
    # Pika's and the Singularity tiers' LoRAs load through LoraLoaderModelOnly; the patches go after those too.
    while True:
        lora = next((key for key, node in nodes.items() if node["class_type"] in ("LoraLoaderModelOnly", "MiniMaxH3TurboLoRA")
                     and node["inputs"].get("model") == [anchor, 0]), None)
        if lora is None:
            break
        anchor = lora
    if attention_mode == "int8":
        _insert_model_patch(nodes, anchor, INT8_ATTENTION_NODE, dict(INT8_ATTENTION_INPUTS))
        return nodes
    if attention_mode in {"sage", "sage_sla"}:
        anchor = _insert_model_patch(nodes, anchor, SAGE_ATTENTION_NODE, sage_inputs)
    if attention_mode in {"sla", "sage_sla"}:
        _insert_model_patch(nodes, anchor, SLA_ATTENTION_NODE, dict(SLA_ATTENTION_INPUTS))
    return nodes


def int8_decode_needed(engine: str, attention_mode: str) -> bool:
    """Turbo's int8 option also decodes with the INT8 video VAE: the combination that was lab-tested (decode 63 s ->
    27 s at 1.5 MP, PSNR 42-47 dB against the fp16 VAE on the same latent). The other int8 engines already decode with
    an INT8 VAE (Singularity) or their own VAE (LTX)."""
    return engine == "turbo" and attention_mode == "int8"


def apply_int8_decode(workflow: dict) -> dict:
    """Return a copy whose video decoders use the INT8 video VAE; the frame encode keeps its own VAE."""
    nodes = deepcopy(workflow)
    decoders = [node for node in nodes.values() if node["class_type"] in ("VAEDecode", "VAEDecodeTiled")]
    if not decoders:
        raise ValueError("Workflow has no video decoder for the INT8 VAE")
    loader = str(max(int(key) for key in nodes if key.isdigit()) + 1)
    nodes[loader] = {"class_type": "VAELoader", "inputs": {"vae_name": FUSED_VIDEO_VAE}}
    for node in decoders:
        node["inputs"]["vae"] = [loader, 0]
    return nodes


def apply_steady_memory(workflow: dict) -> dict:
    """Return a copy of a Sage workflow with the memory patch right after the Sage node."""
    nodes = deepcopy(workflow)
    sage = next(key for key, node in nodes.items() if node["class_type"] == SAGE_ATTENTION_NODE)
    _insert_model_patch(nodes, sage, STEADY_MEMORY_NODE, {})
    return nodes


LTX_FPS = 24


def ltx_frame_count(duration: float) -> int:
    """LTX needs 8k+1 frames; this mirrors the graph's length expression."""
    return 8 * round(duration * LTX_FPS / 8) + 1


def ltx_lipsync_workflow(
    prompt: str,
    duration: float,
    seed: int,
    prefix: str,
    audio_name: str,
    first_frame_name: str,
    width: int,
    height: int,
) -> dict:
    """LTX-2.5 image+audio-to-video lip-sync, one distilled pass, no upscaler.

    The uploaded audio is already trimmed by the bridge, so the graph reads it
    from offset 0, holds it fixed while sampling and muxes it into the output.
    """
    if width % 32 or height % 32:
        raise ValueError("LTX width and height must be multiples of 32")
    nodes = json.loads(LTX_WORKFLOW.read_text(encoding="utf-8"))
    nodes["269"]["inputs"]["image"] = first_frame_name
    nodes["276"]["inputs"]["audio"] = audio_name
    nodes["340:306"]["inputs"]["text"] = prompt
    nodes["340:286"]["inputs"]["noise_seed"] = seed
    nodes["340:330"]["inputs"]["value"] = width
    nodes["340:324"]["inputs"]["value"] = height
    nodes["340:294"]["inputs"]["longer_edge"] = max(width, height)
    nodes["340:323"]["inputs"]["value"] = LTX_FPS
    nodes["clip_duration"]["inputs"]["value"] = float(duration)
    nodes["audio_offset"]["inputs"]["value"] = 0.0
    nodes["341"]["inputs"]["filename_prefix"] = prefix
    return nodes


def ltx_node_classes() -> set[str]:
    """Every ComfyUI node class the LTX lip-sync template uses."""
    nodes = json.loads(LTX_WORKFLOW.read_text(encoding="utf-8"))
    return {node["class_type"] for node in nodes.values()}


LTX_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted face, deformed hands, extra fingers, flickering, jitter, "
    "warped background, text, subtitles, watermark"
)
LTX_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"


def ltx_video_workflow(
    mode: str,
    prompt: str,
    duration: float,
    seed: int,
    prefix: str,
    width: int,
    height: int,
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    include_audio: bool = True,
    sharp_decode: bool = False,
    calm_sampler: bool = False,
) -> dict:
    """LTX-2.5 text/image-to-video with generated audio, one distilled pass.

    Modes: "text" (no image), "opening"/"frames" (first frame in place),
    "closing"/"frames" (last frame pinned with LTXVAddGuide at frame -1).
    Reference mode has its own builder, ltx_reference_workflow.
    LTX always generates audio with the video; include_audio=False only
    leaves it out of the saved file.

    sharp_decode swaps the temporal-tiled decode (whose chunk joins soften a
    few frames every two seconds) for LTX's spatial-only tiled decode;
    calm_sampler swaps euler_ancestral for euler, which adds no fresh noise
    per step and flickers less. Both are opt-in.
    """
    if width % 32 or height % 32:
        raise ValueError("LTX width and height must be multiples of 32")
    if mode == "text" and (first_frame_name or last_frame_name):
        raise ValueError("Text mode takes no images")
    if mode in ("opening", "frames") and not first_frame_name:
        raise ValueError(f"{mode} mode needs an opening image")
    if mode == "closing" and not last_frame_name:
        raise ValueError("Closing mode needs a closing image")
    if mode not in ("text", "opening", "closing", "frames"):
        raise ValueError(f"Unsupported LTX mode: {mode}")
    frames = ltx_frame_count(duration)
    nodes = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": LTX_TRANSFORMER, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": LTX_TEXT_ENCODER, "type": "ltxv", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": LTX_VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": LTX_AUDIO_VAE}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": LTX_NEGATIVE_PROMPT, "clip": ["2", 0]}},
        "7": {"class_type": "LTXVConditioning", "inputs": {"positive": ["5", 0], "negative": ["6", 0], "frame_rate": float(LTX_FPS)}},
        "8": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": width, "height": height, "length": frames, "batch_size": 1}},
        "9": {"class_type": "LTXVEmptyLatentAudio", "inputs": {"frames_number": frames, "frame_rate": LTX_FPS, "batch_size": 1, "audio_vae": ["4", 0]}},
    }
    positive, negative, video_latent = ["7", 0], ["7", 1], ["8", 0]

    def prepared_image(node_id: str, name: str) -> list:
        nodes[f"{node_id}0"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        nodes[f"{node_id}1"] = {"class_type": "ResizeImageMaskNode", "inputs": {
            "resize_type": "scale dimensions", "resize_type.width": width, "resize_type.height": height,
            "resize_type.crop": "center", "scale_method": "lanczos", "input": [f"{node_id}0", 0]}}
        nodes[f"{node_id}2"] = {"class_type": "LTXVPreprocess", "inputs": {"img_compression": 18, "image": [f"{node_id}1", 0]}}
        return [f"{node_id}2", 0]

    if first_frame_name and mode in ("opening", "frames"):
        nodes["12"] = {"class_type": "LTXVImgToVideoInplace", "inputs": {
            "vae": ["3", 0], "image": prepared_image("10", first_frame_name),
            "latent": video_latent, "strength": 0.7, "bypass": False}}
        video_latent = ["12", 0]
    last_frame_guide = bool(last_frame_name and mode in ("closing", "frames"))
    if last_frame_guide:
        nodes["22"] = {"class_type": "LTXVAddGuide", "inputs": {
            "positive": positive, "negative": negative, "vae": ["3", 0], "latent": video_latent,
            "image": prepared_image("20", last_frame_name), "frame_idx": -1, "strength": 1.0}}
        positive, negative, video_latent = ["22", 0], ["22", 1], ["22", 2]
    nodes.update({
        "30": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": video_latent, "audio_latent": ["9", 0]}},
        "31": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "32": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": positive, "negative": negative, "cfg": 1.0}},
        "33": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler" if calm_sampler else "euler_ancestral"}},
        "34": {"class_type": "ManualSigmas", "inputs": {"sigmas": LTX_SIGMAS}},
        "35": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["31", 0], "guider": ["32", 0], "sampler": ["33", 0], "sigmas": ["34", 0], "latent_image": ["30", 0]}},
        "36": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["35", 0]}},
    })
    decoded_video = ["36", 0]
    if last_frame_guide:
        # Drop the appended guide frame before decoding.
        nodes["37"] = {"class_type": "LTXVCropGuides", "inputs": {"positive": positive, "negative": negative, "latent": ["36", 0]}}
        decoded_video = ["37", 2]
    if sharp_decode:
        nodes["40"] = _ltx_seam_free_decode(decoded_video, ["3", 0], frames, width * height)
    else:
        nodes["40"] = {"class_type": "VAEDecodeTiled", "inputs": {
            "tile_size": 512, "overlap": 64, "temporal_size": 64, "temporal_overlap": 16,
            "samples": decoded_video, "vae": ["3", 0]}}
    video_inputs = {"images": ["40", 0], "fps": float(LTX_FPS)}
    if include_audio:
        nodes["41"] = {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["36", 1], "audio_vae": ["4", 0]}}
        video_inputs["audio"] = ["41", 0]
    nodes["42"] = {"class_type": "CreateVideo", "inputs": video_inputs}
    nodes["43"] = {"class_type": "SaveVideo", "inputs": {"video": ["42", 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"}}
    return nodes


LTX_DECODE_OVERLAP = 4


def _ltx_seam_free_decode(samples: list, vae: list, frames: int, pixels: int) -> dict:
    """LTX's spatial-only tiled decode: the whole clip in one temporal pass.

    Lab peaks on the RTX 3080: 4x2 tiles at 1600x896 / 121 frames used 7.9 GB,
    6x4 tiles at 1536x896 / 241 frames used 6.6 GB. Longer or larger clips
    get the smaller 6x4 tiles.

    Tiles blend over ``overlap`` latent cells (32 px each). With 1 cell the
    tiles' slight brightness differences showed as faint rectangles on smooth
    surfaces, with steps at the blend edges (S04 A/B at 1888x1056); 4 cells
    fade them out.
    """
    small = frames <= 121 and pixels <= 1600 * 896
    return {"class_type": "LTXVTiledVAEDecode", "inputs": {
        "vae": vae, "latents": samples, "horizontal_tiles": 4 if small else 6,
        "vertical_tiles": 2 if small else 4, "overlap": LTX_DECODE_OVERLAP, "last_frame_fix": False}}


# The Ingredients IC-LoRA grid (the only size Lightricks trained) and the x2
# refine schedule shared by both reference recipes.
LTX_REFERENCE_GRID = (768, 448)
LTX_REFINE_SIGMAS = "0.85, 0.7250, 0.4219, 0.0"
LTX_INGREDIENTS_NEGATIVE = "worst quality, inconsistent motion, blurry, jittery, distorted"
# LTX 2.5 tends to open on the sheet itself; this line (lab R18) and the
# matching negative terms keep the clip inside the scene from frame one.
LTX25_REFERENCE_OPENING = (
    "The video opens directly inside the scene from the very first frame and never shows "
    "the reference sheet, its panels or a grey studio background."
)
LTX25_REFERENCE_NEGATIVE = "reference sheet, collage, split screen, panels, grey studio background, " + LTX_INGREDIENTS_NEGATIVE


def ltx25_reference_prompt(prompt: str) -> str:
    """Put the opening line where the target description starts (lab R18/R22).

    The text after the line keeps exactly one separating space: in the lab a
    doubled space alone was enough to flip a clean seed into opening on the sheet.
    """
    for marker, joiner in (("### Target Description\n", ""), ("Generated video:", " ")):
        if marker in prompt:
            head, tail = prompt.split(marker, 1)
            return f"{head}{marker}{joiner}{LTX25_REFERENCE_OPENING} {tail.lstrip(' ')}"
    return f"{LTX25_REFERENCE_OPENING} {prompt.lstrip(' ')}"


def ltx_reference_workflow(
    model: str,
    prompt: str,
    duration: float,
    seed: int,
    prefix: str,
    sheet_name: str,
    include_audio: bool = True,
) -> dict:
    """LTX reference mode, built exactly as tested in the speed lab.

    One reference sheet goes through Lightricks' Ingredients IC-LoRA on the
    768x448 grid it was trained on (letterboxed, never cropped). The latent is
    then upscaled x2, refined in three steps without the IC-LoRA, and decoded
    seam-free to 1536x896.

    "2.5" (lab R20-R22): LTX-2.5 distilled with the 2.5 Ingredients LoRA,
    euler_ancestral, plus the opening line that stops 2.5 showing the sheet.
    "2.3" (lab R9-R14): LTX-2.3 dev fp8 with the distilled LoRA at 0.5 and
    the 2.3 Ingredients LoRA, euler.
    """
    if model not in ("2.5", "2.3"):
        raise ValueError("LTX reference model must be 2.5 or 2.3")
    if not sheet_name:
        raise ValueError("Reference mode needs a reference sheet image")
    frames = ltx_frame_count(duration)
    grid_w, grid_h = LTX_REFERENCE_GRID
    if model == "2.5":
        nodes = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": LTX_TRANSFORMER, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": LTX_TEXT_ENCODER, "type": "ltxv", "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": LTX_VIDEO_VAE}},
            "4": {"class_type": "VAELoader", "inputs": {"vae_name": LTX_AUDIO_VAE}},
            "50": {"class_type": "LTXICLoRALoaderModelOnly", "inputs": {
                "model": ["1", 0], "lora_name": LTX25_INGREDIENTS_LORA, "strength_model": 1.0}},
        }
        base_model, clip, video_vae, audio_vae = ["1", 0], ["2", 0], ["3", 0], ["4", 0]
        text, negative_text = ltx25_reference_prompt(prompt), LTX25_REFERENCE_NEGATIVE
        sampler, upscaler = "euler_ancestral", LTX25_LATENT_UPSCALER
    else:
        nodes = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": LTX23_CHECKPOINT}},
            "2": {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": ["1", 0], "lora_name": LTX23_DISTILLED_LORA, "strength_model": 0.5}},
            "50": {"class_type": "LTXICLoRALoaderModelOnly", "inputs": {
                "model": ["2", 0], "lora_name": LTX23_INGREDIENTS_LORA, "strength_model": 1.0}},
            "4": {"class_type": "LTXAVTextEncoderLoader", "inputs": {
                "text_encoder": LTX23_TEXT_ENCODER, "ckpt_name": LTX23_CHECKPOINT, "device": "default"}},
            "12": {"class_type": "LTXVAudioVAELoader", "inputs": {"ckpt_name": LTX23_CHECKPOINT}},
        }
        base_model, clip, video_vae, audio_vae = ["2", 0], ["4", 0], ["1", 2], ["12", 0]
        text, negative_text = prompt, LTX_INGREDIENTS_NEGATIVE
        sampler, upscaler = "euler", LTX23_LATENT_UPSCALER
    nodes.update({
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": clip}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_text, "clip": clip}},
        "7": {"class_type": "LTXVConditioning", "inputs": {"positive": ["5", 0], "negative": ["6", 0], "frame_rate": float(LTX_FPS)}},
        "8": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": grid_w, "height": grid_h, "length": frames, "batch_size": 1}},
        "9": {"class_type": "LTXVEmptyLatentAudio", "inputs": {"frames_number": frames, "frame_rate": LTX_FPS, "batch_size": 1, "audio_vae": audio_vae}},
        "53": {"class_type": "LoadImage", "inputs": {"image": sheet_name}},
        "54": {"class_type": "ResizeAndPadImage", "inputs": {
            "image": ["53", 0], "target_width": grid_w, "target_height": grid_h,
            "padding_color": "black", "interpolation": "lanczos"}},
        "51": {"class_type": "RepeatImageBatch", "inputs": {"image": ["54", 0], "amount": frames}},
        "52": {"class_type": "LTXAddVideoICLoRAGuide", "inputs": {
            "positive": ["7", 0], "negative": ["7", 1], "vae": video_vae, "latent": ["8", 0],
            "image": ["51", 0], "frame_idx": 0, "strength": 1.0, "latent_downscale_factor": ["50", 1],
            "crop": "disabled", "use_tiled_encode": False, "tile_size": 256, "tile_overlap": 64}},
        "30": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["52", 2], "audio_latent": ["9", 0]}},
        "31": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "32": {"class_type": "CFGGuider", "inputs": {"model": ["50", 0], "positive": ["52", 0], "negative": ["52", 1], "cfg": 1.0}},
        "33": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler}},
        "34": {"class_type": "ManualSigmas", "inputs": {"sigmas": LTX_SIGMAS}},
        "35": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["31", 0], "guider": ["32", 0], "sampler": ["33", 0], "sigmas": ["34", 0], "latent_image": ["30", 0]}},
        "36": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["35", 0]}},
        "37": {"class_type": "LTXVCropGuides", "inputs": {"positive": ["52", 0], "negative": ["52", 1], "latent": ["36", 0]}},
        # x2 latent upscale, then a three-step refine on the base model (no IC-LoRA).
        "70": {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": upscaler}},
        "71": {"class_type": "LTXVLatentUpsampler", "inputs": {"samples": ["37", 2], "upscale_model": ["70", 0], "vae": video_vae}},
        "72": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["71", 0], "audio_latent": ["36", 1]}},
        "73": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed + 1}},
        "74": {"class_type": "CFGGuider", "inputs": {"model": base_model, "positive": ["37", 0], "negative": ["37", 1], "cfg": 1.0}},
        "75": {"class_type": "ManualSigmas", "inputs": {"sigmas": LTX_REFINE_SIGMAS}},
        "76": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["73", 0], "guider": ["74", 0], "sampler": ["33", 0], "sigmas": ["75", 0], "latent_image": ["72", 0]}},
        "77": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["76", 0]}},
    })
    nodes["40"] = _ltx_seam_free_decode(["77", 0], video_vae, frames, grid_w * grid_h * 4)
    video_inputs = {"images": ["40", 0], "fps": float(LTX_FPS)}
    if include_audio:
        nodes["41"] = {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["77", 1], "audio_vae": audio_vae}}
        video_inputs["audio"] = ["41", 0]
    nodes["42"] = {"class_type": "CreateVideo", "inputs": video_inputs}
    nodes["43"] = {"class_type": "SaveVideo", "inputs": {"video": ["42", 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"}}
    return nodes


# ComfyUI's official LTX-2.5 templates (Comfy-Org/workflow_templates, video_ltx2_5_i2v / _flf2v),
# exported to API form by ComfyUI's own frontend. Only the inputs change:
# images, prompt, size, length, seed, prefix. The prompt-enhancer branch (off in the templates; its
# Gemma-E2B encoder is not installed) is removed and the prompt goes straight to the text encoder.

def official_ltx_template_workflow(mode: str, prompt: str, duration: float, seed: int, prefix: str, width: int,
                                   height: int, first_frame_name: str, last_frame_name: str | None = None) -> dict:
    nodes = json.loads(Path(OFFICIAL_LTX_TEMPLATES[mode]).read_text(encoding="utf-8"))

    def by_class(cls):
        return [key for key, node in nodes.items() if node["class_type"] == cls]

    def used(key):
        return any(isinstance(value, list) and value and value[0] == key
                   for node in nodes.values() for value in node["inputs"].values())

    for cls in ("TextGenerateLTX2Prompt", "PreviewAny", "ComfySwitchNode", "PrimitiveStringMultiline"):
        for key in by_class(cls):
            nodes.pop(key)
    for key in by_class("CLIPLoader"):
        if nodes[key]["inputs"]["clip_name"].startswith("gemma4_e2b"):
            nodes.pop(key)
    for key in by_class("PrimitiveBoolean"):
        if not used(key):
            nodes.pop(key)
    positive = [key for key in by_class("CLIPTextEncode") if isinstance(nodes[key]["inputs"]["text"], list)]
    assert len(positive) == 1, positive
    nodes[positive[0]]["inputs"]["text"] = prompt
    nodes[by_class("SaveVideo")[0]]["inputs"]["filename_prefix"] = prefix
    for key in by_class("RandomNoise"):
        if nodes[key]["inputs"]["noise_seed"] != 42:  # the i2v template's fixed refine seed (42) stays as shipped
            nodes[key]["inputs"]["noise_seed"] = seed
    seconds = [key for key in by_class("PrimitiveInt") if nodes[key]["inputs"]["value"] == 5]
    assert len(seconds) == 1, seconds
    nodes[seconds[0]]["inputs"]["value"] = int(round(duration))
    loads = by_class("LoadImage")
    if mode == "opening":
        nodes[loads[0]]["inputs"]["image"] = first_frame_name
        selector = by_class("ResolutionSelector")[0]
        for key in by_class("PrimitiveInt"):
            value = nodes[key]["inputs"]["value"]
            if value == [selector, 0]:
                nodes[key]["inputs"]["value"] = width
            elif value == [selector, 1]:
                nodes[key]["inputs"]["value"] = height
        nodes.pop(selector)
    else:
        # The last frame is the image whose resize -> preprocess chain feeds the LTXVAddGuide at frame -1.
        def guide_frame(load_key):
            for resize_key, resize in nodes.items():
                if resize["class_type"] == "ResizeImageMaskNode" and resize["inputs"].get("input") == [load_key, 0]:
                    for pre_key, pre in nodes.items():
                        if pre["class_type"] == "LTXVPreprocess" and pre["inputs"]["image"] == [resize_key, 0]:
                            for guide in nodes.values():
                                if guide["class_type"] == "LTXVAddGuide" and guide["inputs"]["image"] == [pre_key, 0]:
                                    return guide["inputs"]["frame_idx"]
            raise ValueError(f"LoadImage {load_key} feeds no guide")
        for key in loads:
            nodes[key]["inputs"]["image"] = last_frame_name if guide_frame(key) == -1 else first_frame_name
        for key in by_class("PrimitiveInt"):
            if nodes[key]["inputs"]["value"] == 1280:
                nodes[key]["inputs"]["value"] = width
            elif nodes[key]["inputs"]["value"] == 720:
                nodes[key]["inputs"]["value"] = height
    return deepcopy(nodes)


_NODE_VALUE_INPUTS = ("value", "image", "audio", "file", "video", "unet_name", "vae_name", "clip_name", "lora_name",
                      "ckpt_name", "model_name", "sampler_name", "text", "string")


def _linked_value(workflow: dict, link: list, depth: int = 0):
    """The constant a link ends at (a primitive, a file, a passthrough expression), or None if it is computed at run time."""
    node = workflow.get(link[0])
    if not isinstance(node, dict) or depth > 8:
        return None
    inputs = node.get("inputs") or {}
    expression = inputs.get("expression")
    if isinstance(expression, str) and f"values.{expression}" in inputs:
        candidates = [inputs[f"values.{expression}"]]
    elif isinstance(expression, str):
        return None
    else:
        candidates = [inputs[key] for key in _NODE_VALUE_INPUTS if key in inputs][:1]
    for item in candidates:
        if isinstance(item, list) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], int):
            return _linked_value(workflow, item, depth + 1)
        return item
    return None


def workflow_node_values(workflow: dict, text_limit: int = 240) -> list[dict]:
    """Each node's class and input values for the job log. A link to another node shows the value it carries
    and where it comes from, or the source node's class when the value is only computed at run time."""
    def shorten(item):
        if isinstance(item, int) and not isinstance(item, bool) and abs(item) > 2 ** 53:
            return str(item)  # 64-bit seeds lose digits as JSON numbers in the browser
        if isinstance(item, str) and len(item) > text_limit:
            return item[:text_limit] + f"... ({len(item)} chars)"
        return item
    def value(item):
        if isinstance(item, list) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], int):
            source = f"#{item[0]}" + (f".{item[1]}" if item[1] else "")
            linked = _linked_value(workflow, item)
            if linked is not None:
                return f"{shorten(linked)} (from {source})"
            return f"from {(workflow.get(item[0]) or {}).get('class_type', 'node')} {source}"
        if isinstance(item, dict):
            return {key: value(entry) for key, entry in item.items()}
        return shorten(item)
    def order(node_id):
        return (0, int(node_id)) if str(node_id).isdigit() else (1, str(node_id))
    return [{"id": str(node_id), "class_type": str(workflow[node_id].get("class_type")),
             "inputs": {key: value(entry) for key, entry in (workflow[node_id].get("inputs") or {}).items()}}
            for node_id in sorted(workflow, key=order)]
