"""Upscale / interpolation jobs (issue #37): tested limits, graphs, the API and the jobs table."""
import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.db as db_module
import backend.library as library
from backend.db import connect, now_iso
from backend.main import app, worker
from backend.post_process import (aspect_label, crop_percent, plan_post_process, post_model_files, post_node_classes,
                                  post_process_workflow, post_title, probe_video, upscale_size)
from backend.worker import QueueWorker

SHOT = {"width": 1632, "height": 928, "fps": 24.0, "frames": 121, "duration": 5.042, "audio": True}


def classes(workflow: dict) -> set[str]:
    return {node["class_type"] for node in workflow.values()}


class PlanTests(unittest.TestCase):
    def test_interpolation_doubles_frames_and_fps(self):
        options = plan_post_process(SHOT, "interpolate", "rife")
        self.assertEqual((options["width"], options["height"], options["fps"], options["frames"]), (1632, 928, 48.0, 241))
        self.assertTrue(options["audio"])

    def test_upscale_keeps_aspect_on_multiples_of_16(self):
        # near-16:9 / 9:16 sources get the standard delivery sizes with a small center crop
        for size, long_side, target in (((1632, 928), 2560, (2560, 1440)), ((1344, 736), 1920, (1920, 1080)),
                                        ((928, 1632), 2560, (1440, 2560)), ((768, 1344), 1920, (1080, 1920)),
                                        ((1056, 1888), 2560, (1440, 2560)), ((1024, 576), 1920, (1920, 1080))):
            self.assertEqual(upscale_size(*size, long_side), target, size)
        self.assertEqual(crop_percent(1344, 736, 1920, 1080), 2.6)
        # other shapes keep their own, on multiples of 16
        self.assertEqual(upscale_size(768, 768, 1920), (1920, 1920))
        self.assertEqual(upscale_size(1216, 1632, 2560), (1904, 2560))
        options = plan_post_process(SHOT, "upscale", "gan", 2560)
        self.assertEqual((options["width"], options["height"], options["fps"], options["frames"]), (2560, 1440, 24.0, 121))
        self.assertEqual(options["crop_percent"], 1.1)

    def test_unknown_operation_or_method_is_refused(self):
        for operation, method in (("sharpen", "rife"), ("interpolate", "lanczos"), ("upscale", "rife"),
                                  ("upscale", "seedvr2"), ("interpolate", "dat2")):
            with self.assertRaises(ValueError):
                plan_post_process(SHOT, operation, method, 2560)

    def test_models_only_on_tested_sizes_and_lengths(self):
        big = {**SHOT, "width": 1920, "height": 1088}
        long = {**SHOT, "frames": 241, "duration": 10.04}
        for method, operation in (("rife", "interpolate"), ("film", "interpolate"), ("gan", "upscale")):
            with self.assertRaises(ValueError):
                plan_post_process(big, operation, method, 2560)
            with self.assertRaises(ValueError):
                plan_post_process(long, operation, method, 2560)

    def test_lanczos_runs_on_interpolated_clips_but_not_longer(self):
        doubled = {**SHOT, "fps": 48.0, "frames": 241}
        self.assertEqual(plan_post_process(doubled, "upscale", "lanczos", 2560)["frames"], 241)
        with self.assertRaises(ValueError):
            plan_post_process({**SHOT, "frames": 301}, "upscale", "lanczos", 2560)
        self.assertEqual(plan_post_process({**SHOT, "fps": 60.0, "frames": 300}, "upscale", "lanczos", 2560)["frames"], 300)

    def test_1080p_30fps_uploads_follow_the_lab_results(self):
        phone = {"width": 1920, "height": 1080, "fps": 30.0, "frames": 150, "duration": 5.0, "audio": True}
        portrait = {**phone, "width": 1080, "height": 1920}
        rife = plan_post_process(phone, "interpolate", "rife")
        self.assertEqual((rife["fps"], rife["frames"]), (60.0, 299))
        self.assertEqual(plan_post_process(portrait, "interpolate", "rife")["width"], 1080)
        self.assertEqual(plan_post_process(phone, "upscale", "gan", 2560)["width"], 2560)
        with self.assertRaisesRegex(ValueError, "use RIFE"):
            plan_post_process(phone, "interpolate", "film")
        with self.assertRaises(ValueError):
            plan_post_process({**phone, "frames": 151}, "interpolate", "rife")

    def test_interpolating_a_48fps_clip_is_refused(self):
        with self.assertRaises(ValueError):
            plan_post_process({**SHOT, "fps": 48.0}, "interpolate", "rife")

    def test_upscale_targets_are_fixed_and_must_grow(self):
        for long_side in (None, 1280, 3840):
            with self.assertRaises(ValueError):
                plan_post_process(SHOT, "upscale", "lanczos", long_side)
        with self.assertRaises(ValueError):
            plan_post_process({**SHOT, "width": 1920, "height": 1088}, "upscale", "lanczos", 1920)


