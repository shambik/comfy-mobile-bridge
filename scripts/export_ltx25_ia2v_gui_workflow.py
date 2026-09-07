"""Export the supplied LTX-2.5 IA2V API prompt as an editable ComfyUI workflow.

The source prompt may use arbitrary API node IDs, including subgraph-style IDs
such as ``340:312``. The GUI workflow receives stable numeric IDs while the
original API IDs are retained in each node's properties for traceability.

This script queries ComfyUI only for node metadata. It never queues a prompt.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_OUT = ROOT / "workflows" / "video_ltx2_5_ia2v_core_FIXED_api.json"
DEFAULT_GUI_OUT = ROOT / "workflows" / "video_ltx2_5_ia2v_core_FIXED_gui.json"
DEFAULT_COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8190")

EXPECTED_MODEL_BINDINGS = {
    ("ltx_transformer", "unet_name"):
        "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
    ("ltx_clip", "clip_name"):
        "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
    ("ltx_video_vae", "vae_name"):
        "ltx-2.5-video-vae-bf16.safetensors",
    ("340:335", "vae_name"):
        "ltx-2.5-audio-vae-bf16.safetensors",
    ("340:313", "model_name"):
        "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="API-format workflow JSON")
    parser.add_argument("--api-out", type=Path, default=DEFAULT_API_OUT)
    parser.add_argument("--gui-out", type=Path, default=DEFAULT_GUI_OUT)
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def read_object_info(comfy_url: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{comfy_url.rstrip('/')}/object_info", timeout=60) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("ComfyUI /object_info returned a non-object payload")
    return payload


def is_link(value: Any, prompt: dict[str, Any]) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and str(value[0]) in prompt
        and isinstance(value[1], int)
    )


def validate_api_prompt(prompt: dict[str, Any]) -> None:
    if "nodes" in prompt or "links" in prompt:
        raise ValueError("Source is already a GUI workflow; expected API prompt format")
    if not prompt:
        raise ValueError("API prompt is empty")

    for node_id, spec in prompt.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("class_type"), str):
            raise ValueError(f"Node {node_id!r} is missing class_type")
        inputs = spec.get("inputs", {})
        if not isinstance(inputs, dict):
            raise ValueError(f"Node {node_id!r} inputs must be an object")
        for input_name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                source_id = str(value[0])
                if source_id not in prompt:
                    raise ValueError(
                        f"Node {node_id!r} input {input_name!r} references missing node {source_id!r}"
                    )

    for (node_id, input_name), expected in EXPECTED_MODEL_BINDINGS.items():
        node = prompt.get(node_id)
        if not isinstance(node, dict):
            raise ValueError(f"Required model-loader node is missing: {node_id}")
        actual = node.get("inputs", {}).get(input_name)
        if actual != expected:
            raise ValueError(
                f"{node_id}.{input_name} must be {expected!r}; found {actual!r}"
            )


def ordered_inputs(definition: dict[str, Any], api_inputs: dict[str, Any]) -> list[tuple[str, Any]]:
    schema = definition.get("input", {})
    result: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for section in ("required", "optional"):
        values = schema.get(section, {})
        if not isinstance(values, dict):
            continue
        for name, input_spec in values.items():
            if name in api_inputs:
                result.append((name, input_spec))
                seen.add(name)
    for name in api_inputs:
        if name not in seen:
            result.append((name, None))
    return result


def combo_options(input_spec: Any) -> list[Any] | None:
    if not isinstance(input_spec, (list, tuple)) or not input_spec:
        return None
    declared = input_spec[0]
    if isinstance(declared, (list, tuple)):
        return list(declared)
    if declared == "COMBO" and len(input_spec) > 1 and isinstance(input_spec[1], dict):
        options = input_spec[1].get("options")
        if isinstance(options, list):
            return list(options)
    return None


def source_output_type(
    source_id: str,
    source_slot: int,
    prompt: dict[str, Any],
    object_info: dict[str, Any],
) -> str:
    source_class = prompt[source_id]["class_type"]
    outputs = object_info[source_class].get("output", [])
    if source_slot >= len(outputs):
        raise ValueError(f"{source_id} output slot {source_slot} is out of range")
    return str(outputs[source_slot])


def input_type(
    input_spec: Any,
    value: Any,
    prompt: dict[str, Any],
    object_info: dict[str, Any],
) -> Any:
    if input_spec is not None and isinstance(input_spec, (list, tuple)) and input_spec:
        options = combo_options(input_spec)
        if options is not None:
            if not is_link(value, prompt) and isinstance(value, str) and value not in options:
                options.append(value)
            return options
        declared = input_spec[0]
        return declared
    if is_link(value, prompt):
        return source_output_type(str(value[0]), int(value[1]), prompt, object_info)
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INT"
    if isinstance(value, float):
        return "FLOAT"
    if isinstance(value, str):
        return "STRING"
    return "*"


def dependency_depths(prompt: dict[str, Any]) -> dict[str, int]:
    cache: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(node_id: str) -> int:
        if node_id in cache:
            return cache[node_id]
        if node_id in visiting:
            return 0
        visiting.add(node_id)
        dependencies = [
            str(value[0])
            for value in prompt[node_id].get("inputs", {}).values()
            if is_link(value, prompt)
        ]
        result = 0 if not dependencies else max(depth(item) for item in dependencies) + 1
        visiting.remove(node_id)
        cache[node_id] = result
        return result

    for current in prompt:
        depth(current)
    return cache


def node_size(class_type: str) -> list[int]:
    if class_type in {"LoadImage", "LoadAudio"}:
        return [360, 260]
    if class_type == "CLIPTextEncode":
        return [420, 220]
    if class_type in {"UNETLoader", "CLIPLoader", "VAELoader", "LatentUpscaleModelLoader"}:
        return [390, 150]
    return [340, 140]


def convert_to_gui(prompt: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any]:
    missing_classes = sorted({
        spec["class_type"] for spec in prompt.values()
        if spec["class_type"] not in object_info
    })
    if missing_classes:
        raise RuntimeError("ComfyUI is missing node classes: " + ", ".join(missing_classes))

    api_ids = list(prompt)
    numeric_ids = {api_id: index for index, api_id in enumerate(api_ids, start=1)}
    depths = dependency_depths(prompt)
    rows: defaultdict[int, int] = defaultdict(int)
    nodes: list[dict[str, Any]] = []
    links: list[list[Any]] = []
    link_id = 1

    for order, api_id in enumerate(api_ids):
        spec = prompt[api_id]
        class_type = spec["class_type"]
        definition = object_info[class_type]
        api_inputs = spec.get("inputs", {})
        ui_inputs: list[dict[str, Any]] = []
        widgets: list[Any] = []

        for input_name, input_spec in ordered_inputs(definition, api_inputs):
            value = api_inputs[input_name]
            declared_type = input_type(input_spec, value, prompt, object_info)
            if is_link(value, prompt):
                source_id, source_slot = str(value[0]), int(value[1])
                links.append([
                    link_id,
                    numeric_ids[source_id],
                    source_slot,
                    numeric_ids[api_id],
                    len(ui_inputs),
                    declared_type,
                ])
                ui_inputs.append({"name": input_name, "type": declared_type, "link": link_id})
                link_id += 1
            else:
                ui_inputs.append({"name": input_name, "type": declared_type, "link": None})
                widgets.append(value)

        output_types = list(definition.get("output", []))
        output_names = list(definition.get("output_name", []))
        ui_outputs = []
        for slot, output_type in enumerate(output_types):
            name = output_names[slot] if slot < len(output_names) and output_names[slot] else output_type
            ui_outputs.append({
                "name": str(name),
                "type": str(output_type),
                "links": None,
                "slot_index": slot,
            })

        column = depths[api_id]
        row = rows[column]
        rows[column] += 1
        title = spec.get("_meta", {}).get("title")
        node = {
            "id": numeric_ids[api_id],
            "type": class_type,
            "pos": [column * 430, row * 190],
            "size": node_size(class_type),
            "flags": {},
            "order": order,
            "mode": 0,
            "inputs": ui_inputs,
            "outputs": ui_outputs,
            "properties": {
                "Node name for S&R": class_type,
                "source_api_node_id": api_id,
            },
            "widgets_values": widgets,
        }
        if title:
            node["title"] = title
        nodes.append(node)

    nodes_by_id = {node["id"]: node for node in nodes}
    for current_link in links:
        source_id, source_slot = current_link[1], current_link[2]
        output = nodes_by_id[source_id]["outputs"][source_slot]
        if output["links"] is None:
            output["links"] = []
        output["links"].append(current_link[0])

    return {
        "version": 0.4,
        "last_node_id": len(nodes),
        "last_link_id": link_id - 1,
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "extra": {
            "ds": {"scale": 0.7, "offset": [80, 80]},
            "source_api_workflow": DEFAULT_API_OUT.name,
        },
    }


def missing_model_options(prompt: dict[str, Any], object_info: dict[str, Any]) -> list[str]:
    missing = []
    for (node_id, input_name), expected in EXPECTED_MODEL_BINDINGS.items():
        class_type = prompt[node_id]["class_type"]
        input_spec = object_info[class_type].get("input", {}).get("required", {}).get(input_name)
        options = combo_options(input_spec)
        if options is not None and expected not in options:
            missing.append(expected)
    return missing


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    prompt = read_json(source)
    validate_api_prompt(prompt)
    object_info = read_object_info(args.comfy_url)
    gui = convert_to_gui(prompt, object_info)

    args.api_out.parent.mkdir(parents=True, exist_ok=True)
    args.gui_out.parent.mkdir(parents=True, exist_ok=True)
    args.api_out.write_text(json.dumps(prompt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.gui_out.write_text(json.dumps(gui, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote API workflow: {args.api_out}")
    print(f"Wrote GUI workflow: {args.gui_out}")
    print(f"GUI nodes: {len(gui['nodes'])}; links: {len(gui['links'])}")
    missing = missing_model_options(prompt, object_info)
    if missing:
        print("Model files not currently registered by ComfyUI:", file=sys.stderr)
        for filename in missing:
            print(f"- {filename}", file=sys.stderr)


if __name__ == "__main__":
    main()
