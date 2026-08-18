import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.db as db_module
import backend.library as library
from backend.db import connect, now_iso
from backend.main import app


class AssetLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-library-test-")
        self.root = Path(self.temp.name)
        self.original_db = db_module.DB_PATH
        db_module.DB_PATH = self.root / "jobs.sqlite3"
        self.projects = self.root / "projects"
        self.output = self.root / "comfy-output"
        self.output.mkdir()
        self.patches = [
            patch.object(library, "PROJECTS", self.projects),
            patch.object(library, "OUTPUT", self.output),
        ]
        for item in self.patches:
            item.start()
        db_module.init_db()
        library.init_library_db()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        db_module.DB_PATH = self.original_db
        self.temp.cleanup()

    def add_job(self, job_id: str, filename: str, status: str = "completed") -> Path:
        video = self.output / filename
        video.write_bytes(b"video")
        timestamp = now_iso()
        with connect() as db:
            db.execute(
                """INSERT INTO jobs
                   (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,megapixels,
                    aspect_ratio,seed,status,position,output_path,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, "Test clip", "text", 5, "turbo", "v1", "native", 6,
                 1216, 704, .86, "16:9", "42", status, 1, str(video), timestamp, timestamp),
            )
        return video

    def source_path(self, job_id: str) -> Path:
        with connect() as db:
            return Path(db.execute("SELECT output_path FROM jobs WHERE id=?", (job_id,)).fetchone()[0])

    def test_project_folder_move_rename_and_unassign_change_real_file(self):
        project = library.create_project("Music Video")
        accepted = library.create_folder(project["id"], "Accepted shots")
        alternate = library.create_folder(project["id"], "Alternate shots")
        original = self.add_job("job-1", "generated.mp4")

        assignment = library.assign_asset("job", "job-1", project["id"], accepted["id"])
        first = self.projects / "Music Video" / "Accepted shots" / "generated.mp4"
        self.assertFalse(original.exists())
        self.assertTrue(first.is_file())
        self.assertEqual(self.source_path("job-1").resolve(), first.resolve())
        self.assertEqual(assignment["folder_name"], "Accepted shots")

        library.assign_asset("job", "job-1", project["id"], alternate["id"])
        moved = self.projects / "Music Video" / "Alternate shots" / "generated.mp4"
        self.assertTrue(moved.is_file())
        renamed = library.rename_asset("job", "job-1", "rover arrival")
        final = moved.with_name("rover arrival.mp4")
        self.assertTrue(final.is_file())
        self.assertEqual(renamed["filename"], "rover arrival.mp4")
        self.assertEqual(self.source_path("job-1").resolve(), final.resolve())

        self.assertIsNone(library.assign_asset("job", "job-1", None))
        returned = self.output / "rover arrival.mp4"
        self.assertTrue(returned.is_file())
        self.assertEqual(self.source_path("job-1").resolve(), returned.resolve())
        self.assertEqual(library.list_library()["assignments"], [])

    def test_queued_assignment_is_finalized_after_worker_output_exists(self):
        project = library.create_project("Queued Project")
        timestamp = now_iso()
        with connect() as db:
            db.execute(
                """INSERT INTO jobs
                   (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,megapixels,
                    aspect_ratio,seed,status,position,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("queued-job", "Queued", "text", 5, "turbo", "v1", "native", 6,
                 1216, 704, .86, "16:9", "42", "queued", 1, timestamp, timestamp),
            )
        library.assign_asset("job", "queued-job", project["id"])
        rendered = self.output / "rendered.mp4"
        rendered.write_bytes(b"video")
        with connect() as db:
            db.execute("UPDATE jobs SET status='completed',output_path=? WHERE id=?", (str(rendered), "queued-job"))

        organized = library.finalize_completed_asset("job", "queued-job")
        expected = self.projects / "Queued Project" / "rendered.mp4"
        self.assertEqual(organized.resolve(), expected.resolve())
        self.assertTrue(expected.is_file())
        self.assertEqual(self.source_path("queued-job").resolve(), expected.resolve())

    def test_directory_renames_update_managed_asset_paths(self):
        project = library.create_project("Old Project")
        folder = library.create_folder(project["id"], "Old Folder")
        self.add_job("job-rename", "clip.mp4")
        library.assign_asset("job", "job-rename", project["id"], folder["id"])

        library.rename_folder(project["id"], folder["id"], "New Folder")
        library.rename_project(project["id"], "New Project")
        expected = self.projects / "New Project" / "New Folder" / "clip.mp4"
        self.assertTrue(expected.is_file())
        self.assertEqual(self.source_path("job-rename").resolve(), expected.resolve())

    def test_invalid_names_and_nonempty_deletion_are_rejected(self):
        with self.assertRaises(ValueError):
            library.create_project("../escape")
        with self.assertRaises(ValueError):
            library.create_project("CON")
        project = library.create_project("Protected")
        folder = library.create_folder(project["id"], "Shots")
        self.add_job("job-protected", "clip.mp4")
        library.assign_asset("job", "job-protected", project["id"], folder["id"])
        with self.assertRaises(RuntimeError):
            library.delete_folder(project["id"], folder["id"])
        with self.assertRaises(RuntimeError):
            library.delete_project(project["id"])

    def test_api_organizes_renames_and_permanently_deletes_asset(self):
        self.add_job("api-job", "api-result.mp4")
        with TestClient(app) as client:
            token = client.get("/api/session").json()["csrf_token"]
            headers = {"X-CSRF-Token": token}
            project_response = client.post(
                "/api/library/projects", headers=headers, json={"name": "API Project"},
            )
            self.assertEqual(project_response.status_code, 200, project_response.text)
            project = project_response.json()
            folder_response = client.post(
                f"/api/library/projects/{project['id']}/folders",
                headers=headers, json={"name": "Shots"},
            )
            folder = folder_response.json()
            moved = client.patch(
                "/api/library/assets/job/api-job/location", headers=headers,
                json={"project_id": project["id"], "folder_id": folder["id"]},
            )
            self.assertEqual(moved.status_code, 200, moved.text)
            renamed = client.patch(
                "/api/library/assets/job/api-job/name", headers=headers,
                json={"name": "approved-shot"},
            )
            self.assertEqual(renamed.status_code, 200, renamed.text)
            actual = self.projects / "API Project" / "Shots" / "approved-shot.mp4"
            self.assertTrue(actual.is_file())

            deleted = client.delete("/api/jobs/api-job", headers=headers)
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertFalse(actual.exists())
            self.assertEqual(library.list_library()["assignments"], [])


if __name__ == "__main__":
    unittest.main()
