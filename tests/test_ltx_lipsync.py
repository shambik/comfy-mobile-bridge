import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import backend.db as db_module
from backend.config import LTX_MODEL_FILES
from backend.generation import LTX_SIZES, ltx_quality_for_size, normalize_generation_settings
from backend.main import app, worker
from backend.workflows import ltx_frame_count, ltx_lipsync_workflow, ltx_node_classes, ltx_video_workflow


class LtxSettingsTests(unittest.TestCase):
    def test_balanced_vertical_matches_tested_size(self):
        settings = normalize_generation_settings("lip_sync", "ltx", aspect_ratio="9:16")
        self.assertEqual((settings.width, settings.height, settings.steps), (896, 1600, 8))
        self.assertEqual(settings.encoder, "native")
        self.assertEqual(settings.attention_mode, "standard")

    def test_high_quality_stays_inside_the_app_pixel_limit(self):
        for aspect, (width, height) in LTX_SIZES["high"].items():
            settings = normalize_generation_settings("lip_sync", "ltx", aspect_ratio=aspect, ltx_quality="high")
            self.assertEqual((settings.width, settings.height), (width, height))
            self.assertLessEqual(width * height, 2_000_000, aspect)
            self.assertEqual((width % 32, height % 32), (0, 0), aspect)

    def test_quality_round_trips_from_stored_size(self):
        self.assertEqual(ltx_quality_for_size(1056, 1888), "high")
        self.assertEqual(ltx_quality_for_size(896, 1600), "balanced")

    def test_ltx_supports_every_mode(self):
        for mode in ("text", "opening", "closing", "frames", "lip_sync", "reference"):
            self.assertEqual(normalize_generation_settings(mode, "ltx").engine, "ltx", mode)

    def test_ltx_has_fixed_steps_and_known_qualities(self):
        with self.assertRaises(ValueError):
            normalize_generation_settings("lip_sync", "ltx", steps=6)
        with self.assertRaises(ValueError):
            normalize_generation_settings("lip_sync", "ltx", ltx_quality="ultra")
        with self.assertRaises(ValueError):
            normalize_generation_settings("lip_sync", "turbo", 6, ltx_quality="high")


class LtxWorkflowTests(unittest.TestCase):
    def build(self, **overrides):
        values = dict(prompt="close-up singing", duration=5.0, seed=42, prefix="h3_bridge_job",
                      audio_name="voice.wav", first_frame_name="face.png", width=896, height=1600)
        values.update(overrides)
        return ltx_lipsync_workflow(**values)

    def test_inputs_are_wired_into_the_template(self):
        nodes = self.build()
        self.assertEqual(nodes["269"]["inputs"]["image"], "face.png")
        self.assertEqual(nodes["276"]["inputs"]["audio"], "voice.wav")
        self.assertEqual(nodes["340:306"]["inputs"]["text"], "close-up singing")
        self.assertEqual(nodes["340:286"]["inputs"]["noise_seed"], 42)
        self.assertEqual((nodes["340:330"]["inputs"]["value"], nodes["340:324"]["inputs"]["value"]), (896, 1600))
        self.assertEqual(nodes["341"]["inputs"]["filename_prefix"], "h3_bridge_job")
        self.assertEqual(nodes["audio_offset"]["inputs"]["value"], 0.0)

    def test_single_pass_without_upscaler(self):
        nodes = self.build()
        classes = {node["class_type"] for node in nodes.values()}
        self.assertNotIn("LTXVLatentUpsampler", classes)
        self.assertNotIn("LatentUpscaleModelLoader", classes)
        samplers = [k for k, n in nodes.items() if n["class_type"] == "SamplerCustomAdvanced"]
        self.assertEqual(len(samplers), 1)
        # The latent is created at full size, not half size.
        self.assertEqual(nodes["340:302"]["inputs"]["width"], ["340:330", 0])
        self.assertEqual(nodes["340:302"]["inputs"]["height"], ["340:324", 0])

    def test_audio_is_frozen_while_sampling(self):
        nodes = self.build()
        concat = nodes["340:326"]["inputs"]["audio_latent"]
        self.assertEqual(nodes[concat[0]]["class_type"], "SetLatentNoiseMask")
        mask = nodes[concat[0]]["inputs"]["mask"][0]
        self.assertEqual(nodes[mask]["inputs"]["value"], 0)

    def test_every_link_points_at_a_node(self):
        nodes = self.build()
        for node_id, node in nodes.items():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], nodes, f"{node_id} -> {value}")

    def test_frame_count_follows_ltx_grid(self):
        self.assertEqual(ltx_frame_count(5), 121)
        self.assertEqual(ltx_frame_count(7), 169)
        for seconds in (1, 2.5, 5, 7.3, 10):
            self.assertEqual((ltx_frame_count(seconds) - 1) % 8, 0)

    def test_rejects_sizes_off_the_32_grid(self):
        with self.assertRaises(ValueError):
            self.build(width=900)

    def test_node_classes_come_from_the_template(self):
        self.assertIn("LTXVAudioVAEEncode", ltx_node_classes())
        self.assertIn("LTXVImgToVideoInplace", ltx_node_classes())


