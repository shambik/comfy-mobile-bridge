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

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg")
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

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg")
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


# --- RTX VSR + H3 detail (issue #50) -----------------------------------------------------------------------------
from backend.post_process import (H3_DETAIL, H3_DETAIL_LEVELS, h3_detail_chain, h3_detail_frames,  # noqa: E402
                                  h3_detail_input_command, h3_detail_workflow, plan_h3_detail, post_required_files)

RTX_1920 = {"width": 1920, "height": 1080, "fps": 24.0, "frames": 124, "duration": 5.167, "audio": True}
PIKA_OPENING = {"id": "orig", "engine": "pika", "workflow_variant": "direct", "mode": "opening",
                "prompt": "r34l1sm\n\nA courier jumps a gap between rooftops."}
SKIN_PIKA = json.dumps({"model": "base", "speed_lora": "pika", "flow": "pika"})


class H3DetailPlanTests(unittest.TestCase):
    def test_only_the_tested_sources(self):
        cases = [
            (PIKA_OPENING, "pika"),
            ({"engine": "singularity", "mode": "opening", "skin_options_json": SKIN_PIKA}, "pika"),
            ({"engine": "turbo", "turbo_profile": "v4", "mode": "lip_sync"}, "turbo_v4"),
            ({"engine": "pika", "workflow_variant": "turbo4", "mode": "opening"}, None),        # Pika Turbo 4-step
            ({"engine": "pika", "workflow_variant": "direct", "mode": "reference"}, None),
            ({"engine": "singularity", "mode": "opening",
              "skin_options_json": json.dumps({"model": "pruned", "speed_lora": "tier"})}, None),
            ({"engine": "turbo", "turbo_profile": "v4", "mode": "opening"}, None),
            ({"engine": "turbo", "turbo_profile": "v1", "mode": "lip_sync"}, None),
            ({"engine": "ltx", "mode": "opening"}, None),
        ]
        for source, chain in cases:
            self.assertEqual(h3_detail_chain(source)[0], chain, source)
        self.assertIn("tested", h3_detail_chain({"engine": "ltx", "mode": "opening"})[1])

    def test_frames_snap_down_to_17n_plus_5(self):
        for frames, keep in ((124, 124), (362, 362), (360, 345), (117, 107), (243, 243), (4, 0)):
            self.assertEqual(h3_detail_frames(frames), keep)

    def test_plan_keeps_the_tested_limits(self):
        options = plan_h3_detail({**RTX_1920, "frames": 360, "duration": 15.0}, PIKA_OPENING, "s45")
        self.assertEqual((options["method"], options["chain"], options["frames"], options["trimmed_frames"],
                          options["sigmas"], options["width"], options["height"]),
                         (H3_DETAIL, "pika", 345, 15, "0.45, 0.2, 0.0", 1920, 1080))
        self.assertEqual(options["original_job_id"], "orig")
        portrait = plan_h3_detail({**RTX_1920, "width": 1080, "height": 1920, "frames": 117},
                                  {"id": "o", "engine": "turbo", "turbo_profile": "v4", "mode": "lip_sync"}, "s75x3")
        self.assertEqual((portrait["frames"], portrait["chain"], portrait["sigmas"]),
                         (107, "turbo_v4", "0.75, 0.5, 0.25, 0.0"))
        refused = [
            ({**RTX_1920}, PIKA_OPENING, "s90"),                                     # untested strength
            ({**RTX_1920, "width": 2560, "height": 1440}, PIKA_OPENING, "s45"),      # 2560 needs tiles: not tested
            ({**RTX_1920, "fps": 48.0}, PIKA_OPENING, "s45"),                        # smoothed clip
            ({**RTX_1920, "frames": 100}, PIKA_OPENING, "s45"),                      # shorter than tested
            ({**RTX_1920, "frames": 400}, PIKA_OPENING, "s45"),                      # longer than The Last Fold
            ({**RTX_1920}, {"id": "x", "engine": "ltx", "mode": "opening"}, "s45"),  # untested engine
        ]
        for rtx, original, level in refused:
            with self.assertRaises(ValueError):
                plan_h3_detail(rtx, original, level)
        self.assertEqual(set(H3_DETAIL_LEVELS), {"s30", "s45", "s60", "s60x3", "s75x3"})

    def test_input_is_trimmed_with_its_sound(self):
        options = plan_h3_detail({**RTX_1920, "frames": 360}, PIKA_OPENING, "s30")
        command = h3_detail_input_command(options, Path("in.mp4"), Path("out.mp4"))
        self.assertEqual(command[command.index("-frames:v") + 1], "345")
        self.assertEqual(command[command.index("-t") + 1], f"{345 / 24:.6f}")
        self.assertIn("aac", command)


