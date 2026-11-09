"""Upscale / interpolation jobs (issue #37): tested limits, graphs, the API and the jobs table."""
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import backend.db as db_module
import backend.library as library
from backend.db import connect, now_iso
from backend.main import app, worker
from backend.post_process import (aspect_label, crop_percent, plan_post_process, post_model_files, post_node_classes,
                                  post_process_workflow, post_title, probe_video, upscale_size, uses_visual_enhancer,
                                  visual_enhancer_command, visual_enhancer_finish_command, visual_enhancer_size)
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

    def test_models_only_on_tested_sizes_and_long_clips_in_chunks(self):
        big = {**SHOT, "width": 1920, "height": 1088}
        long = {**SHOT, "frames": 600, "duration": 25.0}      # 1632x928: one run holds 268 frames
        for method, operation in (("film", "interpolate"), ("gan", "upscale")):
            with self.assertRaises(ValueError):
                plan_post_process(big, operation, method, 2560)
            chunks = plan_post_process(long, operation, method, 2560)["chunks"]   # issue #44: chunked, not refused
            self.assertEqual(len(chunks), 3)
            self.assertLessEqual(max(c["count"] + c["borrow"] for c in chunks), 268)
        swap = {**SHOT, "width": 736, "height": 1280, "frames": 432}  # the whole-clip test: one run, no chunks
        for method, operation in (("rife", "interpolate"), ("film", "interpolate"), ("gan", "upscale"),
                                  ("lanczos", "upscale")):
            self.assertNotIn("chunks", plan_post_process(swap, operation, method, 2560), method)
        self.assertNotIn("chunks", plan_post_process(SHOT, "interpolate", "rife"))   # one run covers a 5 s shot


    def test_rife_and_fsr3_smooth_upscaled_clips(self):
        # issue #41: whole 2560x1440 shots were measured in the lab; FILM stays capped
        for size in ((2560, 1440), (1440, 2560), (2560, 1456)):
            upscaled = {**SHOT, "width": size[0], "height": size[1], "frames": 124}
            for method in ("rife", "fsr3"):
                options = plan_post_process(upscaled, "interpolate", method)
                self.assertEqual((options["width"], options["height"], options["fps"]), (*size, 48.0))
            with self.assertRaises(ValueError):
                plan_post_process(upscaled, "interpolate", "film")
        with self.assertRaises(ValueError):
            plan_post_process({**SHOT, "width": 2560, "height": 1472}, "interpolate", "rife")

    def test_chunks_join_to_the_same_frame_count_as_one_run(self):
        from backend.post_process import chunk_keep
        for method, operation, frames in (("rife", "interpolate", 900), ("film", "interpolate", 601),
                                          ("gan", "upscale", 700), ("lanczos", "upscale", 1200)):
            options = plan_post_process({**SHOT, "frames": frames}, operation, method, 2560)
            chunks = options["chunks"]
            self.assertEqual(sum(chunk_keep(options, c) for c in chunks), options["frames"], method)
            self.assertEqual(sum(c["count"] for c in chunks), frames)
            if operation == "interpolate":                       # every chunk but the last borrows the next frame
                self.assertEqual([c["borrow"] for c in chunks], [True] * (len(chunks) - 1) + [False])
            else:
                self.assertFalse(any(c["borrow"] for c in chunks))

    def test_joining_chunks_gives_one_run_s_frame_count_with_the_sound(self):
        import subprocess, tempfile
        from backend.post_process import chunk_join_command
        options = plan_post_process({**SHOT, "width": 1440, "height": 2560, "frames": 432, "duration": 18.0},
                                    "interpolate", "rife")
        self.assertEqual([c["count"] for c in options["chunks"]], [144, 144, 144])
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "source.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=64x112:r=24:d=18", "-f", "lavfi",
                            "-i", "sine=d=18", "-shortest", "-pix_fmt", "yuv420p", str(source)], check=True)
            parts = []
            for i, chunk in enumerate(options["chunks"]):     # what RIFE returns for each chunk: 2n-1 frames at 48 fps
                frames = 2 * (chunk["count"] + chunk["borrow"]) - 1
                parts.append(folder / f"c{i}.mp4")
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=s=64x112:r=48",
                                "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(parts[-1])], check=True)
            out = folder / "out.mp4"
            subprocess.run(chunk_join_command(options, parts, source, out), check=True)
            probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                    "stream=codec_type,nb_read_frames", "-of", "csv=p=0", str(out)],
                                   capture_output=True, text=True).stdout.split()
        self.assertIn("video,863", probe)                     # = one RIFE run over 432 frames
        self.assertTrue(any(line.startswith("audio") for line in probe))

    def test_chunk_cuts_keep_the_exact_frames_and_rate(self):
        import subprocess, tempfile
        from backend.post_process import chunk_cut_command
        options = plan_post_process({**SHOT, "width": 1440, "height": 2560, "frames": 432, "duration": 18.0},
                                    "interpolate", "rife")
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.mp4"            # sound first, as in the bridge's own outputs
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=18", "-f", "lavfi", "-i",
                            "testsrc=s=64x112:r=24:d=18", "-map", "0:a", "-map", "1:v", "-pix_fmt", "yuv420p",
                            "-video_track_timescale", "12288", str(source)], check=True)
            for chunk in options["chunks"]:
                out = Path(folder) / f"c{chunk['start']}.mp4"
                subprocess.run(chunk_cut_command(options, chunk, source, out), check=True)
                probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                        "stream=r_frame_rate,nb_read_frames", "-of", "csv=p=0", str(out)],
                                       capture_output=True, text=True).stdout.split()
                self.assertEqual(probe, [f"24/1,{chunk['count'] + chunk['borrow']}"])

    def test_visual_enhancer_is_never_chunked(self):
        land = {"width": 1280, "height": 720, "fps": 24.0, "frames": 432, "duration": 18.0, "audio": True}
        self.assertNotIn("chunks", plan_post_process(land, "upscale", "rtx", 2560))
        self.assertNotIn("chunks", plan_post_process(land, "interpolate", "fsr3"))

    def test_lanczos_runs_on_interpolated_clips_and_longer_ones_in_chunks(self):
        doubled = {**SHOT, "fps": 48.0, "frames": 241}
        self.assertEqual(plan_post_process(doubled, "upscale", "lanczos", 2560)["frames"], 241)
        self.assertEqual(len(plan_post_process({**SHOT, "frames": 301}, "upscale", "lanczos", 2560)["chunks"]), 2)  # 268 per run
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
        self.assertNotIn("chunks", plan_post_process({**phone, "frames": 151}, "interpolate", "rife"))  # 1080p: 196 per run
        self.assertEqual(len(plan_post_process({**phone, "frames": 400}, "interpolate", "rife")["chunks"]), 3)

    def test_gan_runs_on_a_smoothed_shot_up_to_1_5mp(self):
        smoothed = {**SHOT, "fps": 48.0, "frames": 247}
        self.assertEqual(plan_post_process(smoothed, "upscale", "gan", 2560)["frames"], 247)
        portrait = {**smoothed, "width": 928, "height": 1632}
        self.assertEqual(plan_post_process(portrait, "upscale", "gan", 2560)["height"], 2560)
        self.assertIn("chunks", plan_post_process({**smoothed, "width": 1920, "height": 1080}, "upscale", "gan", 2560))
        self.assertNotIn("chunks", plan_post_process({**smoothed, "frames": 249}, "upscale", "gan", 2560))

    def test_interpolating_a_48fps_clip_is_refused(self):
        with self.assertRaises(ValueError):
            plan_post_process({**SHOT, "fps": 48.0}, "interpolate", "rife")

    def test_upscale_targets_are_fixed_and_must_grow(self):
        for long_side in (None, 1280, 3840):
            with self.assertRaises(ValueError):
                plan_post_process(SHOT, "upscale", "lanczos", long_side)
        with self.assertRaises(ValueError):
            plan_post_process({**SHOT, "width": 1920, "height": 1088}, "upscale", "lanczos", 1920)


