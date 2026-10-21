"""Isolated image-workflow experiment backed by the bot's API graphs.

Only JSON graphs in the configured directory are read. No bot Python code,
configuration, credentials, or Telegram delivery logic is executed here.
"""

from __future__ import annotations

import asyncio
import json
import math
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (BOT_IMAGE_WORKFLOWS_DIR, IMAGE_COMFY_INPUT, IMAGE_COMFY_OUTPUT,
                     STATE)
from .comfy import ComfyClient


class BotImageError(ValueError):
    pass


EXCLUDED_NAMES = ("vibevoice", "minimax_h3", " - copy")
PROMPT_CLASSES = ("CLIPTextEncode", "TextEncodeQwenImageEdit", "TextEncodeQwenImageEditPlus", "PrimitiveStringMultiline")
_runs: dict[str, "ImageRun"] = {}
_watchers: dict[str, asyncio.Task] = {}
_submit_lock = asyncio.Lock()
RUN_STATE_DIR = STATE / "bot_image_runs"


def _workflow_path(name: str) -> Path | None:
    if Path(name).name != name or not name.endswith(".json"):
        return None
    path = BOT_IMAGE_WORKFLOWS_DIR / name
    return path if path.is_file() and path in _workflow_files() else None


def _workflow_files() -> list[Path]:
    if not BOT_IMAGE_WORKFLOWS_DIR.is_dir():
        return []
    return [p for p in sorted(BOT_IMAGE_WORKFLOWS_DIR.glob("*.json"))
            if not any(part in p.name.lower() for part in EXCLUDED_NAMES)]


def workflow_input_directory(name: str) -> Path:
    if _workflow_path(name) is None:
        raise BotImageError("Image workflow not found")
    return IMAGE_COMFY_INPUT


def workflow_output_directory(name: str) -> Path:
    if _workflow_path(name) is None:
        raise BotImageError("Image workflow not found")
    return IMAGE_COMFY_OUTPUT


def workflow_image_bounds(name: str, graph: dict[str, Any] | None = None) -> tuple[int, int]:
    selected = graph if graph is not None else _graph(name)
    count = len(_image_nodes(selected))
    return count, count


def workflow_upload_limit(name: str) -> int:
    minimum, maximum = workflow_image_bounds(name)
    return max(4, maximum)


def _graph(name: str) -> dict[str, Any]:
    path = _workflow_path(name)
    if path is None:
        raise BotImageError("Image workflow not found")
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BotImageError(f"Cannot read image workflow {name}") from exc
    if not isinstance(graph, dict) or not graph or not all(
        isinstance(node, dict) and isinstance(node.get("class_type"), str)
        and isinstance(node.get("inputs"), dict) for node in graph.values()
    ):
        raise BotImageError(f"{name} is not an API-format ComfyUI graph")
    if not any(node["class_type"] == "SaveImage" for node in graph.values()):
        raise BotImageError(f"{name} has no SaveImage output")
    # The bot's saved API graphs predate required inputs added by newer ComfyUI
    # nodes. These are the node authors' current defaults, not creative changes.
    for node_id, node in list(graph.items()):
        if node["class_type"] == "ImageScaleToTotalPixels":
            node["inputs"].setdefault("resolution_steps", 1)
        elif node["class_type"] == "FastFilmGrain":
            node["inputs"].setdefault("batch_size", 4)
        elif node["class_type"] == "PreviewImage" and not node["inputs"].get("images"):
            # An empty preview is an invalid, disconnected output node.
            del graph[node_id]
    return graph


def _nodes(graph: dict[str, Any], class_name: str) -> list[tuple[str, dict[str, Any]]]:
    return [(node_id, node) for node_id, node in graph.items() if node["class_type"] == class_name]


def _prompt_node(graph: dict[str, Any]) -> tuple[str, str] | None:
    for class_name in PROMPT_CLASSES:
        for node_id, node in _nodes(graph, class_name):
            title = str(node.get("_meta", {}).get("title", "")).lower()
            if "negative" in title:
                continue
            for key in ("text", "prompt", "value"):
                if isinstance(node["inputs"].get(key), str):
                    return node_id, key
    return None


def _negative_node(graph: dict[str, Any]) -> tuple[str, str] | None:
    for node_id, node in _nodes(graph, "CLIPTextEncode"):
        if "negative" in str(node.get("_meta", {}).get("title", "")).lower():
            return node_id, "text"
    return None