class H3DetailWorkflowTests(unittest.TestCase):
    def test_pika_graph_is_the_lab_graph(self):
        options = plan_h3_detail(dict(RTX_1920), PIKA_OPENING, "s60x3")
        g = h3_detail_workflow(options, "post_x_source.mp4", "h3_bridge_x", seed=2 ** 60 + 7)
        by_class = {node["class_type"]: node["inputs"] for node in g.values()}
        self.assertEqual((by_class["MiniMaxH3ImageToVideo"]["width"], by_class["MiniMaxH3ImageToVideo"]["height"],
                          by_class["MiniMaxH3ImageToVideo"]["length"]), (1920, 1088, 124))
        self.assertEqual(by_class["MiniMaxH3ImageToVideo"]["prompt"], "A courier jumps a gap between rooftops.")
        self.assertEqual(by_class["LoraLoaderModelOnly"]["lora_name"], "pika_h3_flex_fl2va_comfy_bf16.safetensors")
        self.assertNotIn("MiniMaxH3TurboLoRA", by_class)
        self.assertEqual(by_class["ModelAttentionBackend"]["attention"], "comfy kitchen attention")
        self.assertEqual(by_class["ManualSigmas"]["sigmas"], "0.6, 0.4, 0.2, 0.0")
        self.assertEqual(by_class["KSamplerSelect"]["sampler_name"], "er_sde")
        self.assertEqual((by_class["MMH3TemporalSplitParams"]["chunk_length"],
                          by_class["MMH3TemporalSplitParams"]["temporal_overlap"]), (68, 17))
        self.assertEqual(by_class["RandomNoise"]["noise_seed"], (2 ** 60 + 7) % 2 ** 50)
        self.assertEqual((by_class["ImageScale"]["width"], by_class["ImageScale"]["height"]), (1920, 1080))  # back
        self.assertEqual(by_class["CreateVideo"]["audio"], ["2", 1])
        self.assertEqual(by_class["SaveVideo"]["filename_prefix"], "h3_bridge_x")
        self.assertEqual(by_class["SaveVideo"]["format.codec.encoding.crf"], 12.0)
        self.assertEqual(classes(g), post_node_classes(options))

    def test_turbo_graph_uses_the_v4_lora(self):
        options = plan_h3_detail({**RTX_1920, "width": 1080, "height": 1920, "frames": 107},
                                 {"id": "o", "engine": "turbo", "turbo_profile": "v4", "mode": "lip_sync",
                                  "prompt": "He sings."}, "s45")
        g = h3_detail_workflow(options, "v.mp4", "p", seed=1)
        by_class = {node["class_type"]: node["inputs"] for node in g.values()}
        self.assertEqual(by_class["MiniMaxH3TurboLoRA"]["lora_name"], "minimax_h3_turbo_v4_step600_ema.safetensors")
        self.assertEqual((by_class["MiniMaxH3ImageToVideo"]["width"], by_class["MiniMaxH3ImageToVideo"]["height"]),
                         (1088, 1920))
        files = [path.name for path in post_required_files(options)]
        self.assertIn("minimax_h3_turbo_v4_step600_ema.safetensors", files)
        self.assertIn("minimax_h3_fl2va_pruned_int8_convrot.safetensors", files)


