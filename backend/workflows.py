import json
from copy import deepcopy

from .config import (AUDIO_VAE, CLIPPROJ_PROJECTION, CLIPPROJ_TEXT_ENCODER,
                     FL2VA_MODEL, FUSED_MOTION_ADAPTER, FUSED_SLA_MODEL,
                     FUSED_VIDEO_VAE, FUSED_WORKFLOW_FILES, LTX_AUDIO_VAE,
                     LTX_INGREDIENTS_LORA, LTX_TEXT_ENCODER, LTX_TRANSFORMER,
                     LTX_VIDEO_VAE, LTX_WORKFLOW,
                     REF2VA_MODEL, REF2VA_TURBO_LORA, TEXT_ENCODER, TURBO_LORAS,
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


SAGE_ATTENTION_NODE = "PathchSageAttentionKJ"
SLA_ATTENTION_NODE = "H3SLAAttention"
# Same settings as the Fused SLA chain, measured on the Turbo flows in the
# speed lab (sparsity 0.90, 64x64 blocks, dense below 8192 tokens).
SLA_ATTENTION_INPUTS = {
    "sparsity_ratio": 0.90, "block_size": "64", "min_seq_len": 8192,
    "dense_last_steps": 0, "protect_audio": True, "enabled": True,
}


def attention_node_classes(attention_mode: str) -> set[str]:
    """ComfyUI node classes an attention mode adds to a workflow."""
    classes = set()
    if attention_mode in {"sage", "sage_sla"}:
        classes.add(SAGE_ATTENTION_NODE)
    if attention_mode in {"sla", "sage_sla"}:
        classes.add(SLA_ATTENTION_NODE)
    return classes


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
    if attention_mode not in {"sage", "sla", "sage_sla"}:
        raise ValueError(f"Unknown attention mode: {attention_mode}")
    nodes = deepcopy(workflow)
    sage_inputs = {"sage_attention": "auto", "allow_compile": False}
    existing_sla = [key for key, node in nodes.items() if node["class_type"] == SLA_ATTENTION_NODE]
    if existing_sla:
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
    if attention_mode in {"sage", "sage_sla"}:
        anchor = _insert_model_patch(nodes, anchor, SAGE_ATTENTION_NODE, sage_inputs)
    if attention_mode in {"sla", "sage_sla"}:
        _insert_model_patch(nodes, anchor, SLA_ATTENTION_NODE, dict(SLA_ATTENTION_INPUTS))
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
    reference_image_name: str | None = None,
) -> dict:
    """LTX-2.5 text/image-to-video with generated audio, one distilled pass.

    Modes: "text" (no image), "opening"/"frames" (first frame in place),
    "closing"/"frames" (last frame pinned with LTXVAddGuide at frame -1),
    "reference" (one reference sheet through the Ingredients IC-LoRA,
    following Lightricks' official Ingredients graph).
    LTX always generates audio with the video; include_audio=False only
    leaves it out of the saved file.
    """
    if width % 32 or height % 32:
        raise ValueError("LTX width and height must be multiples of 32")
    if mode == "text" and (first_frame_name or last_frame_name):
        raise ValueError("Text mode takes no images")
    if mode in ("opening", "frames") and not first_frame_name:
        raise ValueError(f"{mode} mode needs an opening image")
    if mode == "closing" and not last_frame_name:
        raise ValueError("Closing mode needs a closing image")
    if mode == "reference" and not reference_image_name:
        raise ValueError("Reference mode needs a reference sheet image")
    if mode != "reference" and reference_image_name:
        raise ValueError("Only reference mode takes a reference sheet")
    if mode not in ("text", "opening", "closing", "frames", "reference"):
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
    model = ["1", 0]
    if mode == "reference":
        # Official Ingredients graph: IC-LoRA on the model, the sheet repeated
        # as a guide clip at the IC-LoRA's own grid, guide frames cropped after.
        nodes["50"] = {"class_type": "LTXICLoRALoaderModelOnly", "inputs": {
            "model": ["1", 0], "lora_name": LTX_INGREDIENTS_LORA, "strength_model": 1.0}}
        model = ["50", 0]
        nodes["51"] = {"class_type": "RepeatImageBatch", "inputs": {
            "image": prepared_image("50", reference_image_name), "amount": frames}}
        nodes["52"] = {"class_type": "LTXAddVideoICLoRAGuide", "inputs": {
            "positive": positive, "negative": negative, "vae": ["3", 0], "latent": video_latent,
            "image": ["51", 0], "frame_idx": 0, "strength": 1.0, "latent_downscale_factor": ["50", 1],
            "crop": "disabled", "use_tiled_encode": False, "tile_size": 256, "tile_overlap": 64}}
        positive, negative, video_latent = ["52", 0], ["52", 1], ["52", 2]
    last_frame_guide = bool(last_frame_name and mode in ("closing", "frames"))
    if last_frame_guide:
        nodes["22"] = {"class_type": "LTXVAddGuide", "inputs": {
            "positive": positive, "negative": negative, "vae": ["3", 0], "latent": video_latent,
            "image": prepared_image("20", last_frame_name), "frame_idx": -1, "strength": 1.0}}
        positive, negative, video_latent = ["22", 0], ["22", 1], ["22", 2]
    nodes.update({
        "30": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": video_latent, "audio_latent": ["9", 0]}},
        "31": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "32": {"class_type": "CFGGuider", "inputs": {"model": model, "positive": positive, "negative": negative, "cfg": 1.0}},
        "33": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},
        "34": {"class_type": "ManualSigmas", "inputs": {"sigmas": LTX_SIGMAS}},
        "35": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["31", 0], "guider": ["32", 0], "sampler": ["33", 0], "sigmas": ["34", 0], "latent_image": ["30", 0]}},
        "36": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["35", 0]}},
    })
    decoded_video = ["36", 0]
    if last_frame_guide or mode == "reference":
        # Drop the appended guide frames before decoding.
        nodes["37"] = {"class_type": "LTXVCropGuides", "inputs": {"positive": positive, "negative": negative, "latent": ["36", 0]}}
        decoded_video = ["37", 2]
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
