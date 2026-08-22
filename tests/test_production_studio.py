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
from backend.agents import (AGENT_SCHEMA, AGY_RESPONSE_CONTRACT, AgentExecutionError, AgentResult, _extract_result,
                             _normalize_codex_result, discover_codex_models, process_manager)
from backend.main import app, production_orchestrator
from backend.production import ProductionOrchestrator
from backend.production_db import (add_decision, ensure_agent_settings,
                                   add_artifact, add_message, add_reference, create_shot_attempt, get_production,
                                   init_production_db, list_shots, replace_shot_plan,
                                   megapixels_for_duration, normalize_production_generation,
                                   update_production, update_shot_attempt)


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

    def test_project_generation_defaults_are_saved_and_validated(self):
        response = self.client.post(
            "/api/productions",
            headers={"X-CSRF-Token": self.token},
            data={
                "title": "Turbo v4 production", "lyrics": "Line one",
                "participation_mode": "autonomous", "continuity_mode": "hybrid",
                "generation_turbo_profile": "v4", "generation_steps": "6",
                "generation_megapixels": "0.7", "skills_json": "[]", "approval_gates_json": "[]",
            },
            files={"song": ("song.wav", b"RIFF-test", "audio/wav")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()
        self.assertEqual(created["generation_turbo_profile"], "v4")
        self.assertEqual(created["generation_steps"], 6)
        self.assertEqual(created["generation_megapixels"], 0.7)

    def test_generation_policy_stores_resolution_and_duration_rules(self):
        rules = [
            {"max_duration": 5, "megapixels": 1.5},
            {"max_duration": 8, "megapixels": 1.0},
            {"max_duration": 10, "megapixels": 0.7},
            {"max_duration": 11, "megapixels": 0.6},
            {"max_duration": 15, "megapixels": 0.5},
        ]
        response = self.client.post(
            "/api/productions",
            headers={"X-CSRF-Token": self.token},
            data={
                "title": "Policy production", "lyrics": "Line one",
                "participation_mode": "autonomous", "continuity_mode": "hybrid",
                "generation_aspect_ratio": "1:1",
                "generation_megapixel_rules_json": json.dumps(rules),
                "skills_json": "[]", "approval_gates_json": "[]",
            },
            files={"song": ("song.wav", b"RIFF-test", "audio/wav")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()
        self.assertEqual(created["generation_aspect_ratio"], "1:1")
        self.assertEqual(created["generation_megapixel_rules"], rules)
        self.assertEqual(megapixels_for_duration(5, rules), 1.5)
        self.assertEqual(megapixels_for_duration(8, rules), 1.0)
        self.assertEqual(megapixels_for_duration(10, rules), 0.7)
        self.assertEqual(megapixels_for_duration(11, rules), 0.6)
        self.assertEqual(megapixels_for_duration(15, rules), 0.5)

    def test_normalize_production_generation_rejects_incomplete_policy(self):
        with self.assertRaisesRegex(ValueError, "last megapixel rule"):
            normalize_production_generation(
                "v4", 6, 0.7, "16:9",
                [{"max_duration": 5, "megapixels": 1.5}],
            )

        invalid = self.client.post(
            "/api/productions",
            headers={"X-CSRF-Token": self.token},
            data={
                "title": "Invalid Turbo v4", "lyrics": "Line one",
                "generation_turbo_profile": "v4", "generation_steps": "12",
                "skills_json": "[]", "approval_gates_json": "[]",
            },
            files={"song": ("song.wav", b"RIFF-test", "audio/wav")},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("between 4 and 8", invalid.text)

    def test_create_production_accepts_optional_source_references_before_agent_start(self):
        image = io.BytesIO()
        Image.new("RGB", (32, 32), "green").save(image, "PNG")
        response = self.client.post(
            "/api/productions",
            headers={"X-CSRF-Token": self.token},
            data={
                "title": "Reference-led production", "lyrics": "Line one",
                "participation_mode": "autonomous", "continuity_mode": "hybrid",
                "skills_json": "[]", "approval_gates_json": "[]",
            },
            files=[
                ("song", ("song.wav", b"RIFF-test", "audio/wav")),
                ("reference_files", ("hero.png", image.getvalue(), "image/png")),
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        references = response.json()["references"]
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["name"], "hero.png")
        self.assertEqual(references[0]["kind"], "image")

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

    def test_intervention_interrupts_active_production_and_queues_resume(self):
        production = self.create_production().json()
        production_id = production["id"]
        update_production(
            production_id, status="running", stage="prompt_consultation",
            codex_session_id="codex-session", agy_session_id="agy-session",
        )
        with patch.object(production_orchestrator, "cancel_agents", new=AsyncMock()) as cancel_agents, \
             patch.object(production_orchestrator, "cancel_generation", new=AsyncMock(return_value=True)) as cancel_generation:
            response = self.client.post(
                f"/api/productions/{production_id}/interventions",
                headers={"X-CSRF-Token": self.token},
                json={"recipient": "both", "content": "Stop and address this before generating another shot."},
            )
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()["production"]
        self.assertEqual(detail["status"], "queued")
        self.assertTrue(detail["intervention_requested"])
        self.assertTrue(cancel_agents.await_count)
        self.assertTrue(cancel_generation.await_count)
        self.assertTrue(any("Stop and address this" in item["content"] for item in detail["messages"]))
        self.assertTrue(any("Stopping the current agent work" in item["content"] for item in detail["messages"]))

    def test_agent_context_routes_intervention_to_its_recipient(self):
        production = self.create_production().json()
        production_id = production["id"]
        add_message(production_id, "user", "codex", "intervention", "Codex-only camera correction")
        add_message(production_id, "user", "agy", "intervention", "AGY-only audio correction")
        private = get_production(production_id, private=True)
        orchestrator = ProductionOrchestrator()
        codex_context = orchestrator._base_context(private, "codex")
        agy_context = orchestrator._base_context(private, "agy")
        self.assertIn("Codex-only camera correction", codex_context)
        self.assertNotIn("AGY-only audio correction", codex_context)
        self.assertIn("AGY-only audio correction", agy_context)
        self.assertNotIn("Codex-only camera correction", agy_context)

    def test_intervention_is_consumed_at_safe_checkpoint(self):
        production = self.create_production().json()
        production_id = production["id"]
        update_production(production_id, status="running", intervention_requested=1)
        orchestrator = ProductionOrchestrator()
        self.assertTrue(orchestrator._control_requested(production_id))
        current = get_production(production_id, private=True)
        self.assertEqual(current["status"], "queued")
        self.assertFalse(current["intervention_requested"])

    def test_structured_agent_summary_is_serialized_for_message_storage(self):
        production = self.create_production().json()
        message = add_message(
            production["id"], "agy", "all", "agent", {"decision": "APPROVE", "notes": ["usable"]},
        )
        self.assertIn('"decision": "APPROVE"', message["content"])
        detail = self.client.get(f"/api/productions/{production['id']}").json()
        self.assertEqual(detail["messages"][-1]["content"], message["content"])

    def test_structured_decision_summary_is_serialized_for_decision_storage(self):
        production = self.create_production().json()
        decision = add_decision(
            production["id"], "prompt_consultation", "Prompt package",
            {"summary": "Ready", "confidence": 0.9},
        )
        self.assertIn('"summary": "Ready"', decision["summary"])
        detail = self.client.get(f"/api/productions/{production['id']}").json()
        self.assertEqual(detail["decisions"][-1]["summary"], decision["summary"])

    def test_agent_trace_filters_transport_noise_but_keeps_real_errors(self):
        transport = (
            "2026-08-22 WARN codex_core::responses_retry: stream disconnected - "
            "retrying sampling request (5/5); websocket closed by server before response.completed"
        )
        self.assertIsNone(ProductionOrchestrator._format_agent_trace("codex", "codex", "stderr", transport))
        self.assertIsNone(ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stdout", json.dumps({"type": "error"}),
        ))
        self.assertIsNone(ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stderr",
            "WARN codex_core::shell_snapshot: Failed to create shell snapshot for PowerShell: "
            "Shell snapshot not supported yet for PowerShell",
        ))
        self.assertIsNone(ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stderr",
            "WARN codex_skills::interface: ignoring interface.icon_small: icon path with '..' "
            "must resolve under plugin assets/",
        ))
        self.assertIsNone(ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stderr", "WARN codex_core::client: falling back to HTTP",
        ))
        self.assertIsNone(ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stderr",
            "WARN codex_core_plugins::manager: failed to refresh cached remote plugin catalog",
        ))
        self.assertIsNone(ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stderr",
            "WARN codex_core::hook_runtime: after_agent hook failed; continuing turn",
        ))
        self.assertIsNone(ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stdout", json.dumps({"type": "item.completed"}),
        ))
        real = ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stdout", json.dumps({"type": "error", "message": "quota exceeded"}),
        )
        self.assertIsNotNone(real)
        self.assertEqual(real[1], "error")
        self.assertIn("quota exceeded", real[0])

    def test_agent_trace_keeps_explicit_reasoning_summary_and_plain_response(self):
        reasoning = ProductionOrchestrator._format_agent_trace(
            "agy", "agy", "stdout", json.dumps({
                "type": "item.completed",
                "item": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "The lighting remains consistent."}]},
            }),
        )
        self.assertIsNotNone(reasoning)
        self.assertIn("reasoning summary", reasoning[0])
        self.assertIn("lighting remains consistent", reasoning[0])
        response = ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stdout", json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "I will continue with shot two."},
            }),
        )
        self.assertIsNotNone(response)
        self.assertIn("I will continue with shot two", response[0])

    def test_agent_reply_is_recorded_as_safe_live_summary(self):
        production = self.create_production().json()
        result = AgentResult(
            "agy",
            {
                "summary": "The opening frame is usable.",
                "decision": "APPROVE",
                "next_action": "Continue to the next shot.",
                "content": {"findings": "The performer and lighting remain consistent."},
                "issues": [],
            },
            "private reasoning must never be shown",
            "agy-session",
            "test-model",
            "high",
        )
        ProductionOrchestrator()._record_agent_reply(
            get_production(production["id"], private=True), result,
        )
        detail = self.client.get(f"/api/productions/{production['id']}").json()
        message = detail["messages"][-1]
        self.assertEqual(message["kind"], "agent_trace")
        self.assertEqual(message["metadata"]["stream"], "response")
        self.assertIn("The opening frame is usable", message["content"])
        self.assertIn("Decision: APPROVE", message["content"])
        self.assertIn("Next: Continue to the next shot", message["content"])
        self.assertIn("Findings: The performer and lighting remain consistent", message["content"])
        self.assertNotIn("private reasoning", message["content"])

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

    def test_project_generation_defaults_override_agent_precision(self):
        shots = production_orchestrator._normalize_shots([{
            "title": "Turbo shot", "prompt": "The rapper moves with the beat",
            "duration": 5, "megapixels": 0.692224, "steps": 4, "turbo_profile": "v1",
        }], "hybrid", [], {
            "generation_turbo_profile": "v4", "generation_steps": 6, "generation_megapixels": 0.7,
        })
        self.assertEqual(shots[0]["turbo_profile"], "v4")
        self.assertEqual(shots[0]["steps"], 6)
        self.assertEqual(shots[0]["megapixels"], 0.7)

    def test_project_generation_policy_selects_mp_for_each_duration(self):
        rules = [
            {"max_duration": 5, "megapixels": 1.5},
            {"max_duration": 8, "megapixels": 1.0},
            {"max_duration": 10, "megapixels": 0.7},
            {"max_duration": 11, "megapixels": 0.6},
            {"max_duration": 15, "megapixels": 0.5},
        ]
        shots = production_orchestrator._normalize_shots([
            {"title": f"Shot {duration}", "prompt": "A controlled camera move", "duration": duration}
            for duration in (5, 8, 10, 11, 15)
        ], "hybrid", [], {
            "generation_turbo_profile": "v4", "generation_steps": 6,
            "generation_megapixels": 0.7, "generation_aspect_ratio": "1:1",
            "generation_megapixel_rules": rules,
        })
        self.assertEqual([shot["megapixels"] for shot in shots], [1.5, 1.0, 0.7, 0.6, 0.5])
        self.assertEqual({shot["aspect_ratio"] for shot in shots}, {"1:1"})

    def test_prompt_references_become_i2v_and_audio_is_independent_from_continuity(self):
        references = [
            {"id": "hero", "name": "Hero.png", "kind": "image"},
            {"id": "voice", "name": "Voice.wav", "kind": "audio"},
        ]
        shots = production_orchestrator._normalize_shots([{
            "title": "Hero close-up", "prompt": "The hero turns toward camera",
            "mode": "r2v", "reference_names": ["Hero.png"], "continuity": "hard_cut",
            "duration": 5, "audio_mode": "lip_sync", "audio_source": "reference",
            "audio_reference": "Voice.wav", "audio_start": 3.5, "audio_duration": 5,
            "steps": "not-a-number",
        }], "hybrid", references)
        self.assertEqual(shots[0]["mode"], "opening")
        self.assertEqual(shots[0]["continuity"], "hard_cut")
        self.assertEqual(shots[0]["reference_ids"], ["hero"])
        self.assertEqual(shots[0]["audio_mode"], "lip_sync")
        self.assertEqual(shots[0]["audio_source"], "reference")
        self.assertEqual(shots[0]["audio_reference_id"], "voice")
        self.assertEqual(shots[0]["audio_start"], 3.5)
        self.assertEqual(shots[0]["steps"], 4)

    def test_available_image_references_prevent_accidental_t2v(self):
        references = [
            {"id": "hero", "name": "rapper_identity_master", "kind": "image", "notes": "Primary rapper identity anchor"},
        ]
        shots = production_orchestrator._normalize_shots([{
            "title": "Rooftop reset", "prompt": "The rapper performs on the rooftop",
            "mode": "t2v", "continuity": "hard_cut", "duration": 8,
        }], "hybrid", references)
        self.assertEqual(shots[0]["mode"], "opening")
        self.assertEqual(shots[0]["reference_ids"], ["hero"])

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
        profile_updated = self.client.patch(
            f"/api/productions/{production['id']}/shots/{shots[0]['id']}",
            headers={"X-CSRF-Token": self.token},
            json={"turbo_profile": "v4", "steps": 6},
        )
        self.assertEqual(profile_updated.status_code, 200, profile_updated.text)
        self.assertEqual(profile_updated.json()["shots"][0]["turbo_profile"], "v4")
        self.assertEqual(profile_updated.json()["shots"][0]["steps"], 6)
        invalid_profile = self.client.patch(
            f"/api/productions/{production['id']}/shots/{shots[0]['id']}",
            headers={"X-CSRF-Token": self.token},
            json={"turbo_profile": "v4", "steps": 9},
        )
        self.assertEqual(invalid_profile.status_code, 400)
        self.assertIn("4 to 8", invalid_profile.text)
        retried = self.client.post(
            f"/api/productions/{production['id']}/shots/{shots[0]['id']}/retry",
            headers={"X-CSRF-Token": self.token}, json={"regenerate_downstream": True},
        )
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["stage"], "shot_generation")
        self.assertEqual(retried.json()["status"], "queued")

    def test_lip_sync_shot_prepares_audio_segment_and_uses_native_audio_lock_job(self):
        production = self.create_production().json()
        source_audio = self.root / "voice.wav"
        source_audio.write_bytes(b"source")
        comfy_audio = self.root / "input" / "voice.wav"
        comfy_audio.write_bytes(b"source")
        audio_reference = add_reference(
            production["id"], "audio", "Voice.wav", str(source_audio),
            str(comfy_audio), comfy_audio.name,
        )
        shot = replace_shot_plan(production["id"], [{
            "title": "Dialogue", "prompt": "The character speaks to camera", "mode": "opening",
            "continuity": "hard_cut", "audio_mode": "lip_sync", "audio_source": "reference",
            "audio_start": 2.5, "audio_duration": 5, "audio_reference_id": audio_reference["id"],
            "duration": 5, "megapixels": 1.5, "aspect_ratio": "16:9", "steps": 4,
            "engine": "turbo", "turbo_profile": "v1", "reference_ids": [audio_reference["id"]],
        }])[0]

        class Queue:
            def notify(self): pass

        def fake_prepare(_source, target, _start, _duration):
            target.write_bytes(b"prepared wav")
            return target

        original = production_orchestrator.queue_worker
        production_orchestrator.bind_queue(Queue())
        try:
            with patch.object(production_module, "prepare_audio_segment", side_effect=fake_prepare):
                job_id = production_orchestrator._queue_job({**shot, "production_id": production["id"]}, None)
        finally:
            production_orchestrator.queue_worker = original
        from backend.db import get_job
        job = get_job(job_id, public=False)
        self.assertEqual(job["mode"], "lip_sync")
        self.assertEqual(job["no_audio"], 0)
        self.assertEqual(job["audio_start"], 0)
        self.assertEqual(job["reference_audio_name"], f"production_{production['id']}_shot_001_audio.wav")

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

    def test_assigned_i2v_references_are_rendered_into_a_shot_opening_frame(self):
        production = get_production(self.create_production().json()["id"], private=True)
        source_path = self.root / "productions" / production["id"] / "references" / "hero.png"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (128, 72), "navy").save(source_path, "PNG")
        source_comfy = self.root / "input" / "hero.png"
        Image.new("RGB", (128, 72), "navy").save(source_comfy, "PNG")
        reference = add_reference(
            production["id"], "image", "Hero", str(source_path), str(source_comfy), source_comfy.name,
        )
        shot = replace_shot_plan(production["id"], [{
            "title": "Hero entrance", "prompt": "The hero enters the room", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 0.7, "aspect_ratio": "16:9",
            "steps": 6, "engine": "turbo", "turbo_profile": "v1", "reference_ids": [reference["id"]],
        }])[0]

        async def create_image(_production_id, _prompt, output_path, _model, _effort, **_kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (128, 72), "orange").save(output_path, "PNG")
            return output_path

        with patch.object(process_manager, "generate_reference_image", new=AsyncMock(side_effect=create_image)) as generator:
            artifact, comfy_input = asyncio.run(
                production_orchestrator._generate_shot_opening_frame(production, shot, 1)
            )

        self.assertTrue(artifact.is_file())
        self.assertTrue(comfy_input.is_file())
        self.assertEqual(generator.await_args.kwargs["source_images"], [source_path])
        self.assertNotEqual(artifact, source_path)

    def test_sequential_assigned_references_compose_a_new_frame_with_last_frame_context(self):
        production = get_production(self.create_production().json()["id"], private=True)
        source_path = self.root / "productions" / production["id"] / "references" / "basement.png"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (128, 72), "navy").save(source_path, "PNG")
        source_comfy = self.root / "input" / "basement.png"
        Image.new("RGB", (128, 72), "navy").save(source_comfy, "PNG")
        reference = add_reference(
            production["id"], "image", "Basement", str(source_path), str(source_comfy), source_comfy.name,
        )
        shot = replace_shot_plan(production["id"], [{
            "title": "Basement entrance", "prompt": "The rapper enters the basement beside the sampler", "mode": "opening",
            "continuity": "sequential", "duration": 5, "megapixels": 0.7, "aspect_ratio": "16:9",
            "steps": 6, "engine": "turbo", "turbo_profile": "v1", "reference_ids": [reference["id"]],
        }])[0]
        previous_last = self.root / "input" / "previous-last.png"
        Image.new("RGB", (128, 72), "green").save(previous_last, "PNG")

        async def create_image(_production_id, _prompt, output_path, _model, _effort, **_kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (128, 72), "orange").save(output_path, "PNG")
            return output_path

        with patch.object(process_manager, "generate_reference_image", new=AsyncMock(side_effect=create_image)) as generator:
            artifact, comfy_input = asyncio.run(
                production_orchestrator._generate_shot_opening_frame(production, shot, 1, previous_last)
            )

        self.assertTrue(artifact.is_file())
        self.assertTrue(comfy_input.is_file())
        self.assertEqual(generator.await_args.kwargs["source_images"], [source_path, previous_last])
        self.assertIn("continuity context", generator.await_args.args[1])
        self.assertNotEqual(artifact, source_path)
        self.assertNotEqual(artifact, previous_last)

    def test_i2v_queue_never_sends_original_assigned_reference_directly(self):
        production = get_production(self.create_production().json()["id"], private=True)
        source_path = self.root / "productions" / production["id"] / "references" / "hero.png"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (128, 72), "navy").save(source_path, "PNG")
        source_comfy = self.root / "input" / "hero.png"
        Image.new("RGB", (128, 72), "navy").save(source_comfy, "PNG")
        reference = add_reference(
            production["id"], "image", "Hero", str(source_path), str(source_comfy), source_comfy.name,
        )
        shot = replace_shot_plan(production["id"], [{
            "title": "Hero entrance", "prompt": "The hero enters the room", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 0.7, "aspect_ratio": "16:9",
            "steps": 6, "engine": "turbo", "turbo_profile": "v1", "reference_ids": [reference["id"]],
        }])[0]
        opening = self.root / "input" / "generated-opening.png"
        Image.new("RGB", (128, 72), "orange").save(opening, "PNG")

        class Queue:
            def notify(self): pass

        original = production_orchestrator.queue_worker
        production_orchestrator.bind_queue(Queue())
        try:
            with self.assertRaisesRegex(RuntimeError, "no generated opening frame"):
                production_orchestrator._queue_job({**shot, "production_id": production["id"]}, None)
            job_id = production_orchestrator._queue_job({**shot, "production_id": production["id"]}, opening)
        finally:
            production_orchestrator.queue_worker = original
        from backend.db import get_job
        job = get_job(job_id, public=False)
        self.assertEqual(job["input_path"], str(opening))
        self.assertEqual(job["input_name"], opening.name)
        self.assertEqual(json.loads(job["reference_images_json"]), [])

    def test_review_decision_head_controls_status_and_approval_explanations(self):
        approved = AgentResult(
            "codex", {"decision": "APPROVE. The tiny label is not a rejection reason.", "summary": "Usable"},
            "", None, "test", "medium",
        )
        declined = AgentResult(
            "agy", {"decision": "REVISE. The opening action is not yet usable.", "summary": "Needs work"},
            "", None, "test", "high",
        )
        placeholder = AgentResult(
            "agy", {"summary": {"type": "string"}, "decision": {"type": "string"},
                    "next_action": {"type": "string"}, "content": {"type": ["string", "null"]},
                    "issues": [{"type": ["string", "null"]}]},
            "", None, "test", "high",
        )
        self.assertEqual(ProductionOrchestrator._agent_review_status(approved), "approved")
        self.assertEqual(ProductionOrchestrator._agent_review_status(declined), "rejected")
        self.assertEqual(ProductionOrchestrator._agent_review_status(placeholder), "unavailable")
        self.assertEqual(ProductionOrchestrator._joint_review_status(approved, placeholder)[0], "approved")

    def test_codex_test_exception_acceptance_overrides_agy_regeneration(self):
        agy = AgentResult(
            "agy", {
                "decision": "REGENERATE",
                "summary": "Known defects are preserved for this E2E test.",
            }, "", None, "test", "high",
        )
        codex = AgentResult(
            "codex", {
                "decision": "APPROVE_WITH_TEST_EXCEPTION",
                "summary": "Accept the shot for the user's flow test.",
            }, "", None, "test", "medium",
        )
        self.assertEqual(ProductionOrchestrator._agent_review_status(codex), "approved_exception")
        status, note = ProductionOrchestrator._joint_review_status(agy, codex)
        self.assertEqual(status, "approved")
        self.assertIn("test exception", note)

    def test_reference_stills_are_generated_reviewed_and_registered_without_comfy(self):
        production = get_production(self.create_production().json()["id"], private=True)
        source_path = self.root / "productions" / production["id"] / "references" / "source.png"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (128, 72), "navy").save(source_path, "PNG")
        source_comfy = self.root / "input" / "source.png"
        Image.new("RGB", (128, 72), "navy").save(source_comfy, "PNG")
        add_reference(production["id"], "image", "Source.png", str(source_path), str(source_comfy), source_comfy.name)

        async def create_image(_production_id, _prompt, output_path, _model, _effort, **_kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (128, 72), "orange").save(output_path, "PNG")
            return output_path

        approved = AgentResult(
            "agy", {"summary": "Usable", "decision": "APPROVE", "next_action": "continue",
                    "content": {}, "requires_user": False}, "", None, "test", "high",
        )
        package = {"references": [{"name": "Hero", "kind": "character", "image_prompt": "A grounded hero reference"}]}
        with patch.object(process_manager, "generate_reference_image", new=AsyncMock(side_effect=create_image)) as image_generator, \
             patch.object(production_orchestrator, "_agy", new=AsyncMock(return_value=approved)), \
             patch.object(production_orchestrator, "_codex", new=AsyncMock(return_value=approved)):
            generated = asyncio.run(production_orchestrator._generate_reference_stills(production, package))
        self.assertEqual(len(generated), 1)
        self.assertTrue(Path(generated[0]["path"]).is_file())
        self.assertTrue(Path(generated[0]["comfy_path"]).is_file())
        self.assertEqual(image_generator.await_args.kwargs["source_images"], [source_path])

    def test_reference_generation_retries_after_provider_handoff_failure(self):
        production = get_production(self.create_production().json()["id"], private=True)
        calls = 0

        async def create_image(_production_id, _prompt, output_path, _model, _effort, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("provider connection lost")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (128, 72), "orange").save(output_path, "PNG")
            return output_path

        approved = AgentResult(
            "agy", {"summary": "Usable", "decision": "APPROVE", "next_action": "continue",
                    "content": {}, "requires_user": False}, "", None, "test", "high",
        )
        package = {"references": [{"name": "Hero", "kind": "character", "image_prompt": "A grounded hero reference"}]}
        with patch.object(process_manager, "generate_reference_image", new=AsyncMock(side_effect=create_image)) as image_generator, \
             patch.object(production_orchestrator, "_agy", new=AsyncMock(return_value=approved)), \
             patch.object(production_orchestrator, "_codex", new=AsyncMock(return_value=approved)):
            generated = asyncio.run(production_orchestrator._generate_reference_stills(production, package))
        self.assertEqual(len(generated), 1)
        self.assertEqual(image_generator.await_count, 2)

    def test_reference_specs_decode_resumed_codex_text_wrapper(self):
        production = get_production(self.create_production().json()["id"], private=True)

        async def create_image(_production_id, _prompt, output_path, _model, _effort, **_kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (128, 72), "orange").save(output_path, "PNG")
            return output_path

        approved = AgentResult(
            "agy", {"summary": "Usable", "decision": "APPROVE", "next_action": "continue",
                    "content": {}, "requires_user": False}, "", None, "test", "high",
        )
        package = {"content": {"text": json.dumps({
            "references": [{"name": "Hero", "kind": "character", "image_prompt": "A grounded hero reference"}],
        })}}
        with patch.object(process_manager, "generate_reference_image", new=AsyncMock(side_effect=create_image)), \
             patch.object(production_orchestrator, "_agy", new=AsyncMock(return_value=approved)), \
             patch.object(production_orchestrator, "_codex", new=AsyncMock(return_value=approved)):
            generated = asyncio.run(production_orchestrator._generate_reference_stills(production, package))
        self.assertEqual(len(generated), 1)

    def test_codex_normalization_decodes_nested_text_content(self):
        payload = {"summary": "Ready", "decision": "approve", "next_action": "continue",
                   "content": {"text": json.dumps({"references": [{"name": "Hero"}]})},
                   "issues": None, "confidence": 1, "requires_user": False}
        normalized = _normalize_codex_result(payload)
        self.assertEqual(normalized["content"]["references"][0]["name"], "Hero")

    def test_agy_retries_stale_placeholder_in_fresh_session(self):
        production = get_production(self.create_production().json()["id"], private=True)
        production["agy_session_id"] = "stale-session"
        placeholder = AgentResult(
            "agy", {"summary": "I read the requested file.",
                    "decision": "I have successfully read the file and provided the requested response.",
                    "next_action": "None, the task is complete.", "content": None, "issues": []},
            "", "stale-session", "test", "high",
        )
        approved = AgentResult(
            "agy", {"summary": "Reviewed", "decision": "APPROVE", "next_action": "continue",
                    "content": {"findings": "usable"}, "issues": []},
            "", "fresh-session", "test", "high",
        )
        with patch.object(process_manager, "invoke", new=AsyncMock(side_effect=[placeholder, approved])) as invoke:
            result = asyncio.run(production_orchestrator._agy(production, "Inspect this reference image.", []))
        self.assertIs(result, approved)
        self.assertEqual(invoke.await_count, 2)
        self.assertIsNone(invoke.await_args_list[1].args[6])
        self.assertIn("Do not describe, echo, or reproduce the response schema", invoke.await_args_list[1].args[3])

    def test_agy_retries_schema_echo_in_fresh_session(self):
        production = get_production(self.create_production().json()["id"], private=True)
        placeholder = AgentResult(
            "agy", {"summary": {"type": "string"}, "decision": {"type": "string"},
                    "next_action": {"type": "string"}, "content": {"type": ["string", "null"]},
                    "issues": [{"type": ["string", "null"]}]},
            "", "schema-session", "test", "high",
        )
        approved = AgentResult(
            "agy", {"summary": "Reviewed", "decision": "APPROVE", "next_action": "continue",
                    "content": {"findings": "usable"}, "issues": []},
            "", "fresh-session", "test", "high",
        )
        with patch.object(process_manager, "invoke", new=AsyncMock(side_effect=[placeholder, approved])) as invoke:
            result = asyncio.run(production_orchestrator._agy(production, "Inspect this reference image.", []))
        self.assertIs(result, approved)
        self.assertEqual(invoke.await_count, 2)
        self.assertIsNone(invoke.await_args_list[1].args[6])

    def test_agy_schema_echo_with_new_issue_shape_is_retried(self):
        production = get_production(self.create_production().json()["id"], private=True)
        placeholder = AgentResult(
            "agy", {"summary": {"type": "string"}, "decision": {"type": "string"},
                    "next_action": {"type": "string"}, "content": {"type": ["object", "array", "string", "null"]},
                    "issues": [{"type": ["array", "null"]}]},
            "", "schema-session", "test", "high",
        )
        approved = AgentResult(
            "agy", {"summary": "Reviewed", "decision": "APPROVE", "next_action": "continue",
                    "content": {"findings": "usable"}, "issues": []},
            "", "fresh-session", "test", "high",
        )
        with patch.object(process_manager, "invoke", new=AsyncMock(side_effect=[placeholder, approved])) as invoke:
            result = asyncio.run(production_orchestrator._agy(production, "Inspect this reference image.", []))
        self.assertIs(result, approved)
        self.assertEqual(invoke.await_count, 2)
        self.assertIsNone(invoke.await_args_list[1].args[6])

    def test_agy_retries_contract_validation_failure_from_saved_session(self):
        production = get_production(self.create_production().json()["id"], private=True)
        production["agy_session_id"] = "stale-session"
        failure = AgentExecutionError(
            "agy CLI returned no valid structured response: Agent returned no valid structured response",
            runtime="agy", command=["agy"],
            stdout=json.dumps({"type": "error", "message": "invalid arguments: - at '/issues': got string, want null or array"}),
            returncode=0,
        )
        approved = AgentResult(
            "agy", {"summary": "Reviewed", "decision": "APPROVE", "next_action": "continue",
                    "content": {"findings": "usable"}, "issues": []},
            "", "fresh-session", "test", "high",
        )
        with patch.object(process_manager, "invoke", new=AsyncMock(side_effect=[failure, approved])) as invoke:
            result = asyncio.run(production_orchestrator._agy(production, "Inspect this reference image.", []))
        self.assertIs(result, approved)
        self.assertEqual(invoke.await_count, 2)
        self.assertIsNone(invoke.await_args_list[1].args[6])
        self.assertIn("Do not describe, echo, or reproduce the response schema", invoke.await_args_list[1].args[3])

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

    def test_reference_retry_endpoint_requeues_preserved_checkpoint(self):
        production = self.create_production().json()
        production_id = production["id"]
        from backend.production_db import update_production
        plan_path = self.root / "productions" / production_id / "references" / "reference_plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps({"codex_revision": {"references": []}}), encoding="utf-8")
        update_production(production_id, status="awaiting_user", stage="reference_generation", error="provider handoff failed")

        response = self.client.post(
            f"/api/productions/{production_id}/references/retry",
            headers={"X-CSRF-Token": self.token},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "queued")
        self.assertIsNone(response.json()["error"])


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

    def test_codex_reference_survives_cli_disconnect_after_file_write(self):
        with tempfile.TemporaryDirectory(prefix="reference-handoff-test-") as temp:
            root = Path(temp)
            production_root = root / "productions" / "production"
            target = production_root / "references" / "generated" / "attempt.png"

            async def write_then_disconnect(*_args, **_kwargs):
                target.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (32, 32), "orange").save(target, "PNG")
                raise RuntimeError("connection lost")

            with patch("backend.agents.PRODUCTIONS", root / "productions"), \
                 patch("backend.agents._command_path", return_value="codex"), \
                 patch.object(process_manager, "_run", new=AsyncMock(side_effect=write_then_disconnect)):
                result = asyncio.run(process_manager._generate_reference_image_codex(
                    "production", "A clean reference", target, "gpt-test", "high", [],
                ))

            self.assertEqual(result.resolve(), target.resolve())
            with Image.open(target) as image:
                self.assertEqual(image.size, (32, 32))

    def test_codex_jsonl_response_and_session_are_extracted(self):
        payload = {"summary": "Ready", "decision": "approve", "next_action": "continue", "requires_user": False}
        stdout = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "session-123"}),
            json.dumps({"type": "item.completed", "text": json.dumps(payload)}),
        ])
        result, session = _extract_result(stdout)
        self.assertEqual(result["decision"], "approve")
        self.assertEqual(session, "session-123")

    def test_concatenated_task_result_and_cli_finish_marker_are_extracted(self):
        payload = {
            "summary": "Reviewed",
            "decision": "APPROVE",
            "content": {"finding": "usable"},
            "issues": [],
            "next_action": "continue",
            "confidence": 0.95,
            "requires_user": False,
        }
        stdout = json.dumps({
            "event": "result",
            "result": {
                "status": "SUCCESS",
                "response": json.dumps(payload) + "\n" + json.dumps({
                    "toolAction": "Finishing the task",
                    "toolSummary": "Finish task",
                }),
            },
        })

        result, session = _extract_result(stdout)

        self.assertEqual(result, payload)
        self.assertIsNone(session)

    def test_codex_invocations_use_output_schema_for_new_and_resumed_sessions(self):
        payload = {"summary": "Ready", "decision": "approve", "next_action": "continue", "requires_user": False}
        stdout = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "session-123"}),
            json.dumps({"type": "item.completed", "text": json.dumps(payload)}),
        ])
        with patch("backend.agents._command_path", return_value="codex"), \
             patch("backend.agents._codex_schema_path", return_value=Path("schema.json")), \
             patch.object(process_manager, "_run", new=AsyncMock(return_value=stdout)) as runner:
            asyncio.run(process_manager.invoke_codex("production", "prompt", "gpt-test", "medium"))
            asyncio.run(process_manager.invoke_codex("production", "prompt", "gpt-test", "medium", session_id="session-123"))

        self.assertEqual(runner.await_count, 2)
        for call in runner.await_args_list:
            command = call.args[1]
            schema_index = command.index("--output-schema")
            self.assertEqual(command[schema_index + 1], "schema.json")

    def test_agy_schema_and_prompt_use_the_same_structured_contract(self):
        payload = {
            "summary": "Reviewed",
            "decision": "APPROVE",
            "content": {"findings": "usable"},
            "issues": [],
            "next_action": "continue",
            "confidence": 0.9,
            "requires_user": False,
        }
        stdout = json.dumps({"type": "item.completed", "text": json.dumps(payload)})
        with tempfile.TemporaryDirectory(prefix="agy-schema-test-") as temp:
            root = Path(temp)
            with patch("backend.agents.PRODUCTIONS", root / "productions"), \
                 patch("backend.agents._command_path", return_value="agy"), \
                 patch.object(process_manager, "_run", new=AsyncMock(return_value=stdout)) as runner:
                result = asyncio.run(process_manager.invoke_agy("production", "Inspect this asset.", "gemini-test", "high"))

            schema_path = root / "productions" / "production" / "agent-context" / "response.schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertEqual(schema, AGENT_SCHEMA)
            self.assertEqual(schema["type"], "object")
            self.assertTrue(schema["additionalProperties"])
            self.assertEqual(result.content["content"], {"findings": "usable"})

            command = runner.await_args.args[1]
            self.assertEqual(command[command.index("--output-format") + 1], "stream-json")
            self.assertIn("--json-schema", command)
            request_path = next((root / "productions" / "production" / "agent-context").glob("agy-request-*.md"))
            request = request_path.read_text(encoding="utf-8")
            self.assertIn(AGY_RESPONSE_CONTRACT, request)
            self.assertNotIn("JSON-encoded string", request)

    def test_agy_legacy_string_issues_are_normalized(self):
        payload = {
            "summary": "Reviewed",
            "decision": "REGENERATE",
            "content": {"findings": "needs correction"},
            "issues": "The opening frame has a visible continuity break.",
            "next_action": "Regenerate the opening frame.",
            "confidence": 0.8,
            "requires_user": False,
        }
        stdout = json.dumps({"type": "item.completed", "text": json.dumps(payload)})
        with tempfile.TemporaryDirectory(prefix="agy-legacy-issues-test-") as temp:
            root = Path(temp)
            with patch("backend.agents.PRODUCTIONS", root / "productions"), \
                 patch("backend.agents._command_path", return_value="agy"), \
                 patch.object(process_manager, "_run", new=AsyncMock(return_value=stdout)):
                result = asyncio.run(process_manager.invoke_agy("production", "Inspect this asset.", "gemini-test", "high"))

        self.assertEqual(result.content["issues"], [{"message": "The opening frame has a visible continuity break."}])

    def test_agy_result_envelope_extracts_response_json(self):
        payload = {
            "summary": "Reviewed",
            "decision": "APPROVE",
            "content": {"findings": "usable"},
            "issues": [],
            "next_action": "continue",
            "confidence": 0.96,
            "requires_user": False,
        }
        stdout = json.dumps({
            "event": "result",
            "result": {
                "conversation_id": "agy-session",
                "status": "SUCCESS",
                "response": json.dumps(payload),
                "structured_output": {},
            },
        })
        with tempfile.TemporaryDirectory(prefix="agy-result-envelope-test-") as temp:
            root = Path(temp)
            with patch("backend.agents.PRODUCTIONS", root / "productions"), \
                 patch("backend.agents._command_path", return_value="agy"), \
                 patch.object(process_manager, "_run", new=AsyncMock(return_value=stdout)):
                result = asyncio.run(process_manager.invoke_agy("production", "Inspect this asset.", "gemini-test", "high"))

        self.assertEqual(result.session_id, "agy-session")
        self.assertEqual(result.content["decision"], "APPROVE")
        self.assertEqual(result.content["content"], {"findings": "usable"})

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