class H3DetailApiTests(ApiBase):
    def add_rtx(self, rtx_id: str, original_id: str | None, long_side: int = 1920, method: str = "rtx") -> Path:
        video = self.output / f"{rtx_id}.mp4"
        video.write_bytes(b"video")
        now = now_iso()
        options = {"operation": "upscale", "method": method, "long_side": long_side, "source_job_id": original_id}
        with connect() as db:
            db.execute(
                """INSERT INTO jobs (id,prompt,mode,duration,engine,workflow_variant,turbo_profile,encoder,steps,width,
                   height,megapixels,aspect_ratio,seed,status,position,output_path,post_options_json,created_at,updated_at)
                   VALUES(?,?,?,?,'post',?,'v1','native',1,1920,1080,2.07,'16:9','7','completed',2,?,?,?,?)""",
                (rtx_id, "RTX VSR upscale", "upscale", 15, method, str(video), json.dumps(options), now, now))
        return video

    def add_original(self, job_id: str, engine: str = "pika", mode: str = "opening"):
        self.add_job(job_id)
        with connect() as db:
            db.execute("UPDATE jobs SET engine=?, mode=?, workflow_variant='direct', steps=?, prompt=? WHERE id=?",
                       (engine, mode, 8 if engine == "ltx" else 6, "A laundromat, two friends fold clothes.", job_id))

    def fake_ffmpeg(self, command, **_):
        Path(command[-1]).write_bytes(b"trimmed")
        return subprocess.CompletedProcess(command, 0, "", "")

    def test_queues_from_an_rtx_card_with_the_original_prompt(self):
        self.add_original("orig")
        self.add_rtx("rtx", "orig")
        with patch("backend.main.probe_video", return_value={**RTX_1920, "frames": 360, "duration": 15.0}), \
                patch("backend.main.subprocess.run", side_effect=self.fake_ffmpeg):
            response = self.post("rtx", {"operation": "upscale", "method": "h3detail", "detail": "s45"})
        self.assertEqual(response.status_code, 200, response.text)
        with connect() as db:
            row = dict(db.execute("SELECT * FROM jobs WHERE id=?", (response.json()["created"][0],)).fetchone())
        options = json.loads(row["post_options_json"])
        self.assertEqual((row["engine"], row["workflow_variant"], row["width"], row["height"]),
                         ("post", "h3detail", 1920, 1080))
        self.assertEqual((options["frames"], options["trimmed_frames"], options["source_job_id"],
                          options["original_job_id"], options["chain"]), (345, 15, "rtx", "orig", "pika"))
        self.assertEqual(options["prompt"], "A laundromat, two friends fold clothes.")
        self.assertTrue((self.input / row["input_name"]).is_file())

    def test_refusals_say_why(self):
        self.add_original("orig")
        self.add_original("ltx_orig", engine="ltx")
        self.add_rtx("rtx2560", "orig", long_side=2560)
        self.add_rtx("gan", "orig", method="gan")
        self.add_rtx("rtx_ltx", "ltx_orig")
        self.add_rtx("rtx_gone", "deleted")
        body = {"operation": "upscale", "method": "h3detail", "detail": "s45"}
        with patch("backend.main.probe_video", return_value=dict(RTX_1920)):
            self.assertEqual(self.post("orig", body).status_code, 400)       # not an RTX VSR clip
            self.assertEqual(self.post("rtx2560", body).status_code, 400)
            self.assertEqual(self.post("gan", body).status_code, 400)
            response = self.post("rtx_ltx", body)
            self.assertEqual(response.status_code, 400)
            self.assertIn("tested", response.json()["detail"])
            self.assertEqual(self.post("rtx_gone", body).status_code, 409)
        self.add_rtx("rtx", "orig")
        with patch("backend.main.probe_video", return_value=dict(RTX_1920)):
            self.assertEqual(self.post("rtx", {**body, "detail": None}).status_code, 400)
        self.assertEqual(list(self.input.iterdir()), [])


# --- RIFE 60 / 120 fps (issue #52) -------------------------------------------------------------------------------
from backend.post_process import decimate_command  # noqa: E402

SHOT_24 = {"width": 1632, "height": 928, "fps": 24.0, "frames": 124, "duration": 5.167, "audio": True}


