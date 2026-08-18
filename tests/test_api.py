import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, AsyncMock, patch

from fastapi.testclient import TestClient

import backend.db as db_module
from backend.main import app, worker


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
            "encoder": "native", "audio_start": "2.5",
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
                "SELECT mode,engine,encoder,first_frame_name,reference_audio_name,no_audio FROM jobs"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("lip_sync", "standard", "native", "face.png", "trimmed.wav", 0))

    def test_lip_sync_requires_audio(self):
        response = self.post(mode="lip_sync", engine="standard", encoder="native")
        self.assertEqual(response.status_code, 400)
        self.assertIn("uploaded audio", response.text)

    def test_spectrum_profile_is_persisted(self):
        response = self.post(engine="spectrum", steps="16", resolution="736x416")
        self.assertEqual(response.status_code, 200, response.text)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute("SELECT engine,steps,width,height,status FROM jobs").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("spectrum", 16, 736, 416, "queued"))

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
