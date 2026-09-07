import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_PATH = ROOT / "workflows" / "video_ltx2_5_ia2v_core_FIXED_api.json"
GUI_PATH = ROOT / "workflows" / "video_ltx2_5_ia2v_core_FIXED_gui.json"

EXPECTED_MODELS = {
    "ltx_transformer": (
        "unet_name",
        "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
    ),
    "ltx_clip": (
        "clip_name",
        "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
    ),
    "ltx_video_vae": ("vae_name", "ltx-2.5-video-vae-bf16.safetensors"),
    "340:335": ("vae_name", "ltx-2.5-audio-vae-bf16.safetensors"),
    "340:313": (
        "model_name",
        "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
    ),
}


class LtxWorkflowTests(unittest.TestCase):
    def test_api_workflow_uses_required_models(self):
        workflow = json.loads(API_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("nodes", workflow)
        for node_id, (field, expected) in EXPECTED_MODELS.items():
            self.assertEqual(workflow[node_id]["inputs"][field], expected)

    def test_gui_workflow_is_regular_editable_format(self):
        workflow = json.loads(GUI_PATH.read_text(encoding="utf-8"))
        self.assertEqual(workflow["version"], 0.4)
        self.assertGreater(len(workflow["nodes"]), 0)
        self.assertGreater(len(workflow["links"]), 0)
        node_ids = {node["id"] for node in workflow["nodes"]}
        self.assertEqual(len(node_ids), len(workflow["nodes"]))
        for link in workflow["links"]:
            self.assertIn(link[1], node_ids)
            self.assertIn(link[3], node_ids)

    def test_gui_workflow_preserves_api_node_traceability(self):
        api_workflow = json.loads(API_PATH.read_text(encoding="utf-8"))
        workflow = json.loads(GUI_PATH.read_text(encoding="utf-8"))
        nodes_by_source = {
            node["properties"]["source_api_node_id"]: node
            for node in workflow["nodes"]
        }
        self.assertEqual(set(nodes_by_source), set(api_workflow))
        for node_id, (_, expected) in EXPECTED_MODELS.items():
            self.assertIn(expected, nodes_by_source[node_id]["widgets_values"])


if __name__ == "__main__":
    unittest.main()