class RifeHighFpsTests(unittest.TestCase):
    def test_plan_matches_the_lab_runs(self):
        for target, keep_every, frames in ((120, 1, 616), (60, 2, 308)):
            options = plan_post_process(SHOT_24, "interpolate", "rife", None, target)
            self.assertEqual((options["fps"], options["multiplier"], options["keep_every"], options["frames"],
                              options["graph_fps"], options["width"], options["height"]),
                             (float(target), 5, keep_every, frames, 120.0, 1632, 928))
        self.assertNotIn("chunks", options)

    def test_untested_requests_are_refused_with_a_reason(self):
        refused = [
            ({**SHOT_24, "fps": 30.0}, "interpolate", "rife", 60, "24 fps"),
            ({**SHOT_24, "frames": 145}, "interpolate", "rife", 120, "124 frames"),
            ({**SHOT_24, "width": 1920, "height": 1080}, "interpolate", "rife", 60, "1632x928"),
            (SHOT_24, "interpolate", "film", 60, "RIFE"),
            (SHOT_24, "upscale", "rife", 60, "Upscale supports"),   # the existing method check refuses first
            (SHOT_24, "interpolate", "rife", 90, "60 or 120"),
        ]
        for source, operation, method, target, text in refused:
            with self.assertRaises(ValueError) as caught:
                plan_post_process(source, operation, method, 1920 if operation == "upscale" else None, target)
            self.assertIn(text, str(caught.exception))
        self.assertEqual(plan_post_process(SHOT_24, "interpolate", "rife")["frames"], 247)   # the 48 fps choice is unchanged

    def test_graph_runs_x5_at_120_fps_and_the_title_says_so(self):
        options = plan_post_process(SHOT_24, "interpolate", "rife", None, 60)
        g = post_process_workflow(options, "v.mp4", "p")
        by_class = {node["class_type"]: node["inputs"] for node in g.values()}
        self.assertEqual(by_class["FrameInterpolate"]["multiplier"], 5)
        self.assertEqual(by_class["CreateVideo"]["fps"], 120.0)
        self.assertIn("x5", post_title(options, "A bus"))
        plain = plan_post_process(SHOT_24, "interpolate", "rife")
        self.assertEqual(post_process_workflow(plain, "v.mp4", "p")["11"]["inputs"]["multiplier"], 2)

    def test_60_fps_decimation_command(self):
        options = plan_post_process(SHOT_24, "interpolate", "rife", None, 60)
        command = decimate_command(options, Path("in.mp4"), Path("out.mp4"))
        self.assertIn("select='not(mod(n,2))',setpts=N/(60*TB)", command)
        self.assertEqual(command[command.index("-r") + 1], "60")
        self.assertEqual(command[command.index("-c:a") + 1], "copy")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg")
    def test_decimation_keeps_every_second_frame(self):
        with tempfile.TemporaryDirectory(prefix="h3-decimate-") as temp:
            source, out = Path(temp) / "x5.mp4", Path(temp) / "x2.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=120",
                            "-f", "lavfi", "-i", "sine=frequency=440", "-frames:v", "61", "-t", "0.508", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
            options = plan_post_process(SHOT_24, "interpolate", "rife", None, 60)
            subprocess.run(decimate_command(options, source, out), check=True)
            probe = probe_video(out)
            self.assertEqual((probe["frames"], round(probe["fps"], 3), probe["audio"]), (31, 60.0, True))


class RifeHighFpsApiTests(ApiBase):
    def test_card_request_carries_the_rate(self):
        self.add_job("src")
        with patch("backend.main.probe_video", return_value=dict(SHOT_24)):
            response = self.post("src", {"operation": "interpolate", "method": "rife", "fps_target": 120})
            self.assertEqual(response.status_code, 200, response.text)
            refused = self.post("src", {"operation": "interpolate", "method": "film", "fps_target": 60})
        self.assertEqual(refused.status_code, 400)
        with connect() as db:
            row = db.execute("SELECT workflow_variant, width, height, post_options_json FROM jobs WHERE id=?",
                             (response.json()["created"][0],)).fetchone()
        options = json.loads(row["post_options_json"])
        self.assertEqual((row["workflow_variant"], options["fps"], options["frames"], options["keep_every"]),
                         ("rife", 120.0, 616, 1))


