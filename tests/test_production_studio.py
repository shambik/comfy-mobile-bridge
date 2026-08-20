import io
import asyncio
import json
import tempfile
import unittest
import zipfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch
from PIL import Image

from fastapi.testclient import TestClient

import backend.db as db_module
import backend.production as production_module
import backend.skill_catalog as skill_module
from backend.agents import AgentResult, _extract_result, discover_codex_models, process_manager
from backend.main import app, production_orchestrator
from backend.production import ProductionOrchestrator
from backend.production_db import (add_decision, ensure_agent_settings,
                                   add_artifact, add_reference, create_shot_attempt, get_production,
                                   init_production_db, list_shots, replace_shot_plan,
                                   update_shot_attempt)


class ProductionStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="production-studio-test-")
        self.root = Path(self.temp.name)
        self.original_db = db_module.DB_PATH
        db_module.DB_PATH = self.root / "jobs.sqlite3"
        db_module.init_db()
        init_production_db()
        ensure_agent_settings({
            "codex_runtime": "codex", "codex_model": "gpt-5.6-sol", "codex_effort": "high",
            "agy_runtime": "agy",
            "agy_model": "gemini-3.1-pro-high", "agy_effort": "high",
        })
        (self.root / "input").mkdir()
        self.production_patches = [
            patch("backend.main.PRODUCTIONS", self.root / "productions"),
            patch("backend.main.INPUT", self.root / "input"),
            patch.object(production_module, "PRODUCTIONS", self.root / "productions"),
            patch.object(production_module, "INPUT", self.root / "input"),
            patch.object(production_orchestrator, "notify"),
        ]
        for item in self.production_patches:
            item.start()
        self.client = TestClient(app)
        self.token = self.client.get("/api/session").json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.production_patches):
            item.stop()
        db_module.DB_PATH = self.original_db
        self.temp.cleanup()

    def create_production(self):
        return self.client.post(
            "/api/productions",
            headers={"X-CSRF-Token": self.token},
            data={
                "title": "Test production", "lyrics": "Line one\nLine two",
                "participation_mode": "interactive", "continuity_mode": "hybrid",
                "skills_json": "[]", "approval_gates_json": json.dumps(["treatment", "final"]),
            },
            files={"song": ("song.wav", b"RIFF-test", "audio/wav")},
        )

    def test_create_production_accepts_browser_recorded_webm(self):
        response = self.client.post(
            "/api/productions",
            headers={"X-CSRF-Token": self.token},
            data={
                "title": "Recorded production", "lyrics": "Line one\nLine two",
                "participation_mode": "interactive", "continuity_mode": "hybrid",
                "skills_json": "[]", "approval_gates_json": "[]",
            },
            files={"song": ("recording.webm", b"webm-test", "audio/webm;codecs=opus")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["song_name"], "recording.webm")

    def test_create_and_start_production_preserves_user_configuration(self):
        response = self.create_production()
        self.assertEqual(response.status_code, 200, response.text)
        production = response.json()
        self.assertEqual(production["status"], "draft")
        self.assertEqual(production["participation_mode"], "interactive")
        self.assertNotIn("song_path", production)

        started = self.client.post(
            f"/api/productions/{production['id']}/start",
            headers={"X-CSRF-Token": self.token},
        )
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()["stage"], "song_analysis")
        self.assertEqual(started.json()["status"], "queued")

    def test_user_is_first_class_message_participant(self):
        production = self.create_production().json()
        response = self.client.post(
            f"/api/productions/{production['id']}/interventions",
            headers={"X-CSRF-Token": self.token},
            json={"recipient": "both", "content": "Keep the opening grounded in the lyrics."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        message = response.json()["message"]
        self.assertEqual(message["participant"], "user")
        self.assertEqual(message["recipient"], "both")
        self.assertEqual(message["metadata"]["priority"], "user")

    def test_user_approval_advances_the_pipeline(self):
        production = self.create_production().json()
        production_id = production["id"]
        decision = add_decision(production_id, "treatment_consultation", "Treatment", "Ready")
        from backend.production_db import update_production
        update_production(production_id, status="awaiting_user", stage="treatment_review")
        response = self.client.post(
            f"/api/productions/{production_id}/decisions/{decision['id']}/approve",
            headers={"X-CSRF-Token": self.token}, json={"resolution": "Proceed"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["stage"], "reference_development")
        self.assertEqual(response.json()["status"], "queued")

    def test_agent_settings_require_csrf(self):
        body = {"codex_runtime": "codex", "codex_model": "gpt-5.6-sol", "codex_effort": "high",
                "agy_runtime": "agy", "agy_model": "gemini-3.1-pro-high", "agy_effort": "high"}
        self.assertEqual(self.client.patch("/api/settings/agents", json=body).status_code, 403)
        response = self.client.patch("/api/settings/agents", json=body, headers={"X-CSRF-Token": self.token})
        self.assertEqual(response.status_code, 200, response.text)

    def test_shot_plan_attempts_and_artifacts_are_exposed_without_local_paths(self):
        production = self.create_production().json()
        shots = replace_shot_plan(production["id"], [{
            "title": "Opening", "prompt": "A deliberate opening action", "mode": "text",
            "continuity": "hard_cut", "duration": 5, "megapixels": 1.5,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v1",
        }])
        video = self.root / "result.mp4"
        video.write_bytes(b"video")
        attempt = create_shot_attempt(shots[0]["id"], 1)
        update_shot_attempt(attempt["id"], status="accepted", output_path=str(video), frames=[])
        artifact = add_artifact(production["id"], "final_video", str(video))

        detail = self.client.get(f"/api/productions/{production['id']}").json()
        self.assertEqual(detail["shots"][0]["megapixels"], 1.5)
        self.assertTrue(detail["shots"][0]["attempts"][0]["output_path"].startswith("/api/"))
        self.assertNotIn("path", detail["artifacts"][0])
        download = self.client.get(f"/api/productions/{production['id']}/artifacts/{artifact['id']}")
        self.assertEqual(download.status_code, 200)

    def test_final_user_approval_is_the_only_completion_transition(self):
        production = self.create_production().json()
        decision = add_decision(production["id"], "final_review", "Final", "Ready")
        from backend.production_db import update_production
        update_production(production["id"], status="awaiting_user", stage="user_review", progress=.99)
        response = self.client.post(
            f"/api/productions/{production['id']}/decisions/{decision['id']}/approve",
            headers={"X-CSRF-Token": self.token}, json={"resolution": "Approved final"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(response.json()["stage"], "completed")

    def test_prompt_shots_are_normalized_to_silent_six_step_jobs(self):
        shots = production_orchestrator._normalize_shots([{
            "title": "Street", "video_prompt": "A car moves forward through the street",
            "duration": 10, "continuity": "sequential", "megapixels": .7,
        }], "hybrid")
        self.assertEqual(shots[0]["steps"], 6)
        self.assertEqual(shots[0]["megapixels"], .7)
        self.assertEqual(shots[0]["mode"], "text")  # the first shot cannot inherit a previous frame

    def test_reference_upload_assignment_and_targeted_retry(self):
        production = self.create_production().json()
        image = io.BytesIO()
        Image.new("RGB", (64, 64), "purple").save(image, "PNG")
        uploaded = self.client.post(
            f"/api/productions/{production['id']}/references",
            headers={"X-CSRF-Token": self.token},
            files={"media": ("hero.png", image.getvalue(), "image/png")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        reference = uploaded.json()
        shots = replace_shot_plan(production["id"], [{
            "title": "Hero", "prompt": "Hero walks forward", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 1.5,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v1",
        }])
        edited = self.client.patch(
            f"/api/productions/{production['id']}/shots/{shots[0]['id']}",
            headers={"X-CSRF-Token": self.token},
            json={"mode": "opening", "continuity": "hard_cut", "reference_ids": [reference["id"]]},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["shots"][0]["reference_ids"], [reference["id"]])
        retried = self.client.post(
            f"/api/productions/{production['id']}/shots/{shots[0]['id']}/retry",
            headers={"X-CSRF-Token": self.token}, json={"regenerate_downstream": True},
        )
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["stage"], "shot_generation")
        self.assertEqual(retried.json()["status"], "queued")

    def test_production_reference_limits_match_the_ui_contract(self):
        production = self.create_production().json()
        image = io.BytesIO(); Image.new("RGB", (16, 16), "blue").save(image, "PNG")
        payload = image.getvalue()
        for index in range(9):
            response = self.client.post(
                f"/api/productions/{production['id']}/references",
                headers={"X-CSRF-Token": self.token},
                files={"media": (f"ref-{index}.png", payload, "image/png")},
            )
            self.assertEqual(response.status_code, 200, response.text)
        rejected = self.client.post(
            f"/api/productions/{production['id']}/references",
            headers={"X-CSRF-Token": self.token},
            files={"media": ("ref-10.png", payload, "image/png")},
        )
        self.assertEqual(rejected.status_code, 409)

    def test_paused_production_configuration_creates_revision(self):
        production = self.create_production().json()
        from backend.production_db import update_production
        update_production(production["id"], status="paused")
        response = self.client.patch(
            f"/api/productions/{production['id']}/settings",
            headers={"X-CSRF-Token": self.token},
            json={
                "participation_mode": "autonomous", "continuity_mode": "sequential",
                "codex_runtime": "agy", "codex_model": "gemini-3.1-pro-high", "codex_effort": "high",
                "agy_runtime": "agy", "agy_model": "gemini-3.1-pro-high", "agy_effort": "high",
                "skills": [], "reason": "Use Gemini in both seats",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["codex_runtime"], "agy")
        self.assertEqual(len(response.json()["configuration_revisions"]), 1)

    def test_r2v_shot_uses_assigned_references_and_stays_silent(self):
        production = self.create_production().json()
        image = io.BytesIO(); Image.new("RGB", (64, 64), "blue").save(image, "PNG")
        reference = self.client.post(
            f"/api/productions/{production['id']}/references",
            headers={"X-CSRF-Token": self.token},
            files={"media": ("reference.png", image.getvalue(), "image/png")},
        ).json()
        shot = replace_shot_plan(production["id"], [{
            "title": "R2V", "prompt": "Use the referenced character", "mode": "reference",
            "continuity": "hard_cut", "duration": 5, "megapixels": .7, "aspect_ratio": "16:9",
            "steps": 4, "engine": "turbo", "turbo_profile": "v1", "reference_ids": [reference["id"]],
        }])[0]
        class Queue:
            def notify(self): pass
        original = production_orchestrator.queue_worker
        production_orchestrator.bind_queue(Queue())
        try:
            job_id = production_orchestrator._queue_job({**shot, "production_id": production["id"]}, None)
        finally:
            production_orchestrator.queue_worker = original
        from backend.db import get_job
        job = get_job(job_id, public=False)
        self.assertEqual(job["mode"], "reference")
        self.assertEqual(job["no_audio"], 1)
        self.assertIn(reference["comfy_name"], json.loads(job["reference_images_json"]))

    def test_reference_stills_are_generated_reviewed_and_registered_without_comfy(self):
        production = get_production(self.create_production().json()["id"], private=True)

        async def create_image(_production_id, _prompt, output_path, _model, _effort):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (128, 72), "orange").save(output_path, "PNG")
            return output_path

        approved = AgentResult(
            "agy", {"summary": "Usable", "decision": "APPROVE", "next_action": "continue",
                    "content": {}, "requires_user": False}, "", None, "test", "high",
        )
        package = {"references": [{"name": "Hero", "kind": "character", "image_prompt": "A grounded hero reference"}]}
        with patch.object(process_manager, "generate_reference_image", new=AsyncMock(side_effect=create_image)), \
             patch.object(production_orchestrator, "_agy", new=AsyncMock(return_value=approved)), \
             patch.object(production_orchestrator, "_codex", new=AsyncMock(return_value=approved)):
            generated = asyncio.run(production_orchestrator._generate_reference_stills(production, package))
        self.assertEqual(len(generated), 1)
        self.assertTrue(Path(generated[0]["path"]).is_file())
        self.assertTrue(Path(generated[0]["comfy_path"]).is_file())

    def test_manual_reference_generation_api_uses_selected_provider(self):
        production = self.create_production().json()

        async def generated(production_id, name, prompt, provider):
            stored = self.root / "productions" / production_id / "references" / "manual.png"
            comfy = self.root / "input" / "manual.png"
            stored.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (128, 72), "teal").save(stored, "PNG")
            Image.new("RGB", (128, 72), "teal").save(comfy, "PNG")
            return add_reference(production_id, "image", name, str(stored), str(comfy), comfy.name, prompt)

        with patch.object(production_orchestrator, "generate_manual_reference", new=AsyncMock(side_effect=generated)) as mocked:
            response = self.client.post(
                f"/api/productions/{production['id']}/references/generate",
                headers={"X-CSRF-Token": self.token},
                json={"name": "Night hero", "prompt": "Long dreadlocks and reflective sunglasses", "provider": "agy"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["reference"]["name"], "Night hero")
        self.assertEqual(response.json()["production"]["references"][0]["kind"], "image")
        mocked.assert_awaited_once_with(
            production["id"], "Night hero", "Long dreadlocks and reflective sunglasses", "agy",
        )

    def test_scheduler_can_run_two_productions_concurrently(self):
        first = get_production(self.create_production().json()["id"], private=True)
        second = get_production(self.create_production().json()["id"], private=True)
        orchestrator = ProductionOrchestrator()
        waiting = [first, second]
        started: list[str] = []
        both_started = asyncio.Event()
        release = asyncio.Event()

        def next_production(excluded=None):
            excluded = excluded or set()
            return next((item for item in waiting if item["id"] not in excluded and item["id"] not in started), None)

        async def run_stage(production_id):
            started.append(production_id)
            if len(started) == 2:
                both_started.set()
            await release.wait()

        orchestrator._next = next_production
        orchestrator._run_stage = run_stage

        async def exercise():
            with patch.object(production_module, "PRODUCTION_CONCURRENCY", 2):
                task = asyncio.create_task(orchestrator.loop())
                await asyncio.wait_for(both_started.wait(), timeout=2)
                self.assertEqual(set(orchestrator.active_productions), {first["id"], second["id"]})
                release.set()
                orchestrator.stopping = True
                orchestrator.wake.set()
                await asyncio.wait_for(task, timeout=2)

        asyncio.run(exercise())

    def test_duplicate_preserves_plan_and_remaps_references(self):
        production = self.create_production().json()
        image = io.BytesIO(); Image.new("RGB", (64, 64), "green").save(image, "PNG")
        reference = self.client.post(
            f"/api/productions/{production['id']}/references",
            headers={"X-CSRF-Token": self.token},
            files={"media": ("hero.png", image.getvalue(), "image/png")},
        ).json()
        replace_shot_plan(production["id"], [{
            "title": "Hero", "prompt": "Hero turns toward camera", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 1.5,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v1",
            "reference_ids": [reference["id"]],
        }])
        response = self.client.post(
            f"/api/productions/{production['id']}/duplicate", headers={"X-CSRF-Token": self.token},
        )
        self.assertEqual(response.status_code, 200, response.text)
        duplicate = response.json()
        self.assertEqual(len(duplicate["references"]), 1)
        self.assertEqual(len(duplicate["shots"]), 1)
        self.assertNotEqual(duplicate["references"][0]["id"], reference["id"])
        self.assertEqual(duplicate["shots"][0]["reference_ids"], [duplicate["references"][0]["id"]])

        archived = self.client.patch(
            f"/api/productions/{duplicate['id']}/archive", headers={"X-CSRF-Token": self.token},
            json={"archived": True},
        )
        self.assertTrue(archived.json()["archived"])
        exported = self.client.get(f"/api/productions/{duplicate['id']}/export")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.headers["content-type"], "application/zip")

        deleted = self.client.delete(
            f"/api/productions/{duplicate['id']}", headers={"X-CSRF-Token": self.token},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.get(f"/api/productions/{duplicate['id']}").status_code, 404)

    def test_completed_regular_job_can_be_imported(self):
        production = self.create_production().json()
        video = self.root / "regular-result.mp4"
        video.write_bytes(b"video")
        from backend.db import connect, now_iso
        timestamp = now_iso()
        with connect() as db:
            db.execute(
                """INSERT INTO jobs
                   (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,megapixels,
                    aspect_ratio,seed,status,position,output_path,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("regular-complete", "Imported action", "text", 5, "turbo", "v1", "native", 6,
                 1216, 704, .86, "16:9", "42", "completed", 1, str(video), timestamp, timestamp),
            )
        response = self.client.post(
            f"/api/productions/{production['id']}/imports/jobs",
            headers={"X-CSRF-Token": self.token}, json={"job_ids": ["regular-complete"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["shots"][0]["status"], "accepted")
        self.assertEqual(response.json()["shots"][0]["attempts"][0]["job_id"], "regular-complete")


class SkillCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="skill-catalog-test-")
        self.root = Path(self.temp.name)
        self.original_db = db_module.DB_PATH
        db_module.DB_PATH = self.root / "jobs.sqlite3"
        db_module.init_db()
        init_production_db()
        self.managed = self.root / "managed"
        self.managed.mkdir()
        self.patch = patch.object(skill_module, "MANAGED_SKILLS", self.managed)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        db_module.DB_PATH = self.original_db
        self.temp.cleanup()

    def package(self) -> Path:
        package = self.root / "skill.zip"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("SKILL.md", "---\nname: test-skill\ndescription: Test production skill\n---\n\n# Test\n")
        return package

    def test_managed_skill_can_be_disabled_and_deleted(self):
        skill = skill_module.install_skill_zip(self.package())
        self.assertTrue(skill["managed"])
        self.assertTrue(skill_module.set_skill_enabled(skill["id"], False)["enabled"] is False)
        path = Path(skill["path"])
        skill_module.remove_skill(skill["id"], "complete")
        self.assertFalse(path.exists())

    def test_external_skill_cannot_be_deleted_completely(self):
        external = self.root / "external"
        external.mkdir()
        (external / "SKILL.md").write_text("---\nname: external\ndescription: External\n---\n", encoding="utf-8")
        skill = skill_module.register_skill(str(external))
        with self.assertRaises(PermissionError):
            skill_module.remove_skill(skill["id"], "complete")
        self.assertTrue(external.exists())


class AgentParsingTests(unittest.TestCase):
    def test_auto_image_provider_falls_back_from_codex_to_agy(self):
        expected = Path("reference.png")
        with patch.object(process_manager, "_generate_reference_image_codex", new=AsyncMock(side_effect=RuntimeError("unavailable"))) as codex, \
             patch.object(process_manager, "_generate_reference_image_agy", new=AsyncMock(return_value=expected)) as agy:
            result = asyncio.run(process_manager.generate_reference_image(
                "production", "prompt", expected, "gpt-test", "high", provider="auto",
                agy_model="gemini-test", agy_effort="high",
            ))
        self.assertEqual(result, expected)
        codex.assert_awaited_once()
        agy.assert_awaited_once()

    def test_codex_jsonl_response_and_session_are_extracted(self):
        payload = {"summary": "Ready", "decision": "approve", "next_action": "continue", "requires_user": False}
        stdout = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "session-123"}),
            json.dumps({"type": "item.completed", "text": json.dumps(payload)}),
        ])
        result, session = _extract_result(stdout)
        self.assertEqual(result["decision"], "approve")
        self.assertEqual(session, "session-123")

    def test_codex_catalog_is_discovered_from_cli(self):
        payload = {"models": [{
            "slug": "gpt-test", "display_name": "GPT Test", "visibility": "list",
            "default_reasoning_level": "high",
            "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
        }]}
        with patch("backend.agents._command_path", return_value="codex"), \
             patch("backend.agents._run_model_command", return_value=json.dumps(payload)):
            models = discover_codex_models()
        self.assertEqual(models[0]["id"], "gpt-test")
        self.assertEqual(models[0]["efforts"], ["low", "high"])


if __name__ == "__main__":
    unittest.main()