class WorkflowTests(unittest.TestCase):
    def test_rife_graph(self):
        options = plan_post_process(SHOT, "interpolate", "rife")
        graph = post_process_workflow(options, "src.mp4", "h3_job_x")
        self.assertEqual(graph["10"]["inputs"]["model_name"], "rife_v4.26.safetensors")
        self.assertEqual(graph["11"]["inputs"]["multiplier"], 2)
        self.assertEqual(graph["30"]["inputs"]["fps"], 48.0)
        self.assertEqual(graph["30"]["inputs"]["audio"], ["2", 1])
        self.assertEqual(graph["31"]["inputs"]["filename_prefix"], "h3_job_x")
        self.assertEqual(classes(graph), post_node_classes(options))
        self.assertEqual(post_model_files(options), [("frame_interpolation", "rife_v4.26.safetensors")])

    def test_gan_graph_fits_the_target_with_lanczos(self):
        options = plan_post_process(SHOT, "upscale", "gan", 2560)
        graph = post_process_workflow(options, "src.mp4", "p")
        self.assertEqual(graph["12"]["inputs"]["image"], ["11", 0])
        self.assertEqual((graph["12"]["inputs"]["width"], graph["12"]["inputs"]["height"]), (2560, 1440))
        self.assertEqual(graph["12"]["inputs"]["crop"], "center")
        self.assertEqual(graph["30"]["inputs"]["fps"], ["2", 2])
        self.assertEqual(classes(graph), post_node_classes(options))
        self.assertEqual(post_model_files(options), [("upscale_models", "RealESRGAN_x2plus.pth")])

    def test_lanczos_graph_has_no_model_and_silent_source_stays_silent(self):
        options = plan_post_process({**SHOT, "audio": False}, "upscale", "lanczos", 1920)
        graph = post_process_workflow(options, "src.mp4", "p")
        self.assertNotIn("UpscaleModelLoader", classes(graph))
        self.assertNotIn("audio", graph["30"]["inputs"])
        self.assertEqual(post_model_files(options), [])

    def test_title_names_the_change(self):
        options = plan_post_process(SHOT, "upscale", "lanczos", 2560)
        self.assertTrue(post_title(options, "a bus at dawn").startswith("Lanczos upscale · 1632x928 -> 2560x1440"))

    def test_post_jobs_unload_the_diffusion_family(self):
        self.assertEqual(QueueWorker._engine_family({"engine": "post"}), "post")
        self.assertNotEqual(QueueWorker._engine_family({"engine": "turbo"}), "post")


class ApiBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-post-test-")
        self.root = Path(self.temp.name)
        self.original_db = db_module.DB_PATH
        db_module.DB_PATH = self.root / "jobs.sqlite3"
        self.projects, self.output, self.input = self.root / "projects", self.root / "output", self.root / "input"
        self.output.mkdir()
        self.input.mkdir()
        self.patches = [patch.object(library, "PROJECTS", self.projects), patch.object(library, "OUTPUT", self.output),
                        patch("backend.main.INPUT", self.input), patch.object(worker, "notify"),
                        patch("backend.main.probe_video", return_value=dict(SHOT))]
        for item in self.patches:
            item.start()
        db_module.init_db()
        library.init_library_db()
        self.client = TestClient(app)
        self.token = self.client.get("/api/session").json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        db_module.DB_PATH = self.original_db
        self.temp.cleanup()

    def add_job(self, job_id: str, status: str = "completed") -> Path:
        video = self.output / f"{job_id}.mp4"
        video.write_bytes(b"video")
        now = now_iso()
        with connect() as db:
            db.execute(
                """INSERT INTO jobs (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,megapixels,
                   aspect_ratio,seed,status,position,output_path,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, "A bus at dawn", "opening", 5, "turbo", "v4", "native", 6, 1632, 928, 1.51, "16:9", "42",
                 status, 1, str(video), now, now))
        return video

    def post(self, job_id: str, body: dict):
        return self.client.post(f"/api/jobs/{job_id}/post-process", json=body, headers={"X-CSRF-Token": self.token})


class PostProcessApiTests(ApiBase):
    def test_queues_a_post_job_filed_next_to_the_source(self):
        self.add_job("src")
        project = library.create_project("Missed Bus")
        folder = library.create_folder(project["id"], "Shots")
        library.assign_asset("job", "src", project["id"], folder["id"])
        response = self.post("src", {"operation": "upscale", "method": "gan", "long_side": 2560})
        self.assertEqual(response.status_code, 200, response.text)
        new_id = response.json()["created"][0]
        with connect() as db:
            row = dict(db.execute("SELECT * FROM jobs WHERE id=?", (new_id,)).fetchone())
            place = db.execute("SELECT project_id, folder_id FROM asset_assignments WHERE source_type='job' AND source_id=?",
                               (new_id,)).fetchone()
        self.assertEqual((row["engine"], row["mode"], row["workflow_variant"], row["steps"], row["width"], row["height"],
                          row["status"]), ("post", "upscale", "gan", 1, 2560, 1440, "queued"))
        self.assertEqual(json.loads(row["post_options_json"])["source_job_id"], "src")
        self.assertTrue((self.input / row["input_name"]).is_file())
        self.assertEqual(tuple(place), (project["id"], folder["id"]))
        public = self.client.get("/api/jobs").json()
        job = next(item for item in public["jobs"] if item["id"] == new_id)
        self.assertEqual(job["post_options"]["width"], 2560)
        self.assertEqual(job["aspect_ratio"], "16:9")

    def test_only_finished_jobs(self):
        self.add_job("busy", status="running")
        self.assertEqual(self.post("busy", {"operation": "interpolate", "method": "rife"}).status_code, 409)
        self.assertEqual(self.post("missing", {"operation": "interpolate", "method": "rife"}).status_code, 404)

    def test_untested_requests_are_refused_with_a_reason(self):
        self.add_job("src")
        response = self.post("src", {"operation": "upscale", "method": "seedvr2", "long_side": 2560})
        self.assertEqual(response.status_code, 400)
        with patch("backend.main.probe_video", return_value={**SHOT, "frames": 241}):
            response = self.post("src", {"operation": "interpolate", "method": "film"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("150 frames", response.json()["detail"])
        self.assertEqual(list(self.input.iterdir()), [])

    def test_csrf_is_required(self):
        self.add_job("src")
        response = self.client.post("/api/jobs/src/post-process", json={"operation": "interpolate", "method": "rife"})
        self.assertEqual(response.status_code, 403)


def make_clip(path: Path, width: int, height: int, fps: int, seconds: float, rotation: int | None = None):
    """A small real clip with sound; `rotation` adds a phone-style display rotation flag."""
    plain = path.with_name("plain_" + path.name)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", str(seconds), "-c:v", "libx264", "-pix_fmt",
                    "yuv420p", "-c:a", "aac", "-shortest", str(plain)], check=True)
    if rotation is None:
        plain.replace(path)
    else:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", str(rotation), "-i", str(plain),
                        "-c", "copy", str(path)], check=True)
        plain.unlink()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg")
class UploadTests(ApiBase):
    def setUp(self):
        super().setUp()
        self.real_probe = patch("backend.main.probe_video", side_effect=probe_video)
        self.real_probe.start()

    def tearDown(self):
        self.real_probe.stop()
        super().tearDown()

    def upload(self, path: Path, data: dict, content_type: str = "video/mp4"):
        with path.open("rb") as handle:
            return self.client.post("/api/post-process", data=data, headers={"X-CSRF-Token": self.token},
                                    files={"video": (path.name, handle, content_type)})

    def test_phone_rotation_is_applied_and_job_is_queued(self):
        clip = self.root / "phone.mov"
        make_clip(clip, 640, 360, 24, 2, rotation=90)
        response = self.upload(clip, {"operation": "upscale", "method": "lanczos", "long_side": "1920"}, "video/quicktime")
        self.assertEqual(response.status_code, 200, response.text)
        options = response.json()["options"]
        self.assertEqual((options["source_width"], options["source_height"]), (360, 640))
        self.assertEqual((options["width"], options["height"]), (1080, 1920))
        self.assertEqual(options["source_filename"], "phone.mov")
        with connect() as db:
            row = dict(db.execute("SELECT * FROM jobs WHERE id=?", (response.json()["created"][0],)).fetchone())
        self.assertEqual((row["engine"], row["aspect_ratio"], row["no_audio"]), ("post", "9:16", 0))
        self.assertTrue(row["prompt"].endswith("External video: phone.mov"))
        self.assertEqual([p.name for p in self.input.iterdir()], [row["input_name"]])   # the raw upload is gone

    def test_refused_upload_leaves_no_files(self):
        clip = self.root / "clip.mp4"
        make_clip(clip, 640, 360, 24, 2)
        response = self.upload(clip, {"operation": "upscale", "method": "seedvr2", "long_side": "2560"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(self.input.iterdir()), [])

    def test_wrong_type_is_refused(self):
        clip = self.root / "clip.gif"
        clip.write_bytes(b"GIF89a")
        self.assertEqual(self.upload(clip, {"operation": "upscale", "method": "lanczos"}, "image/gif").status_code, 400)

    def test_aspect_labels(self):
        self.assertEqual([aspect_label(*s) for s in ((1920, 1080), (1080, 1920), (1000, 1000), (1440, 1080))],
                         ["16:9", "9:16", "1:1", "4:3"])


class PostJobsTableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-post-db-")
        self.original_db = db_module.DB_PATH
        db_module.DB_PATH = Path(self.temp.name) / "jobs.sqlite3"

    def tearDown(self):
        db_module.DB_PATH = self.original_db
        self.temp.cleanup()

    def insert(self, engine: str, width: int, height: int, steps: int = 1):
        now = now_iso()
        with connect() as db:
            db.execute(
                """INSERT INTO jobs (id,prompt,mode,duration,engine,workflow_variant,turbo_profile,encoder,steps,width,height,
                   seed,status,position,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"{engine}-{width}x{height}-{steps}", "p", "upscale" if engine == "post" else "text", 5.04, engine,
                 "lanczos" if engine == "post" else "direct", "v1", "native", steps, width, height, "1", "queued", 1, now, now))

    def test_post_jobs_may_exceed_the_generation_size_but_generation_jobs_may_not(self):
        db_module.init_db()
        for size in ((2560, 1440), (1440, 2560), (1920, 1080), (1080, 2338)):
            self.insert("post", *size)
        for engine, width, height, steps in (("turbo", 2560, 1440, 6), ("post", 2560, 1440, 4), ("post", 4096, 4096, 1),
                                             ("post", 2567, 1440, 1)):
            with self.assertRaises(sqlite3.IntegrityError, msg=(engine, width, height, steps)):
                self.insert(engine, width, height, steps)

    def test_old_table_is_rebuilt_and_keeps_its_rows(self):
        db_module.init_db()
        self.insert("turbo", 1632, 928, 6)
        with connect() as db:   # simulate a database from before issue #37
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='jobs'").fetchone()[0]
            db.execute("ALTER TABLE jobs RENAME TO jobs_new_style")
            old = (sql.replace("width % 2 = 0 AND height % 2 = 0", "width % 16 = 0 AND height % 16 = 0")
                      .replace(",'post')", ")").replace("        post_options_json TEXT,\n", ""))
            self.assertNotIn("post_options_json", old)
            db.execute(old)
            columns = [r[1] for r in db.execute("PRAGMA table_info(jobs)")]
            db.execute(f"INSERT INTO jobs ({','.join(columns)}) SELECT {','.join(columns)} FROM jobs_new_style")
            db.execute("DROP TABLE jobs_new_style")
        db_module.init_db()
        with connect() as db:
            self.assertEqual(db.execute("SELECT id FROM jobs").fetchall()[0][0], "turbo-1632x928-6")
            self.assertIn("post_options_json", [r[1] for r in db.execute("PRAGMA table_info(jobs)")])
        self.insert("post", 1920, 1080)


if __name__ == "__main__":
    unittest.main()