class VisualEnhancerPlanTests(unittest.TestCase):
    """RTX VSR and FSR 3 (issue #39): the lab-tested sources were 1632x928 24 fps and 1920x1080 30 fps, 5 s."""
    LAND = {"width": 1920, "height": 1080, "fps": 30.0, "frames": 150, "duration": 5.0, "audio": True}

    def test_rtx_upscales_to_the_standard_sizes(self):
        options = plan_post_process(SHOT, "upscale", "rtx", 2560)
        self.assertEqual((options["width"], options["height"], options["frames"]), (2560, 1440, 121))
        self.assertTrue(uses_visual_enhancer(options))
        self.assertEqual(plan_post_process(self.LAND, "upscale", "rtx", 2560)["width"], 2560)
        self.assertEqual(plan_post_process(SHOT, "upscale", "rtx", 1920)["height"], 1080)
        self.assertFalse(uses_visual_enhancer(plan_post_process(SHOT, "upscale", "gan", 2560)))

    def test_fsr3_doubles_fps_and_adds_a_frame_after_the_last(self):
        options = plan_post_process(SHOT, "interpolate", "fsr3")
        self.assertEqual((options["fps"], options["frames"]), (48.0, 242))
        land = plan_post_process(self.LAND, "interpolate", "fsr3")
        self.assertEqual((land["width"], land["fps"], land["frames"]), (1920, 60.0, 300))

    def test_only_the_tested_sources(self):
        for method, operation, too_big in (("rtx", "upscale", {**self.LAND, "height": 1088}),
                                           ("fsr3", "interpolate", {**self.LAND, "width": 2560, "height": 1488})):
            for source in (too_big, {**SHOT, "fps": 48.0, "frames": 247}):
                with self.assertRaises(ValueError, msg=(method, source)):
                    plan_post_process(source, operation, method, 2560)
            plan_post_process({**self.LAND, "frames": 432}, operation, method, 2560)   # long clips: one VE run

    def test_rtx_renders_at_the_source_shape_then_crops(self):
        # VE stretches to --size, so it gets the source's own shape; the finishing pass crops to the target
        for source, long_side, render in (((1632, 928), 2560, (2560, 1456)), ((1632, 928), 1920, (1920, 1092)),
                                          ((928, 1632), 2560, (1456, 2560)), ((1920, 1080), 2560, (2560, 1440)),
                                          ((768, 1024), 1920, (1440, 1920))):
            options = plan_post_process({**SHOT, "width": source[0], "height": source[1]}, "upscale", "rtx", long_side)
            self.assertEqual(visual_enhancer_size(options), render, source)
            self.assertGreaterEqual(render[0], options["width"])
            self.assertGreaterEqual(render[1], options["height"])

    def test_commands_use_the_lab_engines(self):
        cli, src, out = Path("C:/VE/VE_CLI.exe"), Path("in.mp4"), Path("out.mp4")
        rtx = visual_enhancer_command(cli, plan_post_process(SHOT, "upscale", "rtx", 2560), src, out)
        self.assertEqual(rtx[:7], [str(cli), "upscale", "in.mp4", "--engine", "rtx", "--size", "2560x1456"])
        fsr3 = visual_enhancer_command(cli, plan_post_process(SHOT, "interpolate", "fsr3"), src, out)
        self.assertEqual(fsr3[1:7], ["interpolate", "in.mp4", "--interpolator", "fsr3", "--multiplier", "2"])
        for command in (rtx, fsr3):
            self.assertEqual(command[command.index("-o") + 1], "out.mp4")
            self.assertIn("--json", command)
        with self.assertRaises(ValueError):
            visual_enhancer_command(cli, plan_post_process(SHOT, "upscale", "gan", 2560), src, out)

    def test_finish_crops_and_keeps_the_source_sound(self):
        options = plan_post_process(SHOT, "upscale", "rtx", 2560)
        command = visual_enhancer_finish_command(options, Path("r.mp4"), Path("s.mp4"), Path("o.mp4"))
        self.assertIn("crop=2560:1440:(iw-2560)/2:(ih-1440)/2,setsar=1", command)
        self.assertEqual(command[command.index("-crf") + 1], "12")
        self.assertIn("1:a:0", command)
        self.assertEqual(command[command.index("-c:a") + 1], "copy")
        silent = visual_enhancer_finish_command({**options, "audio": False}, Path("r.mp4"), Path("s.mp4"),
                                                Path("o.mp4"))
        self.assertNotIn("s.mp4", silent)
        self.assertNotIn("-c:a", silent)


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
        with patch("backend.main.probe_video", return_value={**SHOT, "width": 1920, "height": 1080}):
            response = self.post("src", {"operation": "interpolate", "method": "film"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("use RIFE", response.json()["detail"])
        self.assertEqual(list(self.input.iterdir()), [])

    def test_visual_enhancer_methods_need_the_users_cli(self):
        self.add_job("src")
        with patch("backend.main.visual_enhancer_ready", return_value=False):
            response = self.post("src", {"operation": "upscale", "method": "rtx", "long_side": 2560})
            self.assertEqual(response.status_code, 400)
            self.assertIn("visual_enhancer_cli", response.json()["detail"])
            self.assertEqual(self.post("src", {"operation": "interpolate", "method": "fsr3"}).status_code, 400)
            self.assertEqual(self.post("src", {"operation": "interpolate", "method": "rife"}).status_code, 200)
            self.assertFalse(self.client.get("/api/health").json()["visual_enhancer_ready"])
        with patch("backend.main.visual_enhancer_ready", return_value=True):
            response = self.post("src", {"operation": "upscale", "method": "rtx", "long_side": 2560})
        self.assertEqual(response.status_code, 200, response.text)
        with connect() as db:
            row = db.execute("SELECT workflow_variant, width, height FROM jobs WHERE id=?",
                             (response.json()["created"][0],)).fetchone()
        self.assertEqual(tuple(row), ("rtx", 2560, 1440))

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


FAKE_VE_CLI = r"""
import json, os, subprocess, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_VE_MODE", "ok")
if mode == "hang":
    time.sleep(120)
if mode == "fail":
    print(json.dumps({"exit_code": 1, "items": [{"state": "failed", "error": "NGX feature unavailable"}]}))
    sys.exit(1)
src, out = args[1], args[args.index("-o") + 1]
if args[0] == "upscale":
    width, height = args[args.index("--size") + 1].split("x")
    video = ["-vf", f"scale={width}:{height}"]
else:
    video = ["-vf", "fps=48"]
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, *video, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "64k", out], check=True)
print(json.dumps({"exit_code": 0, "items": [{"state": "completed", "output_path": out, "error": ""}]}))
"""


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg")
class VisualEnhancerWorkerTests(unittest.TestCase):
    """The worker runs VE_CLI itself (a stand-in script here), finishes with FFmpeg and verifies the result."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-ve-worker-")
        self.root = Path(self.temp.name)
        self.original_db = db_module.DB_PATH
        db_module.DB_PATH = self.root / "jobs.sqlite3"
        self.input, self.output, self.work = self.root / "input", self.root / "output", self.root / "temp"
        for folder in (self.input, self.output, self.work):
            folder.mkdir()
        self.fake = self.root / "fake_ve.py"
        self.fake.write_text(FAKE_VE_CLI, encoding="utf-8")
        self.worker = QueueWorker()
        self.worker.comfy.ready = AsyncMock(return_value=False)
        self.patches = [
            patch("backend.worker.INPUT", self.input), patch("backend.worker.OUTPUT", self.output),
            patch("backend.worker.TEMP", self.work), patch("backend.worker.visual_enhancer_ready", return_value=True),
            patch("backend.worker.VISUAL_ENHANCER_CLI", self.fake),
            patch("backend.worker.visual_enhancer_command",
                  side_effect=lambda cli, options, src, out: [sys.executable, str(cli), *visual_enhancer_command(
                      cli, options, src, out)[1:]]),
            patch("backend.worker.gpu_sample", return_value={"vram_used_mib": 1500}),
            patch("backend.worker.finalize_completed_asset", return_value=None),
            patch("backend.worker.historical_generation_seconds", return_value=None),
        ]
        for item in self.patches:
            item.start()
        db_module.init_db()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        db_module.DB_PATH = self.original_db
        self.temp.cleanup()

    def queue(self, operation: str, method: str, long_side: int | None = None) -> dict:
        clip = self.input / "post_x_source.mp4"
        make_clip(clip, 480, 272, 24, 1)
        options = plan_post_process(probe_video(clip), operation, method, long_side)
        now = now_iso()
        with connect() as db:
            db.execute(
                """INSERT INTO jobs (id,prompt,mode,duration,engine,workflow_variant,turbo_profile,encoder,steps,width,
                   height,seed,status,position,input_path,input_name,no_audio,post_options_json,created_at,updated_at)
                   VALUES(?,?,?,?,'post',?,'v1','native',1,?,?,'1','running',1,?,?,0,?,?,?)""",
                ("vejob", "p", operation, 1.0, method, options["width"], options["height"], str(clip), clip.name,
                 json.dumps(options), now, now))
        return db_module.get_job("vejob", public=False)

    def run_job(self, job: dict):
        asyncio.run(self.worker._execute_job(job))
        return db_module.get_job("vejob", public=False)

    def test_rtx_upscale_is_cropped_verified_and_keeps_the_source_sound(self):
        job = self.run_job(self.queue("upscale", "rtx", 1920))
        self.assertEqual(job["status"], "completed", job["error"])
        output = Path(job["output_path"])
        self.assertEqual(output.name, "h3_bridge_vejob_00001_.mp4")
        probe = probe_video(output)
        self.assertEqual((probe["width"], probe["height"], probe["audio"]), (1920, 1080, True))
        audio = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=bit_rate",
                                "-of", "csv=p=0", str(output)], capture_output=True, text=True).stdout.strip()
        self.assertGreater(int(audio), 64000)   # the source's track, not the stand-in's 64 kb/s re-encode
        metrics = json.loads(job["metrics_json"])
        self.assertEqual(metrics["peak_gpu"]["vram_used_mib"], 1500)
        runtime = json.loads(job["runtime_json"])
        self.assertIn("--size", runtime["visual_enhancer"]["arguments"])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_fsr3_doubles_the_frame_rate(self):
        job = self.run_job(self.queue("interpolate", "fsr3"))
        self.assertEqual(job["status"], "completed", job["error"])
        self.assertEqual(probe_video(Path(job["output_path"]))["fps"], 48.0)

    def test_a_failed_run_reports_visual_enhancers_reason(self):
        with patch.dict(os.environ, {"FAKE_VE_MODE": "fail"}):
            job = self.run_job(self.queue("upscale", "rtx", 1920))
        self.assertEqual(job["status"], "failed")
        self.assertIn("NGX feature unavailable", job["error"])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_cancel_stops_the_process(self):
        job = self.queue("upscale", "rtx", 1920)

        async def cancel_soon():
            await asyncio.sleep(2)
            self.worker.cancelled.add("vejob")

        async def scenario():
            await asyncio.gather(self.worker._execute_job(job), cancel_soon())

        with patch.dict(os.environ, {"FAKE_VE_MODE": "hang"}):
            asyncio.run(asyncio.wait_for(scenario(), timeout=60))
        self.assertEqual(db_module.get_job("vejob", public=False)["status"], "canceled")

    def test_a_missing_cli_fails_clearly(self):
        with patch("backend.worker.visual_enhancer_ready", return_value=False):
            job = self.run_job(self.queue("interpolate", "fsr3"))
        self.assertEqual(job["status"], "failed")
        self.assertIn("visual_enhancer_cli", job["error"])


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

    def test_a_table_from_before_issue_39_accepts_the_visual_enhancer_methods(self):
        db_module.init_db()
        self.insert("turbo", 1632, 928, 6)
        with connect() as db:
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='jobs'").fetchone()[0]
            db.execute("ALTER TABLE jobs RENAME TO jobs_new_style")
            db.execute(sql.replace(",'rtx','fsr3'", ""))
            columns = [r[1] for r in db.execute("PRAGMA table_info(jobs)")]
            db.execute(f"INSERT INTO jobs ({','.join(columns)}) SELECT {','.join(columns)} FROM jobs_new_style")
            db.execute("DROP TABLE jobs_new_style")
        db_module.init_db()
        now = now_iso()
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
            for method in ("rtx", "fsr3"):
                db.execute(
                    """INSERT INTO jobs (id,prompt,mode,duration,engine,workflow_variant,turbo_profile,encoder,steps,
                       width,height,seed,status,position,created_at,updated_at)
                       VALUES(?,?,?,?,'post',?,'v1','native',1,2560,1440,'1','queued',1,?,?)""",
                    (method, "p", "upscale", 5.0, method, now, now))


if __name__ == "__main__":
    unittest.main()
