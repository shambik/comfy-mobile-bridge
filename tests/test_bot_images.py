import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from backend.bot_images import BotImageError, build_graph, catalog, compatibility
from backend.config import IMAGE_COMFY_URL, QWEN_IMAGE_COMFY_URL
from backend.main import app, image_comfy, qwen_image_comfy, worker


class BotImageWorkflowTests(unittest.TestCase):
    def test_catalog_discovers_image_workflows_only(self):
        items = catalog()
        self.assertGreaterEqual(len(items), 32)
        self.assertTrue(all(item["fields"] for item in items))
        self.assertTrue(all("vibevoice" not in item["name"] for item in items))

    def test_qwen21_recipes_are_separate_and_explain_their_use(self):
        items = {item["name"]: item for item in catalog()}
        t2i = items["qwen21_t2i_api.json"]
        edit = items["qwen21_edit_refs_api.json"]
        self.assertEqual(t2i["engine"], "qwen21")
        self.assertEqual(t2i["task"], "create")
        self.assertEqual(edit["task"], "edit")
        self.assertEqual((edit["min_images"], edit["max_images"]), (1, 10))
        self.assertTrue(edit["multi_image_picker"])
        self.assertIn("Research/evaluation only", t2i["description"])
        self.assertIn("<image1>", edit["description"])

    def test_multi_image_assignment_and_seed(self):
        graph, seed = build_graph("qwen2509_i2i_2inputs.json", prompt="A test edit",
                                  images=["first.png", "second.png"], flags={"seed": 27}, run_id="a" * 32)
        loads = [node["inputs"]["image"] for node in graph.values() if node["class_type"] == "LoadImage"]
        self.assertEqual(loads, ["first.png", "second.png"])
        self.assertEqual(seed, 27)
        self.assertTrue(any(node["inputs"].get("filename_prefix") == "bot_image_" + "a" * 32
                            for node in graph.values() if node["class_type"] == "SaveImage"))

    def test_qwen21_text_to_image_resolution_and_random_seed(self):
        graph, seed = build_graph("qwen21_t2i_api.json", prompt="A test image",
                                  flags={"seed": 123, "steps": 30, "cfg": 1.2, "res": [1280, 768]})
        latent = next(node for node in graph.values() if node["class_type"] == "EmptyLatentImage")
        sampler = next(node for node in graph.values() if node["class_type"] == "KSampler")
        self.assertEqual((latent["inputs"]["width"], latent["inputs"]["height"]), (1280, 768))
        self.assertEqual((sampler["inputs"]["seed"], sampler["inputs"]["steps"], sampler["inputs"]["cfg"]), (123, 30, 1.2))
        self.assertEqual(seed, 123)

    def test_qwen21_edit_accepts_one_to_ten_ordered_references(self):
        graph, _ = build_graph("qwen21_edit_refs_api.json", prompt="Keep <image1>; use <image2> for color",
                               images=["main.png", "style.png"], run_id="b" * 32)
        encoder = next(node for node in graph.values() if node["class_type"] == "TextEncodeQwenImage21")
        self.assertEqual(encoder["inputs"]["images"], {"image_1": ["10", 0], "image_2": ["11", 0]})
        self.assertEqual(sum(node["class_type"] == "LoadImage" for node in graph.values()), 2)
        one_image, _ = build_graph("qwen21_edit_refs_api.json", images=["main.png"])
        one_encoder = next(node for node in one_image.values() if node["class_type"] == "TextEncodeQwenImage21")
        self.assertEqual(one_encoder["inputs"]["images"], {"image_1": ["10", 0]})
        with self.assertRaises(BotImageError):
            build_graph("qwen21_edit_refs_api.json")
        with self.assertRaises(BotImageError):
            build_graph("qwen21_edit_refs_api.json", images=[f"image-{index}.png" for index in range(11)])

    def test_power_lora_choices_and_selection_flag(self):
        items = {item["name"]: item for item in catalog()}
        workflow = items["wan_2_2_4steps_t2i.json"]
        options = {item["filename"]: item["enabled_by_default"] for item in workflow["lora_options"]}
        self.assertTrue(options["low_noise_model.safetensors"])
        self.assertFalse(options["Goofballs_WAN_21_22.safetensors"])
        self.assertFalse(any("Power Lora Loader" in field["label"] for field in workflow["fields"]))

        graph, _ = build_graph(workflow["name"], flags={"powerlora": ["Goofballs_WAN_21_22.safetensors"]})
        loader = next(node for node in graph.values() if node["class_type"] == "Power Lora Loader (rgthree)")
        self.assertTrue(loader["inputs"]["lora_1"]["on"])
        self.assertTrue(loader["inputs"]["lora_2"]["on"])
        with self.assertRaises(BotImageError):
            build_graph(workflow["name"], flags={"powerlora": ["not-in-this-recipe.safetensors"]})

    def test_legacy_power_lora_keyword_flag_is_still_supported(self):
        graph, _ = build_graph("wan_2_2_4steps_t2i.json", flags={"powerlora": "goofball"})
        loader = next(node for node in graph.values() if node["class_type"] == "Power Lora Loader (rgthree)")
        self.assertTrue(loader["inputs"]["lora_2"]["on"])

    def test_compatibility_exposes_comfy_enum_choices_for_dropdowns(self):
        object_info = {"KSampler": {"input": {"required": {
            "sampler_name": [["euler", "dpmpp_2m"], {}],
            "scheduler": [["simple", "karras"], {}],
        }}}}
        status = compatibility(object_info)["qwen21_t2i_api.json"]
        self.assertEqual(status["field_choices"]["6:sampler_name:"], ["euler", "dpmpp_2m"])
        self.assertEqual(status["field_choices"]["6:scheduler:"], ["simple", "karras"])

    def test_outpaint_margins_and_extra_image_rejected(self):
        graph, _ = build_graph("extend_image_outpainting_qwen.json", images=["source.jpg"],
                               flags={"extend": {"left": 100, "top": 0, "right": 120, "bottom": 20}})
        pad = next(node for node in graph.values() if node["class_type"] == "ImagePadForOutpaint")
        self.assertEqual(pad["inputs"]["right"], 120)
        with self.assertRaises(BotImageError):
            build_graph("extend_image_outpainting_qwen.json", images=["one.png", "two.png"])

    def test_advanced_override_is_constrained_to_existing_literal(self):
        workflow = next(item for item in catalog() if item["name"] == "krea_t2i_workflow.json")
        field = next(item for item in workflow["fields"] if item["key"] == "cfg")
        graph, _ = build_graph(workflow["name"], overrides=[{**field, "value": 3}])
        self.assertEqual(graph[field["node"]]["inputs"][field["key"]], 3)
        with self.assertRaises(BotImageError):
            build_graph(workflow["name"], overrides=[{"node": "999", "key": "bad", "value": 1}])

    def test_path_in_workflow_name_rejected(self):
        with self.assertRaises(BotImageError):
            build_graph("../config.local.json")

    def test_legacy_workflows_gain_new_required_node_defaults(self):
        graph, _ = build_graph("nunchaku_qwen2509_i2i_1input_edit.json", images=["source.png"])
        scaled = [node for node in graph.values() if node["class_type"] == "ImageScaleToTotalPixels"]
        self.assertTrue(scaled)
        self.assertTrue(all(node["inputs"]["resolution_steps"] == 1 for node in scaled))
        grain, _ = build_graph("wan_t2i_workflow.json")
        self.assertEqual(next(node for node in grain.values() if node["class_type"] == "FastFilmGrain")["inputs"]["batch_size"], 4)

    def test_compatibility_detects_new_required_inputs(self):
        object_info = {"ImageScaleToTotalPixels": {"input": {"required": {"future_required": ["INT", {}]}}}}
        status = compatibility(object_info)["nunchaku_qwen2509_i2i_1input_edit.json"]
        self.assertFalse(status["ready"])
        self.assertIn("ImageScaleToTotalPixels.future_required", status["missing_inputs"])

    def test_catalog_api_and_csrf(self):
        client = TestClient(app)
        response = client.get("/api/bot-images/workflows")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["workflows"]), 30)
        response = client.post("/api/bot-images/runs", data={"payload": '{}'})
        self.assertIn(response.status_code, (401, 403))

    def test_image_lab_uses_separate_comfy_server(self):
        self.assertEqual(image_comfy.base_url, IMAGE_COMFY_URL)
        self.assertEqual(qwen_image_comfy.base_url, QWEN_IMAGE_COMFY_URL)
        self.assertNotEqual(image_comfy.base_url, worker.comfy.base_url)
        with patch.object(image_comfy, "ready", new_callable=AsyncMock, return_value=True):
            with patch.object(qwen_image_comfy, "ready", new_callable=AsyncMock, return_value=False):
                response = TestClient(app).get("/api/bot-images/status")
        self.assertEqual(response.json(), {"ready": True, "qwen21_ready": False})


if __name__ == "__main__":
    unittest.main()