class LtxVideoWorkflowTests(unittest.TestCase):
    def build(self, mode, **overrides):
        values = dict(prompt="a singer on a neon street", duration=5.0, seed=7, prefix="h3_bridge_job",
                      width=896, height=1600)
        values.update(overrides)
        return ltx_video_workflow(mode, **values)

    @staticmethod
    def classes(nodes):
        return [node["class_type"] for node in nodes.values()]

    def assert_links_resolve(self, nodes):
        for node_id, node in nodes.items():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], nodes, f"{node_id} -> {value}")

    def test_text_mode_has_no_image_and_generates_audio(self):
        nodes = self.build("text")
        classes = self.classes(nodes)
        self.assertNotIn("LoadImage", classes)
        self.assertIn("LTXVEmptyLatentAudio", classes)
        self.assertIn("LTXVAudioVAEDecode", classes)
        self.assertEqual(classes.count("SamplerCustomAdvanced"), 1)
        self.assert_links_resolve(nodes)

    def test_opening_mode_places_the_first_frame(self):
        nodes = self.build("opening", first_frame_name="first.png")
        classes = self.classes(nodes)
        self.assertIn("LTXVImgToVideoInplace", classes)
        self.assertNotIn("LTXVAddGuide", classes)
        self.assertEqual([n["inputs"]["image"] for n in nodes.values() if n["class_type"] == "LoadImage"], ["first.png"])
        self.assert_links_resolve(nodes)

    def test_closing_and_frames_pin_the_last_frame_and_crop_it(self):
        for mode, kwargs in (("closing", {"last_frame_name": "last.png"}),
                             ("frames", {"first_frame_name": "first.png", "last_frame_name": "last.png"})):
            nodes = self.build(mode, **kwargs)
            guide = next(n for n in nodes.values() if n["class_type"] == "LTXVAddGuide")
            self.assertEqual(guide["inputs"]["frame_idx"], -1, mode)
            self.assertIn("LTXVCropGuides", self.classes(nodes), mode)
            decode = next(n for n in nodes.values() if n["class_type"] == "VAEDecodeTiled")
            self.assertEqual(nodes[decode["inputs"]["samples"][0]]["class_type"], "LTXVCropGuides", mode)
            self.assert_links_resolve(nodes)

    def test_no_audio_leaves_audio_out_of_the_file(self):
        nodes = self.build("text", include_audio=False)
        create = next(n for n in nodes.values() if n["class_type"] == "CreateVideo")
        self.assertNotIn("audio", create["inputs"])

    def test_mode_input_checks(self):
        with self.assertRaises(ValueError):
            self.build("opening")
        with self.assertRaises(ValueError):
            self.build("closing")
        with self.assertRaises(ValueError):
            self.build("text", first_frame_name="first.png")
        with self.assertRaises(ValueError):
            self.build("reference")
        with self.assertRaises(ValueError):
            self.build("text", reference_image_name="sheet.png")

    def test_reference_mode_uses_the_ingredients_iclora(self):
        nodes = self.build("reference", reference_image_name="sheet.png")
        lora = next(n for n in nodes.values() if n["class_type"] == "LTXICLoRALoaderModelOnly")
        self.assertEqual(lora["inputs"]["lora_name"], "ltx-2.3-22b-ic-lora-ingredients-0.9.safetensors")
        guider = next(n for n in nodes.values() if n["class_type"] == "CFGGuider")
        self.assertEqual(nodes[guider["inputs"]["model"][0]]["class_type"], "LTXICLoRALoaderModelOnly")
        guide = next(n for n in nodes.values() if n["class_type"] == "LTXAddVideoICLoRAGuide")
        self.assertEqual(nodes[guide["inputs"]["latent_downscale_factor"][0]]["class_type"], "LTXICLoRALoaderModelOnly")
        self.assertIn("LTXVCropGuides", self.classes(nodes))
        self.assertNotIn("LTXVAddGuide", self.classes(nodes))
        self.assertEqual([n["inputs"]["image"] for n in nodes.values() if n["class_type"] == "LoadImage"], ["sheet.png"])
        self.assert_links_resolve(nodes)


class LtxApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-ltx-api-")
        self.path = Path(self.temp.name) / "jobs.sqlite3"
        self.original_path = db_module.DB_PATH
        db_module.DB_PATH = self.path
        db_module.init_db()
        self.models = Path(self.temp.name) / "models"
        for folder, name in LTX_MODEL_FILES:
            (self.models / folder).mkdir(parents=True, exist_ok=True)
            (self.models / folder / name).write_bytes(b"test-marker")
        self.notify_patch = patch.object(worker, "notify")
        self.notify_patch.start()
        self.client = TestClient(app)
        self.token = self.client.get("/api/session").json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        self.notify_patch.stop()
        db_module.DB_PATH = self.original_path
        self.temp.cleanup()

    def post(self, data, with_frame=True, models=None):
        body = {"prompt": "close-up singing", "mode": "lip_sync", "duration": "5",
                "engine": "ltx", "aspect_ratio": "9:16", "audio_start": "0", **data}
        files = {"audio": ("voice.wav", b"audio-placeholder", "audio/wav")}
        if with_frame:
            files["first_frame"] = ("face.png", b"image-placeholder", "image/png")
        with patch("backend.main.MODELS", models or self.models), \
             patch("backend.main.save_image", new=AsyncMock(return_value=("C:/safe/face.png", "face.png"))), \
             patch("backend.main.save_audio", new=AsyncMock(return_value=("C:/safe/voice.wav", "voice.wav"))), \
             patch("backend.main.probe_audio_duration", return_value=5.0):
            return self.client.post("/api/jobs", data=body, files=files, headers={"X-CSRF-Token": self.token})

    def stored(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                "SELECT engine, steps, width, height, first_frame_name, reference_audio_name FROM jobs"
            ).fetchall()

    def test_high_quality_job_is_persisted(self):
        response = self.post({"ltx_quality": "high"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.stored(), [("ltx", 8, 1056, 1888, "face.png", "voice.wav")])

    def test_requires_an_opening_image(self):
        self.assertEqual(self.post({}, with_frame=False).status_code, 400)
        self.assertEqual(self.stored(), [])

    def test_rejects_durations_outside_one_to_ten_seconds(self):
        self.assertEqual(self.post({"duration": "12", "audio_duration": "12"}).status_code, 400)

    def test_text_mode_job_is_persisted(self):
        with patch("backend.main.MODELS", self.models):
            response = self.client.post(
                "/api/jobs",
                data={"prompt": "a singer on a neon street", "mode": "text", "duration": "5",
                      "engine": "ltx", "aspect_ratio": "16:9"},
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute("SELECT mode, engine, steps, width, height FROM jobs").fetchone()
        self.assertEqual(row, ("text", "ltx", 8, 1600, 896))

    def post_reference(self, files, with_lora=True):
        if with_lora:
            (self.models / "loras").mkdir(parents=True, exist_ok=True)
            (self.models / "loras" / "ltx-2.3-22b-ic-lora-ingredients-0.9.safetensors").write_bytes(b"test-marker")
        with patch("backend.main.MODELS", self.models), \
             patch("backend.main.save_image", new=AsyncMock(return_value=("C:/safe/sheet.png", "sheet.png"))):
            return self.client.post(
                "/api/jobs",
                data={"prompt": "the singer from the sheet on stage", "mode": "reference", "duration": "5", "engine": "ltx"},
                files=files, headers={"X-CSRF-Token": self.token},
            )

    def test_reference_mode_takes_one_sheet(self):
        one = [("reference_images", ("sheet.png", b"image-placeholder", "image/png"))]
        self.assertEqual(self.post_reference(one).status_code, 200)
        two = one + [("reference_images", ("other.png", b"image-placeholder", "image/png"))]
        self.assertEqual(self.post_reference(two).status_code, 400)

    def test_reference_mode_needs_the_iclora(self):
        one = [("reference_images", ("sheet.png", b"image-placeholder", "image/png"))]
        response = self.post_reference(one, with_lora=False)
        self.assertEqual(response.status_code, 409)
        self.assertIn("IC-LoRA", response.text)

    def test_reports_missing_models(self):
        response = self.post({}, models=Path(self.temp.name) / "empty")
        self.assertEqual(response.status_code, 409)
        self.assertIn("LTX 2.5 is not fully installed", response.text)


class LtxMigrationTests(unittest.TestCase):
    def test_older_jobs_table_is_rebuilt_to_accept_ltx(self):
        with tempfile.TemporaryDirectory(prefix="h3-ltx-migrate-") as temp:
            fresh = Path(temp) / "fresh.sqlite3"
            legacy = Path(temp) / "legacy.sqlite3"
            original = db_module.DB_PATH
            try:
                db_module.DB_PATH = fresh
                db_module.init_db()
                with closing(sqlite3.connect(fresh)) as connection:
                    create_sql = connection.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()[0]
                legacy_sql = (create_sql.replace(",'ltx'", "")
                              .replace("(engine='ltx' AND steps = 8) OR", ""))
                with closing(sqlite3.connect(legacy)) as connection:
                    connection.execute(legacy_sql)
                    connection.execute(
                        """INSERT INTO jobs (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,
                           width,height,seed,status,position,created_at,updated_at)
                           VALUES ('old','p','text',5,'turbo','v1','native',4,736,416,'1','completed',1,'t','t')""")
                    connection.commit()
                db_module.DB_PATH = legacy
                db_module.init_db()
                with closing(sqlite3.connect(legacy)) as connection:
                    kept = connection.execute("SELECT id, engine FROM jobs").fetchall()
                    connection.execute(
                        """INSERT INTO jobs (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,
                           width,height,seed,status,position,created_at,updated_at)
                           VALUES ('new','p','lip_sync',5,'ltx','v1','native',8,896,1600,'1','queued',2,'t','t')""")
                    connection.commit()
                    count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            finally:
                db_module.DB_PATH = original
        self.assertEqual(kept, [("old", "turbo")])
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
