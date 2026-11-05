import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import db as db_module
from backend.config import OMNI_MODEL
from backend.generation import OMNI_SIZES, normalize_generation_settings
from backend.main import app, worker
from backend.workflows import omni_workflow


def classes(workflow):
    return {node["class_type"] for node in workflow.values()}


class OmniSettingsTests(unittest.TestCase):
    def test_sizes_are_the_tested_ones(self):
        for megapixels, sizes in OMNI_SIZES.items():
            for aspect, size in sizes.items():
                settings = normalize_generation_settings("reference", engine="omni", megapixels=megapixels, aspect_ratio=aspect)
                with self.subTest(megapixels=megapixels, aspect=aspect):
                    self.assertEqual((settings.engine, settings.steps, settings.width, settings.height), ("omni", 8, *size))
                    self.assertEqual((settings.attention_mode, settings.workflow_variant, settings.encoder), ("standard", "direct", "native"))

    def test_untested_choices_are_refused(self):
        for kwargs in ({"mode": "opening"}, {"mode": "lip_sync"}, {"mode": "reference", "steps": 6},
                       {"mode": "reference", "megapixels": 2.0}, {"mode": "reference", "aspect_ratio": "1:1"},
                       {"mode": "reference", "attention_mode": "sage"}, {"mode": "reference", "encoder": "clipproj"},
                       {"mode": "reference", "workflow_variant": "turbo4"}):
            with self.subTest(kwargs), self.assertRaises(ValueError):
                normalize_generation_settings(engine="omni", **kwargs)


class OmniWorkflowTests(unittest.TestCase):
    def test_graph_is_the_comfy_org_template(self):
        workflow = omni_workflow("hello", 5, 7, "x", 928, 1632, ["a.png", "b.png"], audio_name="song.wav")
        self.assertEqual(workflow["127"]["inputs"]["unet_name"], OMNI_MODEL)
        self.assertEqual(workflow["124"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["123"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(workflow["143"]["inputs"]["selection.keep_percent"], 10.0)
        self.assertEqual(workflow["142"]["inputs"]["attention"], "comfy kitchen attention")
        self.assertEqual(workflow["136"]["inputs"]["length"], 124)
        inputs = workflow["136"]["inputs"]
        # Flat keys only: ComfyUI silently drops a nested {"ref_images": {...}} dict.
        self.assertEqual(inputs["ref_images.ref_image_0"], ["137", 0])
        self.assertEqual(inputs["ref_images.ref_image_1"], ["138", 0])
        self.assertEqual(inputs["ref_audios.ref_audio_0"], ["180", 0])
        self.assertFalse([key for key, value in inputs.items() if isinstance(value, dict)])
        self.assertIn("VAEDecodeAudio", classes(workflow))

    def test_reference_video_brings_motion_but_not_its_soundtrack(self):
        workflow = omni_workflow("hello", 5, 7, "x", 576, 1024, ["a.png"], video_names=["shot.mp4"])
        self.assertEqual(workflow["136"]["inputs"]["ref_videos.ref_video_0"], ["151", 0])
        self.assertFalse([key for key in workflow["136"]["inputs"] if key.startswith("ref_video_audios")])

    def test_silent_job_has_no_audio_decode(self):
        workflow = omni_workflow("hello", 5, 7, "x", 576, 1024, ["a.png"], include_audio=False)
        self.assertNotIn("VAEDecodeAudio", classes(workflow))
        self.assertNotIn("audio", workflow["130"]["inputs"])


class OmniApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "jobs.sqlite3"
        self.original_db = db_module.DB_PATH
        db_module.DB_PATH = self.path
        db_module.init_db()
        self.notify_patch = patch.object(worker, "notify")
        self.notify_patch.start()
        self.client = TestClient(app)
        self.token = self.client.get("/api/session").json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        self.notify_patch.stop()
        db_module.DB_PATH = self.original_db
        self.temp.cleanup()

    def post(self, data, files):
        with patch("backend.main.omni_ready", return_value=True), \
             patch("backend.main.save_image", new=AsyncMock(return_value=("C:/safe/sheet.png", "sheet.png"))), \
             patch("backend.main.save_video", new=AsyncMock(return_value=("C:/safe/shot.mp4", "shot.mp4"))):
            return self.client.post("/api/jobs", data=data, files=files, headers={"X-CSRF-Token": self.token})

    def test_job_is_persisted_with_the_tested_size(self):
        data = {"prompt": "<Picture 1> walks", "mode": "reference", "duration": "5", "engine": "omni", "steps": "8",
                "megapixels": "1.5", "aspect_ratio": "9:16"}
        response = self.post(data, {"reference_images": ("sheet.png", b"image", "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT engine,mode,steps,width,height,megapixels FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("omni", "reference", 8, 928, 1632, 1.5))

    def test_reference_video_is_allowed_at_every_size(self):
        # Owner's choice: no size limit with a reference video; the form warns that it is slow.
        data = {"prompt": "<Picture 1> copies <Video 1>", "mode": "reference", "duration": "5", "engine": "omni",
                "steps": "8", "aspect_ratio": "9:16"}
        files = [("reference_images", ("sheet.png", b"image", "image/png")),
                 ("reference_videos", ("shot.mp4", b"video", "video/mp4"))]
        for megapixels in ("0.6", "1.0", "1.5"):
            response = self.post({**data, "megapixels": megapixels}, files)
            self.assertEqual(response.status_code, 200, response.text)
        two_videos = files + [("reference_videos", ("b.mp4", b"video", "video/mp4"))]
        self.assertEqual(self.post({**data, "megapixels": "0.6"}, two_videos).status_code, 400)

    def test_untested_lengths_are_refused(self):
        data = {"prompt": "<Picture 1> walks", "mode": "reference", "duration": "9", "engine": "omni", "steps": "8",
                "megapixels": "1.0", "aspect_ratio": "16:9"}
        response = self.post(data, {"reference_images": ("sheet.png", b"image", "image/png")})
        self.assertEqual(response.status_code, 400, response.text)


if __name__ == "__main__":
    unittest.main()
