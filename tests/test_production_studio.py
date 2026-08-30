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
from backend.agents import (AGENT_SCHEMA, AGY_RESPONSE_CONTRACT, AgentExecutionError, AgentProcessManager,
                             AgentResult, GeneratedImageValidationError, _extract_result,
                             _normalize_codex_result, discover_codex_models, process_manager)
from backend.main import app, production_orchestrator
from backend.production import ProductionOrchestrator
from backend.media import prepare_agent_audio_carrier
from backend.production_db import (add_decision, ensure_agent_settings,
                                   add_artifact, add_message, add_reference, create_shot_attempt, get_production,
                                   init_production_db, list_messages, list_shots, replace_shot_plan,
                                   megapixels_for_duration, normalize_production_generation,
                                   recover_productions, update_production, update_shot, update_shot_attempt)


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

    def test_audio_analysis_requires_verified_media_inspection(self):
        carrier = self.root / "analysis" / "agy_audio_carrier.mp4"
        verified = AgentResult(
            "agy", {
                "summary": "Decoded the song.", "decision": "ANALYZED",
                "content": {
                    "media_inspection": {"decoded_audio": True, "inspected_path": str(carrier)},
                    "duration_seconds": 30.0, "bpm": 90, "sections": [{"name": "verse"}],
                    "vocal_entrances": [2.0], "lyric_timeline": [{"start": 2.0, "text": "line"}],
                },
                "issues": [], "next_action": "plan", "confidence": 0.9, "requires_user": False,
            }, "", None, "gemini-test", "high",
        )
        content = ProductionOrchestrator._validated_audio_analysis(verified, carrier, 30.0, 1)
        self.assertTrue(content["media_inspection"]["decoded_audio"])

        estimated = AgentResult(
            "agy", {**verified.content, "content": {"duration_seconds": 30.0, "bpm": 90}},
            "", None, "gemini-test", "high",
        )
        with self.assertRaisesRegex(RuntimeError, "did not confirm"):
            ProductionOrchestrator._validated_audio_analysis(estimated, carrier)

        wrong_duration = AgentResult(
            "agy", {
                **verified.content,
                "content": {**verified.content["content"], "duration_seconds": 45.0},
            }, "", None, "gemini-test", "high",
        )
        with self.assertRaisesRegex(RuntimeError, "decoded source"):
            ProductionOrchestrator._validated_audio_analysis(wrong_duration, carrier, 30.0, 1)

        duration_alias = AgentResult(
            "agy", {
                **verified.content,
                "content": {
                    **verified.content["content"],
                    "duration": 30.0,
                    "duration_seconds": None,
                },
            }, "", None, "gemini-test", "high",
        )
        normalized = ProductionOrchestrator._validated_audio_analysis(
            duration_alias, carrier, 30.0, 1,
        )
        self.assertEqual(normalized["duration_seconds"], 30.0)

    def test_prepare_agent_audio_carrier_uses_real_source_audio(self):
        source = self.root / "song.wav"
        target = self.root / "analysis" / "carrier.mp4"
        source.write_bytes(b"source-audio")
        completed = type("Completed", (), {"returncode": 0, "stderr": ""})()

        def fake_run(command, **_kwargs):
            Path(command[-1]).write_bytes(b"mp4-with-audio")
            return completed

        with patch("backend.media.shutil.which", return_value="ffmpeg"), \
             patch("backend.media.subprocess.run", side_effect=fake_run) as run:
            self.assertEqual(prepare_agent_audio_carrier(source, target, 30.0), target)
        command = run.call_args.args[0]
        self.assertIn(str(source), command)
        self.assertIn("-t", command)
        self.assertEqual(target.read_bytes(), b"mp4-with-audio")

    def test_agy_media_handoff_wraps_audio_and_preserves_other_media(self):
        production = self.create_production().json()
        audio = self.root / "song.mp3"
        video = self.root / "reference.mp4"
        audio.write_bytes(b"audio")
        video.write_bytes(b"video")

        def create_carrier(source, target, duration_seconds):
            self.assertEqual(source, audio.resolve())
            self.assertEqual(duration_seconds, 12.5)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"carrier")
            return target

        with patch.object(production_module, "is_audio_only_media", side_effect=lambda path: path == audio.resolve()), \
             patch.object(production_module, "probe_audio_metadata", return_value={"duration_seconds": 12.5}), \
             patch.object(production_module, "prepare_agent_audio_carrier", side_effect=create_carrier):
            prepared, note = production_orchestrator._prepare_agy_media_handoff(
                production["id"], [audio, video],
            )

        self.assertEqual(prepared[1], video.resolve())
        self.assertEqual(prepared[0].suffix, ".mp4")
        self.assertTrue(prepared[0].is_file())
        self.assertIn(str(audio.resolve()), note)
        self.assertIn(str(prepared[0]), note)
        self.assertIn("Do not call view_file on the original audio-only file", note)

    def test_agy_call_uses_prepared_audio_carrier(self):
        production = get_production(self.create_production().json()["id"], private=True)
        audio = self.root / "song.wav"
        carrier = self.root / "productions" / production["id"] / "analysis" / "agy-media" / "song.mp4"
        audio.write_bytes(b"audio")
        carrier.parent.mkdir(parents=True, exist_ok=True)
        carrier.write_bytes(b"carrier")
        approved = AgentResult(
            "agy", {"summary": "Analyzed", "decision": "ANALYZED", "next_action": "continue",
                    "content": {"media_inspection": {"decoded_audio": True}}, "issues": []},
            "", "session", "test", "high",
        )
        handoff = f"\n\nAGY MEDIA HANDOFF — REQUIRED:\nInspect with view_file using carrier: {carrier}"
        with patch.object(production_orchestrator, "_prepare_agy_media_handoff", return_value=([carrier], handoff)), \
             patch.object(process_manager, "invoke", new=AsyncMock(return_value=approved)) as invoke:
            result = asyncio.run(production_orchestrator._agy(
                production, "Analyze the supplied song.", [], [audio], fresh_session=True,
            ))

        self.assertIs(result, approved)
        invocation = invoke.await_args.args
        self.assertIn(handoff, invocation[3])
        self.assertIn(carrier.parent.resolve(), invocation[10])

    def test_codex_seat_using_agy_runtime_uses_prepared_audio_carrier(self):
        production = get_production(self.create_production().json()["id"], private=True)
        production["codex_runtime"] = "agy"
        audio = self.root / "song.wav"
        carrier = self.root / "productions" / production["id"] / "analysis" / "agy-media" / "song.mp4"
        audio.write_bytes(b"audio")
        carrier.parent.mkdir(parents=True, exist_ok=True)
        carrier.write_bytes(b"carrier")
        approved = AgentResult(
            "agy", {"summary": "Analyzed", "decision": "ANALYZED", "next_action": "continue",
                    "content": {"media_inspection": {"decoded_audio": True}}, "issues": []},
            "", "session", "test", "high",
        )
        handoff = f"\n\nAGY MEDIA HANDOFF — REQUIRED:\nInspect with view_file using carrier: {carrier}"
        with patch.object(production_orchestrator, "_prepare_agy_media_handoff", return_value=([carrier], handoff)), \
             patch.object(process_manager, "invoke", new=AsyncMock(return_value=approved)) as invoke:
            result = asyncio.run(production_orchestrator._codex(
                production, "Analyze the supplied song.", [], [audio], fresh_session=True,
            ))

        self.assertIs(result, approved)
        invocation = invoke.await_args.args
        self.assertEqual(invocation[0], "agy")
        self.assertIn(handoff, invocation[3])
        self.assertIn(carrier.parent.resolve(), invocation[10])

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
        self.assertEqual(message["metadata"]["execution_status"], "pending")
        self.assertEqual(message["metadata"]["previous_status"], "draft")
        self.assertEqual(response.json()["production"]["status"], "queued")

    def test_agent_requested_shot_update_executes_through_allowlisted_action(self):
        production = self.create_production().json()
        replace_shot_plan(production["id"], [{
            "title": "Opening", "prompt": "Original prompt", "mode": "opening",
            "continuity": "hard_cut", "duration": 8, "megapixels": 0.8,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v4",
        }])
        private = get_production(production["id"], private=True)
        results, policy = asyncio.run(production_orchestrator._execute_intervention_actions(
            private,
            [{"type": "update_shot", "shot_index": 1,
              "changes": {"duration": 5, "megapixels": 1.0, "prompt": "User-directed prompt"}}],
            "message-id",
        ))
        shot = list_shots(production["id"], private=True)[0]
        self.assertIsNone(policy)
        self.assertEqual(results[0]["status"], "completed")
        self.assertEqual(shot["duration"], 5)
        self.assertEqual(shot["megapixels"], 1.0)
        self.assertEqual(shot["prompt"], "User-directed prompt")

    def test_legacy_shot_update_invalidates_stale_generation_attempt(self):
        production = self.create_production().json()
        production_id = production["id"]
        replace_shot_plan(production_id, [{
            "title": "Opening", "prompt": "Old shot-plan prompt", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 0.7,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v4",
        }])
        shot = list_shots(production_id, private=True)[0]
        attempt = create_shot_attempt(shot["id"], 1)
        update_shot_attempt(attempt["id"], job_id="old-comfy-job", status="queued")

        results, policy = asyncio.run(production_orchestrator._execute_intervention_actions(
            get_production(production_id, private=True),
            [{
                "type": "update_shot", "shot_index": 1,
                "changes": {"prompt": "Latest agreed prompt from the user"},
            }],
            "intervention-update-1",
        ))

        saved_shot = list_shots(production_id, private=True)[0]
        saved_attempt = saved_shot["attempts"][0]
        self.assertIsNone(policy)
        self.assertEqual(results[0]["status"], "completed")
        self.assertTrue(results[0]["requeued"])
        self.assertEqual(saved_shot["status"], "planned")
        self.assertIsNone(saved_shot["accepted_attempt"])
        self.assertEqual(saved_attempt["status"], "interrupted")
        self.assertEqual(saved_attempt["job_id"], "old-comfy-job")
        self.assertEqual(saved_shot["prompt"], "Latest agreed prompt from the user")

    def test_legacy_promptless_regeneration_cannot_reuse_old_prompt(self):
        production = self.create_production().json()
        production_id = production["id"]
        replace_shot_plan(production_id, [{
            "title": "Opening", "prompt": "Earlier agent suggestion", "mode": "opening",
            "continuity": "hard_cut", "audio_mode": "silent", "audio_source": "song",
            "audio_start": 0, "audio_duration": 5, "duration": 5,
            "editorial_start": 0, "editorial_end": 5, "trim_in": 0, "trim_out": 0,
            "megapixels": 0.7, "aspect_ratio": "16:9", "steps": 6,
            "engine": "turbo", "turbo_profile": "v4", "reference_ids": [],
        }])
        shot = list_shots(production_id, private=True)[0]
        attempt = create_shot_attempt(shot["id"], 1)
        update_shot_attempt(attempt["id"], job_id="old-comfy-job", status="queued")
        update_production(
            production_id, participation_mode="autonomous", status="running",
            stage="shot_generation",
        )
        message = add_message(
            production_id, "user", "both", "intervention",
            "The prompt is wrong. Fix Shot 1 with the new direction and regenerate it.",
            {"priority": "user", "interrupt": True, "execution_status": "pending",
             "previous_status": "running"},
        )
        result = AgentResult(
            "codex",
            {"summary": "Agreed.", "decision": "REGENERATE", "next_action": "regenerate_shot",
             "content": {"reply": "Agreed, regenerating it.",
                         "actions": [{"type": "regenerate_shot", "shot_index": 1}],
                         "resume_policy": "resume"},
             "issues": [], "requires_user": False},
            "", "codex-session", "test", "medium",
        )
        followup = AgentResult(
            "codex",
            {"summary": "The request needs a concrete prompt.", "decision": "BLOCK",
             "content": {"reply": "A new prompt is required before regeneration.",
                         "actions": [], "resume_policy": "await_user"},
             "issues": [], "requires_user": True},
            "", "codex-session-followup", "test", "medium",
        )
        with patch.object(
            production_orchestrator, "_intervention_council_turn",
            new=AsyncMock(return_value=result),
        ), patch.object(
            production_orchestrator, "_intervention_followup",
            new=AsyncMock(return_value=followup),
        ):
            resumed = asyncio.run(
                production_orchestrator._apply_pending_interventions(
                    get_production(production_id, private=True),
                )
            )

        saved_shot = list_shots(production_id, private=True)[0]
        self.assertEqual(resumed["status"], "awaiting_user")
        self.assertEqual(saved_shot["prompt"], "Earlier agent suggestion")
        self.assertEqual(saved_shot["status"], "planned")
        self.assertEqual(saved_shot["attempts"][0]["status"], "interrupted")
        saved = next(item for item in list_messages(production_id) if item["id"] == message["id"])
        self.assertEqual(saved["metadata"]["execution_result"], "awaiting_action")

    def test_accept_shot_locks_selected_existing_attempt(self):
        production = self.create_production().json()
        production_id = production["id"]
        replace_shot_plan(production_id, [{
            "title": "Existing shot", "prompt": "Keep this shot", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 1.0,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v4",
        }])
        shot = list_shots(production_id, private=True)[0]
        old_attempt = create_shot_attempt(shot["id"], 1)
        selected_attempt = create_shot_attempt(shot["id"], 2)
        old_video = self.root / "old-attempt.mp4"
        selected_video = self.root / "selected-attempt.mp4"
        old_video.write_bytes(b"old")
        selected_video.write_bytes(b"selected")
        update_shot_attempt(old_attempt["id"], status="accepted", output_path=str(old_video))
        update_shot_attempt(selected_attempt["id"], status="reviewing", output_path=str(selected_video))
        update_shot(shot["id"], status="reviewing", accepted_attempt=1)

        private = get_production(production_id, private=True)
        results, policy = asyncio.run(production_orchestrator._execute_intervention_actions(
            private,
            [{"type": "accept_shot", "shot_index": 1, "output_path": str(selected_video)}],
            "message-id",
        ))

        saved_shot = list_shots(production_id, private=True)[0]
        saved_attempts = {item["attempt"]: item for item in saved_shot["attempts"]}
        self.assertIsNone(policy)
        self.assertEqual(results[0]["status"], "completed")
        self.assertEqual(results[0]["attempt"], 2)
        self.assertEqual(saved_shot["status"], "accepted")
        self.assertEqual(saved_shot["accepted_attempt"], 2)
        self.assertEqual(saved_attempts[2]["status"], "accepted")
        self.assertEqual(saved_attempts[1]["status"], "accepted")

    def test_legacy_update_shot_status_accepted_uses_acceptance_operation(self):
        production = self.create_production().json()
        production_id = production["id"]
        replace_shot_plan(production_id, [{
            "title": "Recoverable shot", "prompt": "Use the existing result", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 1.0,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v4",
        }])
        shot = list_shots(production_id, private=True)[0]
        stale_attempt = create_shot_attempt(shot["id"], 1)
        attempt = create_shot_attempt(shot["id"], 2)
        video = self.root / "existing-result.mp4"
        video.write_bytes(b"existing")
        update_shot_attempt(
            stale_attempt["id"], status="accepted",
            output_path=str(self.root / "stale-result.mp4"),
        )
        update_shot_attempt(attempt["id"], status="reviewing", output_path=str(video))
        update_shot(shot["id"], status="reviewing", accepted_attempt=1)

        private = get_production(production_id, private=True)
        results, _ = asyncio.run(production_orchestrator._execute_intervention_actions(
            private,
            [{"type": "update_shot", "shot_index": 1,
              "changes": {"status": "accepted"}}],
            "message-id",
        ))

        saved_shot = list_shots(production_id, private=True)[0]
        self.assertEqual(results[0]["status"], "completed")
        self.assertEqual(results[0]["compatibility_action"], "accept_shot")
        self.assertEqual(saved_shot["status"], "accepted")
        self.assertEqual(saved_shot["accepted_attempt"], 2)

    def test_accepted_shot_with_missing_output_does_not_create_retry(self):
        production = self.create_production().json()
        production_id = production["id"]
        replace_shot_plan(production_id, [{
            "title": "Already accepted", "prompt": "Do not regenerate", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 1.0,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v4",
        }])
        shot = list_shots(production_id, private=True)[0]
        attempt = create_shot_attempt(shot["id"], 1)
        update_shot_attempt(
            attempt["id"], status="accepted",
            output_path=str(self.root / "missing-output.mp4"),
        )
        update_shot(shot["id"], status="accepted", accepted_attempt=1)
        update_production(production_id, status="running", stage="shot_generation")

        private = get_production(production_id, private=True)
        with patch.object(
            production_module, "create_shot_attempt",
            side_effect=AssertionError("an accepted shot must not be regenerated"),
        ):
            asyncio.run(production_orchestrator._run_stage(production_id))

        saved = get_production(production_id, private=True)
        self.assertEqual(saved["status"], "awaiting_user")
        self.assertEqual(saved["stage"], "shot_review")
        self.assertEqual(len(list_shots(production_id, private=True)[0]["attempts"]), 1)
        self.assertTrue(any(
            item.get("metadata", {}).get("accepted_asset_missing") is True
            for item in list_messages(production_id)
        ))

    def test_user_preservation_instruction_maps_each_named_shot_to_acceptance(self):
        production = self.create_production().json()
        production_id = production["id"]
        replace_shot_plan(production_id, [{
            "title": f"Shot {index}", "prompt": "Keep the existing shot", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 1.0,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v4",
        } for index in range(1, 4)])
        for index, shot in enumerate(list_shots(production_id, private=True), 1):
            video = self.root / f"shot-{index}.mp4"
            video.write_bytes(f"shot-{index}".encode())
            attempt = create_shot_attempt(shot["id"], 1)
            update_shot_attempt(attempt["id"], status="reviewing", output_path=str(video))
            update_shot(shot["id"], status="reviewing")

        actions, targets = production_orchestrator._infer_user_acceptance_actions(
            get_production(production_id, private=True),
            "Stop retrying S01, S02 and S03. They are already good; keep them and move to the next shot.",
        )

        self.assertEqual(targets, {1, 2, 3})
        self.assertEqual(
            {(item["type"], item["shot_index"]) for item in actions},
            {("accept_shot", 1), ("accept_shot", 2), ("accept_shot", 3)},
        )

    def test_user_preservation_is_applied_even_if_council_returns_regeneration(self):
        production = self.create_production().json()
        production_id = production["id"]
        replace_shot_plan(production_id, [{
            "title": "Shot 1", "prompt": "Keep the existing shot", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 1.0,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v4",
        }])
        shot = list_shots(production_id, private=True)[0]
        video = self.root / "accepted-shot.mp4"
        video.write_bytes(b"accepted")
        attempt = create_shot_attempt(shot["id"], 1)
        update_shot_attempt(attempt["id"], status="reviewing", output_path=str(video))
        update_shot(shot["id"], status="reviewing")
        update_production(
            production_id, status="running", stage="shot_generation", participation_mode="interactive",
        )
        message = add_message(
            production_id, "user", "both", "intervention",
            "S01 is already good. Do not regenerate it; keep it and move to the next shot.",
            {"priority": "user", "interrupt": True, "execution_status": "pending", "previous_status": "running"},
        )
        council = AgentResult(
            "codex", {"summary": "The shot should be regenerated.", "decision": "REGENERATE",
                       "content": {"reply": "I would regenerate S01.", "actions": [{
                           "type": "regenerate_shot", "shot_index": 1,
                       }], "resume_policy": "resume"}, "issues": []},
            "", "codex-session", "test", "medium",
        )
        followup = AgentResult(
            "codex", {"summary": "Preserved.", "decision": "CONTINUE",
                       "content": {"reply": "S01 was preserved.", "actions": [], "resume_policy": "resume"},
                       "issues": []},
            "", "codex-session", "test", "medium",
        )
        with patch.object(
            production_orchestrator, "_intervention_council_turn", new=AsyncMock(return_value=council),
        ), patch.object(
            production_orchestrator, "_intervention_followup", new=AsyncMock(return_value=followup),
        ):
            result = asyncio.run(
                production_orchestrator._apply_pending_interventions(
                    get_production(production_id, private=True),
                )
            )

        saved_shot = list_shots(production_id, private=True)[0]
        saved_message = next(item for item in list_messages(production_id) if item["id"] == message["id"])
        self.assertEqual(result["status"], "running")
        self.assertEqual(saved_shot["status"], "accepted")
        self.assertEqual(saved_shot["accepted_attempt"], 1)
        self.assertEqual(saved_message["metadata"]["execution_status"], "completed")
        self.assertFalse(any(
            item.get("type") == "regenerate_shot"
            for item in saved_message["metadata"].get("action_results", [])
        ))

    def test_user_preservation_survives_council_failure(self):
        production = self.create_production().json()
        production_id = production["id"]
        replace_shot_plan(production_id, [{
            "title": "Shot 1", "prompt": "Keep the existing shot", "mode": "opening",
            "continuity": "hard_cut", "duration": 5, "megapixels": 1.0,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo", "turbo_profile": "v4",
        }])
        shot = list_shots(production_id, private=True)[0]
        video = self.root / "accepted-shot-council-failure.mp4"
        video.write_bytes(b"accepted")
        attempt = create_shot_attempt(shot["id"], 1)
        update_shot_attempt(attempt["id"], status="reviewing", output_path=str(video))
        update_shot(shot["id"], status="reviewing")
        update_production(
            production_id, status="running", stage="shot_generation", participation_mode="interactive",
        )
        message = add_message(
            production_id, "user", "both", "intervention",
            "S01 is already good. Do not regenerate it; keep it and move to the next shot.",
            {"priority": "user", "interrupt": True, "execution_status": "pending", "previous_status": "running"},
        )

        with patch.object(
            production_orchestrator, "_intervention_council_turn",
            new=AsyncMock(side_effect=RuntimeError("AGY council timeout")),
        ):
            result = asyncio.run(
                production_orchestrator._apply_pending_interventions(
                    get_production(production_id, private=True),
                )
            )

        saved_shot = list_shots(production_id, private=True)[0]
        saved_message = next(item for item in list_messages(production_id) if item["id"] == message["id"])
        self.assertEqual(result["status"], "running")
        self.assertEqual(saved_shot["status"], "accepted")
        self.assertEqual(saved_shot["accepted_attempt"], 1)
        self.assertEqual(saved_message["metadata"]["execution_status"], "completed")
        self.assertTrue(any(
            "council consultation did not complete" in item["content"]
            for item in list_messages(production_id)
        ))

    def test_pending_audio_intervention_is_executed_before_stage_resumes(self):
        production = self.create_production().json()
        message = add_message(
            production["id"], "user", "both", "intervention",
            "Analyze the actual sound file before continuing.",
            {"priority": "user", "interrupt": True, "execution_status": "pending"},
        )
        private = get_production(production["id"], private=True)
        analysis = AgentResult(
            "agy", {"summary": "Analyzed", "decision": "ANALYZED", "next_action": "continue",
                    "content": {"media_inspection": {"decoded_audio": True}}, "issues": []},
            "", "agy-session", "test", "high",
        )
        codex = AgentResult(
            "codex", {"summary": "I will analyze the audio.", "decision": "ACT", "next_action": "analyze",
                      "content": {"reply": "Analyzing the supplied song first.",
                                  "actions": [{"type": "analyze_song_audio"}],
                                  "resume_policy": "resume"}, "issues": []},
            "", "codex-session", "test", "medium",
        )
        followup = AgentResult(
            "codex", {"summary": "Analysis applied", "decision": "CONTINUE", "next_action": "resume",
                      "content": {"reply": "The song was analyzed.", "actions": [],
                                  "resume_policy": "resume"}, "issues": []},
            "", "codex-session", "test", "medium",
        )
        with patch.object(production_orchestrator, "_intervention_council_turn", new=AsyncMock(return_value=codex)) as council, \
             patch.object(production_orchestrator, "_analyze_song_audio", new=AsyncMock(return_value=analysis)) as analyze, \
             patch.object(production_orchestrator, "_intervention_followup", new=AsyncMock(return_value=followup)) as followup_call:
            resumed = asyncio.run(production_orchestrator._apply_pending_interventions(private))

        self.assertEqual(resumed["stage"], private["stage"])
        council.assert_awaited_once()
        analyze.assert_awaited_once()
        followup_call.assert_awaited_once()
        saved = next(item for item in list_messages(production["id"]) if item["id"] == message["id"])
        self.assertEqual(saved["metadata"]["execution_status"], "completed")
        self.assertTrue(any(
            "handled your message" in item["content"]
            for item in list_messages(production["id"])
        ))

    def test_blocking_intervention_result_pauses_instead_of_resuming(self):
        production = self.create_production().json()
        message = add_message(
            production["id"], "user", "both", "intervention",
            "Analyze the actual sound file before continuing.",
            {"priority": "user", "interrupt": True, "execution_status": "pending"},
        )
        private = get_production(production["id"], private=True)
        analysis = AgentResult(
            "agy", {"summary": "Analyzed", "decision": "ANALYZED", "next_action": "continue",
                    "content": {"media_inspection": {"decoded_audio": True}}, "issues": []},
            "", "agy-session", "test", "high",
        )
        codex = AgentResult(
            "codex", {"summary": "Needs reconciliation", "decision": "PAUSE", "next_action": "reconcile",
                      "content": {"reply": "The timeline must be reconciled.", "actions": [],
                                  "resume_policy": "pause"},
                      "issues": [{"description": "Timeline exceeds duration", "severity": "blocking"}]},
            "", "codex-session", "test", "medium",
        )
        with patch.object(production_orchestrator, "_intervention_council_turn", new=AsyncMock(return_value=codex)):
            resumed = asyncio.run(production_orchestrator._apply_pending_interventions(private))

        self.assertEqual(resumed["status"], "paused")
        saved = next(item for item in list_messages(production["id"]) if item["id"] == message["id"])
        self.assertEqual(saved["metadata"]["execution_status"], "completed")
        self.assertEqual(saved["metadata"]["execution_result"], "blocked")
        self.assertTrue(any(
            item.get("metadata", {}).get("resume_blocked") is True
            for item in list_messages(production["id"])
        ))

    def test_intervention_acknowledgement_without_action_does_not_reuse_old_prompt(self):
        production = self.create_production().json()
        production_id = production["id"]
        replace_shot_plan(production_id, [{
            "title": "Opening", "prompt": "Earlier agent suggestion", "mode": "opening",
            "continuity": "hard_cut", "audio_mode": "silent", "audio_source": "song",
            "audio_start": 0, "audio_duration": 5, "duration": 5,
            "editorial_start": 0, "editorial_end": 5, "trim_in": 0, "trim_out": 0,
            "megapixels": 0.7, "aspect_ratio": "16:9", "steps": 6,
            "engine": "turbo", "turbo_profile": "v4", "reference_ids": [],
        }])
        update_production(
            production_id, participation_mode="autonomous", status="running",
            stage="shot_generation",
        )
        message = add_message(
            production_id, "user", "both", "intervention",
            "The generation is back to the old prompt. Fix the shot and use my new direction.",
            {"priority": "user", "interrupt": True, "execution_status": "pending",
             "previous_status": "running"},
        )
        result = AgentResult(
            "codex",
            {"summary": "Agreed.", "decision": "APPROVE", "next_action": "resume",
             "content": {"reply": "Agreed, continuing.", "actions": [], "resume_policy": "resume"},
             "issues": [], "requires_user": False},
            "", "codex-session", "test", "medium",
        )
        with patch.object(
            production_orchestrator, "_intervention_council_turn",
            new=AsyncMock(return_value=result),
        ):
            resumed = asyncio.run(
                production_orchestrator._apply_pending_interventions(
                    get_production(production_id, private=True),
                )
            )

        self.assertEqual(resumed["status"], "awaiting_user")
        self.assertEqual(list_shots(production_id, private=True)[0]["prompt"], "Earlier agent suggestion")
        saved = next(item for item in list_messages(production_id) if item["id"] == message["id"])
        self.assertEqual(saved["metadata"]["execution_result"], "awaiting_action")
        self.assertTrue(any(
            item.get("metadata", {}).get("no_executable_action") is True
            for item in list_messages(production_id)
        ))

    def test_autonomous_intervention_continues_when_agents_request_pause_or_regeneration(self):
        production = self.create_production().json()
        production_id = production["id"]
        update_production(
            production_id, participation_mode="autonomous", status="running",
            stage="shot_generation",
        )
        replace_shot_plan(production_id, [{
            "title": "Opening", "prompt": "Original prompt", "mode": "opening",
            "continuity": "hard_cut", "audio_mode": "silent", "audio_source": "song",
            "audio_start": 0, "audio_duration": 5, "duration": 5,
            "editorial_start": 0, "editorial_end": 5, "trim_in": 0, "trim_out": 0,
            "megapixels": 0.7, "aspect_ratio": "16:9", "steps": 6,
            "engine": "turbo", "turbo_profile": "v4", "reference_ids": [],
        }])
        message = add_message(
            production_id, "user", "both", "intervention",
            "The shot needs a stronger performance. Keep going and fix it automatically.",
            {"priority": "user", "interrupt": True, "execution_status": "pending",
             "previous_status": "running"},
        )
        private = get_production(production_id, private=True)
        result = AgentResult(
            "codex",
            {
                "summary": "The current shot needs a revision.",
                "decision": "REGENERATE",
                "next_action": "regenerate_shot",
                "content": {
                    "reply": "I will regenerate the shot and continue.",
                    "actions": [
                        {"type": "regenerate_shot", "shot_index": 1,
                         "prompt": "A stronger close performance with purposeful movement.",
                         "regenerate_downstream": False},
                        {"type": "pause"},
                    ],
                    "resume_policy": "await_user",
                },
                "issues": [{"description": "Performance is too weak", "severity": "blocking"}],
                "requires_user": True,
            },
            "", "codex-session", "test", "medium",
        )
        followup = AgentResult(
            "codex",
            {
                "summary": "The regenerated shot is queued.",
                "decision": "CONTINUE",
                "content": {
                    "reply": "The requested regeneration was applied and the production can continue.",
                    "actions": [],
                    "resume_policy": "resume",
                },
                "issues": [],
                "requires_user": False,
            },
            "", "codex-session-followup", "test", "medium",
        )
        with patch.object(
            production_orchestrator, "_intervention_council_turn",
            new=AsyncMock(return_value=result),
        ), patch.object(
            production_orchestrator, "_intervention_followup",
            new=AsyncMock(return_value=followup),
        ):
            resumed = asyncio.run(
                production_orchestrator._apply_pending_interventions(private),
            )

        self.assertEqual(resumed["status"], "running")
        saved = next(item for item in list_messages(production_id) if item["id"] == message["id"])
        self.assertEqual(saved["metadata"]["execution_result"], "continued_with_warning")
        self.assertTrue(any(
            item.get("metadata", {}).get("autonomous_continue") is True
            for item in list_messages(production_id)
        ))
        self.assertFalse(any(
            item.get("metadata", {}).get("resume_blocked") is True
            for item in list_messages(production_id)
        ))

    def test_conversational_answer_preserves_a_paused_production(self):
        production = self.create_production().json()
        update_production(production["id"], status="paused")
        message = add_message(
            production["id"], "user", "codex", "intervention",
            "Explain what the next shot is doing.",
            {"priority": "user", "interrupt": True, "execution_status": "pending",
             "previous_status": "paused"},
        )
        private = get_production(production["id"], private=True)
        answer = AgentResult(
            "codex", {"summary": "Explained", "decision": "ANSWER", "next_action": "none",
                      "content": {"reply": "The next shot is a close performance angle.",
                                  "actions": [], "resume_policy": "preserve"}, "issues": [],
                      "requires_user": False},
            "", "codex-session", "test", "medium",
        )
        with patch.object(production_orchestrator, "_intervention_council_turn", new=AsyncMock(return_value=answer)):
            result = asyncio.run(production_orchestrator._apply_pending_interventions(private))

        self.assertEqual(result["status"], "paused")
        saved = next(item for item in list_messages(production["id"]) if item["id"] == message["id"])
        self.assertEqual(saved["metadata"]["execution_result"], "applied")

    def test_intervention_interrupts_active_production_and_queues_resume(self):
        production = self.create_production().json()
        production_id = production["id"]
        update_production(
            production_id, status="running", stage="prompt_consultation",
            codex_session_id="codex-session", agy_session_id="agy-session",
        )
        with patch.object(
            production_orchestrator, "interrupt_active_work",
            new=AsyncMock(return_value={"agent": True, "generation": True, "controller": True}),
        ) as interrupt_active_work:
            response = self.client.post(
                f"/api/productions/{production_id}/interventions",
                headers={"X-CSRF-Token": self.token},
                json={"recipient": "both", "content": "Stop and address this before generating another shot."},
            )
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()["production"]
        self.assertEqual(detail["status"], "queued")
        self.assertFalse(detail["intervention_requested"])
        self.assertTrue(interrupt_active_work.await_count)
        self.assertTrue(any("Stop and address this" in item["content"] for item in detail["messages"]))
        self.assertTrue(any("Stopping the current agent work" in item["content"] for item in detail["messages"]))
        self.assertTrue(any("Intervention applied" in item["content"] for item in detail["messages"]))

    def test_autonomous_intervention_keeps_active_work_running_until_safe_checkpoint(self):
        production = self.create_production().json()
        production_id = production["id"]
        update_production(
            production_id, participation_mode="autonomous", status="running",
            stage="shot_generation",
        )
        with patch.object(
            production_orchestrator, "comfy_generation_running",
            new=AsyncMock(return_value=True),
        ) as comfy_generation_running, patch.object(
            production_orchestrator, "interrupt_active_work",
            new=AsyncMock(return_value={"agent": True, "generation": True, "controller": True}),
        ) as interrupt_active_work:
            response = self.client.post(
                f"/api/productions/{production_id}/interventions",
                headers={"X-CSRF-Token": self.token},
                json={"recipient": "both", "content": "Make the next shot more energetic and keep going."},
            )
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()["production"]
        self.assertEqual(detail["status"], "running")
        self.assertTrue(detail["intervention_requested"])
        interrupt_active_work.assert_not_awaited()
        comfy_generation_running.assert_awaited_once_with(production_id)
        self.assertTrue(any(
            item.get("metadata", {}).get("queued_at_safe_checkpoint") is True
            for item in detail["messages"]
        ))

    def test_autonomous_intervention_is_applied_immediately_when_comfy_is_idle(self):
        production = self.create_production().json()
        production_id = production["id"]
        update_production(
            production_id, participation_mode="autonomous", status="running",
            stage="prompt_consultation",
        )
        with patch.object(
            production_orchestrator, "comfy_generation_running",
            new=AsyncMock(return_value=False),
        ) as comfy_generation_running, patch.object(
            production_orchestrator, "has_active_work", return_value=False,
        ) as has_active_work, patch.object(
            production_orchestrator, "interrupt_active_work",
            new=AsyncMock(),
        ) as interrupt_active_work:
            response = self.client.post(
                f"/api/productions/{production_id}/interventions",
                headers={"X-CSRF-Token": self.token},
                json={"recipient": "both", "content": "Analyze the audio now and keep going."},
            )
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()["production"]
        self.assertEqual(detail["status"], "queued")
        self.assertFalse(detail["intervention_requested"])
        comfy_generation_running.assert_awaited_once_with(production_id)
        has_active_work.assert_called_once_with(production_id)
        interrupt_active_work.assert_not_awaited()
        self.assertTrue(any(
            item.get("metadata", {}).get("applied_immediately") is True
            for item in detail["messages"]
        ))

    def test_intervention_queues_resume_even_when_controller_cancellation_fails(self):
        production = self.create_production().json()
        production_id = production["id"]
        update_production(production_id, status="running", stage="reference_generation")
        with patch.object(
            production_orchestrator, "interrupt_active_work",
            new=AsyncMock(side_effect=RuntimeError("provider cancellation stalled")),
        ):
            response = self.client.post(
                f"/api/productions/{production_id}/interventions",
                headers={"X-CSRF-Token": self.token},
                json={"recipient": "both", "content": "Analyze the audio before continuing."},
            )
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()["production"]
        self.assertEqual(detail["status"], "queued")
        self.assertFalse(detail["intervention_requested"])
        pending = next(item for item in detail["messages"] if item["kind"] == "intervention")
        self.assertEqual(pending["metadata"]["execution_status"], "pending")

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

    def test_resumed_codex_turn_does_not_reattach_all_production_references(self):
        production = get_production(self.create_production().json()["id"], private=True)
        production["codex_session_id"] = "existing-codex-session"
        references = [self.root / "reference-one.png", self.root / "reference-two.png"]
        result = AgentResult(
            "codex", {"summary": "Done", "decision": "CONTINUE", "content": {},
                       "issues": [], "next_action": "continue"},
            "", "new-codex-session", "gpt-test", "medium",
        )

        for compact_context in (False, True):
            with patch.object(production_orchestrator, "_reference_image_paths", return_value=references), \
                 patch.object(process_manager, "invoke", new=AsyncMock(return_value=result)) as invoke:
                asyncio.run(production_orchestrator._codex(
                    production, "Continue from the checkpoint.",
                    compact_context=compact_context,
                ))

            invocation = invoke.await_args.args
            self.assertEqual(invocation[6], "existing-codex-session")
            self.assertEqual(invocation[7], [])

    def test_codex_image_budget_failure_retries_with_fresh_text_only_context(self):
        production = get_production(self.create_production().json()["id"], private=True)
        production["codex_session_id"] = "oversized-codex-session"
        reference = self.root / "reference.png"
        success = AgentResult(
            "codex", {"summary": "Recovered", "decision": "CONTINUE", "content": {},
                       "issues": [], "next_action": "continue"},
            "", "recovered-codex-session", "gpt-test", "medium",
        )
        oversized = RuntimeError(
            "Total image data in 'input' exceeds the 536870912 byte limit for a single /v1/responses request."
        )

        with patch.object(process_manager, "invoke", new=AsyncMock(side_effect=[oversized, success])) as invoke:
            result = asyncio.run(production_orchestrator._codex(
                production, "Continue from the checkpoint.", images=[reference],
            ))

        self.assertIs(result, success)
        first, retry = invoke.await_args_list
        self.assertEqual(first.args[6], "oversized-codex-session")
        self.assertEqual(first.args[7], [reference])
        self.assertIsNone(retry.args[6])
        self.assertEqual(retry.args[7], [])
        self.assertTrue(any(
            "image-input limit" in message["content"]
            for message in list_messages(production["id"])
            if message["participant"] == "codex"
        ))

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
        transport_trace = ProductionOrchestrator._format_agent_trace("codex", "codex", "stderr", transport)
        self.assertIsNotNone(transport_trace)
        self.assertEqual(transport_trace[1], "agent_update")
        self.assertIn("retrying connection (5/5)", transport_trace[0])
        fallback_trace = ProductionOrchestrator._format_agent_trace(
            "codex", "codex", "stdout", json.dumps({
                "type": "item.completed",
                "item": {
                    "type": "error",
                    "message": "Falling back from WebSockets to HTTPS transport after retries",
                },
            }),
        )
        self.assertIsNotNone(fallback_trace)
        self.assertEqual(fallback_trace[1], "agent_update")
        self.assertIn("HTTPS", fallback_trace[0])
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
        valid_result_after_error = ProductionOrchestrator._format_agent_trace(
            "agy", "agy", "stdout", json.dumps({
                "result": {
                    "status": "error",
                    "error": "tool stream ended with an error",
                    "response": json.dumps({"summary": "The shot is approved.", "decision": "APPROVE"}),
                },
            }),
        )
        self.assertIsNone(valid_result_after_error)

    def test_recover_productions_excludes_live_controller_and_marks_orphans(self):
        live = self.create_production().json()
        orphan = self.create_production().json()
        update_production(live["id"], status="running", error=None)
        update_production(orphan["id"], status="running", error=None)

        recovered = recover_productions(
            {live["id"]}, reason="Production controller lost its active process",
        )

        self.assertEqual(recovered, [orphan["id"]])
        self.assertEqual(get_production(live["id"], private=True)["status"], "running")
        orphan_state = self.client.get(f"/api/productions/{orphan['id']}").json()
        self.assertEqual(orphan_state["status"], "paused")
        self.assertEqual(orphan_state["error"], "Production controller lost its active process")
        self.assertTrue(any(
            message["content"].startswith("Production controller lost its active process.")
            for message in orphan_state["messages"]
            if message["participant"] == "system"
        ))

    def test_legacy_watchdog_recovery_does_not_pause_council_productions(self):
        legacy = self.create_production().json()
        council = self.create_production().json()
        update_production(legacy["id"], status="running", pipeline="legacy_music_video_v1", error=None)
        update_production(council["id"], status="running", pipeline="council_music_video_v1", error=None)

        recovered = recover_productions(
            reason="Production controller lost its active process",
            pipeline="legacy_music_video_v1",
        )

        self.assertEqual(recovered, [legacy["id"]])
        self.assertEqual(get_production(legacy["id"], private=True)["status"], "paused")
        self.assertEqual(get_production(council["id"], private=True)["status"], "running")

    def test_recover_productions_requeues_a_pending_intervention(self):
        production = self.create_production().json()
        update_production(
            production["id"], status="pausing", intervention_requested=1, error=None,
        )
        add_message(
            production["id"], "user", "both", "intervention", "Analyze the audio first.",
            {"execution_status": "pending", "previous_status": "running"},
        )

        recovered = recover_productions(reason="Production controller lost its active process")

        self.assertIn(production["id"], recovered)
        state = get_production(production["id"], private=True)
        self.assertEqual(state["status"], "queued")
        self.assertFalse(state["intervention_requested"])
        self.assertIsNone(state["error"])

    def test_production_detail_reports_controller_activity_separately(self):
        production = self.create_production().json()
        update_production(production["id"], status="running", error=None)
        detail = self.client.get(f"/api/productions/{production['id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertFalse(detail.json()["controller_active"])

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

    def test_agy_nested_step_updates_expose_real_tool_activity(self):
        tool_event = json.dumps({
            "event": "step_update",
            "step_update": {
                "state": "ACTIVE", "step_type": "tool", "tool_name": "view_file",
                "tool_info": {"parameters": {"AbsolutePath": "D:/production/review.mp4"}},
            },
        })
        formatted = ProductionOrchestrator._format_agent_trace("agy", "agy", "stdout", tool_event)
        self.assertIsNotNone(formatted)
        self.assertEqual(formatted[1], "tool_activity")
        self.assertIn("view_file", formatted[0])
        self.assertIn("review.mp4", formatted[0])

        response_event = json.dumps({
            "event": "step_update",
            "step_update": {
                "state": "DONE", "step_type": "agent_response", "duration_seconds": 4.2,
                "usage": {"output_tokens": 353},
            },
        })
        formatted = ProductionOrchestrator._format_agent_trace("agy", "agy", "stdout", response_event)
        self.assertIsNotNone(formatted)
        self.assertEqual(formatted[1], "agent_update")
        self.assertIn("353 output tokens", formatted[0])

    def test_completed_agent_reply_is_not_duplicated_as_live_trace(self):
        production = self.create_production().json()
        add_message(
            production["id"], "agy", "all", "agent", "The opening frame is usable.",
            {"decision": "APPROVE", "next_action": "Continue to the next shot."},
        )
        detail = self.client.get(f"/api/productions/{production['id']}").json()
        replies = [message for message in detail["messages"] if message["kind"] == "agent_trace"]
        self.assertEqual(replies, [])

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
        self.assertEqual(image_generator.await_args.kwargs["aspect_ratio"], "16:9")

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

    def test_agent_pipe_cleanup_is_bounded_when_cancel_does_not_finish(self):
        async def exercise():
            release = asyncio.Event()

            async def stubborn_reader():
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    # Reproduce a Windows Proactor pipe read that does not
                    # complete immediately when its task is cancelled.
                    await release.wait()

            task = asyncio.create_task(stubborn_reader())
            await asyncio.sleep(0)
            started = asyncio.get_running_loop().time()
            await process_manager._stop_reader_tasks([task], [], timeout=0.02)
            elapsed = asyncio.get_running_loop().time() - started
            self.assertLess(elapsed, 0.2)
            release.set()
            await asyncio.gather(task, return_exceptions=True)

        asyncio.run(exercise())

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
                    "production", "A clean reference", target, "gpt-test", "high", [], "1:1",
                ))
                command = process_manager._run.await_args.args[1]
                task = process_manager._run.await_args.args[2]
                self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
                self.assertNotIn("--approve-for-me", command)
                self.assertIn("built-in image-generation tool directly", task)
                self.assertIn("bridge", task)
                self.assertNotIn("Copy the selected final image", task)

            self.assertEqual(result.resolve(), target.resolve())
            with Image.open(target) as image:
                self.assertEqual(image.size, (32, 32))

    def test_codex_reference_materializes_standard_generated_image_after_copy_runner_failure(self):
        with tempfile.TemporaryDirectory(prefix="codex-generated-handoff-test-") as temp:
            root = Path(temp)
            production_root = root / "productions" / "production"
            generated_root = root / "codex-home" / "generated_images"
            target = production_root / "references" / "generated" / "attempt.png"
            generated = generated_root / "exec-generated.png"

            async def generate_then_fail_during_copy(*_args, **_kwargs):
                generated.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (32, 32), "purple").save(generated, "PNG")
                raise RuntimeError("CreateProcess timed out connecting runner pipe-in")

            with patch("backend.agents.PRODUCTIONS", root / "productions"), \
                 patch("backend.agents.CODEX_GENERATED_IMAGES", generated_root), \
                 patch("backend.agents._command_path", return_value="codex"), \
                 patch.object(process_manager, "_run", new=AsyncMock(side_effect=generate_then_fail_during_copy)):
                result = asyncio.run(process_manager._generate_reference_image_codex(
                    "production", "A clean reference", target, "gpt-test", "high", [], "1:1",
                ))

            self.assertEqual(result.resolve(), target.resolve())
            self.assertTrue(target.is_file())
            with Image.open(target) as image:
                self.assertEqual(image.size, (32, 32))

    def test_reference_image_validation_rejects_wrong_project_aspect(self):
        with tempfile.TemporaryDirectory(prefix="reference-aspect-test-") as temp:
            target = Path(temp) / "reference.png"
            Image.new("RGB", (128, 72), "orange").save(target, "PNG")
            with self.assertRaises(GeneratedImageValidationError):
                process_manager._validate_generated_image(target, "Test provider", "1:1")
            self.assertFalse(target.exists())

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
            asyncio.run(process_manager.invoke_codex(
                "production", "prompt", "gpt-test", "medium", session_id="session-123",
                extra_dirs=[Path(".")],
            ))

        self.assertEqual(runner.await_count, 2)
        for call in runner.await_args_list:
            command = call.args[1]
            schema_index = command.index("--output-schema")
            self.assertEqual(command[schema_index + 1], "schema.json")
            self.assertIn("mcp_servers.runpod.enabled=false", command)
        self.assertNotIn("--add-dir", runner.await_args_list[1].args[1])

    def test_agent_run_does_not_wait_for_windows_stdin_pipe_to_close(self):
        class FakeStdin:
            def __init__(self):
                self.closed = False

            def write(self, _value):
                return None

            async def drain(self):
                return None

            def close(self):
                self.closed = True

            async def wait_closed(self):
                raise AssertionError("subprocess stdin wait_closed must not be awaited")

        class FakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = asyncio.StreamReader()
                self.stderr = asyncio.StreamReader()
                self.stdout.feed_data(b"result\n")
                self.stdout.feed_eof()
                self.stderr.feed_eof()
                self.returncode = None
                self.pid = 12345

            async def wait(self):
                self.returncode = 0
                return 0

        manager = AgentProcessManager()

        async def run_case():
            fake_process = FakeProcess()
            with patch("backend.agents.asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_process)):
                result = await manager._run("production", ["codex"], "prompt")
            return result, fake_process

        result, fake_process = asyncio.run(run_case())

        self.assertEqual(result, "result\n")
        self.assertTrue(fake_process.stdin.closed)
        self.assertNotIn("production", manager.processes)

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

    def test_agy_salvages_task_result_when_cli_exits_nonzero_after_result(self):
        payload = {
            "summary": "Reviewed successfully",
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
                "conversation_id": "agy-salvaged-session",
                "status": "ERROR",
                "error": "Agent execution terminated due to error",
                "response": json.dumps(payload),
            },
        })
        failure = AgentExecutionError(
            "agy exited after returning a result", runtime="agy", command=["agy"],
            stdout=stdout, returncode=1,
        )
        with tempfile.TemporaryDirectory(prefix="agy-salvage-test-") as temp:
            root = Path(temp)
            with patch("backend.agents.PRODUCTIONS", root / "productions"), \
                 patch("backend.agents._command_path", return_value="agy"), \
                 patch.object(process_manager, "_run", new=AsyncMock(side_effect=failure)):
                result = asyncio.run(process_manager.invoke_agy("production", "Inspect this asset.", "gemini-test", "high"))

        self.assertEqual(result.session_id, "agy-salvaged-session")
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
