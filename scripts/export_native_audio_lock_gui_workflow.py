"""Export the Native AudioLock test workflow in ComfyUI GUI format.

This contacts ComfyUI only for node metadata. It never queues a prompt.
Run it while ComfyUI is available, optionally setting COMFY_URL.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.workflows import native_audio_lock_workflow  # noqa: E402


COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8190")
OUT = ROOT / "workflows" / "native_audio_lock_i2v_5s_gui.json"


def main() -> None:
    with urllib.request.urlopen(f"{COMFY_URL}/object_info", timeout=15) as response:
        info = json.load(response)

    api_prompt = native_audio_lock_workflow(
        prompt="Describe a cinematic scene with natural, precise singing or dialogue lip sync.",
        duration=5,
        seed=123456789,
        prefix="h3_native_audio_lock_test",
        audio_name="reference_audio.wav",
        first_frame_name="opening_frame.png",
        steps=20,
        width=1344,
        height=768,
        megapixels=0.98,
        aspect_ratio="16:9",
    )

    nodes = []
    links = []
    next_link = 1
    for node_id, spec in api_prompt.items():
        class_type = spec["class_type"]
        definition = info.get(class_type)
        if not definition:
            raise RuntimeError(f"ComfyUI does not expose node metadata: {class_type}")
        schema = definition.get("input", {})
        ordered = []
        for section in ("required", "optional"):
            ordered.extend(schema.get(section, {}).items())
        api_inputs = spec.get("inputs", {})
        ui_inputs = []
        widgets = []
        for input_name, input_spec in ordered:
            if input_name not in api_inputs:
                continue
            value = api_inputs[input_name]
            input_type = input_spec[0]
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                link = [next_link, int(value[0]), value[1], int(node_id), len(ui_inputs), input_type]
                links.append(link)
                ui_inputs.append({"name": input_name, "type": input_type, "link": next_link})
                next_link += 1
            else:
                ui_inputs.append({"name": input_name, "type": input_type, "link": None})
                widgets.append(value)
        outputs = definition.get("output", [])
        nodes.append({
            "id": int(node_id), "type": class_type, "pos": [0, 0],
            "size": [320, 120], "flags": {}, "order": len(nodes), "mode": 0,
            "inputs": ui_inputs,
            "outputs": [{"name": item, "type": item, "links": None, "slot_index": index}
                        for index, item in enumerate(outputs)],
            "properties": {"Node name for S&R": class_type},
            "widgets_values": widgets,
        })

    for link in links:
        source = next(node for node in nodes if node["id"] == link[1])
        output = source["outputs"][link[2]]
        if output["links"] is None:
            output["links"] = []
        output["links"].append(link[0])

    payload = {
        "version": 0.4,
        "last_node_id": max(int(node_id) for node_id in api_prompt),
        "last_link_id": next_link - 1,
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "extra": {"ds": {"scale": 0.75, "offset": [0, 0]}},
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