class H3DetailMigrationTests(unittest.TestCase):
    def test_existing_job_tables_take_the_new_variant_and_keep_every_row(self):
        temp = tempfile.TemporaryDirectory(prefix="h3-detail-db-")
        self.addCleanup(temp.cleanup)
        original = db_module.DB_PATH
        self.addCleanup(setattr, db_module, "DB_PATH", original)
        db_module.DB_PATH = Path(temp.name) / "old.sqlite3"
        source = Path(db_module.__file__).read_text(encoding="utf-8")
        start = source.index("    CREATE TABLE jobs (")
        sql = source[start:source.index("    CREATE INDEX idx_jobs_queue", start)].replace(",'h3detail','h3edit'", "")
        old = sqlite3.connect(db_module.DB_PATH)
        old.executescript(sql)
        now = now_iso()
        old.execute("""INSERT INTO jobs (id,prompt,mode,duration,engine,workflow_variant,turbo_profile,encoder,steps,width,
                       height,seed,status,position,created_at,updated_at) VALUES('keep','RTX','upscale',5,'post','rtx',
                       'v1','native',1,1920,1080,'1','completed',1,?,?)""", (now, now))
        old.commit()
        old.close()
        db_module.init_db()
        with connect() as db:
            self.assertEqual(db.execute("SELECT workflow_variant FROM jobs WHERE id='keep'").fetchone()[0], "rtx")
            db.execute("""INSERT INTO jobs (id,prompt,mode,duration,engine,workflow_variant,turbo_profile,encoder,steps,
                          width,height,seed,status,position,created_at,updated_at) VALUES('d','Detail','upscale',5,'post',
                          'h3detail','v1','native',1,1920,1080,'1','queued',2,?,?)""", (now, now))


# ---------------------------------------------------------------- H3 video edit (issue #54)
from backend.video_edit import (EDIT_TASKS, H3_EDIT, build_edit_prompt, edit_input_command,  # noqa: E402
                                edit_required_files, edit_workflow, plan_edit)

TALK = {"width": 720, "height": 1280, "fps": 24.0, "frames": 240, "duration": 10.0, "audio": True}


class VideoEditPlanTests(unittest.TestCase):
    def test_default_is_480_portrait_5_s(self):
        options = plan_edit(TALK, "vfx", None, None, "Change his shirt into a flannel shirt, while preserving his face.",
                            "", "", 0)
        self.assertEqual((options["method"], options["operation"], options["width"], options["height"],
                          options["frames"], options["fps"]), (H3_EDIT, "edit", 480, 864, 124, 24))
        self.assertTrue(options["prompt"].startswith("vfx_edit: Change his shirt"))
        self.assertEqual(options["output_duration"], round(124 / 24, 3))

    def test_landscape_sources_get_turned_sizes(self):
        wide = {**TALK, "width": 1632, "height": 928}
        options = plan_edit(wide, "style", "704", 5, "", "anime", "", 0)
        self.assertEqual((options["width"], options["height"]), (1280, 704))

    def test_tested_limits(self):
        with self.assertRaisesRegex(ValueError, "480x864 only"):
            plan_edit(TALK, "outfit", "704", 5, "Put the jacket from @1 on him", "", "", 1)
        with self.assertRaisesRegex(ValueError, "10 seconds runs at 480"):
            plan_edit(TALK, "vfx", "704", 10, "Change the shirt", "", "", 0)
        with self.assertRaisesRegex(ValueError, "size"):
            plan_edit(TALK, "vfx", "576", 5, "Change the shirt", "", "", 0)
        with self.assertRaisesRegex(ValueError, "5 or 10"):
            plan_edit(TALK, "vfx", "480", 7, "Change the shirt", "", "", 0)
        with self.assertRaisesRegex(ValueError, "photo"):
            plan_edit(TALK, "head", "480", 5, "", "", "Male, short hair", 0)
        with self.assertRaisesRegex(ValueError, "needs at least"):
            plan_edit({**TALK, "duration": 4.0, "frames": 96}, "vfx", "480", 5, "Change the shirt", "", "", 0)
        options = plan_edit(TALK, "vfx", "480", 10, "Change the shirt", "", "", 0)
        self.assertEqual((options["frames"], options["pad_frames"]), (243, 3))   # the 240-frame clip holds 3 frames

    def test_prompts(self):
        self.assertEqual(build_edit_prompt("style", "", "anime", "", 0), "style_transfer: Transform this video into "
                         "a 2D anime style with clean black line art, flat cel shading, soft gradients and vibrant colours.")
        self.assertEqual(build_edit_prompt("vfx", "vfx_edit: Add glasses", "", "", 0), "vfx_edit: Add glasses")
        outfit = build_edit_prompt("outfit", "Put the jacket from @1 and the cap from @2 on him", "", "", 2)
        self.assertEqual(outfit, "vfx_edit: Put the jacket from <Picture 1> and the cap from <Picture 2> on him")
        with self.assertRaisesRegex(ValueError, "not attached"):
            build_edit_prompt("outfit", "Put the cap from @2 on him", "", "", 1)
        with self.assertRaisesRegex(ValueError, "@1"):
            build_edit_prompt("outfit", "Put the cap on him", "", "", 1)
        head = build_edit_prompt("head", "", "", "Male, oval face, blond hair", 1)
        self.assertTrue(head.startswith("head_swap:"))
        self.assertIn("Facial details of <Subject 1>:\nMale, oval face, blond hair\n", head)
        with self.assertRaisesRegex(ValueError, "Describe the face"):
            build_edit_prompt("head", "", "", " ", 1)
        with self.assertRaisesRegex(ValueError, "style"):
            build_edit_prompt("style", "", "watercolour", "", 0)


