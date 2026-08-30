import tempfile
import unittest
import asyncio
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import backend.db as db_module
from backend.agents import AgentResult
from backend.council import COUNCIL_PIPELINE, LEGACY_PIPELINE
from backend.council.capabilities import verify_council_config
from backend.council.contracts import CouncilConfig, positive_generation_duration
from backend.council.controller import CouncilController
from backend.council.db import (council_snapshot, create_task, init_council_db,
                                council_shot_prompt_projection,
                                add_intervention, list_seats, list_tasks, next_ready_task, ready_tasks,
                                retarget_unstarted_tasks, save_config, save_deliverable,
                                save_review, update_task)
from backend.db import init_db
from backend.config import PRODUCTIONS
from backend.production import ProductionOrchestrator
from backend.production_db import (add_decision, create_production, create_shot_attempt,
                                   add_artifact, get_production, init_production_db, list_decisions,
                                   list_messages, list_shots, replace_shot_plan,
                                   resolve_decision, update_production)


CATALOG = {
    "codex": [{"id": "codex-test", "efforts": ["medium"]}],
    "agy": [{"id": "agy-test", "efforts": ["high"]}],
}


def seat(seat_id, runtime, model, effort, roles):
    return {
        "id": seat_id, "label": seat_id.replace("_", " ").title(),
        "runtime": runtime, "model": model, "effort": effort,
        "role_ids": roles,
        "user_enabled_capabilities": ["text", "image", "audio", "video"] if runtime == "agy" else ["text", "image"],
        "priority": 100, "active": True, "custom_instructions": "",
    }


class CouncilTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="council-test-")
        self.original_db = db_module.DB_PATH
        db_module.DB_PATH = Path(self.temp.name) / "jobs.sqlite3"
        init_db()
        init_production_db()
        init_council_db()
        song = Path(self.temp.name) / "song.wav"
        with wave.open(str(song), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 16000)

        # The Council now performs the same audio-carrier handoff as Legacy.
        # Keep these unit tests independent of the machine's ffmpeg PATH;
        # integration/preflight coverage can exercise the real helpers.
        def fake_carrier(_source, target, _duration_seconds=None):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"test audio carrier")
            return target

        self._media_patches = [
            patch(
                "backend.council.controller.probe_audio_metadata",
                return_value={"duration_seconds": 1.0, "codec": "pcm_s16le"},
            ),
            patch(
                "backend.council.controller.prepare_agent_audio_carrier",
                side_effect=fake_carrier,
            ),
        ]
        for media_patch in self._media_patches:
            media_patch.start()
            self.addCleanup(media_patch.stop)

    def tearDown(self):
        db_module.DB_PATH = self.original_db
        self.temp.cleanup()

    def production(self, pipeline=COUNCIL_PIPELINE):
        return create_production({
            "title": "Council test", "pipeline": pipeline,
            "participation_mode": "interactive", "continuity_mode": "hybrid",
            "lyrics": "Test lyrics", "song_path": str(Path(self.temp.name) / "song.wav"),
            "song_name": "song.wav", "codex_model": "codex-test", "codex_effort": "medium",
            "agy_model": "agy-test", "agy_effort": "high", "skills": [], "approval_gates": [],
        })

    def council_config(self):
        return CouncilConfig.model_validate({
            "mode": "multi",
            "seats": [
                seat("codex_director", "codex", "codex-test", "medium", ["visual-director", "storyboard-editor", "technical-director", "scene-frame-designer", "prompt-engineer", "post-production-editor"]),
                seat("agy_audio", "agy", "agy-test", "high", ["audio-analyst", "technical-qc", "av-sync-reviewer"]),
            ],
            "required_role_ids": ["audio-analyst", "visual-director", "storyboard-editor", "technical-director", "scene-frame-designer", "prompt-engineer", "technical-qc", "av-sync-reviewer", "post-production-editor"],
        })

    def audio_analysis_content(self, production_id=None, *, requires_user=False):
        # Council stores the private audio handoff under its configured
        # production state root, not beside the test-only source WAV.
        carrier = (PRODUCTIONS / str(production_id or "__test_audio_carrier__") / "analysis" / "agy_audio_carrier.mp4").resolve()
        return {
            "analysis_complete": True,
            "source": "test song",
            "duration_seconds": 1.0,
            "bpm": 90,
            "meter": "4/4",
            "genre": "test",
            "beat_bar_grid": [],
            "sections": [{"start": 0, "end": 1, "type": "vocal", "energy": 0.5}],
            "energy_changes": [],
            "vocal_entrances": [{"start": 0, "end": 1}],
            "breaths": [],
            "instrumental_breaks": [],
            "transitions": [],
            "lyric_timeline": [{"start": 0, "end": 1, "text": "Test lyrics"}],
            "phrase_safe_cut_points": [0, 1],
            "notes": [],
            "media_inspection": {"decoded_audio": True, "inspected_path": str(carrier)},
            "requires_user": requires_user,
        }

    def test_generation_duration_must_be_positive_integer(self):
        self.assertEqual(positive_generation_duration(5), 5)
        with self.assertRaises(ValueError):
            positive_generation_duration(5.5)
        with self.assertRaises(ValueError):
            positive_generation_duration(0)

    def test_reference_briefs_reads_agent_generation_briefs(self):
        briefs = [{"artifact_id": "character_identity", "brief": "A consistent performer"}]
        payload = {"reference_set": {"generation_briefs": briefs}}

        self.assertEqual(CouncilController._reference_briefs(payload), briefs)
        self.assertEqual(CouncilController._reference_brief_name(briefs[0], 1), "character_identity")

    def test_council_shot_prompt_projection_uses_generated_prompts(self):
        production = self.production()
        scene_task = create_task(
            production["id"], config_revision=1, stage="execution",
            task_type="scene_frame_design", role_id="scene-frame-designer",
            output_contract="scene_frame_plan.v1", idempotency_key="scene-1",
        )
        video_task = create_task(
            production["id"], config_revision=1, stage="execution",
            task_type="generation_prompt", role_id="prompt-engineer",
            output_contract="generation_prompt.v1", idempotency_key="video-1",
        )
        save_deliverable(
            production["id"], scene_task["id"], scene_task["role_id"],
            "scene_frame_plan.v1", {"shot_id": "shot-1", "opening_frame_prompt": "A composed scene frame"},
        )
        save_deliverable(
            production["id"], video_task["id"], video_task["role_id"],
            "generation_prompt.v1", {"shot_id": "shot-1", "prompt": "The complete video prompt"},
        )

        projected = council_shot_prompt_projection(
            production["id"], [{"id": "shot-1", "prompt": "Shot 001"}],
        )

        self.assertEqual(projected[0]["prompt"], "The complete video prompt")
        self.assertEqual(projected[0]["video_prompt"], "The complete video prompt")
        self.assertEqual(projected[0]["scene_frame_prompt"], "A composed scene frame")
        self.assertEqual(projected[0]["prompt_history"][0]["video_prompt"], "The complete video prompt")

    def test_video_generation_uses_prompt_deliverable_not_scene_barrier(self):
        production = self.production()
        replace_shot_plan(production["id"], [{
            "title": "Opening", "prompt": "Old shot-plan prompt", "mode": "opening",
            "continuity": "hard_cut", "audio_mode": "silent", "audio_source": "song",
            "audio_start": 0, "audio_duration": 5, "duration": 5,
            "editorial_start": 0, "editorial_end": 5, "trim_in": 0, "trim_out": 0,
            "megapixels": 0.7, "aspect_ratio": "16:9", "steps": 6,
            "engine": "turbo", "turbo_profile": "v4", "reference_ids": [],
        }])
        shot = list_shots(production["id"], private=True)[0]
        render_task = create_task(
            production["id"], config_revision=1, stage="scene_frames",
            task_type="scene_frame_render", role_id="controller",
            output_contract="scene_frame_asset.v1", idempotency_key="render-1",
            inputs={"shot_id": shot["id"], "shot_index": 1}, worker_type="controller",
        )
        prompt_task = create_task(
            production["id"], config_revision=1, stage="prompting",
            task_type="generation_prompt", role_id="prompt-engineer",
            output_contract="generation_prompt.v1", idempotency_key="prompt-1",
            inputs={"shot_id": shot["id"], "shot_index": 1},
        )
        barrier_task = create_task(
            production["id"], config_revision=1, stage="scene_frames",
            task_type="scene_frame_barrier", role_id="controller",
            output_contract="scene_frame_batch.v1", idempotency_key="barrier-1",
            inputs={"shot_ids": [shot["id"]]}, worker_type="controller",
        )
        generation_task = create_task(
            production["id"], config_revision=1, stage="shot_generation",
            task_type="video_generation", role_id="comfyui",
            output_contract="generated_video.v1", idempotency_key="generation-1",
            dependencies=[prompt_task["id"], barrier_task["id"]],
            inputs={"shot_id": shot["id"], "shot_index": 1}, worker_type="comfyui",
        )
        opening = Path(self.temp.name) / "opening.png"
        output = Path(self.temp.name) / "generated.mp4"
        opening.write_bytes(b"opening")
        output.write_bytes(b"generated")
        save_deliverable(
            production["id"], render_task["id"], "controller", render_task["output_contract"],
            {"shot_id": shot["id"], "opening_artifact_id": "opening-artifact"},
        )
        save_deliverable(
            production["id"], prompt_task["id"], "prompt-engineer", prompt_task["output_contract"],
            {"shot_id": shot["id"], "prompt": "Latest agreed prompt from the Prompt Engineer"},
        )
        save_deliverable(
            production["id"], barrier_task["id"], "controller", barrier_task["output_contract"],
            {"shot_ids": [shot["id"]], "video_generation_unlocked": True},
        )
        controller = CouncilController()
        controller.queue_worker = MagicMock()
        with patch.object(controller, "_artifact_path", return_value=opening), \
             patch.object(controller, "_queue_video_job", return_value="job-1") as queue_job, \
             patch.object(controller, "_wait_for_job", new=AsyncMock(return_value={
                 "status": "completed", "output_path": str(output),
             })), \
             patch("backend.council.controller.PRODUCTIONS", Path(self.temp.name) / "productions"), \
             patch("backend.council.controller.resolve_asset_path", return_value=None), \
             patch("backend.council.controller.media_probe", return_value={"streams": []}), \
             patch("backend.council.controller.extract_review_frames", return_value=[]):
            asyncio.run(controller._generate_video(production, generation_task))

        self.assertEqual(queue_job.call_args.args[2], "Latest agreed prompt from the Prompt Engineer")

    def test_shot_update_requeues_and_clears_stale_video_handoff(self):
        production = self.production()
        replace_shot_plan(production["id"], [{
            "title": "Opening", "prompt": "Old shot-plan prompt", "mode": "opening",
            "continuity": "hard_cut", "audio_mode": "silent", "audio_source": "song",
            "audio_start": 0, "audio_duration": 5, "duration": 5,
            "editorial_start": 0, "editorial_end": 5, "trim_in": 0, "trim_out": 0,
            "megapixels": 0.7, "aspect_ratio": "16:9", "steps": 6,
            "engine": "turbo", "turbo_profile": "v4", "reference_ids": [],
        }])
        shot = list_shots(production["id"], private=True)[0]
        prompt_task = create_task(
            production["id"], config_revision=1, stage="prompting",
            task_type="generation_prompt", role_id="prompt-engineer",
            output_contract="generation_prompt.v1", idempotency_key="update-prompt-1",
            inputs={"shot_id": shot["id"], "shot_index": 1},
        )
        barrier_task = create_task(
            production["id"], config_revision=1, stage="scene_frames",
            task_type="scene_frame_barrier", role_id="controller",
            output_contract="scene_frame_batch.v1", idempotency_key="update-barrier-1",
            inputs={"shot_ids": [shot["id"]]}, worker_type="controller",
        )
        generation_task = create_task(
            production["id"], config_revision=1, stage="shot_generation",
            task_type="video_generation", role_id="comfyui",
            output_contract="generated_video.v1", idempotency_key="update-generation-1",
            dependencies=[prompt_task["id"], barrier_task["id"]],
            inputs={
                "shot_id": shot["id"], "shot_index": 1,
                "job_id": "old-comfy-job", "attempt_id": "old-attempt",
                "output_path": "old-output.mp4",
            }, worker_type="comfyui",
        )
        final_task = create_task(
            production["id"], config_revision=1, stage="assembly",
            task_type="final_assembly", role_id="post-production-editor",
            output_contract="final_video.v1", idempotency_key="update-final-1",
            worker_type="ffmpeg",
        )
        final_review_task = create_task(
            production["id"], config_revision=1, stage="final_review",
            task_type="final_media_review", role_id="technical-qc",
            output_contract="final_review.v1", idempotency_key="update-final-review-1",
            dependencies=[final_task["id"]],
        )

        controller = CouncilController()
        results, policy = asyncio.run(controller._execute_intervention_actions(
            production,
            [{
                "type": "update_shot", "shot_index": 1,
                "changes": {"prompt": "Latest agreed prompt from the user"},
            }],
            "intervention-update-1",
        ))

        tasks = {item["id"]: item for item in list_tasks(production["id"])}
        saved_shot = list_shots(production["id"], private=True)[0]
        self.assertIsNone(policy)
        self.assertEqual(results[0]["status"], "completed")
        self.assertTrue(results[0]["requeued"])
        self.assertEqual(saved_shot["status"], "planned")
        self.assertIsNone(saved_shot["accepted_attempt"])
        self.assertEqual(tasks[prompt_task["id"]]["state"], "queued")
        self.assertEqual(tasks[barrier_task["id"]]["state"], "queued")
        self.assertEqual(tasks[generation_task["id"]]["state"], "queued")
        self.assertEqual(tasks[final_task["id"]]["state"], "queued")
        self.assertEqual(tasks[final_review_task["id"]]["state"], "queued")
        self.assertNotIn("job_id", tasks[generation_task["id"]]["input"])
        self.assertNotIn("attempt_id", tasks[generation_task["id"]]["input"])
        self.assertNotIn("output_path", tasks[generation_task["id"]]["input"])

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_multi_seat_configuration_is_verified_and_persisted(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        self.assertTrue(validation.valid, validation.model_dump())
        production = self.production()
        self.assertEqual(save_config(production["id"], config, validation), 1)
        self.assertEqual(save_config(production["id"], config, validation), 2)
        self.assertEqual(len(list_seats(production["id"])), 2)
        self.assertEqual(council_snapshot(production["id"])["config"]["revision"], 2)

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_solo_codex_cannot_claim_audio_capability(self, _which):
        config = CouncilConfig.model_validate({
            "mode": "solo",
            "seats": [seat("codex_solo", "codex", "codex-test", "medium", ["audio-analyst", "visual-director", "storyboard-editor", "technical-director"])],
        })
        validation = verify_council_config(config, catalog=CATALOG)
        self.assertFalse(validation.valid)
        self.assertTrue(any(gap.get("missing_capabilities") == ["audio"] for gap in validation.capability_gaps))

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_planning_graph_is_idempotent_and_dependency_ordered(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        first = controller.initialize_planning_tasks(production["id"])
        second = controller.initialize_planning_tasks(production["id"])
        self.assertEqual([item["id"] for item in first], [item["id"] for item in second])
        self.assertEqual(len(list_tasks(production["id"])), 4)
        ready = next_ready_task(production["id"])
        self.assertEqual(ready["role_id"], "audio-analyst")
        update_task(ready["id"], state="completed")
        self.assertEqual(next_ready_task(production["id"])["role_id"], "visual-director")

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_execution_graph_materializes_i2v_shots_once(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        planning = controller.initialize_planning_tasks(production["id"])
        for task in planning:
            save_deliverable(
                production["id"], task["id"], task["role_id"], task["output_contract"],
                {"shots": [{"title": "Opening", "prompt": "A deliberate opening shot", "duration": 5}]}
                if task["role_id"] == "technical-director" else {"summary": "approved"},
            )
            update_task(task["id"], state="completed")
        first = controller.initialize_execution_tasks(production["id"])
        second = controller.initialize_execution_tasks(production["id"])
        self.assertEqual([item["id"] for item in first], [item["id"] for item in second])
        shots = list_shots(production["id"], private=True)
        self.assertEqual(len(shots), 1)
        self.assertEqual(shots[0]["mode"], "opening")
        self.assertEqual(shots[0]["duration"], 5)
        self.assertEqual(shots[0]["editorial_start"], 0)
        self.assertEqual(shots[0]["editorial_end"], 5)
        self.assertTrue(any(item["task_type"] == "final_assembly" for item in first))

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_hard_cut_shots_are_dependency_ready_together(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        planning = controller.initialize_planning_tasks(production["id"])
        for task in planning:
            payload = {"shots": [
                {"title": "A", "prompt": "A", "duration": 5, "continuity": "hard_cut"},
                {"title": "B", "prompt": "B", "duration": 5, "continuity": "hard_cut"},
            ]} if task["role_id"] == "technical-director" else {"summary": "approved"}
            save_deliverable(production["id"], task["id"], task["role_id"], task["output_contract"], payload)
            update_task(task["id"], state="completed")
        controller.initialize_execution_tasks(production["id"])
        bundle = next(item for item in list_tasks(production["id"]) if item["task_type"] == "reference_bundle_prepare")
        update_task(bundle["id"], state="completed")
        designs = [item for item in ready_tasks(production["id"]) if item["task_type"] == "scene_frame_design"]
        self.assertEqual(len(designs), 2)
        tasks = list_tasks(production["id"])
        renders = [item for item in tasks if item["task_type"] == "scene_frame_render"]
        barrier = next(item for item in tasks if item["task_type"] == "scene_frame_barrier")
        generations = [item for item in tasks if item["task_type"] == "video_generation"]
        self.assertEqual(set(barrier["dependency_ids"]), {item["id"] for item in renders})
        self.assertTrue(generations)
        self.assertTrue(all(barrier["id"] in item["dependency_ids"] for item in generations))

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_sequential_scene_frames_wait_for_prior_scene_frame(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        planning = controller.initialize_planning_tasks(production["id"])
        for task in planning:
            payload = {"shots": [
                {"title": "A", "prompt": "A", "duration": 5, "continuity": "hard_cut"},
                {"title": "B", "prompt": "B", "duration": 6, "continuity": "sequential",
                 "editorial_start": 5, "editorial_end": 10, "audio_start": 4},
            ]} if task["role_id"] == "technical-director" else {"summary": "approved"}
            save_deliverable(production["id"], task["id"], task["role_id"], task["output_contract"], payload)
            update_task(task["id"], state="completed")
        controller.initialize_execution_tasks(production["id"])
        shots = list_shots(production["id"], private=True)
        self.assertEqual(shots[1]["trim_in"], 1)
        self.assertEqual(shots[1]["trim_out"], 0)
        tasks = list_tasks(production["id"])
        first_render = next(item for item in tasks if item["task_type"] == "scene_frame_render" and item["input"]["shot_id"] == shots[0]["id"])
        second_design = next(item for item in tasks if item["task_type"] == "scene_frame_design" and item["input"]["shot_id"] == shots[1]["id"])
        self.assertIn(first_render["id"], second_design["dependency_ids"])
        self.assertNotIn(
            next(item for item in tasks if item["task_type"] == "shot_acceptance" and item["input"]["shot_id"] == shots[0]["id"])["id"],
            second_design["dependency_ids"],
        )

    def test_ready_batch_serializes_same_resource_only(self):
        controller = CouncilController()
        tasks = [
            {"id": "a", "worker_type": "comfyui"},
            {"id": "b", "worker_type": "comfyui"},
            {"id": "c", "worker_type": "ffmpeg"},
        ]
        with patch("backend.council.controller.ready_tasks", return_value=tasks):
            batch = controller._ready_batch("production", {})
        self.assertEqual([item[0]["id"] for item in batch], ["a", "c"])

    def test_council_stages_unique_comfy_input_frame_for_each_job(self):
        production = self.production()
        controller = CouncilController()
        controller.queue_worker = MagicMock()
        opening = Path(self.temp.name) / "opening.png"
        opening.write_bytes(b"valid-test-image-payload")
        staged = Path(self.temp.name) / "comfy-input"
        shot = {
            "id": "shot-1", "shot_index": 1, "duration": 5,
            "audio_mode": "silent", "engine": "turbo", "steps": 6,
            "megapixels": 0.41, "aspect_ratio": "1:1", "turbo_profile": "v4",
        }
        with patch("backend.council.controller.INPUT", staged):
            first_id = controller._queue_video_job(production, shot, "prompt", opening, None)
            second_id = controller._queue_video_job(production, shot, "prompt", opening, None)
        first = db_module.get_job(first_id, public=False)
        second = db_module.get_job(second_id, public=False)
        self.assertTrue(Path(first["first_frame_path"]).is_file())
        self.assertEqual(Path(first["first_frame_path"]).parent, staged)
        self.assertNotEqual(first["first_frame_name"], "opening.png")
        self.assertNotEqual(first["first_frame_name"], second["first_frame_name"])
        self.assertEqual(Path(first["first_frame_path"]).read_bytes(), opening.read_bytes())

    def test_legacy_scheduler_never_claims_council_production(self):
        council = self.production(COUNCIL_PIPELINE)
        legacy = self.production(LEGACY_PIPELINE)
        update_production(council["id"], status="queued")
        update_production(legacy["id"], status="queued")
        selected = ProductionOrchestrator()._next()
        self.assertEqual(selected["id"], legacy["id"])

    def test_council_tables_are_idempotent(self):
        init_council_db()
        init_council_db()

    def test_council_trace_exposes_meaningful_events_and_filters_diagnostics(self):
        controller = CouncilController()
        reasoning = controller._format_trace(
            "Codex Director", "stdout",
            '{"type":"item.completed","item":{"type":"reasoning","text":"Comparing the treatment with the song structure."}}',
        )
        self.assertEqual(reasoning, (
            "Codex Director reasoning summary: Comparing the treatment with the song structure.",
            "reasoning_summary",
        ))
        self.assertIsNone(controller._format_trace(
            "Codex Director", "stderr",
            "WARN codex_core::responses_retry: stream disconnected before response.completed",
        ))

    def test_council_trace_does_not_duplicate_structured_json(self):
        controller = CouncilController()
        self.assertIsNone(controller._format_trace(
            "AGY Analyst", "stdout",
            '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"summary\\":\\"done\\"}"}}',
        ))

    def test_council_trace_exposes_codex_stream_updates_without_schema_echoes(self):
        controller = CouncilController()
        message = controller._format_trace(
            "Codex Director", "stdout",
            '{"type":"item.updated","item":{"type":"agent_message","content":[{"type":"output_text","text":"I am checking the approved scene brief."}]}}',
        )
        self.assertEqual(message, (
            "Codex Director response: I am checking the approved scene brief.",
            "agent_update",
        ))
        reasoning = controller._format_trace(
            "Codex Director", "stdout",
            '{"type":"response.reasoning_summary_text.delta","delta":"Comparing the shot timing."}',
        )
        self.assertEqual(reasoning, (
            "Codex Director reasoning summary: Comparing the shot timing.",
            "reasoning_summary",
        ))

    def test_intervention_actions_are_deduplicated_across_council_seats(self):
        controller = CouncilController()
        actions = [
            {"type": "regenerate_shot", "shot_index": 1, "prompt": "Use the approved close framing."},
            {"type": "regenerate_shot", "shot_index": 1, "prompt": "Use the approved close framing."},
            {"type": "add_production_note", "note": "Keep the motion restrained."},
        ]
        unique = controller._dedupe_intervention_actions(actions)
        self.assertEqual(len(unique), 2)
        self.assertEqual(unique[0]["type"], "regenerate_shot")

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_intervention_executes_once_then_uses_saved_session_followup(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        replace_shot_plan(production["id"], [{
            "title": "Basement performance",
            "prompt": "The performer works the sampler in a controlled medium close shot.",
            "mode": "opening", "continuity": "hard_cut", "audio_mode": "silent",
            "audio_source": "song", "audio_start": 0, "audio_duration": 5,
            "duration": 5, "editorial_start": 0, "editorial_end": 5,
            "trim_in": 0, "trim_out": 0, "megapixels": 0.7,
            "aspect_ratio": "16:9", "steps": 6, "engine": "turbo",
            "turbo_profile": "v4", "reference_ids": [],
        }])
        intervention = add_intervention(
            production["id"], "Change the first shot to a tighter framing and continue.",
            ["codex_director"],
        )
        initial = AgentResult(
            "codex",
            {"summary": "I will update the shot.", "decision": "approve", "content": {
                "reply": "I will update the first shot and continue.",
                "actions": [
                    {"type": "update_shot", "shot_index": 1, "changes": {"prompt": "Tight close shot of the performer working the sampler with restrained camera motion."}},
                    {"type": "update_shot", "shot_index": 1, "changes": {"prompt": "Tight close shot of the performer working the sampler with restrained camera motion."}},
                ], "resume_policy": "resume", "requires_user": False,
            }, "issues": [], "next_action": "Apply the update.", "confidence": 0.9,
             "requires_user": False},
            "", "codex-session-1", "codex-test", "medium",
        )
        followup = AgentResult(
            "codex",
            {"summary": "The update was applied.", "decision": "approve", "content": {
                "reply": "The tighter framing was applied once and the production can continue.",
                "actions": [], "resume_policy": "resume", "requires_user": False,
            }, "issues": [], "next_action": "Continue to the next checkpoint.", "confidence": 0.9,
             "requires_user": False},
            "", "codex-session-2", "codex-test", "medium",
        )
        with patch(
            "backend.council.controller.process_manager.invoke",
            new=AsyncMock(side_effect=[initial, followup]),
        ) as invoke:
            asyncio.run(CouncilController()._execute_intervention_turn(production, intervention))
        refreshed = get_production(production["id"], private=True)
        self.assertEqual(invoke.await_count, 2)
        self.assertEqual(list_shots(production["id"], private=True)[0]["prompt"],
                         "Tight close shot of the performer working the sampler with restrained camera motion.")
        self.assertEqual(council_snapshot(production["id"])["interventions"][0]["state"], "applied")
        self.assertEqual(refreshed["status"], "running")
        self.assertTrue(any(
            item.get("metadata", {}).get("intervention_followup")
            for item in list_messages(production["id"])
            if item.get("kind") == "agent_response"
        ))

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_intervention_acknowledgement_without_action_does_not_resume_stale_prompt(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        replace_shot_plan(production["id"], [{
            "title": "Opening", "prompt": "Earlier Council suggestion", "mode": "opening",
            "continuity": "hard_cut", "audio_mode": "silent", "audio_source": "song",
            "audio_start": 0, "audio_duration": 5, "duration": 5,
            "editorial_start": 0, "editorial_end": 5, "trim_in": 0, "trim_out": 0,
            "megapixels": 0.7, "aspect_ratio": "16:9", "steps": 6,
            "engine": "turbo", "turbo_profile": "v4", "reference_ids": [],
        }])
        update_production(
            production["id"], participation_mode="autonomous", status="running",
            stage="shot_generation",
        )
        intervention = add_intervention(
            production["id"],
            "The generation is back to the old prompt. Fix the first shot and use my new direction.",
            ["codex_director"],
        )
        acknowledgement = AgentResult(
            "codex",
            {"summary": "Agreed.", "decision": "APPROVE", "next_action": "resume",
             "content": {"reply": "Agreed, continuing.", "actions": [], "resume_policy": "resume"},
             "issues": [], "requires_user": False},
            "", "codex-session", "codex-test", "medium",
        )
        with patch("backend.council.controller.process_manager.invoke", new=AsyncMock(return_value=acknowledgement)):
            asyncio.run(CouncilController()._execute_intervention_turn(production, intervention))

        refreshed = get_production(production["id"], private=True)
        self.assertEqual(refreshed["status"], "awaiting_user")
        self.assertEqual(list_shots(production["id"], private=True)[0]["prompt"], "Earlier Council suggestion")
        saved = council_snapshot(production["id"])["interventions"][0]
        self.assertTrue(saved["action_results"] == [])
        self.assertTrue(any(
            item.get("metadata", {}).get("no_executable_action") is True
            for item in list_messages(production["id"])
        ))

    def test_execution_contract_rejects_weak_scene_and_video_prompts(self):
        controller = CouncilController()
        scene_task = {"task_type": "scene_frame_design", "output_contract": "scene_frame_plan.v1"}
        prompt_task = {"task_type": "generation_prompt", "output_contract": "generation_prompt.v1"}
        with self.assertRaisesRegex(RuntimeError, "detailed shot-specific"):
            controller._validate_task_deliverable(scene_task, {"opening_frame_prompt": "man in room"})
        with self.assertRaisesRegex(RuntimeError, "detailed executable"):
            controller._validate_task_deliverable(prompt_task, {"prompt": "move slightly"})
        controller._validate_task_deliverable(scene_task, {
            "opening_frame_prompt": "Medium close shot of the established performer beside the sampler in the approved basement studio under amber practical light",
            "source_reference_ids": ["performer", "studio"],
        })
        controller._validate_task_deliverable(prompt_task, {
            "prompt": "The established performer taps the sampler pads in rhythm while the locked medium close camera holds with subtle handheld breathing motion",
        })

    @patch("backend.council.controller.selected_skill_manifest_context", return_value="SELECTED SKILL FILES")
    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_council_prompt_contains_enabled_skills_seat_instructions_and_shot_context(self, _which, _skills):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        production["skills"] = ["skill-one"]
        save_config(production["id"], config, validation)
        planning = CouncilController().initialize_planning_tasks(production["id"])
        for task in planning:
            payload = {"shots": [{"title": "Basement performance", "prompt": "Performer works the sampler", "duration": 5}]}
            if task["role_id"] != "technical-director":
                payload = {"summary": "approved"}
            save_deliverable(production["id"], task["id"], task["role_id"], task["output_contract"], payload)
            update_task(task["id"], state="completed")
        task = next(item for item in CouncilController().initialize_execution_tasks(production["id"])
                    if item["task_type"] == "scene_frame_design")
        configured_seat = next(item for item in list_seats(production["id"]) if "scene-frame-designer" in item["role_ids"])
        configured_seat["custom_instructions"] = "Keep the visual language grounded."
        prompt = CouncilController()._build_prompt(production, task, configured_seat, [])
        self.assertIn("SELECTED SKILL FILES", prompt)
        self.assertNotIn("ENABLED SKILL INSTRUCTIONS", prompt)
        self.assertIn("project-native; read before acting", prompt)
        self.assertIn("Keep the visual language grounded.", prompt)
        self.assertIn("Basement performance", prompt)
        self.assertIn("SCENE-FRAME CONTRACT", prompt)
        self.assertIn("CREATIVE DIRECTION", prompt)

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_council_task_persists_session_and_deliverable(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        task = controller.initialize_planning_tasks(production["id"])[0]
        result = AgentResult(
            "agy",
            {
                "summary": "Song analysis complete.", "decision": "approve",
                "content": self.audio_analysis_content(production["id"]), "issues": [],
                "next_action": "Create the visual treatment.", "confidence": 0.9,
                "requires_user": False,
            },
            "", "agy-session-1", "agy-test", "high",
        )
        with patch("backend.council.controller.process_manager.invoke", new=AsyncMock(return_value=result)):
            asyncio.run(controller._execute_task(production, task))
        snapshot = council_snapshot(production["id"])
        self.assertEqual(snapshot["tasks"][0]["state"], "completed")
        self.assertEqual(snapshot["deliverables"][0]["contract"], "audio_timeline.v1")
        self.assertEqual(snapshot["activity"]["state"], "completed")

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_agent_revision_is_bounded_and_requeued(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        task = controller.initialize_planning_tasks(production["id"])[0]
        result = AgentResult(
            "agy",
            {
                "summary": "The timeline needs one correction.", "decision": "revise",
                "content": {}, "issues": [{"severity": "medium", "message": "Missing boundary"}],
                "next_action": "Correct the boundary.", "confidence": 0.6,
                "requires_user": False,
            },
            "", "agy-session-1", "agy-test", "high",
        )
        with patch("backend.council.controller.process_manager.invoke", new=AsyncMock(return_value=result)):
            asyncio.run(controller._execute_task(production, task))
        snapshot = council_snapshot(production["id"])
        self.assertEqual(snapshot["tasks"][0]["state"], "queued")
        self.assertEqual(snapshot["tasks"][0]["attempt"], 1)
        self.assertEqual(snapshot["activity"]["state"], "retrying")

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_non_user_escalation_stays_inside_bounded_revision_loop(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        task = controller.initialize_planning_tasks(production["id"])[0]
        result = AgentResult(
            "agy",
            {
                "summary": "The specialist can resolve this conflict.", "decision": "escalate",
                "content": {}, "issues": [{"severity": "medium", "message": "Revise the boundary"}],
                "next_action": "Return to the specialist.", "confidence": 0.7,
                "requires_user": False,
            },
            "", "agy-session-1", "agy-test", "high",
        )
        with patch("backend.council.controller.process_manager.invoke", new=AsyncMock(return_value=result)):
            asyncio.run(controller._execute_task(production, task))
        snapshot = council_snapshot(production["id"])
        self.assertEqual(snapshot["tasks"][0]["state"], "queued")
        self.assertFalse(any(item["status"] == "pending" for item in list_decisions(production["id"])))
        self.assertEqual(get_production(production["id"], private=True)["status"], "running")

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_rejected_review_returns_findings_to_prompt_engineer_before_regeneration(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        planning = controller.initialize_planning_tasks(production["id"])
        for task in planning:
            payload = {"shots": [{"title": "Opening", "prompt": "Original prompt", "duration": 5}]}
            if task["role_id"] != "technical-director":
                payload = {"summary": "approved"}
            save_deliverable(production["id"], task["id"], task["role_id"], task["output_contract"], payload)
            update_task(task["id"], state="completed")
        controller.initialize_execution_tasks(production["id"])
        shot = list_shots(production["id"], private=True)[0]
        tasks = list_tasks(production["id"])
        prompt_task = next(item for item in tasks if item["task_type"] == "generation_prompt")
        generation_task = next(item for item in tasks if item["task_type"] == "video_generation")
        qc_task = next(item for item in tasks if item["task_type"] == "technical_media_review")
        accept_task = next(item for item in tasks if item["task_type"] == "shot_acceptance")
        attempt = create_shot_attempt(shot["id"], 1, "opening.png")
        save_deliverable(
            production["id"], generation_task["id"], "comfyui", generation_task["output_contract"],
            {"shot_id": shot["id"], "attempt_id": attempt["id"]},
        )
        review_delivery = save_deliverable(
            production["id"], qc_task["id"], "technical-qc", qc_task["output_contract"],
            {"summary": "Motion defect"},
        )
        save_review(
            production["id"], qc_task["id"], review_delivery["id"], "agy_audio",
            "technical_media_review", "revise",
            [{"severity": "high", "message": "Correct the movement direction",
              "target_role": "scene-frame-designer"}],
        )
        asyncio.run(controller._accept_or_retry_shot(production, accept_task))
        refreshed = {item["id"]: item for item in list_tasks(production["id"])}
        design_task = next(item for item in refreshed.values() if item["task_type"] == "scene_frame_design")
        render_task = next(item for item in refreshed.values() if item["task_type"] == "scene_frame_render")
        self.assertEqual(design_task["state"], "queued")
        self.assertEqual(render_task["state"], "queued")
        self.assertEqual(refreshed[prompt_task["id"]]["state"], "queued")
        self.assertEqual(refreshed[generation_task["id"]]["state"], "queued")
        self.assertEqual(refreshed[accept_task["id"]]["state"], "queued")
        self.assertEqual(
            refreshed[prompt_task["id"]]["input"]["review_feedback"][0]["findings"][0]["message"],
            "Correct the movement direction",
        )

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_recovery_reconciles_approved_shot_by_shot_id(self, _which):
        """A persisted approval without task_id must unblock the acceptance task."""
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        planning = controller.initialize_planning_tasks(production["id"])
        for task in planning:
            payload = {"shots": [{"title": "Opening", "prompt": "Opening", "duration": 5}]} if task["role_id"] == "technical-director" else {"summary": "approved"}
            save_deliverable(production["id"], task["id"], task["role_id"], task["output_contract"], payload)
            update_task(task["id"], state="completed")
        controller.initialize_execution_tasks(production["id"])
        shot = list_shots(production["id"], private=True)[0]
        tasks = list_tasks(production["id"])
        generation = next(item for item in tasks if item["task_type"] == "video_generation")
        acceptance = next(item for item in tasks if item["task_type"] == "shot_acceptance")
        attempt = create_shot_attempt(shot["id"], 1, "opening.png")
        save_deliverable(
            production["id"], generation["id"], "comfyui", generation["output_contract"],
            {"shot_id": shot["id"], "attempt_id": attempt["id"]},
        )
        update_task(acceptance["id"], state="waiting")
        decision = add_decision(
            production["id"], "shot_review", "Approve shot", "Approved",
            {"shot_id": shot["id"], "attempt_id": attempt["id"]},
        )
        resolve_decision(production["id"], decision["id"], "approved", "user", "Approved")
        self.assertTrue(controller._reconcile_approved_waiting_tasks(production["id"]))
        refreshed = {item["id"]: item for item in list_tasks(production["id"])}
        self.assertEqual(refreshed[acceptance["id"]]["state"], "completed")
        self.assertEqual(get_production(production["id"], private=True)["status"], "queued")
        self.assertEqual(list_shots(production["id"], private=True)[0]["accepted_attempt"], 1)

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_agent_escalation_creates_actionable_decision_and_can_resume(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        task = controller.initialize_planning_tasks(production["id"])[0]
        result = AgentResult(
            "agy",
            {
                "summary": "User direction is required.", "decision": "escalate",
                "content": self.audio_analysis_content(production["id"], requires_user=True), "issues": [],
                "next_action": "Approve the proposed boundary.", "confidence": 0.7,
                "requires_user": True,
            },
            "", "agy-session-1", "agy-test", "high",
        )
        with patch("backend.council.controller.process_manager.invoke", new=AsyncMock(return_value=result)):
            asyncio.run(controller._execute_task(production, task))
        snapshot = council_snapshot(production["id"])
        self.assertEqual(snapshot["tasks"][0]["state"], "waiting")
        self.assertEqual(len(snapshot["deliverables"]), 1)
        decision = next(item for item in list_decisions(production["id"]) if item["status"] == "pending")
        self.assertEqual(decision["payload"]["task_id"], task["id"])
        self.assertTrue(controller.approve_waiting_task(production["id"], decision["payload"]))
        self.assertEqual(list_tasks(production["id"])[0]["state"], "completed")
        self.assertEqual(get_production(production["id"], private=True)["status"], "queued")

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_new_config_revision_retargets_only_unstarted_tasks(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        first_revision = save_config(production["id"], config, validation)
        tasks = CouncilController().initialize_planning_tasks(production["id"])
        update_task(tasks[0]["id"], state="completed", attempt=1)
        second_revision = save_config(production["id"], config, validation)
        changed = retarget_unstarted_tasks(production["id"], second_revision)
        refreshed = {item["id"]: item for item in list_tasks(production["id"])}
        self.assertEqual(changed, len(tasks) - 1)
        self.assertEqual(refreshed[tasks[0]["id"]]["config_revision"], first_revision)
        self.assertTrue(all(refreshed[item["id"]]["config_revision"] == second_revision for item in tasks[1:]))

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_live_config_revision_retargets_waiting_tasks_without_locking_them(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        first_revision = save_config(production["id"], config, validation)
        tasks = CouncilController().initialize_planning_tasks(production["id"])
        update_task(tasks[0]["id"], state="completed", attempt=1)
        update_task(tasks[1]["id"], state="waiting")
        second_revision = save_config(production["id"], config, validation)
        changed = retarget_unstarted_tasks(production["id"], second_revision)
        refreshed = {item["id"]: item for item in list_tasks(production["id"])}
        self.assertEqual(changed, len(tasks) - 1)
        self.assertEqual(refreshed[tasks[0]["id"]]["config_revision"], first_revision)
        self.assertEqual(refreshed[tasks[1]["id"]]["config_revision"], second_revision)

    @patch("backend.council.capabilities.shutil.which", return_value="agent.cmd")
    def test_live_revision_does_not_duplicate_existing_logical_planning_graph(self, _which):
        config = self.council_config()
        validation = verify_council_config(config, catalog=CATALOG)
        production = self.production()
        save_config(production["id"], config, validation)
        controller = CouncilController()
        first = controller.initialize_planning_tasks(production["id"])
        second_revision = save_config(production["id"], config, validation)
        retarget_unstarted_tasks(production["id"], second_revision)
        second = controller.initialize_planning_tasks(production["id"])
        self.assertEqual([item["id"] for item in first], [item["id"] for item in second])
        self.assertEqual(len(list_tasks(production["id"])), len(first))
        self.assertTrue(all(item["config_revision"] == second_revision for item in second))


if __name__ == "__main__":
    unittest.main()
