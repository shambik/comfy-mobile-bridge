import tempfile
import unittest
from pathlib import Path

import backend.h3_still as h3_still
from backend.h3_still import H3StillError, H3StillRun, _build_workflow


class H3StillWorkflowTests(unittest.TestCase):
    def build(self, *, input_mode="text", engine="standard", steps=20, image_name=None, reference_names=None):
        return _build_workflow(
            prompt="A test frame <Picture 1>",
            input_mode=input_mode,
            engine=engine,
            steps=steps,
            aspect_ratio="1:1",
            megapixels=1.0,
            seed=123,
            prefix="image/test",
            image_name=image_name,
            reference_names=reference_names or [],
            ref_image_size="max",
            turbo_profile="v1",
        )

    def test_standard_text_graph_keeps_five_frame_first_frame_path(self):
        workflow = self.build()
        self.assertEqual(workflow["104"]["inputs"]["length"], 5)
        self.assertEqual(workflow["9"]["inputs"]["steps"], 20)
        self.assertEqual(workflow["14"]["inputs"]["sampler"], ["17", 0])
        self.assertEqual(workflow["200"]["class_type"], "ImageFromBatch")
        self.assertEqual(workflow["201"]["class_type"], "SaveImage")

    def test_turbo_graph_uses_selected_steps_and_turbo_sampler(self):
        workflow = self.build(engine="turbo", steps=8)
        self.assertEqual(workflow["9"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["18"]["class_type"], "MiniMaxH3TurboLoRA")
        self.assertEqual(workflow["19"]["class_type"], "MiniMaxH3SigmaShift")
        self.assertEqual(workflow["20"]["class_type"], "MiniMaxH3TurboSampler")
        self.assertEqual(workflow["14"]["inputs"]["sampler"], ["20", 0])

    def test_edit_graph_connects_uploaded_image_as_first_frame(self):
        workflow = self.build(input_mode="edit", image_name="edit.png", steps=12)
        self.assertEqual(workflow["202"]["inputs"]["image"], "edit.png")
        self.assertEqual(workflow["104"]["inputs"]["first_frame"], ["202", 0])

    def test_reference_graph_connects_multiple_images_and_ref2va_conditioning(self):
        workflow = self.build(input_mode="reference", reference_names=["face.png", "wardrobe.png"])
        self.assertNotIn("104", workflow)
        self.assertEqual(workflow["136"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(workflow["136"]["inputs"]["ref_image_size"], "max")
        self.assertEqual(
            workflow["136"]["inputs"]["ref_images"],
            {"ref_image_0": ["137", 0], "ref_image_1": ["138", 0]},
        )
        self.assertEqual(workflow["14"]["inputs"]["latent_image"], ["136", 1])

    def test_reference_turbo_uses_ref2va_turbo_chain(self):
        workflow = self.build(input_mode="reference", engine="turbo", steps=6, reference_names=["face.png"])
        self.assertEqual(workflow["18"]["inputs"]["lora_name"], "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors")
        self.assertEqual(workflow["14"]["inputs"]["sampler"], ["20", 0])

    def test_invalid_input_combinations_raise(self):
        with self.assertRaises(H3StillError):
            self.build(input_mode="reference")
        with self.assertRaises(H3StillError):
            self.build(input_mode="edit")


class H3StillRunTests(unittest.TestCase):
    def test_public_payload_contains_progress_and_timing(self):
        run = H3StillRun(
            id="a" * 32,
            prompt_id="prompt",
            client_id="client",
            prefix="image/test",
            seed=42,
            prompt="test",
            input_mode="text",
            engine="standard",
            steps=20,
            aspect_ratio="1:1",
            megapixels=1.0,
        )
        payload = run.public()
        self.assertEqual(payload["total_steps"], 20)
        self.assertIn("elapsed_seconds", payload)
        self.assertIn("generation_seconds", payload)
        self.assertIn("eta_seconds", payload)

    def test_delete_removes_generated_image_from_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "still.png"
            path.write_bytes(b"png")
            run = H3StillRun(
                id="b" * 32,
                prompt_id="prompt",
                client_id="client",
                prefix="image/test",
                seed=42,
                prompt="test",
                input_mode="text",
                engine="standard",
                steps=20,
                aspect_ratio="1:1",
                megapixels=1.0,
                status="completed",
                image_path=path,
            )
            h3_still._runs[run.id] = run
            h3_still.delete_h3_still(run.id)
            self.assertFalse(path.exists())
            self.assertIsNone(h3_still.get_h3_still(run.id))


if __name__ == "__main__":
    unittest.main()