class VideoEditWorkflowTests(unittest.TestCase):
    def test_graph_matches_the_lab_run(self):
        options = plan_edit(TALK, "outfit", "480", 5, "Put the jacket from @1 on him", "", "", 1)
        options["photos"] = ["upload_jacket.png"]
        graph = edit_workflow(options, "post_x_source.mp4", "h3_bridge_x", 12345)
        self.assertEqual(graph["21"]["inputs"]["lora_name"],
                         "h3_edit\\minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors")
        self.assertEqual(graph["22"]["inputs"]["lora_name"], "h3_edit\\minimax_h3_vfx_edit_v1.0_r128.safetensors")
        self.assertEqual((graph["23"]["inputs"]["shift_video"], graph["23"]["inputs"]["shift_audio"]), (12.0, 3.0))
        sampler = graph["30"]["inputs"]
        self.assertEqual((sampler["steps"], sampler["cfg"], sampler["sampler_name"], sampler["scheduler"],
                          sampler["seed"]), (4, 1.0, "euler", "simple", 12345))
        rtv = graph["13"]["inputs"]
        self.assertEqual((rtv["width"], rtv["height"], rtv["length"]), (480, 864, 124))
        self.assertEqual(rtv["ref_images.ref_image_0"], ["50", 0])          # flat key, not a nested dict
        self.assertEqual(graph["50"]["inputs"]["image"], "upload_jacket.png")
        self.assertEqual(graph["14"]["inputs"]["frame_idx"], 0)
        self.assertEqual(graph["43"]["inputs"]["audio"], ["2", 1])          # the source's own sound
        self.assertEqual(graph["44"]["inputs"]["filename_prefix"], "h3_bridge_x")

    def test_every_task_needs_its_lora(self):
        for task, spec in EDIT_TASKS.items():
            names = [path.name for path in edit_required_files({"task": task})]
            self.assertIn(spec["lora"], names)
            self.assertIn("minimax_h3_ref2va_pruned_int8_convrot.safetensors", names)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg")
    def test_input_is_cropped_padded_and_keeps_sound(self):
        with tempfile.TemporaryDirectory(prefix="h3-edit-") as folder:
            clip, out = Path(folder) / "talk.mp4", Path(folder) / "edit.mp4"
            make_clip(clip, 640, 1136, 30, 5.0)       # 30 fps, 150 frames = 120 at 24 fps: 4 frames are held
            options = plan_edit(probe_video(clip), "vfx", "480", 5, "Change the shirt", "", "", 0)
            subprocess.run(edit_input_command(options, clip, out), check=True)
            probe = probe_video(out)
            self.assertEqual((probe["width"], probe["height"], probe["fps"], probe["frames"], probe["audio"]),
                             (480, 864, 24.0, 124, True))


