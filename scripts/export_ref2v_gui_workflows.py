"""Export editable ComfyUI GUI workflows for Ref2V.

This only reads ComfyUI's object metadata and writes workflow JSON files; it
does not queue or execute a prompt.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.workflows import reference_workflow  # noqa: E402


COMFY_URL = "http://127.0.0.1:8190"
OUT = ROOT / "workflows"


def object_info() -> dict:
    with urllib.request.urlopen(f"{COMFY_URL}/object_info", timeout=15) as response:
        return json.load(response)


def export(api_prompt: dict, info: dict, name: str) -> None:
    nodes = []
    links = []
    link_id = 1
    positions = {
        "13": (-900, 0), "11": (-900, 260), "24": (-900, 520),
        "7": (-900, 780), "105": (-900, 980), "106": (-600, 980),
        "127": (-350, 0), "128": (0, 0), "129": (300, 0),
        "123": (300, 180), "124": (600, 0), "136": (900, 0),
        "137": (600, 400), "138": (600, 700), "139": (600, 1000),
        "140": (600, 1300), "141": (600, 1600), "142": (600, 1900),
        "143": (600, 2200), "144": (600, 2500), "145": (600, 2800),
        "150": (900, 500), "151": (1150, 500),
        "152": (900, 800), "153": (1150, 800),
        "154": (900, 1100), "155": (1150, 1100),
        "180": (900, 1450), "10": (1450, 0), "23": (1450, 220),
        "91": (1750, 0), "92": (2050, 0), "15": (-350, 500),
        "16": (600, -300), "14": (1200, 0),
    }

    for node_id, spec in api_prompt.items():
        class_type = spec["class_type"]
        definition = info.get(class_type)
        if not definition:
            raise RuntimeError(f"ComfyUI does not expose node metadata: {class_type}")
        schema = definition.get("input", {})
        ordered = []
        for section in ("required", "optional"):
            ordered.extend((key, value) for key, value in schema.get(section, {}).items())
        api_inputs = spec.get("inputs", {})
        ui_inputs = []
        widgets = []

        expanded = dict(api_inputs)
        for key in ("ref_images", "ref_videos", "ref_video_audios", "ref_audios"):
            values = api_inputs.get(key)
            if isinstance(values, dict):
                expanded.pop(key, None)
                expanded.update(values)
                template = schema.get("optional", {}).get(key, [None, {}])[1].get("template", {})
                template_type = template.get("input", {}).get("required", {}).get(
                    key.removesuffix("s"), ["ANY", {}]
                )
                ordered = [(item_key, item_value) for item_key, item_value in ordered if item_key != key]
                ordered.extend((item_key, template_type) for item_key in values)
        ordered_names = {item_key for item_key, _ in ordered}
        for item_key in expanded:
            if item_key not in ordered_names and item_key.startswith("values."):
                ordered.append((item_key, ("FLOAT,INT,BOOLEAN", {})))

        for input_name, input_spec in ordered:
            if input_name not in expanded:
                continue
            value = expanded[input_name]
            input_type = input_spec[0]
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                source, source_slot = value
                links.append([link_id, int(source), int(source_slot), int(node_id), len(ui_inputs), input_type])
                ui_inputs.append({"name": input_name, "type": input_type, "link": link_id})
                link_id += 1
            else:
                ui_inputs.append({"name": input_name, "type": input_type, "link": None})
                widgets.append(value)

        output_types = definition.get("output", [])
        ui_outputs = []
        for index, output_type in enumerate(output_types):
            ui_outputs.append({"name": output_type, "type": output_type, "links": None, "slot_index": index})

        nodes.append({
            "id": int(node_id), "type": class_type,
            "pos": list(positions.get(node_id, (0, 0))), "size": [320, 120],
            "flags": {}, "order": len(nodes), "mode": 0,
            "inputs": ui_inputs, "outputs": ui_outputs,
            "properties": {"Node name for S&R": class_type},
            "widgets_values": widgets,
        })

    for link in links:
        _, source_id, source_slot, _, _, _ = link
        source_node = next(node for node in nodes if node["id"] == source_id)
        if source_node["outputs"][source_slot].get("links") is None:
            source_node["outputs"][source_slot]["links"] = []
        source_node["outputs"][source_slot]["links"].append(link[0])

    payload = {
        "version": 0.4, "last_node_id": max(int(key) for key in api_prompt),
        "last_link_id": link_id - 1, "nodes": nodes, "links": links,
        "groups": [], "config": {}, "extra": {"ds": {"scale": 0.75, "offset": [0, 0]}},
    }
    (OUT / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metadata = object_info()
    common = dict(
        prompt="Describe the desired reference-guided video.", duration=5, seed=123456789,
        prefix="ref2v_gui", image_name="reference_image_01.png",
        audio_name="reference_audio.wav", width=1344, height=768,
        megapixels=0.98, aspect_ratio="16:9", include_audio=True,
        image_names=[f"reference_image_{index:02d}.png" for index in range(1, 10)],
        video_names=[f"reference_video_{index:02d}.mp4" for index in range(1, 4)],
    )
    standard = reference_workflow(**common, turbo=False, steps=20)
    turbo = reference_workflow(**common, turbo=True, steps=4)
    export(standard, metadata, "ref2v_standard_9images_3videos_audio.json")
    export(turbo, metadata, "ref2v_turbo_9images_3videos_audio.json")
    print(f"Wrote GUI workflows to {OUT}")


if __name__ == "__main__":
    main()