def _image_nodes(graph: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    found = _nodes(graph, "LoadImage")
    return sorted(found, key=lambda entry: (
        int(str(entry[1].get("_meta", {}).get("title", "")).rsplit(" ", 1)[-1])
        if str(entry[1].get("_meta", {}).get("title", "")).rsplit(" ", 1)[-1].isdigit() else 0,
        int(entry[0]) if entry[0].isdigit() else 0,
    ))


def _scalar_fields(graph: dict[str, Any], *, include_power_lora: bool = False) -> list[dict[str, Any]]:
    fields = []
    for node_id, node in graph.items():
        # This custom node is managed by the dedicated LoRA picker below. Its
        # widget payload contains editor metadata, not useful expert controls.
        if node["class_type"] == "Power Lora Loader (rgthree)" and not include_power_lora:
            continue
        title = str(node.get("_meta", {}).get("title") or node["class_type"])
        for key, value in node["inputs"].items():
            if key == "image" and node["class_type"] == "LoadImage":
                continue
            if key == "filename_prefix" and node["class_type"] == "SaveImage":
                continue  # unique output prefix is owned by the run
            if isinstance(value, (str, int, float, bool)) and value is not None:
                fields.append({"node": node_id, "key": key, "value": value,
                               "type": "boolean" if isinstance(value, bool) else
                               "number" if isinstance(value, (int, float)) else "text",
                               "label": f"{title} · {key}"})
            elif isinstance(value, dict):
                for subkey, subvalue in value.items():
                    if isinstance(subvalue, (str, int, float, bool)) and subvalue is not None:
                        fields.append({"node": node_id, "key": key, "subkey": subkey,
                                       "value": subvalue,
                                       "type": "boolean" if isinstance(subvalue, bool) else
                                       "number" if isinstance(subvalue, (int, float)) else "text",
                                       "label": f"{title} · {key}.{subkey}"})
    return fields


def _power_lora_options(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose only LoRAs explicitly configured in this recipe's loader nodes."""
    options: dict[str, dict[str, Any]] = {}
    for _, node in _nodes(graph, "Power Lora Loader (rgthree)"):
        slots = [(key, value) for key, value in node["inputs"].items()
                 if key.startswith("lora_") and isinstance(value, dict)
                 and isinstance(value.get("lora"), str) and value["lora"].strip()]
        slots.sort(key=lambda entry: int(entry[0].removeprefix("lora_"))
                   if entry[0].removeprefix("lora_").isdigit() else 0)
        for _, slot in slots:
            filename = slot["lora"].strip()
            key = filename.casefold()
            option = options.setdefault(key, {
                "filename": filename,
                "enabled_by_default": False,
            })
            option["enabled_by_default"] = option["enabled_by_default"] or slot.get("on") is True
    return list(options.values())


def _field_choice_options(item: dict[str, Any], graph: dict[str, Any],
                          object_info: dict[str, Any]) -> dict[str, list[Any]]:
    """Map enumerable Comfy inputs to their installed choices for select menus."""
    result: dict[str, list[Any]] = {}
    for field in item["fields"]:
        if field["type"] != "text" or field.get("subkey") is not None:
            continue
        node = graph.get(field["node"], {})
        input_specs = object_info.get(node.get("class_type"), {}).get("input", {})
        choices = {**input_specs.get("required", {}), **input_specs.get("optional", {})}
        spec = choices.get(field["key"])
        if not isinstance(spec, list) or not spec or not isinstance(spec[0], list):
            continue
        values = spec[0]
        if values and all(isinstance(value, (str, int, float, bool)) for value in values):
            field_id = f"{field['node']}:{field['key']}:"
            result[field_id] = values
    return result


def _workflow_steps(graph: dict[str, Any]) -> int | None:
    for class_name in ("KSampler", "BasicScheduler"):
        for _, node in _nodes(graph, class_name):
            value = node["inputs"].get("steps")
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _model_files(graph: dict[str, Any]) -> str:
    values = []
    for node in graph.values():
        for value in node.get("inputs", {}).values():
            if isinstance(value, str) and value.lower().endswith((".gguf", ".safetensors", ".pth")):
                values.append(value.lower())
    return " ".join(values)


def _control_kind(graph: dict[str, Any]) -> str | None:
    classes = {node["class_type"] for node in graph.values()}
    if {"OpenPosePreprocessor", "DepthAnythingV2Preprocessor"} <= classes or "Switch any [Crystools]" in classes:
        return "pose_depth"
    if "DWPreprocessor" in classes or "OpenPose Pose" in classes:
        return "pose"
    if "DepthAnythingV2Preprocessor" in classes:
        return "depth"
    for _, node in _nodes(graph, "AIO_Preprocessor"):
        value = str(node["inputs"].get("preprocessor", "")).lower()
        if "depth" in value:
            return "depth"
        if "pose" in value or "dwpre" in value:
            return "pose"
    return None


def _input_roles(name: str, graph: dict[str, Any], task: str, control_kind: str | None) -> list[dict[str, str]]:
    image_nodes = _image_nodes(graph)
    roles: list[dict[str, str]] = []
    if not image_nodes:
        return roles
    if task == "expand":
        return [{"label": "Image to expand", "help": "The existing image stays inside the frame; the prompt should describe what to add outside its edges."}]
    if task == "upscale":
        return [{"label": "Image to upscale", "help": "Upload the source image. This workflow enlarges it and may rebuild fine details; it does not need a separate guide image."}]
    if control_kind:
        roles.append({"label": "Image to edit", "help": "This is the base image the result should transform. It is not the pose/depth guide."})
        if len(image_nodes) > 1:
            if control_kind == "pose":
                guide_label = "Pose guide photo"
                guide_help = "Upload a photo showing the body pose to follow. The workflow extracts pose landmarks automatically; do not upload a pre-drawn skeleton unless that is what you want used."
            elif control_kind == "depth":
                guide_label = "Depth guide photo"
                guide_help = "Upload a photo whose spatial layout should guide the result. This workflow estimates depth from the photo automatically; it does not expect a precomputed depth map."
            else:
                guide_label = "Pose / depth guide photo"
                guide_help = "This photo controls structure, not identity. Choose Pose or Depth below: Pose extracts body landmarks; Depth extracts the scene's near/far layout. The current graph default is Pose."
            roles.append({"label": guide_label, "help": guide_help})
        for index in range(2, len(image_nodes)):
            roles.append({"label": f"Extra reference image {index + 1}", "help": f"An additional appearance or content reference, not the control guide. Refer to it as image {index + 1} in your instruction."})
        return roles
    if "ImageStitch" in {node["class_type"] for node in graph.values()} and len(image_nodes) > 1:
        positions = ("top-left", "top-right", "bottom-left", "bottom-right")
        for index in range(len(image_nodes)):
            position = positions[index] if index < len(positions) else f"tile {index + 1}"
            roles.append({"label": f"Board tile {index + 1} · {position}", "help": f"This image becomes the {position} tile in one combined reference board. Mention the tile or image number in your prompt."})
        return roles
    if task == "edit":
        roles.append({"label": "Main image to edit", "help": "This is the source image and the primary visual anchor. Describe what should change and what should remain the same."})
        for index in range(1, len(image_nodes)):
            roles.append({"label": f"Reference image {index + 1}", "help": f"An additional visual reference. Say what to borrow from image {index + 1} (for example, identity, clothing, object, or style)."})
        return roles
    for index in range(len(image_nodes)):
        roles.append({"label": f"Input image {index + 1}", "help": "Source image used by this recipe."})
    return roles


def _workflow_card(name: str, graph: dict[str, Any]) -> dict[str, Any]:
    lowered = name.lower()
    classes = {node["class_type"] for node in graph.values()}
    image_count = len(_image_nodes(graph))
    model_files = _model_files(graph)
    if "ImagePadForOutpaint" in classes:
        task = "expand"
        title = "Extend an image"
        description = "Add space around the source image while keeping its original content."
    elif "upscal" in lowered or "ImageUpscaleWithModel" in classes:
        task = "upscale"
        title = "Upscale an image"
        description = "Increase image size and detail from one source image."
    elif image_count:
        task = "edit"
        title = "Edit with reference images"
        description = f"Give the model {image_count} image{'s' if image_count != 1 else ''} to guide its edit."
    else:
        task = "create"
        title = "Create from a prompt"
        description = "Generate a new image from your text description."

    if "wan_2_2" in lowered:
        model = "Wan 2.2"
    elif "wan_2_1" in lowered:
        model = "Wan 2.1"
    elif "wan14b" in model_files:
        model = "Wan 14B Fusion"
    elif "wan" in lowered:
        model = "Wan image workflow"
    elif "krea" in lowered:
        model = "Krea"
    elif "kontext" in lowered:
        model = "Flux Kontext"
    elif "flux" in lowered:
        model = "Flux"
    elif "qwen2509" in lowered:
        model = "Qwen Image Edit 2509"
    elif "qwen" in lowered:
        model = "Qwen Image Edit" if task in {"edit", "expand"} else "Qwen Image"
    else:
        model = "Other image model"

    steps = _workflow_steps(graph)
    control_kind = _control_kind(graph)
    variants = []
    if "nunchaku" in lowered:
        variants.append("Nunchaku INT4")
    elif "q8_0" in model_files:
        variants.append("GGUF Q8")
    elif "q4_k_s" in model_files:
        variants.append("GGUF Q4")
    if steps:
        variants.append(f"{steps} steps")
    if "simplified" in lowered:
        variants.append("simplified graph")
    if "dslr" in lowered:
        variants.append("DSLR style LoRA")
    if "2048" in lowered:
        variants.append("2048 px target")
    if "TiledDiffusion" in classes or "TTP_Image_Tile_Batch" in classes:
        variants.append("tiled high-resolution")
    if "flux_kontext_workflow" in lowered:
        variants.append("diffusion-model loader")
    elif "kontext_i2i_workflow" in lowered:
        variants.append("checkpoint loader")
    if task == "upscale" and "DepthAnythingV2Preprocessor" in classes:
        variants.append("depth-guided film restoration")
    if "FastFilmGrain" in classes:
        variants.append("film grain on")
    elif "wan_t2i_workflow_nograin" in lowered:
        variants.append("film grain off")
    if "simple_upscaler" in lowered:
        variants.append("single-pass model upscale")

    if task == "expand":
        title = f"{model} · Outpaint"
        description = "Keep the original image in the center and generate the missing areas around it. The input image is the canvas to expand."
    elif task == "upscale":
        title = f"{model} · Upscale"
        if "2048" in lowered:
            description = "Enlarge the uploaded image toward a 2048-pixel output, then refine detail. Use this when you need a fixed larger export."
        elif "simple_upscaler" in lowered:
            description = "A straightforward model upscaler: upload one image and enlarge it without a text-editing pass."
        elif "wan_2_1" in lowered:
            description = "Use one source image for a generative upscale; the prompt and denoise strength can change how much detail is reconstructed."
        else:
            description = "Upload one source image for a tiled/detail-restoration upscale. Tiling helps process large images in sections."
    elif task == "create":
        title = f"{model} · Text to image"
        description = f"Create a new image from a prompt with {model}." + (f" This recipe uses {steps} sampling steps." if steps else "")
        if "dslr" in lowered:
            description += " It also enables the bundled DSLR-style LoRA."
        elif "simplified" in lowered:
            description += " This is the simplified graph variant."
    else:
        is_board = "ImageStitch" in classes and image_count > 1
        if control_kind == "pose_depth":
            control_label = "Pose/depth guide"
        elif control_kind == "pose":
            control_label = "Pose guide"
        elif control_kind == "depth":
            control_label = "Depth guide"
        else:
            control_label = ""
        if is_board:
            title = f"{model} · {image_count}-image board"
            description = f"The {image_count} uploads are assembled into one reference board before editing. Slots are placed row by row, so identify the relevant image number or tile in your prompt."
        elif control_label:
            title = f"{model} · {image_count} inputs · {control_label}"
            if control_kind == "pose_depth":
                description = "Image 1 is the image to edit. Image 2 is a guide photo: select Pose or Depth below. Pose extracts body landmarks; Depth extracts near/far layout."
            elif control_kind == "pose":
                description = "Image 1 is the image to edit. Image 2 is a pose-guide photo; the workflow extracts the body pose automatically."
            else:
                description = "Image 1 is the image to edit. Image 2 is a depth-guide photo; the workflow estimates its depth automatically."
            if image_count > 2:
                description += " Image 3 is an extra visual reference, not the control guide."
        elif image_count > 1:
            title = f"{model} · {image_count} visual references"
            description = f"Upload {image_count} visual references in order. Image 1 is the primary edit anchor; later images add content or appearance guidance. Tell the prompt what to take from each numbered image."
        else:
            title = f"{model} · Single-image edit"
            description = "Upload the image to change. Describe the edits explicitly and state which important details should stay unchanged."

    if steps and task not in {"create"}:
        description += f" Sampling preset: {steps} steps."
    if "nunchaku" in lowered:
        description += " Uses the Nunchaku INT4 model path, intended to lower model memory use."
    elif "q8_0" in model_files:
        description += " Uses the quantized GGUF Q8 model variant."
    elif "q4_k_s" in model_files:
        description += " Uses the quantized GGUF Q4 model variant."
    if "flux_kontext_workflow" in lowered:
        description += " Loads the Flux Kontext diffusion model directly."
    elif "kontext_i2i_workflow" in lowered:
        description += " Loads Flux Kontext through a full checkpoint."
    if task == "upscale" and "DepthAnythingV2Preprocessor" in classes:
        description += " It also estimates depth and applies a film-restoration finish."
    if "FastFilmGrain" in classes:
        description += " Film grain is enabled in this recipe."
    elif "wan_t2i_workflow_nograin" in lowered:
        description += " This variant leaves the output free of the film-grain node."

    if variants:
        variant_summary = " · ".join(variants)
        title += f" · {variant_summary}"

    return {"task": task, "title": title, "description": description, "model": model,
            "variant": " · ".join(variants), "input_roles": _input_roles(name, graph, task, control_kind),
            "control_kind": control_kind or ""}


def catalog() -> list[dict[str, Any]]:
    result = []
    for path in _workflow_files():
        try:
            graph = _graph(path.name)
        except BotImageError:
            continue
        classes = sorted({node["class_type"] for node in graph.values()})
        card = _workflow_card(path.name, graph)
        minimum_images, maximum_images = workflow_image_bounds(path.name, graph)
        result.append({"name": path.name, "label": path.stem.replace("_", " "), **card,
                       "image_count": len(_image_nodes(graph)), "min_images": minimum_images,
                       "max_images": maximum_images, "multi_image_picker": minimum_images != maximum_images,
                       "prompt_supported": _prompt_node(graph) is not None,
                       "negative_supported": _negative_node(graph) is not None,
                       "has_outpaint": "ImagePadForOutpaint" in classes,
                       "has_controlnet_switch": "Switch any [Crystools]" in classes,
                       "has_power_lora": "Power Lora Loader (rgthree)" in classes,
                       "lora_options": _power_lora_options(graph),
                       "node_classes": classes,
                       "fields": _scalar_fields(graph)})
    return result


def compatibility(object_info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Report absent classes, required inputs, and unavailable model choices."""
    result = {}
    for item in catalog():
        graph = _graph(item["name"])
        missing_nodes = sorted(set(item["node_classes"]) - set(object_info))
        missing_models = []
        missing_inputs = []
        for node in graph.values():
            spec = object_info.get(node["class_type"], {}).get("input", {})
            for key in spec.get("required", {}):
                if key not in node["inputs"]:
                    missing_inputs.append(f"{node['class_type']}.{key}")
            choices = {**spec.get("required", {}), **spec.get("optional", {})}
            for key, value in node["inputs"].items():
                if key == "image" and node["class_type"] == "LoadImage":
                    continue
                input_spec = choices.get(key)
                if (isinstance(value, str) and isinstance(input_spec, list) and input_spec
                        and isinstance(input_spec[0], list) and input_spec[0] and
                        all(isinstance(choice, str) for choice in input_spec[0]) and
                        value not in input_spec[0]):
                    missing_models.append(f"{node['class_type']}.{key}: {value}")
        result[item["name"]] = {"ready": not missing_nodes and not missing_models and not missing_inputs,
                                "missing_nodes": missing_nodes, "missing_models": missing_models,
                                "missing_inputs": sorted(set(missing_inputs)),
                                "field_choices": _field_choice_options(item, graph, object_info)}
    return result


def _set_field(graph: dict[str, Any], node_id: str, key: str, subkey: str | None, value: Any) -> None:
    try:
        old = graph[node_id]["inputs"][key]
        if subkey is not None:
            old = old[subkey]
    except (KeyError, TypeError):
        raise BotImageError(f"Unknown input {node_id}.{key}") from None
    if isinstance(old, bool):
        if not isinstance(value, bool):
            raise BotImageError(f"{node_id}.{key} must be boolean")
    elif isinstance(old, int):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise BotImageError(f"{node_id}.{key} must be an integer")
        if not isinstance(value, int) and key not in {"cfg", "denoise", "guidance", "strength"}:
            raise BotImageError(f"{node_id}.{key} must be an integer")
    elif isinstance(old, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e9:
            raise BotImageError(f"{node_id}.{key} must be a finite number")
    elif isinstance(old, str):
        if not isinstance(value, str) or len(value) > 8000:
            raise BotImageError(f"{node_id}.{key} must be text under 8000 characters")
    else:
        raise BotImageError(f"{node_id}.{key} cannot be edited")
    if subkey is None:
        graph[node_id]["inputs"][key] = value
    else:
        graph[node_id]["inputs"][key][subkey] = value


def build_graph(name: str, *, prompt: str = "", negative: str = "",
                images: list[str] | None = None, overrides: list[dict[str, Any]] | None = None,
                flags: dict[str, Any] | None = None, run_id: str | None = None) -> tuple[dict[str, Any], int]:
    graph = _graph(name)
    images = images or []
    flags = flags or {}
    input_nodes = _image_nodes(graph)
    minimum_images, maximum_images = workflow_image_bounds(name, graph)
    if not minimum_images <= len(images) <= maximum_images:
        if minimum_images == maximum_images:
            raise BotImageError(f"{name} requires exactly {minimum_images} input image(s)")
        raise BotImageError(f"{name} requires between {minimum_images} and {maximum_images} input images")
    for image_name, (_, node) in zip(images, input_nodes):
        if Path(image_name).name != image_name:
            raise BotImageError("Invalid image filename")
        node["inputs"]["image"] = image_name
    prompt_ref = _prompt_node(graph)
    if prompt and prompt_ref:
        graph[prompt_ref[0]]["inputs"][prompt_ref[1]] = prompt[:8000]
    if negative:
        neg_ref = _negative_node(graph)
        if not neg_ref:
            raise BotImageError("This workflow has no negative prompt input")
        graph[neg_ref[0]]["inputs"][neg_ref[1]] = negative[:8000]
    valid_fields = {(field["node"], field["key"], field.get("subkey"))
                    for field in _scalar_fields(graph, include_power_lora=True)}
    for item in overrides or []:
        node_id, key, subkey = str(item.get("node", "")), str(item.get("key", "")), item.get("subkey")
        if (node_id, key, subkey) not in valid_fields:
            raise BotImageError(f"Input {node_id}.{key} is not editable")
        _set_field(graph, node_id, key, subkey, item.get("value"))
    # Telegram bot flags, applied only to node types they actually affect.
    for flag, class_name, field_name in (
        ("steps", "KSampler", "steps"), ("cfg", "KSampler", "cfg"),
        ("seednoise", "KSampler", "denoise"), ("upnoise", "UltimateSDUpscale", "denoise"),
    ):
        if flags.get(flag) is not None:
            targets = _nodes(graph, class_name)
            if flag in {"steps", "seednoise"} and not targets:
                targets = _nodes(graph, "BasicScheduler")
            if not targets or field_name not in targets[0][1]["inputs"]:
                raise BotImageError(f"{flag} is not supported by this workflow")
            _set_field(graph, targets[0][0], field_name, None, flags[flag])
    seed = flags.get("seed")
    if seed is None:
        for item in overrides or []:
            if item.get("key") in {"seed", "noise_seed"} and item.get("subkey") is None:
                seed = item.get("value")
                break
    if seed is None:
        seed = secrets.randbelow(2**53)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**53:
        raise BotImageError("Seed must be an integer from 0 to 2^53-1")
    for node in graph.values():
        if node["class_type"] in {"RandomNoise", "KSampler"}:
            for key in ("noise_seed", "seed"):
                if key in node["inputs"] and not isinstance(node["inputs"][key], list):
                    node["inputs"][key] = seed
    if flags.get("chngsmp"):
        targets = _nodes(graph, "KSampler")
        if not targets or not {"sampler_name", "scheduler"} <= targets[0][1]["inputs"].keys():
            raise BotImageError("Sampler override is unavailable for this workflow")
        targets[0][1]["inputs"].update(sampler_name="dpmpp_2m", scheduler="karras")
    if flags.get("res"):
        size = flags["res"]
        if not isinstance(size, list) or len(size) != 2 or any(type(x) is not int or x < 64 or x > 8192 for x in size):
            raise BotImageError("Resolution must be two integers between 64 and 8192")
        targets = next((_nodes(graph, c) for c in ("EmptyHunyuanLatentVideo", "EmptySD3LatentImage", "EmptyLatentImage") if _nodes(graph, c)), [])
        if not targets:
            raise BotImageError("This workflow has no resolution node")
        targets[0][1]["inputs"].update(width=size[0], height=size[1])
    if flags.get("extend"):
        values = flags["extend"]
        targets = _nodes(graph, "ImagePadForOutpaint")
        if not targets or not isinstance(values, dict) or any(type(values.get(k)) is not int or not 0 <= values[k] <= 2048 for k in ("left", "top", "right", "bottom")):
            raise BotImageError("Outpainting requires four integer margins from 0 to 2048")
        targets[0][1]["inputs"].update({k: values[k] for k in ("left", "top", "right", "bottom")})
    if flags.get("controlnet"):
        switch = [(n, v) for n, v in _nodes(graph, "Switch any [Crystools]")
                  if "TRUE ---> OPENPOSE" in str(v.get("_meta", {}).get("title", ""))]
        if not switch or flags["controlnet"] not in {"openpose", "depth"}:
            raise BotImageError("ControlNet mode is unavailable for this workflow")
        switch[0][1]["inputs"]["boolean"] = flags["controlnet"] == "openpose"
    power_lora_selection = flags.get("powerlora")
    if power_lora_selection:
        targets = _nodes(graph, "Power Lora Loader (rgthree)")
        if not targets:
            raise BotImageError("This workflow has no Power LoRA loader")
        if isinstance(power_lora_selection, str):
            # Preserve the bot's legacy `--powerlora keyword` behavior for
            # clients that still send a comma-separated substring filter.
            keywords = [value.strip().casefold() for value in power_lora_selection.split(",") if value.strip()]
            if not keywords:
                raise BotImageError("Choose at least one LoRA")
            matches = lambda filename: any(keyword in filename.casefold() for keyword in keywords)
        elif isinstance(power_lora_selection, list) and all(
            isinstance(value, str) and value.strip() for value in power_lora_selection
        ):
            requested = {value.strip().casefold() for value in power_lora_selection}
            available = {item["filename"].casefold() for item in _power_lora_options(graph)
                         if not item["enabled_by_default"]}
            unknown = requested - available
            if unknown:
                raise BotImageError("LoRA choice is not an optional add-on in this workflow: " + ", ".join(sorted(unknown)))
            matches = lambda filename: filename.casefold() in requested
        else:
            raise BotImageError("powerlora must be a list of recipe LoRAs or a legacy keyword string")
        for _, node in targets:
            for key, value in node["inputs"].items():
                if key.startswith("lora_") and isinstance(value, dict) and isinstance(value.get("lora"), str):
                    if matches(value["lora"]):
                        value["on"] = True
    for node in graph.values():
        if node["class_type"] == "SaveImage":
            node["inputs"]["filename_prefix"] = f"bot_image_{run_id or uuid.uuid4().hex}"
    return graph, seed


def _output_paths(history: dict[str, Any], output_directory: Path) -> list[Path]:
    paths = []
    root = output_directory.resolve()
    for output in (history.get("outputs") or {}).values():
        for image in output.get("images", []) if isinstance(output, dict) else []:
            if image.get("type") != "output":
                continue
            filename = image.get("filename", "")
            subfolder = image.get("subfolder", "")
            if not isinstance(filename, str) or not isinstance(subfolder, str):
                continue
            path = (root / subfolder / filename).resolve()
            if path.is_relative_to(root) and path.is_file():
                paths.append(path)
    return paths


@dataclass
class ImageRun:
    id: str
    workflow: str
    prompt_id: str
    client_id: str
    seed: int
    status: str = "queued"
    step: int = 0
    total_steps: int = 0
    error: str | None = None
    paths: list[Path] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "workflow": self.workflow, "prompt_id": self.prompt_id,
                "seed": self.seed, "status": self.status, "step": self.step,
                "total_steps": self.total_steps, "error": self.error,
                "elapsed_seconds": round((self.finished or time.time()) - (self.started or self.created), 1),
                "generation_seconds": round(self.finished - self.started, 1) if self.finished and self.started else None,
                "images": [f"/api/bot-images/runs/{self.id}/images/{i}" for i in range(len(self.paths))],
                "created_at": datetime.fromtimestamp(self.created, timezone.utc).isoformat()}


def get_run(run_id: str) -> ImageRun | None:
    if run_id in _runs:
        return _runs[run_id]
    if len(run_id) != 32 or not all(char in "0123456789abcdef" for char in run_id):
        return None
    path = RUN_STATE_DIR / f"{run_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        run = ImageRun(id=run_id, workflow=data["workflow"], prompt_id=data["prompt_id"],
                       client_id=data["client_id"], seed=data["seed"],
                       status=data["status"], step=data.get("step", 0),
                       total_steps=data.get("total_steps", 0), error=data.get("error"),
                       paths=[Path(value) for value in data.get("paths", [])],
                       created=data["created"], started=data.get("started"), finished=data.get("finished"))
        root = workflow_output_directory(run.workflow).resolve()
        if any(not image.resolve().is_relative_to(root) for image in run.paths):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    _runs[run_id] = run
    return run


def _persist(run: ImageRun) -> None:
    RUN_STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"workflow": run.workflow, "prompt_id": run.prompt_id,
               "client_id": run.client_id, "seed": run.seed, "status": run.status,
               "step": run.step, "total_steps": run.total_steps, "error": run.error,
               "paths": [str(path) for path in run.paths], "created": run.created,
               "started": run.started, "finished": run.finished}
    path = RUN_STATE_DIR / f"{run.id}.json"
    pending = RUN_STATE_DIR / f"{run.id}.tmp"
    pending.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    pending.replace(path)


def has_active_run() -> bool:
    return any(run.status in {"queued", "running"} for run in _runs.values())


async def inspect_run(comfy: ComfyClient, run: ImageRun) -> None:
    if run.status in {"completed", "failed"}:
        return
    try:
        history = await comfy.history(run.prompt_id)
    except Exception:
        return
    if not history:
        try:
            state = ComfyClient.prompt_queue_state(await comfy.queue(), run.prompt_id)
        except Exception:
            return
        if state == "queue_running":
            run.status = "running"
            run.started = run.started or time.time()
            _persist(run)
        return
    status = history.get("status") or {}
    errors = [message for message in status.get("messages", []) if isinstance(message, list) and message and message[0] == "execution_error"]
    if errors or status.get("status_str") == "error":
        run.status = "failed"
        run.error = json.dumps(errors[-1][1], ensure_ascii=False)[:2000] if errors else "ComfyUI execution failed"
        run.finished = time.time()
        _persist(run)
        return
    paths = _output_paths(history, workflow_output_directory(run.workflow))
    if paths:
        run.paths = paths
        run.status = "completed"
        run.finished = time.time()
    elif status.get("completed") or status.get("status_str") == "success":
        run.status = "failed"
        run.error = "ComfyUI completed without a saved image"
        run.finished = time.time()
    _persist(run)


async def _watch(comfy: ComfyClient, run: ImageRun) -> None:
    stop = asyncio.Event()

    async def on_message(message: dict[str, Any]) -> None:
        if str((message.get("data") or {}).get("prompt_id")) != run.prompt_id:
            return
        data = message.get("data") or {}
        if message.get("type") == "execution_start":
            run.status = "running"
            run.started = run.started or time.time()
        elif message.get("type") == "progress":
            try:
                run.step = int(data.get("value", 0))
                run.total_steps = int(data.get("max", 0))
            except (TypeError, ValueError):
                pass

    monitor = asyncio.create_task(comfy.monitor_progress(run.client_id, on_message, asyncio.Event(), stop))
    try:
        while run.status not in {"completed", "failed"}:
            await inspect_run(comfy, run)
            if run.status not in {"completed", "failed"}:
                await asyncio.sleep(1)
    except Exception as exc:
        run.error = str(exc)
        run.status = "failed"
        run.finished = time.time()
        _persist(run)
    finally:
        stop.set()
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
        _watchers.pop(run.id, None)


async def start_run(comfy: ComfyClient, name: str, prompt: str, negative: str,
                    images: list[str], overrides: list[dict[str, Any]], flags: dict[str, Any]) -> ImageRun:
    run_id = uuid.uuid4().hex
    graph, seed = build_graph(name, prompt=prompt, negative=negative, images=images,
                              overrides=overrides, flags=flags, run_id=run_id)
    try:
        status = compatibility(await comfy.object_info())[name]
    except (OSError, ValueError, KeyError) as exc:
        raise BotImageError(f"Could not validate image workflow: {exc}") from exc
    if not status["ready"]:
        problems = status["missing_nodes"] + status["missing_inputs"] + status["missing_models"]
        raise BotImageError("Image workflow is incompatible with this ComfyUI: " + "; ".join(problems))
    client_id = f"bot-image-{run_id}"
    async with _submit_lock:
        try:
            prompt_id = await comfy.submit(graph, client_id)
        except Exception as exc:
            raise BotImageError(f"ComfyUI rejected the workflow: {exc}") from exc
    run = ImageRun(run_id, name, prompt_id, client_id, seed)
    _runs[run_id] = run
    _persist(run)
    _watchers[run_id] = asyncio.create_task(_watch(comfy, run))
    return run


def delete_run(run_id: str) -> None:
    run = get_run(run_id)
    if not run:
        raise KeyError(run_id)
    if run.status in {"queued", "running"}:
        raise BotImageError("Generation is still active")
    for path in run.paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise BotImageError(f"Image is in use and cannot be deleted: {exc}") from exc
    del _runs[run_id]
    (RUN_STATE_DIR / f"{run_id}.json").unlink(missing_ok=True)