class VideoEditApiTests(ApiBase):
    def fake_ffmpeg(self, command, **_):
        Path(command[-1]).write_bytes(b"prepared")
        return subprocess.CompletedProcess(command, 0, "", "")

    def edit(self, data: dict, files=None):
        return self.client.post("/api/edit", data=data, files=files or [], headers={"X-CSRF-Token": self.token})

    def test_queues_an_edit_of_a_finished_job_next_to_it(self):
        self.add_job("src")
        with patch("backend.main.probe_video", return_value=dict(TALK)), \
                patch("backend.main.subprocess.run", side_effect=self.fake_ffmpeg):
            response = self.edit({"source_job_id": "src", "task": "vfx", "prompt": "Change his shirt into a red shirt"})
        self.assertEqual(response.status_code, 200, response.text)
        with connect() as db:
            row = dict(db.execute("SELECT * FROM jobs WHERE id=?", (response.json()["created"][0],)).fetchone())
        options = json.loads(row["post_options_json"])
        self.assertEqual((row["engine"], row["mode"], row["workflow_variant"], row["width"], row["height"], row["steps"]),
                         ("post", "edit", "h3edit", 480, 864, 1))
        self.assertEqual((options["source_job_id"], options["size"], options["seconds"]), ("src", "480", 5))
        self.assertTrue(row["prompt"].startswith("H3 edit · Text edit · 480x864 · 5 s"))
        self.assertAlmostEqual(row["duration"], 124 / 24, places=2)

    def test_head_swap_keeps_its_photo_and_refusals_leave_no_files(self):
        from PIL import Image
        self.add_job("src")
        photo = self.root / "face.png"
        Image.new("RGB", (64, 64), "white").save(photo)
        with patch("backend.main.probe_video", return_value=dict(TALK)), \
                patch("backend.main.subprocess.run", side_effect=self.fake_ffmpeg):
            with photo.open("rb") as handle:
                refused = self.edit({"source_job_id": "src", "task": "head", "size": "704", "seconds": "10",
                                     "face": "Male"}, [("photos", ("face.png", handle, "image/png"))])
            self.assertEqual(refused.status_code, 400)
            self.assertEqual(list(self.input.iterdir()), [])
            with photo.open("rb") as handle:
                response = self.edit({"source_job_id": "src", "task": "head", "size": "704", "face": "Male, short hair"},
                                     [("photos", ("face.png", handle, "image/png"))])
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["created"][0]
        options = response.json()["options"]
        self.assertEqual(len(options["photos"]), 1)
        self.assertTrue((self.input / options["photos"][0]).is_file())
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/input/reference_image_0").status_code, 200)

    def test_unfinished_source_is_refused(self):
        self.add_job("busy", status="running")
        response = self.edit({"source_job_id": "busy", "task": "vfx", "prompt": "Change the shirt"})
        self.assertEqual(response.status_code, 409)


class VideoEditMigrationTests(unittest.TestCase):
    def test_existing_job_tables_take_the_edit_mode_and_variant(self):
        temp = tempfile.TemporaryDirectory(prefix="h3-edit-db-")
        self.addCleanup(temp.cleanup)
        original = db_module.DB_PATH
        self.addCleanup(setattr, db_module, "DB_PATH", original)
        db_module.DB_PATH = Path(temp.name) / "old.sqlite3"
        source = Path(db_module.__file__).read_text(encoding="utf-8")
        start = source.index("    CREATE TABLE jobs (")
        sql = source[start:source.index("    CREATE INDEX idx_jobs_queue", start)]
        sql = sql.replace(",'h3edit'", "").replace(",'edit')", ")")
        old = sqlite3.connect(db_module.DB_PATH)
        old.executescript(sql)
        now = now_iso()
        old.execute("""INSERT INTO jobs (id,prompt,mode,duration,engine,workflow_variant,turbo_profile,encoder,steps,width,
                       height,seed,status,position,created_at,updated_at) VALUES('keep','Detail','upscale',5,'post',
                       'h3detail','v1','native',1,1920,1080,'1','completed',1,?,?)""", (now, now))
        old.commit()
        old.close()
        db_module.init_db()
        with connect() as db:
            self.assertEqual(db.execute("SELECT workflow_variant FROM jobs WHERE id='keep'").fetchone()[0], "h3detail")
            db.execute("""INSERT INTO jobs (id,prompt,mode,duration,engine,workflow_variant,turbo_profile,encoder,steps,
                          width,height,seed,status,position,created_at,updated_at) VALUES('e','Edit','edit',5.2,'post',
                          'h3edit','v1','native',1,480,864,'1','queued',2,?,?)""", (now, now))


if __name__ == "__main__":
    unittest.main()
