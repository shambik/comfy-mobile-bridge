"""Character swap through the app API (issue #46): a finished job -> parts -> marks -> a queued swap job."""
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import backend.character_swap as cs
import backend.db as db_module
from backend import library
from backend.db import connect, now_iso
from backend.main import app, worker


class SwapApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-swap-api-")
        self.root = Path(self.temp.name)
        self.original_db = db_module.DB_PATH
        db_module.DB_PATH = self.root / "jobs.sqlite3"
        self.output, self.input = self.root / "output", self.root / "input"
        self.output.mkdir()
        self.input.mkdir()
        self.patches = [patch.object(library, "PROJECTS", self.root / "projects"),
                        patch.object(library, "OUTPUT", self.output), patch.object(worker, "notify"),
                        patch.object(cs, "SWAPS", self.root / "swaps"), patch.object(cs, "CHARACTERS", self.root / "chars"),
                        patch.object(cs, "CHARACTERS_FILE", self.root / "chars" / "characters.json"),
                        patch.object(cs, "INPUT", self.input), patch("backend.main.INPUT", self.input)]
        for item in self.patches:
            item.start()
        db_module.init_db()
        library.init_library_db()
        self.client = TestClient(app)
        self.token = self.client.get("/api/session").json()["csrf_token"]
        self.headers = {"X-CSRF-Token": self.token}

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        db_module.DB_PATH = self.original_db
        self.temp.cleanup()

    def add_job(self, job_id="src", seconds=5):
        video = self.output / f"{job_id}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=s=64x112:r=24:d={seconds}",
                        "-f", "lavfi", "-i", f"sine=d={seconds}", "-shortest", "-pix_fmt", "yuv420p", str(video)],
                       check=True)
        now = now_iso()
        with connect() as db:
            db.execute("""INSERT INTO jobs (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,
                          megapixels,aspect_ratio,seed,status,position,output_path,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (job_id, "Two friends at a bus stop", "opening", seconds, "turbo", "v4", "native", 6, 736, 1312,
                        0.97, "9:16", "42", "completed", 1, str(video), now, now))

    def character(self, name="Suit man"):
        image = self.root / f"{name}.png"
        Image.new("RGB", (96, 96), (200, 10, 10)).save(image)
        with image.open("rb") as handle:
            r = self.client.post("/api/swap/characters", data={"name": name, "look": "bald, black suit"},
                                 files={"image": (image.name, handle, "image/png")}, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def test_a_finished_job_becomes_a_queued_swap_job_with_its_real_graph(self):
        self.add_job()
        swap = self.client.post("/api/swap", data={"job_id": "src"}, headers=self.headers).json()
        self.assertEqual((swap["frames"], len(swap["shots"])), (107, 1))
        char = self.character()
        marks = [{"shot": 0, "x": 0.5, "y": 0.4, "character_id": char, "description": "the man in the grey coat"}]
        r = self.client.put(f"/api/swap/{swap['id']}/marks", json={"marks": marks, "mode": "reference"},
                            headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post(f"/api/swap/{swap['id']}/render", headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        job_id = r.json()["job_id"]
        with connect() as db:
            row = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual((row["engine"], row["mode"], row["workflow_variant"], row["steps"], row["width"], row["height"],
                          row["status"], row["attention_mode"]), ("swap", "swap", "viggle", 6, 736, 1280, "queued", "standard"))
        options = json.loads(row["swap_options_json"])
        self.assertEqual(options["graph"]["base"]["1"]["inputs"]["unet_name"], cs.VIGGLE_MODEL)
        self.assertIn(("diffusion_models", cs.VIGGLE_MODEL), [tuple(m) for m in options["models"]])
        self.assertTrue((self.input / options["graph"]["set"]["7.file"]).is_file())
        public = next(j for j in self.client.get("/api/jobs").json()["jobs"] if j["id"] == job_id)
        self.assertIn("Viggle Remake", public["swap_options"]["card"]["tags"])
        self.assertIn("in place of the man in the grey coat", public["swap_options"]["graph"]["set"]["11.prompt"])
        # the worker's follow-up marks the swap done once its job completes
        with connect() as db:
            db.execute("UPDATE jobs SET status='completed', output_path=? WHERE id=?", (str(self.output / "src.mp4"), job_id))
        cs.follow(db_module.get_job)
        self.assertEqual(cs.get_swap(swap["id"])["status"], "done")

    def test_akatz_queues_one_job_with_its_own_graph_and_models(self):
        self.add_job()
        swap = self.client.post("/api/swap", data={"job_id": "src"}, headers=self.headers).json()
        char = self.character()
        marks = [{"shot": 0, "x": 0.8, "y": 0.4, "character_id": char, "description": "man in a grey coat"}]
        self.client.put(f"/api/swap/{swap['id']}/marks", json={"marks": marks, "mode": "reference", "engine": "akatz"},
                        headers=self.headers)
        with patch.object(cs, "AKATZ_GRAPH", self.root / "akatz.api.json"):
            job_id = self.client.post(f"/api/swap/{swap['id']}/render", headers=self.headers).json()["job_id"]
        with connect() as db:
            row = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        self.assertEqual((row["workflow_variant"], row["steps"], row["width"], row["height"]), ("akatz", 8, 512, 928))
        options = json.loads(row["swap_options_json"])
        self.assertEqual(options["graph"]["set"]["select.selection"], "rightmost")
        self.assertIn(("checkpoints", "sam3.1_multiplex_fp16.safetensors"), [tuple(m) for m in options["models"]])

    def test_old_job_tables_are_rebuilt_with_every_row_kept(self):
        db_module.DB_PATH = self.root / "old.sqlite3"
        old = sqlite3.connect(db_module.DB_PATH)
        cs_sql = (Path(db_module.__file__).read_text(encoding="utf-8"))
        start = cs_sql.index("    CREATE TABLE jobs (")
        end = cs_sql.index("    CREATE INDEX idx_jobs_queue", start)
        sql = (cs_sql[start:end].replace(",'swap')),", ")),").replace(",'viggle','akatz','swap_join'", "")
               .replace("        swap_options_json TEXT,\n", "").replace("              (engine='swap' AND steps IN (1,6,8)) OR\n", ""))
        old.executescript(sql)
        now = now_iso()
        old.execute("""INSERT INTO jobs (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,seed,status,
                       position,created_at,updated_at) VALUES('keep','A shot','opening',5,'turbo','v4','native',6,736,416,
                       '1','completed',1,?,?)""", (now, now))
        old.commit()
        old.close()
        db_module.init_db()
        with connect() as db:
            self.assertEqual(db.execute("SELECT prompt FROM jobs WHERE id='keep'").fetchone()[0], "A shot")
            self.assertIn("swap_options_json", {r[1] for r in db.execute("PRAGMA table_info(jobs)")})
            db.execute("""INSERT INTO jobs (id,prompt,mode,duration,engine,workflow_variant,turbo_profile,encoder,steps,width,
                          height,seed,status,position,created_at,updated_at) VALUES('s','Swap','swap',5,'swap','viggle','v1',
                          'native',6,736,1280,'1','queued',2,?,?)""", (now, now))


if __name__ == "__main__":
    unittest.main()
