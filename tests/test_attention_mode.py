import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.db as db_module
from backend.config import FUSED_VIDEO_VAE, FUSED_WORKFLOW_FILES, VIDEO_VAE
from backend.generation import normalize_generation_settings
from backend.main import app, worker
from backend.workflows import (apply_attention_mode, apply_int8_decode, attention_node_classes,
                               fused_sla_workflow, int8_decode_needed, ltx_lipsync_workflow,
                               native_audio_lock_workflow, official_fused_workflow,
                               reference_workflow, singularity_workflow, turbo_workflow)


def model_chain(workflow: dict) -> list[str]:
    """Class types along the MODEL wire, starting at the UNET loader."""
    current = next(key for key, node in workflow.items() if node["class_type"] == "UNETLoader")
    chain = [workflow[current]["class_type"]]
    while True:
        consumers = [key for key, node in workflow.items()
                     if node["inputs"].get("model") == [current, 0]]
        patches = [key for key in consumers
                   if workflow[key]["class_type"] in {"MiniMaxH3TurboLoRA", "LoraLoaderModelOnly", "PathchSageAttentionKJ",
                                                     "H3SLAAttention", "MiniMaxChunkFeedForward", "ModelAttentionBackend"}]
        if not patches:
            return chain
        current = patches[0]
        chain.append(workflow[current]["class_type"])


needs_official_fused = unittest.skipUnless(
    FUSED_WORKFLOW_FILES["direct"].exists(),
    "needs the official Fused workflows in state/h3-new-flow/official (never committed)",
)


class AttentionSettingsTests(unittest.TestCase):
    def test_default_is_standard(self):
        self.assertEqual(normalize_generation_settings("text").attention_mode, "standard")

    def test_turbo_accepts_every_mode(self):
        for mode in ("standard", "sage", "sla", "sage_sla"):
            settings = normalize_generation_settings("text", "turbo", 6, attention_mode=mode)
            self.assertEqual(settings.attention_mode, mode)

    def test_fused_sla_accepts_only_sage(self):
        self.assertEqual(
            normalize_generation_settings("text", "fused_sla", 4, attention_mode="sage").attention_mode, "sage")
        for mode in ("sla", "sage_sla"):
            with self.assertRaises(ValueError):
                normalize_generation_settings("text", "fused_sla", 4, attention_mode=mode)

    def test_standard_and_spectrum_stay_standard(self):
        with self.assertRaises(ValueError):
            normalize_generation_settings("text", "standard", 20, attention_mode="sage")
        with self.assertRaises(ValueError):
            normalize_generation_settings("text", "spectrum", 16, attention_mode="sla")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_generation_settings("text", "turbo", 6, attention_mode="flash")

    def test_int8_only_where_it_was_tested(self):
        tested = [("turbo", "opening", 6, {}), ("turbo", "lip_sync", 6, {}), ("turbo", "frames", 6, {}),
                  ("singularity", "reference", 8, {"megapixels": 1.5, "aspect_ratio": "9:16"}),
                  ("singularity", "opening", 8, {"megapixels": 1.5, "aspect_ratio": "9:16"}),
                  ("ltx", "lip_sync", None, {}), ("ltx", "opening", None, {}), ("ltx", "frames", None, {})]
        for engine, mode, steps, extra in tested:
            settings = normalize_generation_settings(mode, engine, steps, attention_mode="int8", **extra)
            self.assertEqual(settings.attention_mode, "int8", (engine, mode))
        untested = [("turbo", "text", 6, {}), ("turbo", "reference", 6, {}),
                    ("singularity", "frames", 8, {"megapixels": 1.5, "aspect_ratio": "9:16"}),
                    ("ltx", "text", None, {}), ("ltx", "closing", None, {}), ("ltx", "reference", None, {"aspect_ratio": "16:9"}),
                    ("pika", "opening", None, {}), ("standard", "reference", 20, {}),
                    ("spectrum", "text", 16, {}), ("fused_sla", "text", 4, {}), ("omni", "reference", None, {})]
        for engine, mode, steps, extra in untested:
            with self.assertRaises(ValueError, msg=(engine, mode)):
                normalize_generation_settings(mode, engine, steps, attention_mode="int8", **extra)

    def test_defaults_stay_as_they_were(self):
        self.assertEqual(normalize_generation_settings("opening", "turbo", 6).attention_mode, "standard")
        self.assertEqual(normalize_generation_settings("lip_sync", "ltx").attention_mode, "standard")
        self.assertEqual(normalize_generation_settings("reference", "singularity", 8, megapixels=1.5,
                                                       aspect_ratio="9:16").attention_mode, "sage")


