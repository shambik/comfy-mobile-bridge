import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, AsyncMock, patch

from fastapi.testclient import TestClient

import backend.db as db_module
from backend.main import app, packet_audio_duration, worker


class JobApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-api-test-")
        self.path = Path(self.temp.name) / "jobs.sqlite3"
        self.original_path = db_module.DB_PATH
        db_module.DB_PATH = self.path
        db_module.init_db()
        self.notify_patch = patch.object(worker, "notify")
        self.notify_patch.start()
        self.client = TestClient(app)
        session = self.client.get("/api/session")
        self.token = session.json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        self.notify_patch.stop()
        db_module.DB_PATH = self.original_path
        self.temp.cleanup()

    def post(self, **values):
        data = {"prompt": "A calm cinematic forest", "mode": "text", "duration": "5", **values}
        return self.client.post("/api/jobs", data=data, headers={"X-CSRF-Token": self.token})

    def test_job_page_keeps_finished_results_behind_a_long_queue(self):
        for _ in range(36):
            self.assertEqual(self.post(engine="turbo", steps="4", resolution="512x288").status_code, 200)
        connection = sqlite3.connect(self.path)
        try:
            ids = [row[0] for row in connection.execute("SELECT id FROM jobs ORDER BY position")]
            connection.execute("UPDATE jobs SET status='completed', finished_at=created_at WHERE id=?", (ids[0],))
            connection.execute("UPDATE jobs SET status='running' WHERE id=?", (ids[1],))
            connection.commit()
        finally:
            connection.close()

        page = self.client.get("/api/jobs?limit=32&include_library=false").json()
        listed = [job["id"] for job in page["jobs"]]
        self.assertEqual(page["jobs_total"], 36)
        self.assertEqual(listed[0], ids[1])
        self.assertEqual(set(listed[:35]), set(ids[1:]))
        self.assertEqual(listed[35:], [ids[0]])
        self.assertEqual([job["id"] for job in self.client.get("/api/jobs?status=queued&limit=5&include_library=false").json()["jobs"]], ids[2:7])

    def test_selected_profile_is_persisted(self):
        response = self.post(engine="turbo", steps="6", resolution="512x288")
        self.assertEqual(response.status_code, 200, response.text)

        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT engine,steps,width,height,status FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("turbo", 6, 512, 288, "queued"))

    def test_turbo_v4_profile_is_persisted_when_model_exists(self):
        models = Path(self.temp.name) / "models"
        lora = models / "loras" / "minimax_h3_turbo_v4_step600_ema.safetensors"
        lora.parent.mkdir(parents=True)
        lora.write_bytes(b"test-marker")
        with patch("backend.main.MODELS", models):
            response = self.post(engine="turbo", turbo_profile="v4", steps="6")
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT turbo_profile,steps FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("v4", 6))

    def test_whole_history_loads_past_500_jobs(self):
        # Issue #76: "load all" asks for every job; the old cap of 500 left "N remaining" forever.
        first = self.post(engine="turbo", steps="4", resolution="512x288").json()["created"][0]
        connection = sqlite3.connect(self.path)
        try:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(jobs)")]
            row = connection.execute(f"SELECT {','.join(columns)} FROM jobs WHERE id=?", (first,)).fetchone()
            copies = []
            for index in range(1, 620):
                values = dict(zip(columns, row))
                values.update(id=f"{index:032x}", position=index + 1, status="completed")
                copies.append(tuple(values[column] for column in columns))
            connection.executemany(f"INSERT INTO jobs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                   copies)
            connection.commit()
        finally:
            connection.close()
        page = self.client.get("/api/jobs?limit=620&include_library=false&include_sequences=false").json()
        self.assertEqual(page["jobs_total"], 620)
        self.assertEqual(len(page["jobs"]), 620)

    def test_job_list_leaves_full_run_details_to_the_job_route(self):
        # Issue #76: the list carries only what a card shows; the run-details panel loads the rest per job.
        job_id = self.post(engine="turbo", steps="4", resolution="512x288").json()["created"][0]
        plain = self.post(engine="turbo", steps="4", resolution="512x288").json()["created"][0]
        runtime = {"comfy": {"version": "0.44.0", "command_line": "python main.py"},
                   "workflow": {"builder": "turbo_workflow", "nodes": [{"id": "1", "class_type": "X", "inputs": {}}]},
                   "long_take": {"run": "bridge_x", "parts": 2, "saved": 1}, "swap": {"window_now": 2}}
        db_module.update_job(job_id, runtime=runtime)
        listed = {job["id"]: job for job in self.client.get("/api/jobs?limit=10&include_library=false").json()["jobs"]}
        self.assertEqual(listed[job_id]["runtime"], {"long_take": runtime["long_take"], "swap": runtime["swap"]})
        self.assertTrue(listed[job_id]["runtime_details"])
        self.assertIsNone(listed[plain]["runtime"])
        self.assertFalse(listed[plain]["runtime_details"])
        detail = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["runtime"], runtime)
        self.assertEqual(self.client.get("/api/jobs/not-a-job").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/revision").status_code, 200)  # still its own route

    def test_long_take_parts_play_while_the_job_renders(self):
        job_id = self.post(engine="turbo", steps="4", resolution="512x288").json()["created"][0]
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/parts/1").status_code, 404)  # not a long take
        root = Path(self.temp.name) / "output"
        segments = root / "h3_chains" / "velora_ad_1" / "segments"
        segments.mkdir(parents=True)
        (segments / "clip_0001.ab12.mp4").write_bytes(b"part-one")
        db_module.update_job(job_id, runtime={"long_take": {"run": "velora_ad_1", "parts": 4, "saved": 1}})
        with patch("backend.main.COMFY_OUTPUT", root):
            first = self.client.get(f"/api/jobs/{job_id}/parts/1")
            second = self.client.get(f"/api/jobs/{job_id}/parts/2")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, b"part-one")
        self.assertEqual(first.headers["content-type"], "video/mp4")
        self.assertEqual(second.status_code, 404)
        self.assertEqual(db_module.get_job(job_id)["runtime"]["long_take"]["parts"], 4)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg")
    def test_long_take_part_is_played_with_its_sound(self):
        # Context-Loop keeps a part's picture and sound apart until assembly; the card gets them joined.
        job_id = self.post(engine="turbo", steps="4", resolution="512x288").json()["created"][0]
        root = Path(self.temp.name) / "output"
        run = root / "h3_chains" / "velora_ad_2"
        (run / "segments").mkdir(parents=True)
        (run / "generated_audio").mkdir()
        video = run / "segments" / "clip_0001.ab12.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64:r=24:d=1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(video)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        str(run / "generated_audio" / "clip_0001.ab12.wav")], check=True)
        db_module.update_job(job_id, runtime={"long_take": {"run": "velora_ad_2", "parts": 2, "saved": 1}})
        state = Path(self.temp.name) / "state"
        with patch("backend.main.COMFY_OUTPUT", root), patch("backend.main.STATE", state):
            response = self.client.get(f"/api/jobs/{job_id}/parts/1")
        self.assertEqual(response.status_code, 200, response.text[:200])
        joined = state / "long_take_parts" / "velora_ad_2" / "clip_0001.ab12.mp4"
        streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                  str(joined)], capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(sorted(streams), ["audio", "video"])
        self.assertEqual(response.content, joined.read_bytes())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs FFmpeg")
    def test_failed_long_take_is_assembled_from_its_saved_parts(self):
        # 2026-11-22: Context-Loop refused a damaged checkpoint after part 4; the saved parts still make the video.
        job_id = self.post(engine="turbo", steps="4", resolution="512x288").json()["created"][0]
        root = Path(self.temp.name) / "output"
        run = root / "h3_chains" / "velora_ad_3"
        (run / "segments").mkdir(parents=True)
        (run / "generated_audio").mkdir()
        for index, colour in ((1, "red"), (2, "blue")):
            stem = f"clip_000{index}.ab{index}c"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:s=64x64:r=24:d=1",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(run / "segments" / f"{stem}.mp4")], check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                            str(run / "generated_audio" / f"{stem}.wav")], check=True)
        headers = {"X-CSRF-Token": self.token}
        db_module.update_job(job_id, status="failed", error="H3 chain clip 2 checkpoint failed its SHA-256 integrity check.",
                             runtime={"long_take": {"run": "velora_ad_3", "parts": 3, "saved": 2}})
        with patch("backend.main.COMFY_OUTPUT", root), patch("backend.library.finalize_completed_asset", return_value=None):
            missing = self.client.post(f"/api/jobs/{job_id}/assemble-parts", headers=headers)
            self.assertEqual(missing.status_code, 409, missing.text)  # part 3 not saved
            db_module.update_job(job_id, runtime={"long_take": {"run": "velora_ad_3", "parts": 2, "saved": 2}})
            joined = self.client.post(f"/api/jobs/{job_id}/assemble-parts", headers=headers)
            self.assertEqual(joined.status_code, 200, joined.text)
            again = self.client.post(f"/api/jobs/{job_id}/assemble-parts", headers=headers)
            self.assertEqual(again.status_code, 409, again.text)  # already completed
        job = db_module.get_job(job_id, public=False)
        self.assertEqual(job["status"], "completed")
        self.assertIsNone(job["error"])
        output = Path(job["output_path"])
        self.assertEqual(output, root / f"h3_bridge_{job_id}_00001_.mp4")
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                "stream=codec_type,nb_read_frames", "-of", "csv=p=0", str(output)],
                               capture_output=True, text=True, check=True).stdout.split()
        self.assertIn("video,48", probe)  # 24 + 24 frames end to end
        self.assertTrue(any(line.startswith("audio") for line in probe))

    def test_only_a_stopped_long_take_is_assembled(self):
        job_id = self.post(engine="turbo", steps="4", resolution="512x288").json()["created"][0]
        db_module.update_job(job_id, runtime={"long_take": {"run": "velora_ad_4", "parts": 2, "saved": 2}})
        refused = self.client.post(f"/api/jobs/{job_id}/assemble-parts", headers={"X-CSRF-Token": self.token})
        self.assertEqual(refused.status_code, 409, refused.text)  # still queued
        plain = self.post(engine="turbo", steps="4", resolution="512x288").json()["created"][0]
        db_module.update_job(plain, status="failed")
        self.assertEqual(self.client.post(f"/api/jobs/{plain}/assemble-parts",
                                          headers={"X-CSRF-Token": self.token}).status_code, 400)

    def test_singularity_long_take_is_one_job_with_its_parts(self):
        # Issue #65: 2 or 3 parts separated by '---' lines, reference mode, length = parts x 5 s.
        files = {"reference_images": ("sheet.png", b"image-placeholder", "image/png")}
        parts = "summary:\nshe starts\n\nmore of part one\n---\nsummary:\nshe goes on\n---\nsummary:\nshe ends"
        data = {"prompt": parts, "mode": "reference", "engine": "singularity", "workflow_variant": "skin_god",
                "steps": "8", "attention_mode": "int8", "aspect_ratio": "9:16", "megapixels": "1.5",
                "skin_options": '{"parts": 3}'}
        with patch("backend.main.singularity_ready", return_value=True), \
             patch("backend.main.save_image", new=AsyncMock(return_value=("C:/safe/sheet.png", "sheet.png"))):
            refusals = {
                "wrong length": self.client.post("/api/jobs", data={**data, "duration": "10"}, files=files, headers={"X-CSRF-Token": self.token}),
                "two parts written": self.client.post("/api/jobs", data={**data, "duration": "15", "prompt": "a\n---\nb"}, files=files, headers={"X-CSRF-Token": self.token}),
                "batch": self.client.post("/api/jobs", data={**data, "duration": "15", "batch": "true"}, files=files, headers={"X-CSRF-Token": self.token}),
                "part too long": self.client.post("/api/jobs", data={**data, "duration": "15", "prompt": "a\n---\nb\n---\n" + "c" * 4001}, files=files, headers={"X-CSRF-Token": self.token}),
            }
            opening = self.client.post("/api/jobs", data={**data, "mode": "opening", "duration": "15"},
                                       files={"image": ("face.png", b"image-placeholder", "image/png")}, headers={"X-CSRF-Token": self.token})
            response = self.client.post("/api/jobs", data={**data, "duration": "15"}, files=files, headers={"X-CSRF-Token": self.token})
        for name, refused in refusals.items():
            with self.subTest(name):
                self.assertEqual(refused.status_code, 400, refused.text)
        self.assertEqual(opening.status_code, 400, opening.text)
        self.assertIn("reference mode only", opening.text)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["created"]), 1)
        connection = sqlite3.connect(self.path)
        try:
            prompt, duration, options = connection.execute("SELECT prompt,duration,skin_options_json FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(duration, 15)
        self.assertIn('"parts": 3', options)
        stored = prompt.split("\n---\n")
        self.assertEqual(len(stored), 3)
        self.assertTrue(all(part.startswith("r34l1sm\n\n") for part in stored))  # People trigger on every part
        self.assertIn("she starts\n\nmore of part one", stored[0])

    def test_pika_turbo_is_persisted_and_keeps_its_tested_length(self):
        files = {"image": ("face.png", b"image-placeholder", "image/png")}
        data = {"prompt": "A fighter turns to camera", "mode": "opening", "engine": "pika", "workflow_variant": "turbo4",
                "steps": "4", "attention_mode": "sage", "aspect_ratio": "16:9", "megapixels": "1.5"}
        with patch("backend.main.pika_ready", return_value=True), \
             patch("backend.main.pika_turbo4_ready", return_value=True), \
             patch("backend.main.save_image", new=AsyncMock(return_value=("C:/safe/face.png", "face.png"))):
            refused = self.client.post("/api/jobs", data={**data, "duration": "6"}, files=files, headers={"X-CSRF-Token": self.token})
            response = self.client.post("/api/jobs", data={**data, "duration": "5"}, files=files, headers={"X-CSRF-Token": self.token})
        self.assertEqual(refused.status_code, 400, refused.text)
        self.assertIn("tested up to 5 seconds", refused.text)
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT engine,workflow_variant,steps,attention_mode,width,height FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("pika", "turbo4", 4, "sage", 1632, 928))

    def test_reference_audio_is_persisted_as_an_optional_official_reference(self):
        data = {
            "prompt": "<Picture 1> speaks in time with <Audio 1>",
            "mode": "reference", "duration": "5", "engine": "standard",
        }
        files = {
            "image": ("face.png", b"image-placeholder", "image/png"),
            "reference_audio": ("voice.wav", b"audio-placeholder", "audio/wav"),
        }
        with patch("backend.main.save_image", new=AsyncMock(return_value=("C:/safe/face.png", "face.png"))), \
             patch("backend.main.save_audio", new=AsyncMock(return_value=("C:/safe/voice.wav", "voice.wav"))):
            response = self.client.post(
                "/api/jobs", data=data, files=files,
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT input_name,reference_audio_name FROM jobs"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("face.png", "voice.wav"))

    def test_lip_sync_accepts_optional_opening_frame_and_uploaded_audio(self):
        data = {
            "prompt": "",
            "mode": "lip_sync", "duration": "5", "engine": "standard",
            "encoder": "native", "audio_start": "2.5", "audio_duration": "6",
        }
        files = {
            "first_frame": ("face.png", b"image-placeholder", "image/png"),
            "audio": ("voice.wav", b"audio-placeholder", "audio/wav"),
        }
        with patch("backend.main.save_image", new=AsyncMock(return_value=("C:/safe/face.png", "face.png"))), \
             patch("backend.main.save_audio", new=AsyncMock(return_value=("C:/safe/voice.wav", "voice.wav"))) as save_audio_mock, \
             patch("backend.main.probe_audio_duration", return_value=208.5), \
             patch("backend.main.trim_audio", return_value=("C:/safe/trimmed.wav", "trimmed.wav")):
            response = self.client.post(
                "/api/jobs", data=data, files=files,
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        save_audio_mock.assert_awaited_once_with(ANY, allow_longer=True)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT mode,engine,encoder,audio_start,audio_duration,first_frame_name,reference_audio_name,no_audio FROM jobs"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("lip_sync", "standard", "native", 2.5, 6.0, "face.png", "trimmed.wav", 0))

    def test_lip_sync_refuses_an_audio_start_past_the_end(self):
        data = {
            "prompt": "",
            "mode": "lip_sync", "duration": "5", "engine": "standard",
            "encoder": "native", "audio_start": "48.4", "audio_duration": "5",
        }
        files = {"audio": ("segment.wav", b"audio-placeholder", "audio/wav")}
        with patch("backend.main.save_audio", new=AsyncMock(return_value=("C:/safe/segment.wav", "segment.wav"))), \
             patch("backend.main.probe_audio_duration", return_value=5.0), \
             patch("backend.main.trim_audio") as trim_audio_mock:
            response = self.client.post(
                "/api/jobs", data=data, files=files,
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("would be silent", response.text)
        trim_audio_mock.assert_not_called()

    def test_lip_sync_accepts_optional_closing_frame_with_uploaded_audio(self):
        data = {
            "prompt": "Music-driven motion",
            "mode": "lip_sync", "duration": "5", "engine": "turbo",
            "encoder": "native", "audio_start": "0", "audio_pretrimmed": "true",
            "audio_original_start": "5",
        }
        files = {
            "first_frame": ("runner.png", b"opening-placeholder", "image/png"),
            "last_frame": ("shoe.png", b"closing-placeholder", "image/png"),
            "audio": ("music.wav", b"audio-placeholder", "audio/wav"),
        }
        save_image_mock = AsyncMock(side_effect=[
            ("C:/safe/runner.png", "runner.png"),
            ("C:/safe/shoe.png", "shoe.png"),
        ])
        with patch("backend.main.save_image", new=save_image_mock), \
             patch("backend.main.save_audio", new=AsyncMock(return_value=("C:/safe/music.wav", "music.wav"))), \
             patch("backend.main.probe_audio_duration", return_value=5.0):
            response = self.client.post(
                "/api/jobs", data=data, files=files,
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT mode,first_frame_name,last_frame_name,reference_audio_name,no_audio FROM jobs"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("lip_sync", "runner.png", "shoe.png", "music.wav", 0))

    def test_lip_sync_requires_audio(self):
        response = self.post(mode="lip_sync", engine="standard", encoder="native")
        self.assertEqual(response.status_code, 400)
        self.assertIn("uploaded audio", response.text)

    def test_fused_lip_sync_profile_is_persisted_with_direct_workflow(self):
        files = {
            "audio": ("voice.wav", b"audio-placeholder", "audio/wav"),
        }
        data = {
            "prompt": "A singer performs naturally to the uploaded vocal",
            "mode": "lip_sync", "duration": "5", "engine": "fused_sla",
            "encoder": "native", "steps": "6", "audio_pretrimmed": "true",
            "audio_original_start": "0",
        }
        with patch("backend.main.fused_sla_ready", return_value=True), \
             patch("backend.main.fused_workflow_ready", return_value=True), \
             patch("backend.main.save_audio", new=AsyncMock(return_value=("C:/safe/voice.wav", "voice.wav"))), \
             patch("backend.main.probe_audio_duration", return_value=5.0):
            response = self.client.post(
                "/api/jobs", data=data, files=files,
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT mode,engine,workflow_variant,steps,reference_audio_name FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("lip_sync", "fused_sla", "direct", 6, "voice.wav"))

    def test_lip_sync_preserves_a_client_pretrimmed_audio_window(self):
        data = {
            "prompt": "",
            "mode": "lip_sync", "duration": "5", "engine": "standard",
            "encoder": "native", "audio_start": "0", "audio_pretrimmed": "true", "audio_original_start": "48.4",
        }
        files = {"audio": ("segment.wav", b"audio-placeholder", "audio/wav")}
        with patch("backend.main.save_audio", new=AsyncMock(return_value=("C:/safe/segment.wav", "segment.wav"))), \
             patch("backend.main.probe_audio_duration", return_value=5.0), \
             patch("backend.main.trim_audio") as trim_audio_mock:
            response = self.client.post(
                "/api/jobs", data=data, files=files,
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        trim_audio_mock.assert_not_called()
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT audio_start,audio_duration,reference_audio_name FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, (48.4, 5.0, "segment.wav"))

    def test_live_webm_packet_duration_fallback(self):
        payload = {
            "packets": [
                {"pts_time": "-0.007", "duration_time": "0.020"},
                {"pts_time": "4.973", "duration_time": "0.020"},
            ]
        }
        self.assertAlmostEqual(packet_audio_duration(payload), 5.0, places=3)

    def test_comfy_status_distinguishes_busy_process_from_stopped(self):
        with patch.object(worker.comfy, "ready", new=AsyncMock(return_value=False)), \
             patch.object(worker.comfy, "discovered_pid", return_value=8190):
            response = self.client.get("/api/comfy/status")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["running"], True)
        self.assertEqual(response.json()["responsive"], False)
        self.assertEqual(response.json()["busy"], True)
        self.assertEqual(response.json()["pid"], 8190)

    def test_spectrum_profile_is_persisted(self):
        response = self.post(engine="spectrum", steps="16", resolution="736x416")
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT engine,steps,width,height,status FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("spectrum", 16, 736, 416, "queued"))

    def test_fused_sla_profile_is_persisted_at_four_steps(self):
        with patch("backend.main.fused_sla_ready", return_value=True),              patch("backend.main.fused_workflow_ready", return_value=True):
            response = self.post(engine="fused_sla", steps="4", resolution="512x288")
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT engine,steps,width,height,status FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("fused_sla", 4, 512, 288, "queued"))

    def test_fused_sla_accepts_eight_step_quality_mode(self):
        with patch("backend.main.fused_sla_ready", return_value=True),              patch("backend.main.fused_workflow_ready", return_value=True):
            response = self.post(engine="fused_sla", steps="8", resolution="512x288")
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT engine,steps FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("fused_sla", 8))

    def test_fused_sla_reference_requires_reference_media(self):
        with patch("backend.main.fused_sla_ready", return_value=True),              patch("backend.main.fused_workflow_ready", return_value=True):
            response = self.post(mode="reference", engine="fused_sla", steps="4")
        self.assertEqual(response.status_code, 400)
        self.assertIn("at least one image or video", response.text)

    def test_fused_ref2va_reference_profile_is_persisted(self):
        files = {"image": ("reference.png", b"image-placeholder", "image/png")}
        with patch("backend.main.fused_sla_ready", return_value=True), \
             patch("backend.main.fused_workflow_ready", return_value=True), \
             patch("backend.main.save_image", new=AsyncMock(return_value=("C:/safe/reference.png", "reference.png"))):
            response = self.client.post(
                "/api/jobs",
                data={"prompt": "A person turns toward camera", "mode": "reference", "duration": "5", "engine": "fused_sla", "steps": "4"},
                files=files,
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT engine,workflow_variant,steps FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("fused_sla", "ref2va", 4))

    def test_fused_ref2va_allows_long_duration_and_selected_steps(self):
        files = {"image": ("reference.png", b"image-placeholder", "image/png")}
        with patch("backend.main.fused_sla_ready", return_value=True), \
             patch("backend.main.fused_workflow_ready", return_value=True), \
             patch("backend.main.save_image", new=AsyncMock(return_value=("C:/safe/reference.png", "reference.png"))):
            response = self.client.post(
                "/api/jobs",
                data={"prompt": "A person walks through a neon city", "mode": "reference", "duration": "10", "engine": "fused_sla", "steps": "8"},
                files=files,
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT workflow_variant,duration,steps FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("ref2va", 10.0, 8))

    def test_completed_job_last_frame_can_be_extracted_and_served(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            job_id = connection.execute("SELECT id FROM jobs").fetchone()[0]
            connection.execute(
                "UPDATE jobs SET status='completed',output_path=? WHERE id=?",
                (str(Path(self.temp.name) / "generated.mp4"), job_id),
            )
            connection.commit()
        finally:
            connection.close()

        source = Path(self.temp.name) / "generated.mp4"
        source.write_bytes(b"video")
        extracted = Path(self.temp.name) / "extracted"

        def fake_extract(video, target, width, height):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"png")
            return target

        with patch("backend.main.resolve_asset_path", return_value=source), \
             patch("backend.main.EXTRACTED_LAST_FRAMES", extracted), \
             patch("backend.main.extract_last_frame", side_effect=fake_extract):
            extracted_response = self.client.post(
                f"/api/jobs/{job_id}/last-frame",
                headers={"X-CSRF-Token": self.token},
            )
            served_response = self.client.get(f"/api/jobs/{job_id}/last-frame")

        self.assertEqual(extracted_response.status_code, 200, extracted_response.text)
        self.assertEqual(extracted_response.json()["width"], 736)
        self.assertEqual(extracted_response.json()["height"], 416)
        self.assertEqual(served_response.status_code, 200, served_response.text)
        self.assertEqual(served_response.content, b"png")

    def test_fused_ref2va_multiref_accepts_all_reference_media(self):
        data = {
            "prompt": "Use the image, motion and voice references consistently",
            "mode": "reference", "duration": "5", "engine": "fused_sla",
            "workflow_variant": "ref2va_multiref", "steps": "4",
        }
        files = [
            ("reference_images", ("face.png", b"image-one", "image/png")),
            ("reference_images", ("wardrobe.png", b"image-two", "image/png")),
            ("reference_videos", ("motion.mp4", b"video-one", "video/mp4")),
            ("reference_audio", ("voice.wav", b"audio-one", "audio/wav")),
        ]
        with patch("backend.main.fused_sla_ready", return_value=True), \
             patch("backend.main.fused_workflow_ready", return_value=True), \
             patch("backend.main.save_image", new=AsyncMock(side_effect=[
                 ("C:/safe/face.png", "face.png"),
                 ("C:/safe/wardrobe.png", "wardrobe.png"),
             ])), \
             patch("backend.main.save_video", new=AsyncMock(return_value=("C:/safe/motion.mp4", "motion.mp4"))), \
             patch("backend.main.save_audio", new=AsyncMock(return_value=("C:/safe/voice.wav", "voice.wav"))):
            response = self.client.post(
                "/api/jobs", data=data, files=files,
                headers={"X-CSRF-Token": self.token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT engine,workflow_variant,reference_images_json,reference_videos_json,reference_audio_name FROM jobs"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row[0:2], ("fused_sla", "ref2va_multiref"))
        self.assertEqual(row[2], '["face.png", "wardrobe.png"]')
        self.assertEqual(row[3], '["motion.mp4"]')
        self.assertEqual(row[4], "voice.wav")

    def test_clipproj_profile_is_persisted(self):
        with patch("backend.main.clipproj_ready", return_value=True):
            response = self.post(encoder="clipproj")
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT encoder FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("clipproj",))

    def test_connected_batch_creates_one_sequence_and_ordered_children(self):
        response = self.post(
            prompt="Shot one\n\nShot two\n\nShot three",
            batch="true", connected="true", encoder="native",
        )
        self.assertEqual(response.status_code, 200, response.text)
        sequence_id = response.json()["sequence_id"]
        self.assertTrue(sequence_id)
        connection = sqlite3.connect(self.path)
        try:
            sequence = connection.execute(
                "SELECT kind,status,total_items,engine,encoder FROM sequences WHERE id=?",
                (sequence_id,),
            ).fetchone()
            children = connection.execute(
                """SELECT prompt,sequence_index,sequence_total,status,position
                   FROM jobs WHERE sequence_id=? ORDER BY sequence_index""",
                (sequence_id,),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(sequence, ("connected", "queued", 3, "turbo", "native"))
        self.assertEqual([row[:4] for row in children], [
            ("Shot one", 1, 3, "queued"),
            ("Shot two", 2, 3, "queued"),
            ("Shot three", 3, 3, "queued"),
        ])
        self.assertEqual(len({row[4] for row in children}), 1)

    def test_history_results_can_be_queued_for_ordered_join(self):
        first = self.post(prompt="First clip").json()["created"][0]
        second = self.post(prompt="Second clip").json()["created"][0]
        first_path = Path(self.temp.name) / "first.mp4"
        second_path = Path(self.temp.name) / "second.mp4"
        first_path.write_bytes(b"one")
        second_path.write_bytes(b"two")
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE jobs SET status='completed',output_path=? WHERE id=?",
                (str(first_path), first),
            )
            connection.execute(
                "UPDATE jobs SET status='completed',output_path=? WHERE id=?",
                (str(second_path), second),
            )
            connection.commit()
        finally:
            connection.close()

        response = self.client.post(
            "/api/sequences/join",
            json={"ids": [f"job:{second}", f"job:{first}"]},
            headers={"X-CSRF-Token": self.token},
        )
        self.assertEqual(response.status_code, 200, response.text)
        sequence_id = response.json()["sequence_id"]
        connection = sqlite3.connect(self.path)
        try:
            rows = connection.execute(
                """SELECT source_job_id,clip_path FROM sequence_items
                   WHERE sequence_id=? ORDER BY item_index""",
                (sequence_id,),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual([row[0] for row in rows], [second, first])
        self.assertEqual([Path(row[1]).name for row in rows], ["second.mp4", "first.mp4"])

    def test_legacy_request_keeps_current_defaults(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT engine,turbo_profile,encoder,steps,width,height FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("turbo", "v1", "native", 4, 736, 416))

    def test_invalid_profiles_are_rejected(self):
        self.assertEqual(self.post(engine="standard", steps="7").status_code, 400)
        response = self.post(mode="reference", engine="turbo", steps="4")
        self.assertEqual(response.status_code, 400)
        self.assertIn("requires at least one image or video", response.json()["detail"])

if __name__ == "__main__":
    unittest.main()
