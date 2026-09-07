import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.db as db_module
from backend.main import app


class VideoVaultApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-video-vault-test-")
        self.root = Path(self.temp.name)
        self.db_path = self.root / "jobs.sqlite3"
        self.vault_path = self.root / "video-vault"
        self.original_db_path = db_module.DB_PATH
        db_module.DB_PATH = self.db_path
        db_module.init_db()
        self.client = TestClient(app)
        session = self.client.get("/api/session")
        self.token = session.json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        db_module.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def test_upload_download_and_delete_remove_the_real_file(self):
        probe = {
            "format": {"duration": "5.0"},
            "streams": [{"codec_type": "video", "width": 640, "height": 360, "r_frame_rate": "24/1"}],
        }
        with patch("backend.video_vault.VIDEO_VAULT", self.vault_path), \
             patch("backend.video_vault.media_probe", return_value=probe):
            response = self.client.post(
                "/api/video-vault",
                files={"video": ("pilot.mp4", b"video-payload", "video/mp4")},
                headers={"X-CSRF-Token": self.token},
            )
            self.assertEqual(response.status_code, 200, response.text)
            item = response.json()
            self.assertEqual(item["original_name"], "pilot.mp4")
            self.assertEqual(item["width"], 640)
            self.assertTrue(item["available"])

            connection = sqlite3.connect(self.db_path)
            try:
                stored_name = connection.execute(
                    "SELECT stored_name FROM video_vault_items WHERE id=?", (item["id"],)
                ).fetchone()[0]
            finally:
                connection.close()
            stored_path = self.vault_path / stored_name
            self.assertTrue(stored_path.is_file())

            download = self.client.get(item["download_url"])
            self.assertEqual(download.status_code, 200, download.text)
            self.assertEqual(download.content, b"video-payload")

            deleted = self.client.delete(item["delete_url"], headers={"X-CSRF-Token": self.token})
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertTrue(deleted.json()["file_deleted"])
            self.assertFalse(stored_path.exists())

            listing = self.client.get("/api/video-vault")
            self.assertEqual(listing.status_code, 200, listing.text)
            self.assertEqual(listing.json()["items"], [])


if __name__ == "__main__":
    unittest.main()