class AttentionWorkflowTests(unittest.TestCase):
    def test_standard_returns_workflow_unchanged(self):
        workflow = turbo_workflow("test", 5, 1, "p", steps=6, turbo_profile="v4")
        self.assertIs(apply_attention_mode(workflow, "standard"), workflow)

    def test_turbo_modes_patch_after_the_lora(self):
        base = turbo_workflow("test", 5, 1, "p", steps=6, turbo_profile="v4")
        expected = {
            "sage": ["UNETLoader", "MiniMaxH3TurboLoRA", "PathchSageAttentionKJ"],
            "sla": ["UNETLoader", "MiniMaxH3TurboLoRA", "H3SLAAttention"],
            "sage_sla": ["UNETLoader", "MiniMaxH3TurboLoRA", "PathchSageAttentionKJ", "H3SLAAttention"],
        }
        for mode, chain in expected.items():
            patched = apply_attention_mode(base, mode)
            self.assertEqual(model_chain(patched), chain, mode)
            self.assertNotIn("H3SLAAttention", {n["class_type"] for n in base.values()}, "base must not change")

    def test_sla_uses_the_tested_settings(self):
        patched = apply_attention_mode(turbo_workflow("test", 5, 1, "p", steps=6), "sla")
        sla = next(n for n in patched.values() if n["class_type"] == "H3SLAAttention")
        self.assertEqual(sla["inputs"]["sparsity_ratio"], 0.90)
        self.assertEqual(sla["inputs"]["block_size"], "64")
        sage = apply_attention_mode(turbo_workflow("test", 5, 1, "p", steps=6), "sage")
        sage_node = next(n for n in sage.values() if n["class_type"] == "PathchSageAttentionKJ")
        self.assertEqual(sage_node["inputs"]["sage_attention"], "auto")

    def test_turbo_lip_sync_and_reference_are_patched(self):
        lip_sync = native_audio_lock_workflow(
            "test", 5, 1, "p", audio_name="a.wav", first_frame_name="f.png",
            steps=6, turbo=True, turbo_profile="v4",
        )
        self.assertEqual(
            model_chain(apply_attention_mode(lip_sync, "sage_sla")),
            ["UNETLoader", "MiniMaxH3TurboLoRA", "PathchSageAttentionKJ", "H3SLAAttention"],
        )
        reference = reference_workflow("test", 5, 1, "p", "ref.png", steps=6, turbo=True)
        self.assertEqual(
            model_chain(apply_attention_mode(reference, "sla")),
            ["UNETLoader", "LoraLoaderModelOnly", "H3SLAAttention"],
        )

    @needs_official_fused
    def test_fused_sla_gets_sage_before_its_sparse_node(self):
        for workflow in (fused_sla_workflow("test", 5, 1, "p"),
                         official_fused_workflow("direct", "test", 5, 1, "p")):
            chain = model_chain(apply_attention_mode(workflow, "sage"))
            self.assertLess(chain.index("PathchSageAttentionKJ"), chain.index("H3SLAAttention"))
            self.assertEqual(chain.count("H3SLAAttention"), 1)
            with self.assertRaises(ValueError):
                apply_attention_mode(workflow, "sla")

    def test_int8_patches_after_the_lora_on_every_tested_engine(self):
        turbo = apply_attention_mode(turbo_workflow("test", 5, 1, "p", steps=6, turbo_profile="v4"), "int8")
        self.assertEqual(model_chain(turbo), ["UNETLoader", "MiniMaxH3TurboLoRA", "ModelAttentionBackend"])
        node = next(n for n in turbo.values() if n["class_type"] == "ModelAttentionBackend")
        self.assertEqual(node["inputs"]["attention"], "comfy kitchen attention")
        skin = apply_attention_mode(singularity_workflow("test", 5, 1, "p", "skin_god", 928, 1632, ["ref.png"]), "int8")
        chain = model_chain(skin)
        self.assertEqual(chain[-1], "ModelAttentionBackend")
        self.assertNotIn("PathchSageAttentionKJ", chain)
        ltx = apply_attention_mode(ltx_lipsync_workflow(prompt="close-up", duration=5.0, seed=4, prefix="p",
                                                        audio_name="a.wav", first_frame_name="f.png",
                                                        width=896, height=1600), "int8")
        self.assertIn("ModelAttentionBackend", {n["class_type"] for n in ltx.values()})

    def test_int8_decode_only_on_turbo_and_only_the_decoder(self):
        self.assertTrue(int8_decode_needed("turbo", "int8"))
        for engine, mode in (("turbo", "standard"), ("turbo", "sage"), ("singularity", "int8"), ("ltx", "int8")):
            self.assertFalse(int8_decode_needed(engine, mode), (engine, mode))
        base = native_audio_lock_workflow("test", 5, 1, "p", audio_name="a.wav", first_frame_name="f.png",
                                          steps=6, turbo=True, turbo_profile="v4")
        patched = apply_int8_decode(base)
        decoders = [n for n in patched.values() if n["class_type"] in ("VAEDecode", "VAEDecodeTiled")]
        self.assertTrue(decoders)
        for decoder in decoders:
            loader = patched[decoder["inputs"]["vae"][0]]
            self.assertEqual(loader["inputs"]["vae_name"], FUSED_VIDEO_VAE)
        fp16 = [n for n in patched.values() if n["class_type"] == "VAELoader" and n["inputs"]["vae_name"] == VIDEO_VAE]
        self.assertTrue(fp16, "the frame encode keeps the fp16 VAE")
        self.assertNotIn(FUSED_VIDEO_VAE, {n["inputs"].get("vae_name") for n in base.values()}, "base must not change")

    def test_node_classes(self):
        self.assertEqual(attention_node_classes("int8"), {"ModelAttentionBackend"})
        self.assertEqual(attention_node_classes("standard"), set())
        self.assertEqual(attention_node_classes("sage_sla"), {"PathchSageAttentionKJ", "H3SLAAttention"})


class AttentionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-attention-test-")
        self.path = Path(self.temp.name) / "jobs.sqlite3"
        self.original_path = db_module.DB_PATH
        db_module.DB_PATH = self.path
        db_module.init_db()
        self.notify_patch = patch.object(worker, "notify")
        self.notify_patch.start()
        self.client = TestClient(app)
        self.token = self.client.get("/api/session").json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        self.notify_patch.stop()
        db_module.DB_PATH = self.original_path
        self.temp.cleanup()

    def post(self, **values):
        data = {"prompt": "A calm cinematic forest", "mode": "text", "duration": "5", **values}
        return self.client.post("/api/jobs", data=data, headers={"X-CSRF-Token": self.token})

    def stored_modes(self):
        connection = sqlite3.connect(self.path)
        try:
            return [row[0] for row in connection.execute("SELECT attention_mode FROM jobs ORDER BY position")]
        finally:
            connection.close()

    def test_mode_is_persisted_and_defaults_to_standard(self):
        self.assertEqual(self.post(engine="turbo", steps="6").status_code, 200)
        response = self.post(engine="turbo", steps="6", attention_mode="sage_sla")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.stored_modes(), ["standard", "sage_sla"])

    def test_unsupported_mode_for_engine_is_rejected(self):
        response = self.post(engine="standard", steps="20", attention_mode="sla")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stored_modes(), [])

    def test_int8_is_refused_for_an_untested_mode(self):
        response = self.post(engine="turbo", steps="6", attention_mode="int8")
        self.assertEqual(response.status_code, 400)
        self.assertIn("tested", response.json()["detail"])
        self.assertEqual(self.stored_modes(), [])


class AttentionMigrationTests(unittest.TestCase):
    def test_existing_jobs_table_gains_the_column_and_keeps_rows(self):
        with tempfile.TemporaryDirectory(prefix="h3-attention-migrate-") as temp:
            fresh = Path(temp) / "fresh.sqlite3"
            legacy = Path(temp) / "legacy.sqlite3"
            original = db_module.DB_PATH
            try:
                db_module.DB_PATH = fresh
                db_module.init_db()
                with closing(sqlite3.connect(fresh)) as connection:
                    create_sql = connection.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()[0]
                legacy_sql = "\n".join(
                    line for line in create_sql.splitlines() if "attention_mode" not in line)
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
                    row = connection.execute("SELECT id, attention_mode FROM jobs").fetchone()
            finally:
                db_module.DB_PATH = original
        self.assertEqual(row, ("old", "standard"))

    def test_four_mode_table_is_rebuilt_to_accept_int8_and_keeps_rows(self):
        with tempfile.TemporaryDirectory(prefix="h3-attention-int8-") as temp:
            fresh = Path(temp) / "fresh.sqlite3"
            legacy = Path(temp) / "legacy.sqlite3"
            original = db_module.DB_PATH
            try:
                db_module.DB_PATH = fresh
                db_module.init_db()
                with closing(sqlite3.connect(fresh)) as connection:
                    create_sql = connection.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()[0]
                self.assertIn("'sage_sla','int8'", create_sql)
                with closing(sqlite3.connect(legacy)) as connection:
                    connection.execute(create_sql.replace(",'int8'", ""))
                    connection.execute(
                        """INSERT INTO jobs (id,prompt,mode,duration,engine,turbo_profile,attention_mode,encoder,steps,
                           width,height,seed,status,position,created_at,updated_at)
                           VALUES ('old','p','text',5,'turbo','v1','sage_sla','native',4,736,416,'1','completed',1,'t','t')""")
                    connection.commit()
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(
                            """INSERT INTO jobs (id,prompt,mode,duration,engine,turbo_profile,attention_mode,encoder,steps,
                               width,height,seed,status,position,created_at,updated_at)
                               VALUES ('x','p','text',5,'turbo','v1','int8','native',4,736,416,'1','queued',2,'t','t')""")
                db_module.DB_PATH = legacy
                db_module.init_db()
                with closing(sqlite3.connect(legacy)) as connection:
                    kept = connection.execute("SELECT id, attention_mode, status FROM jobs").fetchall()
                    connection.execute(
                        """INSERT INTO jobs (id,prompt,mode,duration,engine,turbo_profile,attention_mode,encoder,steps,
                           width,height,seed,status,position,created_at,updated_at)
                           VALUES ('new','p','opening',5,'turbo','v4','int8','native',6,928,1632,'2','queued',2,'t','t')""")
                    connection.commit()
                    modes = [r[0] for r in connection.execute("SELECT attention_mode FROM jobs ORDER BY position")]
            finally:
                db_module.DB_PATH = original
        self.assertEqual(kept, [("old", "sage_sla", "completed")])
        self.assertEqual(modes, ["sage_sla", "int8"])


if __name__ == "__main__":
    unittest.main()
