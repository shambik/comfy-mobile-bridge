from copy import deepcopy

from .config import (AUDIO_VAE, CLIPPROJ_PROJECTION, CLIPPROJ_TEXT_ENCODER,
                     FL2VA_MODEL, REF2VA_MODEL, TEXT_ENCODER, TURBO_LORAS,
                     VIDEO_VAE)

FPS = 24


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
):
    nodes = {
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "13": _clip_loader(encoder, reference=reference),
        "15": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "16": {"class_type": "BasicGuider", "inputs": {"model": [model_node, 0], "conditioning": [condition_node, 0]}},
        "23": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["14", 0], "vae": ["24", 0]}},
        "24": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["11", 0]}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["15", 0], "guider": ["16", 0], "sampler": [sampler_node["id"], 0],
            "sigmas": [sampler_node["scheduler"], 0], "latent_image": [condition_node, 1]}},
        "91": {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "fps": FPS, "audio": ["23", 0], "bit_depth": 8}},
        "92": {"class_type": "SaveVideo", "inputs": {"video": ["91", 0], "filename_prefix": prefix, "format": "mp4", "codec": "auto"}},
    }
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
    encoder: str = "native",
    turbo_profile: str = "v1",
):
    length = 124 if duration == 5 else 243
    nodes = _common_decode("104", "18", {"id": "19", "scheduler": "9"}, seed, prefix, encoder)
    nodes.update({
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": FL2VA_MODEL, "weight_dtype": "default"}},
        "18": {"class_type": "MiniMaxH3TurboLoRA", "inputs": {"model": ["6", 0], "lora_name": TURBO_LORAS[turbo_profile], "strength": 1.0, "low_vram": True}},
        "19": {"class_type": "MiniMaxH3TurboSampler", "inputs": {}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["18", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0], "prompt": prompt, "width": width, "height": height, "length": length}},
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
    encoder: str = "native",
):
    length = 124 if duration == 5 else 243
    nodes = _common_decode("104", "6", {"id": "17", "scheduler": "9"}, seed, prefix, encoder)
    nodes.update({
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": FL2VA_MODEL, "weight_dtype": "default"}},
        "17": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["6", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0], "prompt": prompt, "width": width, "height": height, "length": length}},
    })
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
    encoder: str = "native",
):
    """Native H3 with the optional Spectrum v0.2.5 acceleration node.

    Spectrum is deliberately kept separate from the Turbo sampler. It wraps
    the native model after the H3 sigma-shift node and uses RES multistep,
    which is one of Spectrum's supported sampler paths.
    """
    length = 124 if duration == 5 else 243
    nodes = _common_decode("104", "18", {"id": "19", "scheduler": "9"}, seed, prefix, encoder)
    nodes.update({
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
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0], "prompt": prompt, "width": width, "height": height, "length": length}},
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
    spectrum: bool = False,
    encoder: str = "native",
):
    length = 124 if duration == 5 else 243
    model_node = "129" if spectrum else "127"
    sampler_node = "130" if spectrum else "123"
    nodes = _common_decode(
        "136", model_node, {"id": sampler_node, "scheduler": "124"},
        seed, prefix, encoder, reference=True,
    )
    nodes.update({
        "127": {"class_type": "UNETLoader", "inputs": {"unet_name": REF2VA_MODEL, "weight_dtype": "default"}},
        "124": {"class_type": "BasicScheduler", "inputs": {"model": [model_node, 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "137": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["13", 0], "vae": ["11", 0], "audio_vae": ["24", 0], "prompt": prompt,
            "width": width, "height": height, "length": length, "ref_image_size": "match",
             "ref_images": {"ref_image_0": ["137", 0]}}},
    })
    if audio_name:
        nodes["138"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_name}}
        nodes["136"]["inputs"]["ref_audios"] = {"ref_audio_0": ["138", 0]}
    if spectrum:
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
