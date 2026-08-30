from __future__ import annotations

import asyncio
import json
import re
import secrets
import shutil
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..agents import AgentExecutionError, process_manager
from ..config import (
    AGY_DEFAULT_EFFORT, AGY_DEFAULT_MODEL, CODEX_DEFAULT_EFFORT, CODEX_DEFAULT_MODEL,
    INPUT, PRODUCTIONS, ROOT,
)
from ..db import connect, get_job, next_position, now_iso
from ..generation import normalize_generation_settings
from ..library import resolve_asset_path
from ..media import (assemble_clips, attach_song, extract_last_frame, extract_review_frames,
                     media_probe, prepare_agent_audio_carrier, prepare_audio_segment,
                     probe_audio_metadata)
from ..production_db import (add_artifact, add_decision, add_event, add_message, add_reference,
                             create_shot_attempt, get_artifact, get_production, get_reference,
    list_artifacts, list_decisions, list_references, list_shots,
    megapixels_for_duration, replace_shot_plan, update_production,
    normalize_production_generation, update_shot, update_shot_attempt)
from ..skill_catalog import selected_skill_manifest_context
from ..worker import QueueWorker
from . import COUNCIL_PIPELINE
from .contracts import CouncilEnvelope, positive_generation_duration, role_skill_path, roles_by_id
from .db import (add_activity, create_task, deliverable_for_task, get_session,
                 get_task,
                 latest_config, latest_deliverable, latest_review_for_task,
                 list_deliverables, list_interventions, list_seats, list_tasks,
                 ready_tasks, retarget_unstarted_tasks, save_deliverable, save_review, update_intervention,
                 update_session, update_task, update_task_dependencies, update_task_input)


PLANNING_GRAPH = (
    {"key": "audio-analysis", "stage": "song_analysis", "task_type": "audio_analysis", "role": "audio-analyst"},
    {"key": "visual-treatment", "stage": "treatment", "task_type": "visual_treatment", "role": "visual-director", "depends": ["audio-analysis"]},
    {"key": "storyboard", "stage": "storyboard", "task_type": "storyboard_planning", "role": "storyboard-editor", "depends": ["audio-analysis", "visual-treatment"]},
    {"key": "execution-plan", "stage": "execution_planning", "task_type": "execution_planning", "role": "technical-director", "depends": ["storyboard"]},
)


class CouncilController:
    """Durable, deterministic scheduler for the isolated Council pipeline."""

    def __init__(self) -> None:
        self._wake = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._active: dict[str, asyncio.Task[None]] = {}
        self.queue_worker: QueueWorker | None = None
        self.current_jobs: dict[str, str] = {}

    def bind_queue(self, worker: QueueWorker) -> None:
        self.queue_worker = worker

    def has_active_generation(self, production_id: str) -> bool:
        return production_id in self.current_jobs

    async def comfy_generation_running(self, production_id: str) -> bool:
        """Return true only while this production owns an actively sampled job.

        ``current_jobs`` is intentionally not enough: a controller can still be
        waiting for output validation after Comfy has stopped sampling.  The
        queue status is the source of truth for intervention timing.
        """
        job_id = self.current_jobs.get(production_id)
        if not job_id:
            return False
        try:
            job = get_job(job_id, public=False)
        except Exception:
            return False
        # A queued Comfy job has not started sampling yet, so it is safe to
        # cancel/replan Council work around it. Only an actively executing
        # generation must receive an intervention at its next safe checkpoint.
        return bool(job and job.get("status") in {"starting", "running", "verifying"})

    def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stopping = False
        self._repair_missing_waiting_decisions()
        self._loop_task = asyncio.create_task(self._loop(), name="council-controller")

    def _repair_missing_waiting_decisions(self) -> None:
        """Make pre-fix waiting tasks actionable after a bridge restart."""
        with connect() as db:
            rows = db.execute(
                "SELECT id FROM productions WHERE pipeline=? AND status='awaiting_user'",
                (COUNCIL_PIPELINE,),
            ).fetchall()
        for row in rows:
            production_id = str(row["id"])
            if any(item["status"] == "pending" for item in list_decisions(production_id)):
                continue
            waiting = next((item for item in list_tasks(production_id) if item["state"] == "waiting"), None)
            if not waiting:
                continue
            role_label = str(waiting["role_id"]).replace("-", " ").title()
            add_decision(
                production_id, waiting["stage"], f"Council input required · {role_label}",
                f"{role_label} stopped at a user decision checkpoint. Approve to resume this task using the preserved Council state.",
                {"task_id": waiting["id"], "role_id": waiting["role_id"], "recovered": True},
            )
            add_message(
                production_id, "system", "user", "decision",
                f"Recovered the missing {role_label} decision card after bridge restart.",
                {"task_id": waiting["id"], "gate": waiting["stage"], "recovered": True},
            )

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        for production_id in list(self._active):
            await process_manager.cancel(production_id)
        if self._loop_task:
            await self._loop_task
        if self._active:
            await asyncio.gather(*self._active.values(), return_exceptions=True)
        self._active.clear()

    def notify(self) -> None:
        self._wake.set()

    def has_active_work(self, production_id: str) -> bool:
        task = self._active.get(production_id)
        return bool(task and not task.done())

    @property
    def active_productions(self) -> list[str]:
        return sorted(key for key, task in self._active.items() if not task.done())

    async def cancel(self, production_id: str) -> bool:
        """Cancel the tracked Council owner, not only its child CLI process.

        Legacy cancellation stops the provider, cancels the owning scheduler
        task, and waits for it to leave the in-memory active map.  Council used
        to do only the first part, leaving a cancelled-looking controller alive
        and making interventions appear ignored.
        """
        cancelled = await process_manager.cancel(production_id)
        job_id = self.current_jobs.get(production_id)
        if job_id:
            cancelled = True
            if self.queue_worker:
                try:
                    await self.queue_worker.cancel(job_id)
                except Exception:
                    pass
        owner = self._active.get(production_id)
        if owner and not owner.done() and owner is not asyncio.current_task():
            cancelled = True
            owner.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(owner), timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                pass
        if owner and owner.done():
            self._active.pop(production_id, None)
        self.notify()
        return cancelled

    async def _loop(self) -> None:
        while not self._stopping:
            self._reap()
            for production_id in self._queued_productions():
                if production_id not in self._active:
                    self._active[production_id] = asyncio.create_task(
                        self._run_production(production_id), name=f"council-{production_id}",
                    )
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    def _reap(self) -> None:
        for production_id, task in list(self._active.items()):
            if task.done():
                self._active.pop(production_id, None)
                try:
                    task.result()
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # final containment; stage methods persist normal errors
                    update_production(production_id, status="failed", error=str(exc))
                    add_activity(production_id, "controller", "failed", f"Controller failed: {exc}")

    @staticmethod
    def _queued_productions() -> list[str]:
        with connect() as db:
            rows = db.execute(
                """SELECT id FROM productions
                   WHERE pipeline=? AND status IN ('queued','running','retrying')
                   ORDER BY created_at""",
                (COUNCIL_PIPELINE,),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def initialize_planning_tasks(self, production_id: str) -> list[dict[str, Any]]:
        config = latest_config(production_id)
        if not config:
            raise RuntimeError("Council production has no validated configuration")
        existing = list_tasks(production_id)
        created: dict[str, dict[str, Any]] = {}
        role_map = roles_by_id()
        for node in PLANNING_GRAPH:
            key = f"planning:{node['key']}:r{config['revision']}"
            dependencies = [created[name]["id"] for name in node.get("depends", [])]
            task = self._find_existing_task(existing, key) or create_task(
                production_id,
                config_revision=int(config["revision"]),
                stage=str(node["stage"]),
                task_type=str(node["task_type"]),
                role_id=str(node["role"]),
                output_contract=str(role_map[str(node["role"])]["output_contract"]),
                idempotency_key=key,
                dependencies=dependencies,
            )
            if task not in existing:
                existing.append(task)
            created[str(node["key"])] = task
        return list(created.values())

    @staticmethod
    def _logical_task_key(idempotency_key: str) -> str:
        """Remove the config revision suffix from a task identity.

        Settings revisions describe which model/effort a future turn uses;
        they do not describe a second copy of the same production task.
        Keeping the logical identity stable prevents a live settings edit from
        creating a duplicate planning or shot graph.
        """
        return re.sub(r":r\d+(?=:|$)", "", str(idempotency_key))

    @classmethod
    def _find_existing_task(cls, tasks: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
        exact = next((item for item in tasks if item.get("idempotency_key") == key), None)
        if exact and exact.get("state") not in {"cancelled", "failed"}:
            return exact
        logical = cls._logical_task_key(key)
        candidates = [
            item for item in tasks
            if cls._logical_task_key(str(item.get("idempotency_key") or "")) == logical
            and item.get("state") not in {"cancelled", "failed"}
        ]
        if not candidates:
            return None
        # Prefer the newest revision, then a task that is already part of the
        # active graph. Completed older attempts remain historical evidence but
        # must not cause another live task to be created.
        return max(candidates, key=lambda item: (int(item.get("config_revision") or 0), str(item.get("updated_at") or "")))

    @staticmethod
    def _find_shot_rows(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            for key in ("shots", "shot_plan", "timeline", "scenes"):
                rows = value.get(key)
                if isinstance(rows, list) and rows and all(isinstance(item, dict) for item in rows):
                    return rows
            for child in value.values():
                found = CouncilController._find_shot_rows(child)
                if found:
                    return found
        if isinstance(value, list):
            for child in value:
                found = CouncilController._find_shot_rows(child)
                if found:
                    return found
        return []

    @staticmethod
    def _prompt_value(value: Any) -> str:
        if isinstance(value, str):
            return " ".join(value.split())
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            return "; ".join(
                item for child in value
                if (item := CouncilController._prompt_value(child))
            )
        if isinstance(value, dict):
            return "; ".join(
                f"{key.replace('_', ' ')}: {item}"
                for key, child in value.items()
                if (item := CouncilController._prompt_value(child))
            )
        return ""

    @classmethod
    def _shot_detail_prompt(cls, value: Any) -> str:
        """Extract a creative brief from nested execution-plan structures.

        The technical-director contract may keep the shot rows and the richer
        ``opening_frame_briefs``/``generation_plan`` records in separate
        branches.  The old materializer only looked at a top-level prompt and
        silently substituted ``Shot 001`` when it missed that branch.
        """
        if not isinstance(value, dict):
            return ""
        fields = (
            "prompt", "video_prompt", "generation_prompt", "scene_description",
            "visual_description", "description", "action", "visual_action",
            "performance", "camera", "camera_movement", "framing", "composition",
            "lighting", "motion", "continuity", "audio_context", "lyric_excerpt",
            "negative_constraints", "acceptance_criteria",
        )
        parts: list[str] = []
        seen: set[str] = set()
        for key in fields:
            text = cls._prompt_value(value.get(key))
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                parts.append(text)
        for key in ("shot_spec", "visual", "scene", "generation", "opening_frame", "video"):
            child = value.get(key)
            if isinstance(child, dict):
                text = cls._shot_detail_prompt(child)
                if text and text.casefold() not in seen:
                    seen.add(text.casefold())
                    parts.append(text)
        return " ".join(parts)

    @classmethod
    def _find_shot_detail(cls, value: Any, row: dict[str, Any], index: int) -> dict[str, Any] | None:
        """Find the detailed record belonging to one shot in any plan branch."""
        wanted: set[str] = {
            f"s{index:02d}", f"s{index:03d}", f"shot {index:02d}",
            f"shot {index:03d}", f"shot_{index:02d}", f"shot_{index:03d}",
            str(index),
        }
        for key in ("shot_id", "shot", "id", "key", "slug", "name", "title", "label"):
            raw = row.get(key)
            if raw is not None:
                wanted.add(str(raw).strip().casefold())
        title = str(row.get("title") or row.get("name") or "").strip().casefold()

        def matches(item: dict[str, Any]) -> bool:
            identifiers = {
                str(item.get(key)).strip().casefold()
                for key in ("shot_id", "shot", "id", "key", "slug", "name", "title", "label")
                if item.get(key) is not None
            }
            if identifiers & wanted:
                return True
            if title and title in identifiers:
                return True
            for key in ("shot_index", "index", "number", "position"):
                try:
                    if int(item.get(key)) == index:
                        return True
                except (TypeError, ValueError):
                    continue
            return False

        def walk(node: Any) -> dict[str, Any] | None:
            if isinstance(node, dict):
                if matches(node) and cls._shot_detail_prompt(node):
                    return node
                for key in (
                    "opening_frame_briefs", "shot_briefs", "generation_plan",
                    "shot_plan", "shots", "scenes", "timeline", "visual_treatment",
                ):
                    if key in node:
                        found = walk(node[key])
                        if found:
                            return found
                for child in node.values():
                    found = walk(child)
                    if found:
                        return found
            elif isinstance(node, list):
                for child in node:
                    found = walk(child)
                    if found:
                        return found
            return None

        return walk(value)

    @classmethod
    def _usable_shot_prompt(cls, prompt: Any, title: str) -> bool:
        text = " ".join(str(prompt or "").split())
        if not text:
            return False
        # Keep short prompts valid for interactive/test productions.  The
        # dangerous case is a missing scene brief silently becoming a generic
        # title such as ``Shot 001``; that is what must be rejected here.
        if re.fullmatch(r"(?:shot|scene)\s*[_ -]?\d+", text, flags=re.IGNORECASE):
            return False
        if title and text.casefold() == title.casefold() and re.fullmatch(
            r"(?:shot|scene)\s*[_ -]?\d+", title, flags=re.IGNORECASE
        ):
            return False
        return True

    def _plan_sources(self, production_id: str) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for contract in ("execution_manifest.v1", "storyboard.v1", "visual_treatment.v1"):
            deliverable = latest_deliverable(production_id, contract)
            payload = (deliverable or {}).get("payload")
            if isinstance(payload, (dict, list)):
                sources.append(payload)
        return sources

    def _materialize_shot_plan(self, production: dict[str, Any]) -> list[dict[str, Any]]:
        production_id = str(production["id"])
        existing = list_shots(production_id, private=True)
        sources = self._plan_sources(production_id)
        if existing:
            # Older Council runs already persisted title-only prompts. Repair
            # those records in place from the approved manifest so resuming a
            # production cannot submit a generic Shot 001 prompt again.
            for index, shot in enumerate(existing, 1):
                title = str(shot.get("title") or f"Shot {index:03d}").strip()
                if self._usable_shot_prompt(shot.get("prompt"), title):
                    continue
                detail = next((self._find_shot_detail(source, shot, index) for source in sources), None)
                prompt = self._shot_detail_prompt(detail)
                if not self._usable_shot_prompt(prompt, title):
                    raise RuntimeError(
                        f"Approved Council shot {index} ({title}) has no usable shot-specific prompt; "
                        "the execution manifest must provide the scene action and camera brief."
                    )
                update_shot(shot["id"], prompt=prompt)
            return list_shots(production_id, private=True)
        execution = latest_deliverable(production_id, "execution_manifest.v1")
        storyboard = latest_deliverable(production_id, "storyboard.v1")
        source = (execution or {}).get("payload") or (storyboard or {}).get("payload") or {}
        rows = self._find_shot_rows(source)
        if not rows:
            raise RuntimeError("The approved Council plan does not contain a usable shot list")
        references = list_references(production_id, private=True)
        image_ids = [str(item["id"]) for item in references if item.get("kind") == "image"]
        normalized: list[dict[str, Any]] = []
        cursor = 0.0
        mp_rules = production.get("generation_megapixel_rules") or []
        for index, row in enumerate(rows, 1):
            raw_start = row.get("editorial_start", row.get("start", row.get("start_time", cursor)))
            raw_end = row.get("editorial_end", row.get("end", row.get("end_time")))
            raw_duration = row.get("generation_duration", row.get("duration"))
            if raw_duration is None and raw_end is not None:
                raw_duration = max(1, round(float(raw_end) - float(raw_start)))
            duration = positive_generation_duration(raw_duration or 5)
            start = float(raw_start or cursor)
            end = float(raw_end) if raw_end is not None else start + duration
            if end <= start:
                raise ValueError(f"Shot {index} has an invalid editorial range")
            audio_start = float(row.get("audio_start", row.get("model_audio_start", start)))
            editorial_duration = end - start
            trim_in = float(row.get("editorial_trim_in", row.get("trim_in", max(0.0, start - audio_start))))
            trim_out = float(row.get("editorial_trim_out", row.get("trim_out", max(0.0, duration - trim_in - editorial_duration))))
            if trim_in < 0 or trim_out < 0 or trim_in + trim_out >= duration:
                raise ValueError(f"Shot {index} has invalid editorial trims")
            title = str(row.get("title") or row.get("name") or f"Shot {index:03d}").strip()
            raw_prompt = str(
                row.get("prompt") or row.get("video_prompt") or row.get("description") or ""
            ).strip()
            detail = next((self._find_shot_detail(candidate, row, index) for candidate in sources), None)
            detail_prompt = self._shot_detail_prompt(detail)
            prompt = raw_prompt if self._usable_shot_prompt(raw_prompt, title) else detail_prompt
            if not self._usable_shot_prompt(prompt, title):
                raise RuntimeError(
                    f"Execution manifest shot {index} ({title}) has no usable shot-specific prompt; "
                    "refusing to fall back to the shot title."
                )
            requested_audio_mode = str(production.get("generation_audio_mode") or "auto").strip().lower()
            if requested_audio_mode == "lip_sync":
                audio_mode = "lip_sync"
            elif requested_audio_mode == "silent":
                audio_mode = "silent"
            else:
                audio_mode = str(row.get("audio_mode") or ("lip_sync" if row.get("lip_sync") else "silent"))
            if audio_mode not in {"silent", "lip_sync"}:
                audio_mode = "silent"
            requested_refs = row.get("reference_ids") if isinstance(row.get("reference_ids"), list) else image_ids
            continuity = str(row.get("continuity") or production.get("continuity_mode") or "hard_cut")
            if continuity not in {"hard_cut", "sequential"}:
                continuity = "hard_cut"
            normalized.append({
                "title": title, "prompt": prompt, "mode": "opening",
                "continuity": continuity,
                "audio_mode": audio_mode, "audio_source": "song", "audio_start": audio_start,
                "audio_duration": float(duration if audio_mode == "lip_sync" else row.get("audio_duration", duration)), "duration": duration,
                "megapixels": float(row.get("megapixels") or megapixels_for_duration(duration, mp_rules)),
                "aspect_ratio": str(production.get("generation_aspect_ratio") or "16:9"),
                "steps": int(production.get("generation_steps") or 6), "engine": "turbo",
                "turbo_profile": str(production.get("generation_turbo_profile") or "v4"),
                "reference_ids": [str(value) for value in requested_refs if str(value) in image_ids],
                "editorial_start": start, "editorial_end": end, "trim_in": trim_in, "trim_out": trim_out,
            })
            cursor = end
        return replace_shot_plan(production_id, normalized)

    def initialize_execution_tasks(self, production_id: str) -> list[dict[str, Any]]:
        production = get_production(production_id, private=True)
        config = latest_config(production_id)
        if not production or not config:
            raise RuntimeError("Council production configuration is missing")
        shots = self._materialize_shot_plan(production)
        existing = list_tasks(production_id)
        revision = int(config["revision"])
        created: list[dict[str, Any]] = []
        visual_task = next((item for item in list_tasks(production_id) if item["task_type"] == "visual_treatment"), None)
        reference_bundle = self._find_existing_task(existing, f"reference-bundle:r{revision}") or create_task(
            production_id, config_revision=revision, stage="references", task_type="reference_bundle_prepare",
            role_id="controller", worker_type="controller", output_contract="reference_bundle.v1",
            idempotency_key=f"reference-bundle:r{revision}",
            dependencies=[visual_task["id"]] if visual_task else [], inputs={}, max_attempts=2,
        )
        created.append(reference_bundle)
        # Reference preparation is a separate phase from video generation.
        # Build every shot's scene-frame task first so the scheduler can place
        # a hard barrier in front of every ComfyUI video task. Sequential shots
        # may still be prepared in order, but they must not depend on a video
        # acceptance task; that would create a reference -> video -> reference
        # cycle and defeat the barrier.
        scene_tasks: list[dict[str, Any]] = []
        prior_scene_render: str | None = None
        for shot in shots:
            prefix = f"shot:{shot['id']}:r{revision}"
            common = {"shot_id": shot["id"], "shot_index": shot["shot_index"]}
            scene_dependencies = [reference_bundle["id"]]
            if prior_scene_render and shot.get("continuity") == "sequential":
                scene_dependencies.append(prior_scene_render)
            design = self._find_existing_task(existing, f"{prefix}:scene-design") or create_task(
                production_id, config_revision=revision, stage="scene_frames", task_type="scene_frame_design",
                role_id="scene-frame-designer", output_contract="scene_frame_plan.v1",
                idempotency_key=f"{prefix}:scene-design",
                dependencies=scene_dependencies,
                inputs=common,
            )
            if design["state"] in {"queued", "waiting"} and set(design.get("dependency_ids", [])) != set(scene_dependencies):
                update_task_dependencies(design["id"], scene_dependencies)
                design = get_task(design["id"]) or design
            render = self._find_existing_task(existing, f"{prefix}:scene-render") or create_task(
                production_id, config_revision=revision, stage="scene_frames", task_type="scene_frame_render",
                role_id="controller", worker_type="controller", output_contract="scene_frame_asset.v1",
                idempotency_key=f"{prefix}:scene-render", dependencies=[design["id"]], inputs=common, max_attempts=2,
            )
            scene_tasks.append({"shot": shot, "prefix": prefix, "common": common, "design": design, "render": render})
            created.extend([design, render])
            prior_scene_render = render["id"]

        barrier_dependencies = [item["render"]["id"] for item in scene_tasks]
        scene_frame_barrier = self._find_existing_task(existing, f"scene-frame-batch:r{revision}") or create_task(
            production_id, config_revision=revision, stage="scene_frames", task_type="scene_frame_barrier",
            role_id="controller", worker_type="controller", output_contract="scene_frame_batch.v1",
            idempotency_key=f"scene-frame-batch:r{revision}",
            dependencies=barrier_dependencies,
            inputs={"shot_ids": [item["shot"]["id"] for item in scene_tasks]}, max_attempts=1,
        )
        if (
            scene_frame_barrier["state"] in {"queued", "waiting"}
            and set(scene_frame_barrier.get("dependency_ids", [])) != set(barrier_dependencies)
        ):
            update_task_dependencies(scene_frame_barrier["id"], barrier_dependencies)
            scene_frame_barrier = get_task(scene_frame_barrier["id"]) or scene_frame_barrier
        created.append(scene_frame_barrier)
        acceptance_ids: list[str] = []
        for scene in scene_tasks:
            shot = scene["shot"]
            prefix = scene["prefix"]
            common = scene["common"]
            design = scene["design"]
            render = scene["render"]
            prompt = self._find_existing_task(existing, f"{prefix}:prompt") or create_task(
                production_id, config_revision=revision, stage="prompting", task_type="generation_prompt",
                role_id="prompt-engineer", output_contract="generation_prompt.v1",
                idempotency_key=f"{prefix}:prompt", dependencies=[render["id"]], inputs=common,
            )
            generation = self._find_existing_task(existing, f"{prefix}:generation") or create_task(
                production_id, config_revision=revision, stage="shot_generation", task_type="video_generation",
                role_id="comfyui", worker_type="comfyui", output_contract="generated_video.v1",
                idempotency_key=f"{prefix}:generation",
                dependencies=[prompt["id"], scene_frame_barrier["id"]], inputs=common, max_attempts=3,
            )
            generation_dependencies = [prompt["id"], scene_frame_barrier["id"]]
            if generation["state"] in {"queued", "waiting"} and set(generation.get("dependency_ids", [])) != set(generation_dependencies):
                update_task_dependencies(generation["id"], generation_dependencies)
                generation = get_task(generation["id"]) or generation
            qc = self._find_existing_task(existing, f"{prefix}:technical-qc") or create_task(
                production_id, config_revision=revision, stage="shot_review", task_type="technical_media_review",
                role_id="technical-qc", output_contract="technical_qc.v1",
                idempotency_key=f"{prefix}:technical-qc", dependencies=[generation["id"]], inputs=common, max_attempts=2,
            )
            review_dependencies = [qc["id"]]
            if shot.get("audio_mode") == "lip_sync":
                av = self._find_existing_task(existing, f"{prefix}:av-sync") or create_task(
                    production_id, config_revision=revision, stage="shot_review", task_type="av_sync_review",
                    role_id="av-sync-reviewer", output_contract="av_sync_review.v1",
                    idempotency_key=f"{prefix}:av-sync", dependencies=[generation["id"]], inputs=common, max_attempts=2,
                )
                review_dependencies.append(av["id"])
            accept = self._find_existing_task(existing, f"{prefix}:accept") or create_task(
                production_id, config_revision=revision, stage="shot_review", task_type="shot_acceptance",
                role_id="controller", worker_type="controller", output_contract="shot_acceptance.v1",
                idempotency_key=f"{prefix}:accept", dependencies=review_dependencies, inputs={**common, "generation_task_id": generation["id"], "review_task_ids": review_dependencies}, max_attempts=1,
            )
            created.extend([prompt, generation, qc, *([av] if shot.get("audio_mode") == "lip_sync" else []), accept])
            acceptance_ids.append(accept["id"])
        assembly = self._find_existing_task(existing, f"assembly:r{revision}") or create_task(
            production_id, config_revision=revision, stage="assembly", task_type="final_assembly",
            role_id="post-production-editor", worker_type="ffmpeg", output_contract="assembly_result.v1",
            idempotency_key=f"assembly:r{revision}", dependencies=acceptance_ids, inputs={}, max_attempts=2,
        )
        final = self._find_existing_task(existing, f"final-review:r{revision}") or create_task(
            production_id, config_revision=revision, stage="final_review", task_type="final_media_review",
            role_id="technical-qc", output_contract="final_review.v1",
            idempotency_key=f"final-review:r{revision}", dependencies=[assembly["id"]], inputs={}, max_attempts=2,
        )
        return [*created, assembly, final]

    def approve_planning(self, production_id: str) -> None:
        self.initialize_execution_tasks(production_id)
        update_production(production_id, status="queued", stage="scene_frames", progress=0.36, error=None)
        add_activity(production_id, "controller", "queued", "Planning approved; scene-frame work is queued")
        self.notify()

    def approve_waiting_task(self, production_id: str, decision_payload: dict[str, Any] | None = None) -> bool:
        """Resume a non-review Council role after explicit user approval."""
        payload = decision_payload or {}
        task_id = str(payload.get("task_id") or "")
        waiting = [
            item for item in list_tasks(production_id)
            if item["state"] == "waiting" and item["task_type"] != "shot_acceptance"
            and (not task_id or item["id"] == task_id)
        ]
        if not waiting:
            return False
        task = waiting[0]
        if deliverable_for_task(task["id"]):
            update_task(
                task["id"], state="completed", lease_token=None,
                finished_at=now_iso(), error_code=None, error_detail=None,
            )
        else:
            # Compatibility recovery for waiting tasks created before their
            # envelopes were persisted as deliverables.
            update_task(
                task["id"], state="queued", lease_token=None,
                error_code=None, error_detail=None,
            )
        update_production(production_id, status="queued", stage=task["stage"], error=None)
        add_activity(
            production_id, "controller", "queued",
            f"User approved {task['role_id'].replace('-', ' ')}; Council execution will continue",
            task_id=task["id"],
        )
        self.notify()
        return True

    @staticmethod
    def _dependency_deliverables(task: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for task_id in task.get("dependency_ids", []) if (item := deliverable_for_task(task_id))]

    @staticmethod
    def _payload_text(payload: Any, *keys: str) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in payload.values():
                found = CouncilController._payload_text(value, *keys)
                if found:
                    return found
        return ""

    def _shot(self, production_id: str, shot_id: str) -> dict[str, Any]:
        shot = next((item for item in list_shots(production_id, private=True) if item["id"] == shot_id), None)
        if not shot:
            raise RuntimeError("Council shot no longer exists")
        return shot

    def _image_provider_seat(self, production_id: str, revision: int) -> dict[str, Any]:
        seats = [seat for seat in list_seats(production_id, revision) if seat["active"] and "image" in seat.get("effective_capabilities", [])]
        preferred = next((seat for seat in seats if "scene-frame-designer" in seat["role_ids"]), None)
        if not preferred and seats:
            preferred = seats[0]
        if not preferred:
            raise RuntimeError("No configured Council seat has verified image capability")
        return preferred

    @staticmethod
    def _image_provider_options(seat: dict[str, Any]) -> dict[str, Any]:
        """Use the selected image seat first, with Legacy's safe fallback.

        A Council seat may be AGY-only or Codex-only.  ``auto`` still honors
        that seat as the preferred provider while supplying a valid model for
        the other provider if the first CLI completes without a file.
        """
        runtime = str(seat.get("runtime") or "codex")
        if runtime == "agy":
            return {
                "model": CODEX_DEFAULT_MODEL,
                "effort": CODEX_DEFAULT_EFFORT,
                "provider": "auto",
                "preferred_provider": "agy",
                "agy_model": seat["model"],
                "agy_effort": seat["effort"],
            }
        return {
            "model": seat["model"],
            "effort": seat["effort"],
            "provider": "auto",
            "preferred_provider": "codex",
            "agy_model": AGY_DEFAULT_MODEL,
            "agy_effort": AGY_DEFAULT_EFFORT,
        }

    def _image_callbacks(
        self, production_id: str, seat: dict[str, Any], task: dict[str, Any], phase: str,
    ) -> tuple[Any, Any]:
        label = f"{seat['label']} · {phase}"
        return (
            self._trace_callback(production_id, seat, task, label=label),
            self._heartbeat_callback(production_id, seat, task, label=phase),
        )

    async def _execute_controller_task(self, production: dict[str, Any], task: dict[str, Any]) -> None:
        production_id = str(production["id"])
        attempt = int(task["attempt"]) + 1
        update_task(task["id"], state="running", attempt=attempt, lease_token=uuid.uuid4().hex,
                    started_at=task.get("started_at") or now_iso(), error_code=None, error_detail=None)
        update_production(production_id, status="running", stage=task["stage"])
        add_activity(production_id, task["worker_type"], "running",
                     f"{task['worker_type'].title()} · {task['task_type'].replace('_', ' ')}",
                     role_id=task["role_id"], task_id=task["id"])
        try:
            if task["task_type"] == "reference_bundle_prepare":
                await self._prepare_reference_bundle(production, task)
            elif task["task_type"] == "scene_frame_barrier":
                await self._complete_scene_frame_barrier(production, task)
            elif task["task_type"] == "scene_frame_render":
                await self._render_scene_frames(production, task)
            elif task["task_type"] == "video_generation":
                await self._generate_video(production, task)
            elif task["task_type"] == "shot_acceptance":
                await self._accept_or_retry_shot(production, task)
            elif task["task_type"] == "final_assembly":
                await self._assemble(production, task)
            else:
                raise RuntimeError(f"Unsupported Council controller task: {task['task_type']}")
        except asyncio.CancelledError:
            update_task(task["id"], state="queued", lease_token=None,
                        error_code="interrupted", error_detail="Interrupted at a safe checkpoint")
            raise
        except Exception as exc:
            if task["task_type"] == "video_generation":
                failed_inputs = dict(task.get("input") or {})
                attempt_id = failed_inputs.get("attempt_id")
                if attempt_id:
                    update_shot_attempt(str(attempt_id), status="failed", error=str(exc)[:8000])
                shot_id = failed_inputs.get("shot_id")
                if shot_id:
                    update_shot(
                        str(shot_id),
                        status="retrying" if attempt < int(task["max_attempts"]) else "failed",
                    )
                # Failed Comfy jobs are terminal. A controller retry must stage
                # fresh inputs and create a new job instead of polling the same
                # failed job ID again.
                update_task_input(task["id"], {
                    "shot_id": failed_inputs.get("shot_id"),
                    "shot_index": failed_inputs.get("shot_index"),
                })
            if attempt < int(task["max_attempts"]):
                update_task(task["id"], state="queued", lease_token=None,
                            error_code="controller_task_error", error_detail=str(exc))
                add_activity(production_id, "controller", "retrying",
                             f"{task['task_type'].replace('_', ' ').title()} retry queued",
                             task_id=task["id"], metadata={"error": str(exc)})
                return
            update_task(task["id"], state="failed", lease_token=None, finished_at=now_iso(),
                        error_code="controller_task_error", error_detail=str(exc))
            update_production(production_id, status="failed", stage=task["stage"], error=str(exc))
            add_message(production_id, "system", "all", "error", str(exc), {"task_id": task["id"]})

    @staticmethod
    def _reference_briefs(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            # The visual-treatment contract stores agent-authored reference
            # briefs under reference_set.generation_briefs.  Keep the older
            # keys for backwards compatibility, but do not silently fall
            # through to the generic controller reference when this field is
            # present.
            for key in ("references", "reference_briefs", "visual_references", "generation_briefs"):
                rows = value.get(key)
                if isinstance(rows, list):
                    found = [item for item in rows if isinstance(item, dict)]
                    if found:
                        return found
            for child in value.values():
                found = CouncilController._reference_briefs(child)
                if found:
                    return found
        if isinstance(value, list):
            for child in value:
                found = CouncilController._reference_briefs(child)
                if found:
                    return found
        return []

    @staticmethod
    def _reference_brief_name(brief: dict[str, Any], index: int) -> str:
        return str(
            brief.get("name")
            or brief.get("title")
            or brief.get("label")
            or brief.get("artifact_id")
            or brief.get("id")
            or brief.get("type")
            or f"Production reference {index}"
        ).strip()

    async def _prepare_reference_bundle(self, production: dict[str, Any], task: dict[str, Any]) -> None:
        production_id = str(production["id"])
        existing = [item for item in list_references(production_id, private=True) if item.get("kind") == "image"]
        generated: list[dict[str, Any]] = []
        treatment = latest_deliverable(production_id, "visual_treatment.v1") or {}
        treatment_payload = treatment.get("payload") or {}
        briefs = self._reference_briefs(treatment_payload)[:9]
        if not briefs and not existing:
            description = self._payload_text(treatment_payload, "treatment", "description", "summary")
            briefs = [{
                "name": "Production visual anchor",
                "prompt": description or str(production.get("concept") or production.get("lyrics") or production["title"]),
            }]
        existing_names = {str(item.get("name") or "").strip().casefold() for item in existing}
        missing_briefs = [
            brief for index, brief in enumerate(briefs, 1)
            if self._reference_brief_name(brief, index).casefold() not in existing_names
        ]
        if missing_briefs:
            seat = self._image_provider_seat(production_id, int(task["config_revision"]))
            target_dir = PRODUCTIONS / production_id / "references" / "generated"
            # User-supplied references are planning anchors. Do not feed a
            # newly generated character/location/prop still into the next
            # reference generation: that caused one accidental fallback image
            # to contaminate the entire reference bundle.
            source_images = [Path(item["path"]) for item in existing if Path(item["path"]).is_file()]
            for index, brief in enumerate(missing_briefs, 1):
                name = self._reference_brief_name(brief, index)
                prompt = self._payload_text(brief, "prompt", "description", "brief") or name
                target = target_dir / f"council_reference_{index:02d}.png"
                options = self._image_provider_options(seat)
                trace, heartbeat = self._image_callbacks(
                    production_id, seat, task, f"Reference {index}/{len(missing_briefs)}",
                )
                await process_manager.generate_reference_image(
                    production_id, prompt, target, options["model"], options["effort"],
                    provider=options["provider"], agy_model=options["agy_model"],
                    agy_effort=options["agy_effort"], source_images=source_images,
                    aspect_ratio=str(production.get("generation_aspect_ratio") or "16:9"),
                    on_output=trace, on_heartbeat=heartbeat,
                    preferred_provider=options["preferred_provider"],
                )
                comfy_name = f"council_ref_{uuid.uuid4().hex}.png"
                comfy_path = INPUT / comfy_name
                comfy_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, comfy_path)
                reference = add_reference(
                    production_id, "image", name, str(target), str(comfy_path), comfy_name,
                    json.dumps({"generated": True, "prompt": prompt, "provider_seat": seat["id"]}, ensure_ascii=False),
                )
                generated.append(reference)
            existing.extend(generated)
        payload = {
            "reference_ids": [item["id"] for item in existing],
            "generated_reference_ids": [item["id"] for item in generated],
            "source": "generated" if generated else "user_supplied",
        }
        if generated:
            generated_ids = payload["reference_ids"]
            for shot in list_shots(production_id, private=True):
                if not shot.get("reference_ids"):
                    update_shot(shot["id"], reference_ids=generated_ids)
        save_deliverable(production_id, task["id"], "controller", task["output_contract"], payload)
        update_task(task["id"], state="completed", lease_token=None, finished_at=now_iso())
        add_message(
            production_id, "system", "all", "status",
            f"Reference bundle ready with {len(existing)} image reference{'s' if len(existing) != 1 else ''}.", payload,
        )

    async def _complete_scene_frame_barrier(self, production: dict[str, Any], task: dict[str, Any]) -> None:
        """Release video generation only after every shot frame is materialized.

        Scene-frame renders are deliberately prepared as a batch. Without this
        checkpoint the scheduler can start Shot 001's video as soon as its own
        opening frame exists while later shots are still creating references,
        which makes the production appear to alternate between reference and
        video work.
        """
        production_id = str(production["id"])
        shot_ids = [str(value) for value in (task.get("input") or {}).get("shot_ids", [])]
        render_tasks = [
            item for item in list_tasks(production_id)
            if item["task_type"] == "scene_frame_render"
            and (not shot_ids or str(item.get("input", {}).get("shot_id")) in shot_ids)
        ]
        missing: list[str] = []
        for render_task in render_tasks:
            delivery = deliverable_for_task(render_task["id"])
            opening_id = (delivery or {}).get("payload", {}).get("opening_artifact_id") if delivery else None
            if not delivery or not self._artifact_path(production_id, opening_id):
                missing.append(str(render_task.get("input", {}).get("shot_id") or render_task["id"]))
        if missing:
            raise RuntimeError(
                "Scene-frame preparation is incomplete; missing opening frames for: "
                + ", ".join(missing)
            )
        payload = {
            "shot_ids": shot_ids,
            "scene_frame_task_ids": [item["id"] for item in render_tasks],
            "scene_frame_count": len(render_tasks),
            "video_generation_unlocked": True,
        }
        save_deliverable(production_id, task["id"], "controller", task["output_contract"], payload)
        update_task(task["id"], state="completed", lease_token=None, finished_at=now_iso())
        add_message(
            production_id, "system", "all", "status",
            f"All {len(render_tasks)} shot-specific scene references are ready. Video generation is now unlocked.",
            payload,
        )

    async def _render_scene_frames(self, production: dict[str, Any], task: dict[str, Any]) -> None:
        production_id = str(production["id"])
        shot = self._shot(production_id, str(task["input"]["shot_id"]))
        dependency = self._dependency_deliverables(task)[0]
        plan = dependency["payload"]
        plan_prompt = self._payload_text(plan, "opening_frame_prompt", "prompt", "description")
        if not plan_prompt:
            raise RuntimeError(f"{shot['title']} scene-frame plan has no opening-frame composition prompt")
        requested_reference_ids: list[str] = []
        if isinstance(plan, dict):
            raw_ids = plan.get("source_reference_ids") or plan.get("selected_reference_ids") or plan.get("reference_ids")
            if isinstance(raw_ids, list):
                requested_reference_ids = [str(value) for value in raw_ids]
        shot_reference_ids = [str(value) for value in shot.get("reference_ids", [])]
        selected_reference_ids = [value for value in requested_reference_ids if value in shot_reference_ids]
        if not selected_reference_ids:
            selected_reference_ids = shot_reference_ids
        prompt = f"""Create one new, polished, shot-specific opening frame for MiniMax H3 I2V.

This must depict the actual first moment of the planned shot. The supplied images are identity, location,
wardrobe, prop, lighting, and art-direction anchors only. Do not copy a reference image as the scene, do
not create a reference board or collage, and do not let a prop close-up replace the planned composition.
Combine only the relevant visual facts into a coherent new frame. Preserve established character identity.
No captions, watermarks, logos, invented writing, or readable gibberish.
Do not infer a location from the pipeline name, controller role, seat name, or the word
"council". Do not add a council chamber, boardroom, desk, meeting room, podium, or
microphone unless that setting is explicitly required by the production concept, the
shot action, the required composition, or a selected reference.

Production concept: {production.get('concept') or ''}
Shot action and intent: {shot['prompt']}
Required composition: {plan_prompt}
Target framing and continuity: {self._payload_text(plan, 'framing', 'composition_notes', 'continuity_notes')}
Target aspect ratio: {shot['aspect_ratio']}
""".strip()
        references = [
            reference for reference_id in selected_reference_ids
            if (reference := get_reference(production_id, reference_id, private=True)) and reference.get("kind") == "image"
        ]
        source_images = [Path(item["path"]) for item in references if Path(item["path"]).is_file()]
        seat = self._image_provider_seat(production_id, int(task["config_revision"]))
        options = self._image_provider_options(seat)
        trace, heartbeat = self._image_callbacks(
            production_id, seat, task, f"Opening frame {shot['title']}",
        )
        target_dir = PRODUCTIONS / production_id / "scene_frames" / f"shot_{shot['shot_index']:03d}"
        render_number = int(task.get("attempt") or 0) + 1
        opening = target_dir / f"opening_v{render_number:02d}.png"
        await process_manager.generate_reference_image(
            production_id, prompt, opening, options["model"], options["effort"],
            provider=options["provider"], agy_model=options["agy_model"],
            agy_effort=options["agy_effort"], source_images=source_images,
            aspect_ratio=shot["aspect_ratio"],
            on_output=trace, on_heartbeat=heartbeat,
            preferred_provider=options["preferred_provider"],
        )
        opening_artifact = add_artifact(production_id, "scene_opening_frame", str(opening), {
            "shot_id": shot["id"], "shot_index": shot["shot_index"], "source_reference_ids": selected_reference_ids,
            "composition_prompt": prompt,
        })
        closing_artifact = None
        needs_closing = bool(plan.get("requires_closing_frame") or plan.get("closing_frame_required")) if isinstance(plan, dict) else False
        if needs_closing and shot.get("audio_mode") != "lip_sync":
            closing_prompt = self._payload_text(plan, "closing_frame_prompt", "end_frame_prompt")
            if closing_prompt:
                closing = target_dir / f"closing_v{render_number:02d}.png"
                close_trace, close_heartbeat = self._image_callbacks(
                    production_id, seat, task, f"Closing frame {shot['title']}",
                )
                await process_manager.generate_reference_image(
                    production_id, closing_prompt, closing, options["model"], options["effort"],
                    provider=options["provider"], agy_model=options["agy_model"],
                    agy_effort=options["agy_effort"], source_images=[opening, *source_images],
                    aspect_ratio=shot["aspect_ratio"],
                    on_output=close_trace, on_heartbeat=close_heartbeat,
                    preferred_provider=options["preferred_provider"],
                )
                closing_artifact = add_artifact(production_id, "scene_closing_frame", str(closing), {
                    "shot_id": shot["id"], "shot_index": shot["shot_index"],
                })
        payload = {"shot_id": shot["id"], "opening_artifact_id": opening_artifact["id"],
                   "closing_artifact_id": closing_artifact["id"] if closing_artifact else None,
                   "source_reference_ids": selected_reference_ids}
        save_deliverable(production_id, task["id"], "controller", task["output_contract"], payload,
                         [value for value in (opening_artifact["id"], closing_artifact["id"] if closing_artifact else None) if value])
        update_task(task["id"], state="completed", lease_token=None, finished_at=now_iso())
        add_message(production_id, "system", "all", "status",
                    f"Scene frame ready for {shot['title']}; the generated frame will be sent to I2V.",
                    {"shot_id": shot["id"], **payload})

    def _artifact_path(self, production_id: str, artifact_id: str | None) -> Path | None:
        artifact = get_artifact(production_id, artifact_id) if artifact_id else None
        path = Path(artifact["path"]) if artifact else None
        return path if path and path.is_file() else None

    def _queue_video_job(self, production: dict[str, Any], shot: dict[str, Any], prompt: str,
                         opening: Path, closing: Path | None) -> str:
        if not self.queue_worker:
            raise RuntimeError("Council controller is not connected to the ComfyUI queue")
        if not opening.is_file() or opening.stat().st_size <= 0:
            raise RuntimeError(f"Council opening frame is missing or empty: {opening}")
        audio_mode = shot.get("audio_mode") or "silent"
        mode = "lip_sync" if audio_mode == "lip_sync" else "frames" if closing else "opening"
        settings = normalize_generation_settings(
            mode, engine=shot["engine"], steps=int(shot["steps"]), megapixels=float(shot["megapixels"]),
            aspect_ratio=shot["aspect_ratio"], turbo_profile=shot["turbo_profile"],
        )
        job_id, timestamp = uuid.uuid4().hex, now_iso()

        # ComfyUI LoadImage resolves names from its input directory. Keep the
        # production artifact immutable and stage a unique copy for this job,
        # matching the proven Legacy pipeline.
        INPUT.mkdir(parents=True, exist_ok=True)
        frame_prefix = f"council_{production['id']}_shot_{int(shot['shot_index']):03d}_{job_id}"
        comfy_opening = INPUT / f"{frame_prefix}_opening.png"
        shutil.copy2(opening, comfy_opening)
        comfy_closing = None
        if closing:
            if not closing.is_file() or closing.stat().st_size <= 0:
                raise RuntimeError(f"Council closing frame is missing or empty: {closing}")
            comfy_closing = INPUT / f"{frame_prefix}_closing.png"
            shutil.copy2(closing, comfy_closing)

        audio_path = audio_name = None
        if audio_mode == "lip_sync":
            prepared = INPUT / f"council_{production['id']}_shot_{shot['shot_index']:03d}_audio.wav"
            prepare_audio_segment(Path(production["song_path"]), prepared, float(shot.get("audio_start") or 0),
                                  float(shot.get("audio_duration") or shot["duration"]))
            audio_path, audio_name = str(prepared), prepared.name
        with connect() as db:
            db.execute(
                """INSERT INTO jobs
                   (id,prompt,mode,duration,audio_start,engine,turbo_profile,encoder,steps,width,height,
                    megapixels,aspect_ratio,seed,status,position,no_audio,input_path,input_name,
                    reference_images_json,reference_videos_json,reference_audio_path,reference_audio_name,
                    first_frame_path,first_frame_name,last_frame_path,last_frame_name,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, prompt, mode, int(shot["duration"]), 0, settings.engine, settings.turbo_profile,
                 settings.encoder, settings.steps, settings.width, settings.height, settings.megapixels,
                 settings.aspect_ratio, str(secrets.randbits(64)), next_position(db), int(audio_mode != "lip_sync"),
                 str(comfy_opening), comfy_opening.name, "[]", "[]", audio_path, audio_name,
                 str(comfy_opening), comfy_opening.name,
                 str(comfy_closing) if comfy_closing else None, comfy_closing.name if comfy_closing else None,
                 timestamp, timestamp),
            )
        self.queue_worker.notify()
        add_event(str(production["id"]), "shot.queued", {"shot_id": shot["id"], "job_id": job_id, "pipeline": COUNCIL_PIPELINE})
        return job_id

    async def _wait_for_job(self, production_id: str, job_id: str) -> dict[str, Any]:
        self.current_jobs[production_id] = job_id
        previous: tuple[Any, ...] | None = None
        try:
            while True:
                job = get_job(job_id, public=False)
                if not job:
                    raise RuntimeError("The queued ComfyUI job disappeared")
                state = (job.get("status"), job.get("phase"), job.get("step"), job.get("total_steps"))
                if state != previous:
                    add_activity(production_id, "comfyui", "running" if job["status"] in {"queued", "starting", "running", "verifying"} else job["status"],
                                 f"ComfyUI · {job.get('phase') or job['status']} · step {job.get('step') or 0}/{job.get('total_steps') or 0}",
                                 worker_id=job_id, metadata={"job_id": job_id, "progress": job.get("progress")})
                    add_event(production_id, "shot.progress", {"job_id": job_id, "status": job["status"], "phase": job.get("phase"), "progress": job.get("progress"), "step": job.get("step"), "total_steps": job.get("total_steps")})
                    previous = state
                if job["status"] == "completed":
                    return job
                if job["status"] in {"failed", "canceled"}:
                    raise RuntimeError(job.get("error") or f"ComfyUI job {job['status']}")
                await asyncio.sleep(3)
        finally:
            self.current_jobs.pop(production_id, None)

    async def _generate_video(self, production: dict[str, Any], task: dict[str, Any]) -> None:
        production_id = str(production["id"])
        shot = self._shot(production_id, str(task["input"]["shot_id"]))
        inputs = dict(task["input"])
        dependencies = self._dependency_deliverables(task)
        # The generation task also depends on the scene-frame barrier.  The
        # barrier is deliberately created after the prompt task, so selecting
        # the last dependency silently discarded the Prompt Engineer's latest
        # agreed prompt and fell back to the stale shot-plan prompt.
        prompt_delivery = next(
            (item for item in dependencies if item.get("contract") == "generation_prompt.v1"),
            None,
        )
        prompt = self._payload_text((prompt_delivery or {}).get("payload"), "prompt", "video_prompt", "generation_prompt") or shot["prompt"]
        render_task = next((item for item in list_tasks(production_id) if item["task_type"] == "scene_frame_render" and item["input"].get("shot_id") == shot["id"]), None)
        render = deliverable_for_task(render_task["id"]) if render_task else None
        if not render:
            raise RuntimeError(f"{shot['title']} has no generated scene frame")
        opening = self._artifact_path(production_id, render["payload"].get("opening_artifact_id"))
        closing = self._artifact_path(production_id, render["payload"].get("closing_artifact_id"))
        if not opening:
            raise RuntimeError(f"{shot['title']} opening-frame artifact is missing")
        attempt_row = None
        if inputs.get("attempt_id"):
            attempt_row = next((a for a in shot.get("attempts", []) if a["id"] == inputs["attempt_id"]), None)
        if not attempt_row:
            number = max([int(item["attempt"]) for item in shot.get("attempts", [])] or [0]) + 1
            attempt_row = create_shot_attempt(shot["id"], number, str(opening))
            inputs["attempt_id"] = attempt_row["id"]
        job_id = str(inputs.get("job_id") or "")
        if not job_id:
            job_id = self._queue_video_job(production, shot, prompt, opening, closing)
            inputs["job_id"] = job_id
            update_task_input(task["id"], inputs)
            update_shot_attempt(attempt_row["id"], job_id=job_id, status="generating")
            update_shot(shot["id"], status="generating")
        job = await self._wait_for_job(production_id, job_id)
        output = resolve_asset_path("job", job_id) or (Path(job["output_path"]) if job.get("output_path") else None)
        if not output or not Path(output).is_file():
            raise RuntimeError(f"{shot['title']} completed but its output file is missing")
        output = Path(output)
        # A lip-sync Council shot is not considered generated until the actual
        # returned media contains an audio stream. This check runs before any
        # review task, so a silent video cannot be approved as lip-sync merely
        # because its frames look acceptable.
        media_metadata = await asyncio.to_thread(
            media_probe, output, shot.get("audio_mode") == "lip_sync",
        )
        audio_verified = shot.get("audio_mode") == "lip_sync" and any(
            stream.get("codec_type") == "audio"
            for stream in media_metadata.get("streams", [])
        )
        if shot.get("audio_mode") == "lip_sync" and not audio_verified:
            raise RuntimeError(f"{shot['title']} completed without a verified audio stream")
        review_dir = PRODUCTIONS / production_id / "shots" / f"shot_{shot['shot_index']:03d}" / f"attempt_{attempt_row['attempt']:02d}" / "review_frames"
        frames = await asyncio.to_thread(extract_review_frames, output, review_dir, 1.0, 48)
        video_artifact = add_artifact(production_id, "shot_video", str(output), {
            "shot_id": shot["id"], "job_id": job_id, "attempt_id": attempt_row["id"],
            "audio_verified": audio_verified, "media_probe": media_metadata,
        })
        frame_artifacts = [add_artifact(production_id, "review_frame", str(frame), {"shot_id": shot["id"], "attempt_id": attempt_row["id"]}) for frame in frames]
        update_shot_attempt(attempt_row["id"], status="reviewing", output_path=str(output), frames=[str(frame) for frame in frames])
        update_shot(shot["id"], status="reviewing")
        payload = {"shot_id": shot["id"], "job_id": job_id, "attempt_id": attempt_row["id"],
                   "video_artifact_id": video_artifact["id"], "review_frame_artifact_ids": [item["id"] for item in frame_artifacts],
                   "audio_verified": audio_verified, "media_probe": media_metadata}
        save_deliverable(production_id, task["id"], "comfyui", task["output_contract"], payload,
                         [video_artifact["id"], *[item["id"] for item in frame_artifacts]])
        update_task(task["id"], state="completed", lease_token=None, finished_at=now_iso())

    async def _accept_or_retry_shot(self, production: dict[str, Any], task: dict[str, Any]) -> None:
        production_id = str(production["id"])
        shot = self._shot(production_id, str(task["input"]["shot_id"]))
        reviews = [latest_review_for_task(task_id) for task_id in task["input"].get("review_task_ids", [])]
        reviews = [item for item in reviews if item]
        rejected = [item for item in reviews if item["decision"] in {"revise", "escalate"}]
        generation = deliverable_for_task(str(task["input"]["generation_task_id"]))
        if not generation:
            raise RuntimeError("Shot acceptance has no generated-video deliverable")
        if shot.get("audio_mode") == "lip_sync" and not generation["payload"].get("audio_verified"):
            raise RuntimeError(f"{shot['title']} cannot be approved because its audio stream was not verified")
        attempt_id = generation["payload"]["attempt_id"]
        attempt_number = next((int(item["attempt"]) for item in shot["attempts"] if item["id"] == attempt_id), 1)
        if rejected:
            # Bounded regeneration creates a new task revision; approved task IDs
            # remain immutable and can never accidentally execute twice.
            prior_generation = next(item for item in list_tasks(production_id) if item["id"] == task["input"]["generation_task_id"])
            if attempt_number >= 3:
                update_shot_attempt(attempt_id, status="review_pending", error="Council review revision budget exhausted")
                update_shot(shot["id"], status="review_pending")
                add_decision(production_id, "shot_review", f"Review {shot['title']}",
                             "The Council revision budget was exhausted. User direction is required.",
                             {"shot_id": shot["id"], "attempt_id": attempt_id, "reviews": reviews})
                update_production(production_id, status="awaiting_user", stage="shot_review")
                update_task(task["id"], state="waiting", lease_token=None)
                return
            update_shot_attempt(attempt_id, status="rejected", error="Council requested regeneration")
            update_shot(shot["id"], status="retrying")
            # Route the inspectors' concrete findings back through the Prompt
            # Engineer before spending GPU time again.  The old implementation
            # regenerated with the same prompt, so review could identify a real
            # defect without giving the responsible specialist a chance to fix it.
            prompt_task = next(
                (
                    item for item in list_tasks(production_id)
                    if item["task_type"] == "generation_prompt"
                    and item["input"].get("shot_id") == shot["id"]
                ),
                None,
            )
            feedback = [
                {
                    "gate": item["gate_id"],
                    "decision": item["decision"],
                    "findings": item["findings"],
                }
                for item in rejected
            ]
            target_roles = {
                str(finding.get("target_role") or "prompt-engineer")
                for item in rejected
                for finding in item.get("findings", [])
                if isinstance(finding, dict)
            }
            all_tasks = list_tasks(production_id)
            if "scene-frame-designer" in target_roles:
                design_task = next(
                    (
                        item for item in all_tasks
                        if item["task_type"] == "scene_frame_design"
                        and item["input"].get("shot_id") == shot["id"]
                    ),
                    None,
                )
                render_task = next(
                    (
                        item for item in all_tasks
                        if item["task_type"] == "scene_frame_render"
                        and item["input"].get("shot_id") == shot["id"]
                    ),
                    None,
                )
                if design_task:
                    design_inputs = dict(design_task["input"])
                    design_inputs["review_feedback"] = feedback
                    design_inputs["revision_for_attempt"] = attempt_number + 1
                    update_task_input(design_task["id"], design_inputs)
                    update_task(
                        design_task["id"], state="queued", lease_token=None,
                        finished_at=None, error_code=None, error_detail=None,
                    )
                if render_task:
                    update_task(
                        render_task["id"], state="queued", lease_token=None,
                        finished_at=None, error_code=None, error_detail=None,
                    )
            if prompt_task:
                prompt_inputs = dict(prompt_task["input"])
                prompt_inputs["review_feedback"] = feedback
                prompt_inputs["revision_for_attempt"] = attempt_number + 1
                update_task_input(prompt_task["id"], prompt_inputs)
                update_task(
                    prompt_task["id"], state="queued", lease_token=None,
                    finished_at=None, error_code=None, error_detail=None,
                )

            # Requeue the generation/QC/acceptance chain safely.  Generation is
            # dependency-gated by the revised prompt task, so it cannot start
            # until the specialist has returned a corrected prompt.
            update_task_input(prior_generation["id"], {"shot_id": shot["id"], "shot_index": shot["shot_index"]})
            update_task(prior_generation["id"], state="queued", lease_token=None, finished_at=None)
            for review_task_id in task["input"].get("review_task_ids", []):
                update_task(review_task_id, state="queued", lease_token=None, finished_at=None)
            update_task(task["id"], state="queued", lease_token=None, finished_at=None)
            add_message(
                production_id, "system", "all", "status",
                f"Council review returned {shot['title']} to the Prompt Engineer before regeneration.",
                {"shot_id": shot["id"], "attempt": attempt_number + 1,
                 "review_feedback": feedback, "target_roles": sorted(target_roles)},
            )
            return
        update_shot_attempt(attempt_id, status="accepted")
        update_shot(shot["id"], status="accepted", accepted_attempt=attempt_number)
        payload = {"shot_id": shot["id"], "attempt_id": attempt_id, "decision": "approve", "review_ids": [item["id"] for item in reviews]}
        save_deliverable(production_id, task["id"], "controller", task["output_contract"], payload)
        update_task(task["id"], state="completed", lease_token=None, finished_at=now_iso())
        add_message(production_id, "system", "all", "status", f"{shot['title']} passed the configured Council review gates.", payload)

    async def _assemble(self, production: dict[str, Any], task: dict[str, Any]) -> None:
        production_id = str(production["id"])
        clips: list[Path] = []
        segments: list[dict[str, float]] = []
        for shot in list_shots(production_id, private=True):
            accepted = next((item for item in shot["attempts"] if int(item["attempt"]) == int(shot.get("accepted_attempt") or -1)), None)
            path = resolve_asset_path("job", accepted["job_id"]) if accepted and accepted.get("job_id") else None
            if not path and accepted and accepted.get("output_path"):
                path = Path(accepted["output_path"])
            if not path or not Path(path).is_file():
                raise RuntimeError(f"{shot['title']} has no accepted video artifact")
            clips.append(Path(path))
            segments.append({"trim_in": float(shot.get("trim_in") or 0), "trim_out": float(shot.get("trim_out") or 0)})
        assembly_dir = PRODUCTIONS / production_id / "assembly"
        revision = len([item for item in list_artifacts(production_id, private=True) if item.get("kind") == "final_video"]) + 1
        silent = assembly_dir / f"silent_master_v{revision:03d}.mp4"
        final = assembly_dir / f"final_with_song_v{revision:03d}.mp4"
        assembly_result = await asyncio.to_thread(assemble_clips, clips, silent, segments)
        await asyncio.to_thread(attach_song, silent, Path(production["song_path"]), final)
        assembly_metadata = {"revision": revision, "clips": len(clips), "segments": assembly_result.get("segments", [])}
        silent_artifact = add_artifact(production_id, "silent_master", str(silent), assembly_metadata)
        final_artifact = add_artifact(production_id, "final_video", str(final), assembly_metadata)
        save_deliverable(production_id, task["id"], "post-production-editor", task["output_contract"],
                         {"silent_artifact_id": silent_artifact["id"], "final_artifact_id": final_artifact["id"], "clip_count": len(clips)},
                         [silent_artifact["id"], final_artifact["id"]])
        update_task(task["id"], state="completed", lease_token=None, finished_at=now_iso())
        add_message(production_id, "system", "all", "status", "All approved Council shots were assembled and the original song was attached.")

    def approve_waiting_shot(self, production_id: str, decision_payload: dict[str, Any] | None = None) -> bool:
        """Accept the preserved attempt after an explicit user override.

        This bypasses rejected automated reviews intentionally; re-queueing the
        acceptance task would merely evaluate the same rejected reviews again.
        """
        payload = decision_payload or {}
        shot_id = str(payload.get("shot_id") or "")
        waiting = [
            item for item in list_tasks(production_id)
            if item["task_type"] == "shot_acceptance" and item["state"] == "waiting"
            and (not shot_id or str(item.get("input", {}).get("shot_id")) == shot_id)
        ]
        if not waiting:
            return False
        task = waiting[0]
        shot = self._shot(production_id, str(task["input"]["shot_id"]))
        generation = deliverable_for_task(str(task["input"]["generation_task_id"]))
        if not generation:
            raise RuntimeError("The preserved shot generation is unavailable")
        attempt_id = str(payload.get("attempt_id") or generation["payload"].get("attempt_id") or "")
        attempt = next((item for item in shot.get("attempts", []) if item["id"] == attempt_id), None)
        if not attempt:
            raise RuntimeError("The preserved shot attempt is unavailable")
        attempt_number = int(attempt["attempt"])
        update_shot_attempt(attempt_id, status="accepted", error=None)
        update_shot(shot["id"], status="accepted", accepted_attempt=attempt_number)
        acceptance = {
            "shot_id": shot["id"], "attempt_id": attempt_id, "decision": "user_override",
            "review_ids": [
                item["id"]
                for item in (
                    latest_review_for_task(review_task_id)
                    for review_task_id in task["input"].get("review_task_ids", [])
                )
                if item
            ],
        }
        save_deliverable(production_id, task["id"], "user", task["output_contract"], acceptance)
        update_task(task["id"], state="completed", lease_token=None, finished_at=now_iso(), error_code=None, error_detail=None)
        update_production(production_id, status="queued", stage="shot_review", error=None)
        add_activity(production_id, "controller", "queued", f"User accepted {shot['title']}; continuing the dependency graph", task_id=task["id"])
        self.notify()
        return True

    def _task_resource(self, production_id: str, task: dict[str, Any]) -> str:
        """Return the exclusive lane used by a task inside one production.

        Different saved agent sessions may run concurrently. A single seat is
        always serialized so its conversation order remains deterministic.
        ComfyUI stays a single lane; its global queue remains the final GPU
        authority across productions.
        """
        worker_type = str(task.get("worker_type") or "agent")
        if worker_type == "agent":
            seat = self._eligible_seat(production_id, task)
            return f"seat:{seat['id']}" if seat else f"missing-seat:{task['id']}"
        if task.get("task_type") in {"scene_frame_render", "reference_bundle_prepare"}:
            try:
                seat = self._image_provider_seat(production_id, int(task["config_revision"]))
                return f"seat:{seat['id']}"
            except RuntimeError:
                return f"image:{production_id}"
        if worker_type == "comfyui":
            return "comfyui"
        if worker_type == "ffmpeg":
            return "ffmpeg"
        return "controller"

    def _ready_batch(
        self, production_id: str, running: dict[str, tuple[asyncio.Task[None], str]],
    ) -> list[tuple[dict[str, Any], str]]:
        occupied = {resource for _, resource in running.values()}
        batch: list[tuple[dict[str, Any], str]] = []
        for task in ready_tasks(production_id):
            resource = self._task_resource(production_id, task)
            if resource in occupied:
                continue
            occupied.add(resource)
            batch.append((task, resource))
        return batch

    def _reconcile_approved_waiting_tasks(self, production_id: str) -> bool:
        """Finish waiting tasks whose user decision was already approved.

        A decision and its task are persisted separately. If the bridge was
        restarted, or an approval arrived while the controller was between
        scheduler ticks, the decision can be approved while the task remains
        in ``waiting``. Treat the approved decision as the source of truth so
        the controller cannot spin forever over a task the user already
        accepted.
        """
        changed = False
        tasks = list_tasks(production_id)
        for decision in list_decisions(production_id):
            if decision.get("status") != "approved":
                continue
            payload = decision.get("payload") or {}
            task_id = str(payload.get("task_id") or "")
            task = next((item for item in tasks if item.get("id") == task_id), None)
            if not task and payload.get("shot_id"):
                shot_id = str(payload["shot_id"])
                task = next(
                    (
                        item for item in tasks
                        if item.get("state") == "waiting"
                        and item.get("task_type") == "shot_acceptance"
                        and str((item.get("input") or {}).get("shot_id") or "") == shot_id
                    ),
                    None,
                )
            if not task or task.get("state") != "waiting":
                continue
            if task.get("task_type") == "shot_acceptance":
                changed = self.approve_waiting_shot(production_id, payload) or changed
            else:
                changed = self.approve_waiting_task(production_id, payload) or changed
            refreshed = get_task(str(task["id"]))
            tasks = [refreshed if item.get("id") == task["id"] and refreshed else item for item in tasks]
        return changed

    async def _run_one_task(self, production: dict[str, Any], task: dict[str, Any]) -> None:
        try:
            if task.get("worker_type") == "agent":
                await self._execute_task(production, task)
            else:
                await self._execute_controller_task(production, task)
        except asyncio.CancelledError:
            # Preparation can fail before _execute_task reaches its provider
            # try/except (for example a missing song/carrier).  Make the same
            # safe-checkpoint guarantee at the task boundary so a cancelled or
            # interrupted Council turn never remains falsely "running".
            if task.get("worker_type") == "agent":
                current = get_task(task["id"]) or task
                if current.get("state") in {"starting", "running", "validating"}:
                    update_task(
                        task["id"], state="queued", lease_token=None,
                        error_code="interrupted",
                        error_detail="Task interrupted at a safe checkpoint",
                    )
                    interventions = [
                        item for item in list_interventions(str(production["id"]))
                        if item["state"] in {"delivered", "acknowledged"}
                        and (not item["target_seat_ids"] or item.get("affected_task_ids") == [task["id"]])
                    ]
                    self._requeue_interventions_for_task(
                        interventions, task["id"],
                        "Task was interrupted before the intervention was applied",
                    )
                    add_activity(
                        str(production["id"]), "agent", "queued",
                        f"{task['task_type']} was interrupted and requeued safely",
                        task_id=task["id"],
                    )
            raise
        except Exception as exc:
            # The media handoff and prompt construction happen before the
            # provider invocation try block. Persist those failures exactly as
            # provider/contract failures instead of letting the controller die
            # with a task that still claims to be running.
            if task.get("worker_type") == "agent":
                current = get_task(task["id"]) or task
                if current.get("state") in {"starting", "running", "validating"}:
                    seat = self._eligible_seat(str(production["id"]), current)
                    if seat:
                        role_label = str(current["role_id"]).replace("-", " ").title()
                        interventions = [
                            item for item in list_interventions(str(production["id"]))
                            if item["state"] in {"delivered", "acknowledged"}
                            and (not item["target_seat_ids"] or seat["id"] in item["target_seat_ids"])
                        ]
                        self._handle_task_failure(
                            production, current, seat, role_label,
                            int(current.get("attempt") or 1), interventions, exc,
                        )
                        return
            raise

    @staticmethod
    def _intervention_requests_audio_analysis(content: str) -> bool:
        text = str(content or "").casefold()
        return bool(
            re.search(r"\b(analy[sz]e|inspect|listen|hear|map|tim(?:e|ing)|bpm|beat|audio|sound|song|music|wav|mp3|lyrics?)\b", text)
            and re.search(r"\b(audio|sound|song|music|wav|mp3|bpm|beat|lyrics?)\b", text)
        )

    async def _intervention_audio_paths(
        self, production: dict[str, Any], instruction: str,
    ) -> tuple[list[Path], dict[str, Any]]:
        """Prepare the same verified AGY audio carrier used by Legacy.

        An intervention asking AGY to inspect the song must carry real media
        into that turn.  Sending only the path or lyrics recreates the exact
        failure the Legacy flow already solved.
        """
        song_path = Path(str(production.get("song_path") or "").strip())
        if not self._intervention_requests_audio_analysis(instruction):
            return [], {}
        if not song_path.is_file():
            raise RuntimeError(f"The production song is missing: {song_path}")
        analysis_dir = PRODUCTIONS / str(production["id"]) / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        try:
            metadata = await asyncio.to_thread(probe_audio_metadata, song_path)
        except (RuntimeError, OSError) as exc:
            metadata = {"preflight_error": str(exc)}
        preflight = analysis_dir / "audio_preflight.json"
        preflight.write_text(
            json.dumps({"song_path": str(song_path), "metadata": metadata, "source": "backend.ffprobe"},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        carrier = analysis_dir / "agy_audio_carrier.mp4"
        if not carrier.is_file() or carrier.stat().st_size <= 0:
            await asyncio.to_thread(
                prepare_agent_audio_carrier, song_path, carrier,
                float(metadata.get("duration_seconds") or 0) or None,
            )
        return [carrier], {
            "agy_audio_carrier_path": str(carrier.resolve()),
            "audio_preflight_path": str(preflight.resolve()),
            "audio_expected_duration": float(metadata.get("duration_seconds") or 0),
        }

    @staticmethod
    def _intervention_plan(content: Any) -> dict[str, Any]:
        payload = content if isinstance(content, dict) else {}
        actions = payload.get("actions")
        if not isinstance(actions, list):
            actions = []
        policy = str(payload.get("resume_policy") or "").strip().lower()
        if policy not in {"resume", "pause", "await_user", "preserve"}:
            policy = ""
        return {
            "reply": str(payload.get("reply") or "").strip(),
            "actions": [item for item in actions if isinstance(item, dict)],
            "resume_policy": policy,
            "requires_user": bool(payload.get("requires_user")),
            "issues": payload.get("issues", []) if isinstance(payload.get("issues"), list) else [],
        }

    @staticmethod
    def _intervention_requests_executable_action(instruction: str) -> bool:
        """Detect a user message that must mutate the saved Council work."""
        text = " ".join(str(instruction or "").casefold().split())
        if not text:
            return False
        target = re.search(
            r"\b(?:shot|scene|prompt|generation|video|clip|image|frame|character|reference|"
            r"production|flow|camera|movement|audio|lyrics?|settings?|config)\b",
            text,
        )
        if not target:
            return False
        question_lead = re.match(
            r"^(?:what|why|how|where|when|which|who|can|could|does|do|is|are)\b",
            text,
        )
        complaint = re.search(
            r"\b(?:wrong|old|stale|ignored|missing|broken|bad|incorrect|instead|again|still|"
            r"doesn't|didn't|isn't|aren't|not|back to)\b",
            text,
        )
        if question_lead and not complaint:
            return False
        return bool(re.search(
            r"\b(?:change|fix|correct|revise|rewrite|replace|remove|add|use|avoid|make|keep|"
            r"preserve|stop|regenerate|rerun|redo|retry|try|don't|do not|must|should|want|"
            r"needs?)\b",
            text,
        ) or complaint)

    @staticmethod
    def _has_effective_intervention_action(action_results: list[dict[str, Any]]) -> bool:
        """Return whether the intervention changed an executable checkpoint."""
        effective = {
            "analyze_song_audio", "update_shot", "accept_shot",
            "regenerate_shot", "update_production_config",
        }
        return any(
            item.get("status") in {"completed", "queued"}
            and str(item.get("type") or "").casefold() in effective
            for item in action_results
        )

    @staticmethod
    def _intervention_action_key(action: dict[str, Any]) -> str:
        """Return a stable identity for one bridge action.

        In a multi-seat intervention more than one seat may agree on the same
        action.  The bridge must execute that action once, while still keeping
        every seat's response available for the conversation.
        """
        action_type = str(action.get("type") or "").strip().lower()
        identity: dict[str, Any] = {"type": action_type}
        if action_type in {"update_shot", "regenerate_shot"}:
            identity["shot_index"] = action.get("shot_index")
            if action_type == "update_shot":
                identity["changes"] = action.get("changes")
            else:
                identity["prompt"] = action.get("prompt")
        elif action_type == "update_production_config":
            identity["changes"] = action.get("changes")
        elif action_type == "add_production_note":
            identity["note"] = action.get("note")
        elif action_type == "ask_user":
            identity["question"] = action.get("question")
        return json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str)

    @classmethod
    def _dedupe_intervention_actions(cls, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for action in actions:
            key = cls._intervention_action_key(action)
            if key in seen:
                continue
            seen.add(key)
            unique.append(action)
        return unique

    @staticmethod
    def _validated_intervention_shot_changes(
        production: dict[str, Any], shot: dict[str, Any], changes: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "title", "prompt", "mode", "continuity", "audio_mode", "audio_source",
            "audio_start", "audio_duration", "duration", "megapixels", "aspect_ratio",
            "steps", "engine", "turbo_profile", "reference_ids",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("Unsupported shot fields: " + ", ".join(sorted(unknown)))
        normalized = dict(changes)
        if "mode" in normalized and normalized["mode"] not in {"text", "opening"}:
            raise ValueError("Council interventions currently support only T2V or I2V shots")
        if "continuity" in normalized and normalized["continuity"] not in {"hard_cut", "sequential"}:
            raise ValueError("Shot continuity must be hard_cut or sequential")
        if "audio_mode" in normalized and normalized["audio_mode"] not in {"silent", "lip_sync"}:
            raise ValueError("Shot audio mode must be silent or lip_sync")
        if "audio_source" in normalized and normalized["audio_source"] not in {"song", "reference"}:
            raise ValueError("Shot audio source must be song or reference")
        if "aspect_ratio" in normalized and normalized["aspect_ratio"] not in {"16:9", "1:1", "9:16", "4:3", "3:4"}:
            raise ValueError("Unsupported shot aspect ratio")
        if "turbo_profile" in normalized and normalized["turbo_profile"] not in {"v1", "v4"}:
            raise ValueError("Turbo profile must be v1 or v4")
        if "duration" in normalized:
            value = float(normalized["duration"])
            if not value.is_integer() or not 1 <= value <= 15:
                raise ValueError("Shot duration must be a whole number from 1 through 15 seconds")
            normalized["duration"] = int(value)
        if "megapixels" in normalized:
            value = round(float(normalized["megapixels"]), 1)
            if not 0.1 <= value <= 2.0:
                raise ValueError("Shot megapixels must be between 0.1 and 2.0")
            normalized["megapixels"] = value
        profile = str(normalized.get("turbo_profile") or shot.get("turbo_profile") or "v1")
        if "steps" in normalized:
            value = int(normalized["steps"])
            if not 4 <= value <= (8 if profile == "v4" else 12):
                raise ValueError(f"Turbo {profile} steps are outside the supported range")
            normalized["steps"] = value
        for key in ("audio_start", "audio_duration"):
            if key in normalized and normalized[key] is not None:
                normalized[key] = float(normalized[key])
                if normalized[key] < 0:
                    raise ValueError(f"{key} cannot be negative")
        if "reference_ids" in normalized:
            if not isinstance(normalized["reference_ids"], list):
                raise ValueError("reference_ids must be an array")
            known = {item["id"] for item in list_references(production["id"], private=True)}
            invalid = set(map(str, normalized["reference_ids"])) - known
            if invalid:
                raise ValueError("Unknown production references: " + ", ".join(sorted(invalid)))
            normalized["reference_ids"] = list(map(str, normalized["reference_ids"]))
        return normalized

    def _reset_shot_tasks(self, production_id: str, shot_id: str) -> list[str]:
        reset_types = {
            "scene_frame_design", "scene_frame_render", "scene_frame_barrier",
            "generation_prompt", "video_generation", "technical_media_review",
            "av_sync_review", "shot_acceptance",
        }
        # A changed shot invalidates the final master as well.  Leaving these
        # global tasks completed lets the controller finish with the previous
        # assembly after the new shot has been accepted.
        final_types = {"final_assembly", "final_media_review"}
        reset: list[str] = []
        for task in list_tasks(production_id):
            task_type = task.get("task_type")
            task_input = dict(task.get("input") or {})
            belongs_to_shot = (
                task_input.get("shot_id") == shot_id
                or shot_id in [str(value) for value in task_input.get("shot_ids", [])]
            )
            if task_type in final_types:
                should_reset = True
            else:
                should_reset = task_type in reset_types and belongs_to_shot
            if not should_reset:
                continue
            update_task(
                task["id"], state="queued", attempt=0, lease_token=None,
                started_at=None, finished_at=None, error_code="intervention_regeneration",
                error_detail="Requeued from a user intervention",
            )
            # Preserve static workflow inputs, but never preserve ephemeral
            # Comfy handoffs.  Keeping an old job/attempt ID here causes the
            # next run to poll or review the previous generation instead of
            # queueing the prompt that the agents just agreed on.
            if task_type == "video_generation":
                for key in ("job_id", "attempt_id", "output_path"):
                    task_input.pop(key, None)
            update_task_input(task["id"], task_input)
            reset.append(task["id"])
        return reset

    @staticmethod
    def _shot_change_requires_regeneration(changes: dict[str, Any]) -> bool:
        """Return whether a shot edit invalidates generated media."""
        return bool(set(changes) & {
            "prompt", "mode", "continuity", "audio_mode", "audio_source",
            "audio_start", "audio_duration", "duration", "megapixels",
            "aspect_ratio", "steps", "engine", "turbo_profile", "reference_ids",
        })

    def _invalidate_shot_generation(self, production_id: str, shot: dict[str, Any]) -> list[str]:
        """Supersede old attempts and requeue every affected Council task."""
        for attempt in shot.get("attempts", []):
            if attempt.get("status") in {"queued", "generating", "reviewing", "review_pending"}:
                update_shot_attempt(
                    attempt["id"], status="interrupted",
                    error="Superseded by an intervention shot update",
                )
        reset = self._reset_shot_tasks(production_id, str(shot["id"]))
        update_shot(shot["id"], status="planned", accepted_attempt=None)
        return reset

    async def _execute_intervention_actions(
        self, production: dict[str, Any], actions: list[dict[str, Any]], intervention_id: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        results: list[dict[str, Any]] = []
        policy: str | None = None
        for action in actions:
            action_type = str(action.get("type") or "").strip().lower()
            try:
                if action_type == "analyze_song_audio":
                    task = next((item for item in list_tasks(production["id"]) if item["task_type"] == "audio_analysis"), None)
                    if not task:
                        raise ValueError("The Council audio-analysis task is unavailable")
                    update_task(task["id"], state="queued", attempt=0, lease_token=None,
                                started_at=None, finished_at=None, error_code="intervention_audio_analysis",
                                error_detail="Queued by the user intervention")
                    for dependent in list_tasks(production["id"]):
                        if dependent["id"] != task["id"] and dependent["stage"] in {"treatment", "storyboard", "execution_planning"}:
                            update_task(dependent["id"], state="queued", attempt=0, lease_token=None,
                                        started_at=None, finished_at=None, error_code="audio_analysis_refresh",
                                        error_detail="Waiting for refreshed audio analysis")
                    results.append({"type": action_type, "status": "queued", "task_id": task["id"]})
                elif action_type == "update_shot":
                    shot_index = int(action.get("shot_index"))
                    shot = next((item for item in list_shots(production["id"], private=True)
                                 if int(item["shot_index"]) == shot_index), None)
                    if not shot:
                        raise ValueError(f"Shot {shot_index} does not exist")
                    changes = action.get("changes")
                    if not isinstance(changes, dict) or not changes:
                        raise ValueError("update_shot requires a non-empty changes object")
                    normalized = self._validated_intervention_shot_changes(production, shot, changes)
                    update_shot(shot["id"], **normalized)
                    requeued = self._invalidate_shot_generation(production["id"], shot) if self._shot_change_requires_regeneration(normalized) else []
                    results.append({
                        "type": action_type, "status": "completed", "shot_index": shot_index,
                        "changes": normalized, "requeued": bool(requeued), "task_ids": requeued,
                    })
                elif action_type == "regenerate_shot":
                    shot_index = int(action.get("shot_index"))
                    shot = next((item for item in list_shots(production["id"], private=True)
                                 if int(item["shot_index"]) == shot_index), None)
                    if not shot:
                        raise ValueError(f"Shot {shot_index} does not exist")
                    prompt = action.get("prompt")
                    if prompt is not None and not str(prompt).strip():
                        raise ValueError("regenerate_shot prompt cannot be empty")
                    reuse_prompt = action.get("reuse_prompt") is True
                    if prompt is None and not reuse_prompt:
                        # Do not leave an old queued/reviewing attempt alive
                        # after rejecting an underspecified correction.  A
                        # later resume must wait for a concrete prompt rather
                        # than silently reusing that stale render.
                        self._invalidate_shot_generation(production["id"], shot)
                        raise ValueError(
                            "regenerate_shot requires a complete new prompt; "
                            "set reuse_prompt=true only for an intentional same-prompt rerun"
                        )
                    if prompt is not None:
                        update_shot(shot["id"], prompt=str(prompt).strip())
                    reset = self._invalidate_shot_generation(production["id"], shot)
                    results.append({
                        "type": action_type, "status": "queued", "shot_index": shot_index,
                        "prompt_updated": prompt is not None,
                        "reuse_prompt": reuse_prompt,
                        "prompt": str(prompt).strip() if prompt is not None else shot.get("prompt"),
                        "task_ids": reset,
                    })
                elif action_type == "update_production_config":
                    changes = action.get("changes")
                    if not isinstance(changes, dict) or not changes:
                        raise ValueError("update_production_config requires a non-empty changes object")
                    current = get_production(production["id"], private=True) or production
                    generation = normalize_production_generation(
                        changes.get("generation_turbo_profile", current.get("generation_turbo_profile")),
                        changes.get("generation_steps", current.get("generation_steps")),
                        changes.get("generation_megapixels", current.get("generation_megapixels")),
                        changes.get("generation_aspect_ratio", current.get("generation_aspect_ratio")),
                        changes.get("generation_megapixel_rules", current.get("generation_megapixel_rules")),
                    )
                    allowed = {"continuity_mode", "participation_mode", "generation_audio_mode"}
                    unknown = set(changes) - {
                        "generation_turbo_profile", "generation_steps", "generation_megapixels",
                        "generation_aspect_ratio", "generation_megapixel_rules", *allowed,
                    }
                    if unknown:
                        raise ValueError("Unsupported production config fields: " + ", ".join(sorted(unknown)))
                    for key in allowed & set(changes):
                        generation[key] = changes[key]
                    update_production(production["id"], **generation)
                    results.append({"type": action_type, "status": "completed", "changes": generation})
                elif action_type == "add_production_note":
                    note = str(action.get("note") or "").strip()
                    if not note:
                        raise ValueError("add_production_note requires note text")
                    add_message(production["id"], "system", "all", "status", f"Production instruction recorded: {note}",
                                {"intervention_id": intervention_id, "durable_instruction": True})
                    results.append({"type": action_type, "status": "completed", "note": note})
                elif action_type == "ask_user":
                    question = str(action.get("question") or "").strip()
                    if not question:
                        raise ValueError("ask_user requires a question")
                    policy = "await_user"
                    results.append({"type": action_type, "status": "completed", "question": question})
                elif action_type in {"pause", "resume"}:
                    policy = action_type
                    results.append({"type": action_type, "status": "completed"})
                else:
                    raise ValueError(f"Unsupported intervention action: {action_type or '(missing type)'}")
            except Exception as exc:
                results.append({"type": action_type or "invalid", "status": "failed", "error": str(exc)})
        return results, policy

    async def _execute_intervention_followup(
        self,
        production: dict[str, Any],
        intervention: dict[str, Any],
        targets: list[dict[str, Any]],
        config: dict[str, Any],
        instruction: str,
        action_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Ask the same saved sessions to interpret real action outcomes.

        Legacy does a second turn after applying actions.  Without this turn a
        Council agent can only describe what it *requested*, so the UI may say
        that a shot was fixed even when the bridge rejected the action.  The
        follow-up is intentionally non-executing: actions are already applied,
        and the response is used only to explain the result and choose the
        next checkpoint policy.
        """
        production_id = str(production["id"])
        followups: list[dict[str, Any]] = []
        peer: dict[str, Any] | None = None
        for seat in targets:
            role_id = str((seat.get("role_ids") or ["executive-producer"])[0])
            task = {
                "id": f"intervention:{intervention['id']}:followup:{seat['id']}",
                "config_revision": int(config["revision"]),
                "stage": production.get("stage") or "intervention",
                "task_type": "user_intervention",
                "role_id": role_id,
                "output_contract": "council.intervention.v1",
                "input": {
                    "intervention_id": intervention["id"],
                    "user_message": instruction,
                    "intervention_followup": True,
                    "action_results": action_results,
                    "peer_response": peer or {},
                },
                "attempt": 0,
            }
            session = get_session(production_id, seat["id"]) or {}
            add_activity(
                production_id, "agent", "running",
                f"{seat['label']} is interpreting the intervention results",
                worker_id=seat["id"], role_id=role_id, task_id=task["id"],
                metadata={"runtime": seat["runtime"], "model": seat["model"],
                          "intervention_id": intervention["id"], "followup": True},
            )
            trace = self._trace_callback(
                production_id, seat, task, label=f"{seat['label']} · intervention follow-up",
            )
            heartbeat = self._heartbeat_callback(
                production_id, seat, task, label="intervention follow-up",
            )
            prompt = self._build_prompt(production, task, seat, [intervention])
            prompt += f"""

ACTION OUTCOMES
{json.dumps(action_results, ensure_ascii=False, indent=2)}

FOLLOW-UP CONTRACT
Interpret these actual bridge outcomes for the user. Do not repeat or propose any
action. Return content with actions: [], a truthful reply, and resume_policy.
If an action failed, explain the failure and do not claim it succeeded. If an
action was queued for ComfyUI, say that it is queued rather than completed.
"""
            if peer:
                prompt += "\n\nPRIOR COUNCIL FOLLOW-UP:\n" + json.dumps(peer, ensure_ascii=False)
            extra_dirs = [Path(str(production.get("song_path"))).parent] if production.get("song_path") else []
            result = await self._invoke_council_agent(
                production, task, seat, prompt, session.get("provider_session_id"),
                [], trace, heartbeat, extra_dirs,
            )
            envelope = CouncilEnvelope.model_validate(result.content)
            plan = self._intervention_plan(envelope.content)
            # A follow-up is deliberately read-only. Keep the reply, but never
            # execute a second copy of an action returned by a provider.
            if plan["actions"]:
                plan["issues"] = [
                    *plan["issues"],
                    {"severity": "medium", "message": "Follow-up returned actions; they were ignored because the original actions were already executed."},
                ]
                plan["actions"] = []
            plan["issues"] = [*plan["issues"], *envelope.issues]
            update_session(
                production_id, seat["id"], provider_session_id=result.session_id,
                status="active", handoff_summary=plan["reply"][:4000],
            )
            add_message(
                production_id, seat["runtime"], "all", "agent_response",
                plan["reply"] or envelope.summary,
                {"live": False, "intervention_id": intervention["id"],
                 "intervention_followup": True, "seat_id": seat["id"],
                 "seat_label": seat["label"], "role_id": role_id,
                 "decision": envelope.decision, "content": envelope.content,
                 "issues": plan["issues"], "next_action": envelope.next_action,
                 "model": seat["model"], "effort": seat["effort"]},
            )
            followups.append({
                "seat_id": seat["id"], "seat_label": seat["label"],
                "reply": plan["reply"] or envelope.summary,
                "resume_policy": plan["resume_policy"],
                "requires_user": plan["requires_user"],
                "issues": plan["issues"],
                "decision": envelope.decision,
            })
            peer = envelope.content if isinstance(envelope.content, dict) else {"summary": envelope.summary}
        return followups

    async def _execute_intervention_turn(
        self, production: dict[str, Any], intervention: dict[str, Any],
    ) -> None:
        """Give an accepted user intervention a real saved-session turn.

        This is the Council equivalent of Legacy's `_apply_pending_interventions`:
        the message is delivered to the selected seats, declared actions are
        executed by the bridge, and only then is the checkpoint resumed.
        """
        production_id = str(production["id"])
        config = latest_config(production_id)
        if not config:
            raise RuntimeError("Council intervention has no active configuration")
        seats = list_seats(production_id, int(config["revision"]))
        target_ids = set(intervention.get("target_seat_ids") or [])
        targets = [seat for seat in seats if seat["active"] and (not target_ids or seat["id"] in target_ids)]
        if not targets:
            raise RuntimeError("Council intervention has no active target seat")
        instruction = str(intervention.get("content") or "").strip()
        all_actions: list[dict[str, Any]] = []
        agent_plans: list[dict[str, Any]] = []
        replies: list[str] = []
        affected = [f"intervention:{intervention['id']}:{seat['id']}" for seat in targets]
        update_intervention(intervention["id"], "delivered", delivered_at=now_iso(), affected_task_ids=affected)
        add_activity(production_id, "controller", "running", "Delivering the user intervention to the saved Council sessions",
                     metadata={"intervention_id": intervention["id"], "target_seat_ids": [seat["id"] for seat in targets]})
        try:
            media_paths, media_input = await self._intervention_audio_paths(production, instruction)
            peer: dict[str, Any] | None = None
            for seat in targets:
                role_id = str((seat.get("role_ids") or ["executive-producer"])[0])
                task = {
                    "id": f"intervention:{intervention['id']}:{seat['id']}",
                    "config_revision": int(config["revision"]), "stage": production.get("stage") or "intervention",
                    "task_type": "user_intervention", "role_id": role_id,
                    "output_contract": "council.intervention.v1",
                    "input": {"intervention_id": intervention["id"], "user_message": instruction, "peer_response": peer or {}, **media_input},
                    "attempt": 0,
                }
                add_activity(production_id, "agent", "running", f"{seat['label']} is handling the user intervention",
                             worker_id=seat["id"], role_id=role_id, task_id=task["id"],
                             metadata={"runtime": seat["runtime"], "model": seat["model"], "intervention_id": intervention["id"]})
                session = get_session(production_id, seat["id"]) or {}
                trace = self._trace_callback(production_id, seat, task, label=f"{seat['label']} · intervention")
                heartbeat = self._heartbeat_callback(production_id, seat, task, label="intervention")
                prompt = self._build_prompt(production, task, seat, [intervention])
                if peer:
                    prompt += "\n\nPRIOR COUNCIL MEMBER RESPONSE:\n" + json.dumps(peer, ensure_ascii=False)
                extra_dirs = [Path(str(production.get("song_path"))).parent] if production.get("song_path") else []
                extra_dirs.extend(path.parent for path in media_paths)
                result = await self._invoke_council_agent(
                    production, task, seat, prompt, session.get("provider_session_id"), media_paths,
                    trace, heartbeat, extra_dirs,
                )
                envelope = CouncilEnvelope.model_validate(result.content)
                plan = self._intervention_plan(envelope.content)
                plan["issues"] = [*plan["issues"], *envelope.issues]
                agent_plans.append(plan)
                update_session(production_id, seat["id"], provider_session_id=result.session_id,
                               status="active", handoff_summary=plan["reply"][:4000])
                all_actions.extend(plan["actions"])
                if plan["reply"]:
                    replies.append(f"{seat['label']}: {plan['reply']}")
                peer = envelope.content if isinstance(envelope.content, dict) else {"summary": envelope.summary}
                add_message(
                    production_id, seat["runtime"], "all", "agent_response", plan["reply"] or envelope.summary,
                    {"live": False, "intervention_id": intervention["id"], "seat_id": seat["id"],
                     "seat_label": seat["label"], "role_id": role_id, "decision": envelope.decision,
                     "content": envelope.content, "issues": envelope.issues, "next_action": envelope.next_action,
                     "model": seat["model"], "effort": seat["effort"]},
                )
            # Two Council seats may return the same action.  Preserve both
            # consultations, but execute each bridge mutation only once.
            all_actions = self._dedupe_intervention_actions(all_actions)
            action_results, action_policy = await self._execute_intervention_actions(
                get_production(production_id, private=True) or production, all_actions, intervention["id"],
            )
            failed = [item for item in action_results if item.get("status") == "failed"]
            followups = await self._execute_intervention_followup(
                get_production(production_id, private=True) or production,
                intervention, targets, config, instruction, action_results,
            ) if action_results else []
            followup_replies = [item["reply"] for item in followups if item.get("reply")]
            if followup_replies:
                replies.extend(f"{item['seat_label']}: {item['reply']}" for item in followups if item.get("reply"))
            followup_issues = [issue for item in followups for issue in item.get("issues", [])]
            all_review_issues = [
                *[issue for plan in agent_plans for issue in plan.get("issues", [])],
                *followup_issues,
            ]
            all_review_issues = [issue for issue in all_review_issues if isinstance(issue, dict)]
            blocking_issues = [
                issue for issue in all_review_issues
                if str(issue.get("severity") or "").casefold() in {"blocking", "critical", "error"}
            ]
            requires_executable_action = self._intervention_requests_executable_action(instruction)
            effective_intervention_action = self._has_effective_intervention_action(action_results)
            no_executable_action = requires_executable_action and not effective_intervention_action
            requires_user = any(plan.get("requires_user") for plan in agent_plans) or any(
                item.get("requires_user") for item in followups
            )
            followup_policy = next(
                (str(item.get("resume_policy") or "") for item in reversed(followups)
                 if item.get("resume_policy")),
                "",
            )
            agent_policy = next(
                (str(plan.get("resume_policy") or "") for plan in reversed(agent_plans)
                 if plan.get("resume_policy")),
                "",
            )
            policy = action_policy or followup_policy or agent_policy or (
                "resume" if production.get("participation_mode") == "autonomous" else "preserve"
            )
            if no_executable_action:
                policy = "await_user"
            update_intervention(
                intervention["id"], "applied", acknowledged_at=now_iso(), applied_at=now_iso(),
                resume_policy=policy, action_results=action_results, error=(
                    "; ".join(str(item.get("error")) for item in failed) if failed else None
                ),
            )
            current = get_production(production_id, private=True) or production
            autonomous = current.get("participation_mode") == "autonomous"
            if no_executable_action:
                # An agent acknowledgement cannot replace the saved shot or
                # prompt.  Do not resume into stale Council deliverables.
                target_status = "awaiting_user"
            elif autonomous and current.get("status") not in {"completed", "stopped"}:
                # In autonomous mode an intervention is guidance, not a new
                # approval gate.  Preserve warnings in the conversation and
                # continue from the checkpoint unless the user explicitly
                # stopped the production.
                target_status = "running"
            elif failed or blocking_issues:
                target_status = "paused"
            elif policy == "await_user" or requires_user:
                target_status = "awaiting_user"
            elif policy == "pause":
                target_status = "paused"
            elif policy == "preserve" and current.get("status") not in {"queued", "running", "retrying"}:
                target_status = current.get("status")
            else:
                target_status = "running"
            update_production(production_id, status=target_status, intervention_requested=0,
                              error=("; ".join(str(item.get("error")) for item in failed) if failed else None))
            add_message(
                production_id, "system", "all", "intervention_status",
                "The Council acknowledged your change request but returned no executable shot or production action. "
                "No new generation was started and the previous prompt was not reused; the production is waiting "
                "for a concrete correction."
                if no_executable_action else
                "Council applied the intervention and is continuing from the saved checkpoint."
                if target_status == "running" else
                f"Council applied the intervention; production is now {target_status}.",
                {"intervention_id": intervention["id"], "state": "applied", "resume_policy": policy,
                 "action_results": action_results, "replies": replies,
                 "issues": all_review_issues,
                 "deduplicated_action_count": len(all_actions),
                 "no_executable_action": no_executable_action},
            )
            add_activity(
                production_id, "controller", "completed",
                "User intervention acknowledged; waiting for an executable correction"
                if no_executable_action else
                "User intervention applied; checkpoint resumed"
                if target_status == "running" else
                f"User intervention applied; production is now {target_status}",
                metadata={"intervention_id": intervention["id"], "action_count": len(action_results),
                          "no_executable_action": no_executable_action},
            )
        except asyncio.CancelledError:
            update_intervention(intervention["id"], "queued", queued_reason="Intervention turn interrupted; retrying from saved session")
            add_activity(production_id, "controller", "queued", "Intervention turn interrupted and requeued safely",
                         metadata={"intervention_id": intervention["id"]})
            raise
        except Exception as exc:
            update_intervention(intervention["id"], "failed", error=str(exc)[:8000])
            update_production(production_id, status="retrying", error=str(exc))
            add_message(production_id, "system", "user", "error",
                        f"Council intervention failed before the checkpoint resumed: {exc}",
                        {"intervention_id": intervention["id"], "state": "failed"})
            add_activity(production_id, "controller", "failed", "Council intervention failed",
                         metadata={"intervention_id": intervention["id"], "error": str(exc)})

    async def _run_production(self, production_id: str) -> None:
        production = get_production(production_id, private=True)
        if not production or production.get("pipeline") != COUNCIL_PIPELINE:
            return
        # A user pressing Resume is an explicit retry boundary. Requeue failed
        # tasks while preserving their prior failure in the event log; never
        # create a duplicate task with a new idempotency key.
        for failed in list_tasks(production_id):
            if failed.get("state") != "failed":
                continue
            update_task(
                failed["id"], state="queued", attempt=0, lease_token=None,
                started_at=None, finished_at=None,
                error_code="manual_retry", error_detail=(
                    f"Previous failure retained; retrying after Resume: "
                    f"{failed.get('error_detail') or 'unspecified failure'}"
                ),
            )
            add_activity(
                production_id, "controller", "retrying",
                f"Retrying failed Council task {failed['task_type']} from the saved checkpoint",
                task_id=failed["id"],
            )
            add_event(
                production_id, "council.task_requeued",
                {"task_id": failed["id"], "reason": "resume"},
            )
        config = latest_config(production_id)
        if config:
            # A restart may occur after a live settings edit was persisted but
            # before the controller applied the new revision to queued/waiting
            # tasks. Apply it here without touching an in-flight/completed turn.
            retarget_unstarted_tasks(production_id, int(config["revision"]))
        self.initialize_planning_tasks(production_id)
        self._reconcile_approved_waiting_tasks(production_id)
        # A bridge restart cannot leave an unowned task permanently running.
        # Requeue it with its persisted input (including any ComfyUI job ID),
        # allowing the task-specific reconciler to attach instead of duplicate.
        for stale in list_tasks(production_id):
            if stale["state"] in {"starting", "running", "validating"}:
                update_task(stale["id"], state="queued", lease_token=None,
                            error_code="controller_recovery", error_detail="Recovered after controller restart")
        update_production(production_id, status="running", error=None, started_at=production.get("started_at") or now_iso())
        add_activity(production_id, "controller", "running", "Controller is evaluating the next dependency-ready task")
        add_event(production_id, "council.controller_started", {})

        running: dict[str, tuple[asyncio.Task[None], str]] = {}
        try:
            while not self._stopping:
                production = get_production(production_id, private=True)
                if not production:
                    return
                if production.get("status") in {"paused", "awaiting_user", "stopped", "completed", "failed"}:
                    return

                stopping = production.get("stop_requested") or production.get("status") in {"stopped", "stopping"}
                pausing = production.get("pause_requested") or production.get("status") in {"paused", "pausing"}
                if (stopping or pausing) and running:
                    # Do not abandon a queued/running GPU job. Agent processes
                    # are cancelled by the control route; every lane reaches a
                    # persisted safe checkpoint before the controller exits.
                    done, _ = await asyncio.wait(
                        [item[0] for item in running.values()],
                        timeout=1.0, return_when=asyncio.FIRST_COMPLETED,
                    )
                    for finished in done:
                        key = next(key for key, value in running.items() if value[0] is finished)
                        running.pop(key, None)
                        try:
                            finished.result()
                        except asyncio.CancelledError:
                            pass
                    continue
                if stopping:
                    update_production(production_id, status="stopped", stop_requested=0)
                    add_activity(production_id, "controller", "stopped", "Council production stopped at a safe checkpoint")
                    return
                if pausing:
                    update_production(production_id, status="paused", pause_requested=0)
                    add_activity(production_id, "controller", "paused", "Council production paused at a safe checkpoint")
                    return

                # Decisions are stored separately from task state. Reconcile
                # on every cycle so an approval arriving between scheduler
                # ticks cannot leave the controller spinning on one task.
                if self._reconcile_approved_waiting_tasks(production_id):
                    continue

                # A Council intervention is a durable turn in the saved agent
                # sessions, not merely a flag attached to the next task.  Give
                # it priority over newly-ready work so the user's message is
                # handled before another creative turn starts.  If ComfyUI was
                # sampling, the controller only reaches this point after that
                # generation has reached its safe checkpoint.
                pending_intervention = next(
                    (
                        item for item in list_interventions(production_id)
                        if item["state"] in {"queued", "acknowledged"}
                    ),
                    None,
                )
                if pending_intervention:
                    await self._execute_intervention_turn(production, pending_intervention)
                    continue

                for task, resource in self._ready_batch(production_id, running):
                    work = asyncio.create_task(
                        self._run_one_task(production, task),
                        name=f"council-task-{task['id']}",
                    )
                    running[task["id"]] = (work, resource)

                if running:
                    done, _ = await asyncio.wait(
                        [item[0] for item in running.values()],
                        timeout=1.0, return_when=asyncio.FIRST_COMPLETED,
                    )
                    for finished in done:
                        key = next(key for key, value in running.items() if value[0] is finished)
                        running.pop(key, None)
                        try:
                            finished.result()
                        except asyncio.CancelledError:
                            pass
                    continue

                tasks = list_tasks(production_id)
                failed = next((item for item in tasks if item["state"] == "failed"), None)
                if failed:
                    update_production(production_id, status="failed", stage=failed["stage"], error=failed.get("error_detail"))
                    return
                waiting = next((item for item in tasks if item["state"] == "waiting"), None)
                if waiting:
                    role_label = str(waiting["role_id"]).replace("-", " ").title()
                    pending = next(
                        (
                            item for item in list_decisions(production_id)
                            if item["status"] == "pending"
                            and str((item.get("payload") or {}).get("task_id") or "") == str(waiting["id"])
                        ),
                        None,
                    )
                    if not pending:
                        pending = add_decision(
                            production_id, waiting["stage"], f"Council input required · {role_label}",
                            f"{role_label} is waiting for your decision before execution can continue.",
                            {"task_id": waiting["id"], "role_id": waiting["role_id"], "recovered": True},
                        )
                    update_production(production_id, status="awaiting_user", stage=waiting["stage"], error=None)
                    add_activity(
                        production_id, "controller", "waiting",
                        f"Council is waiting for your decision · {role_label}", task_id=waiting["id"],
                    )
                    return
                if tasks and all(item["state"] == "completed" for item in tasks):
                    if production.get("stage") == "final_review":
                        update_production(production_id, status="awaiting_user", stage="user_review", progress=0.99)
                        add_activity(production_id, "controller", "waiting", "Final master is ready for user review")
                    elif production.get("stage") not in {"user_review", "completed"}:
                        if production.get("participation_mode") == "autonomous":
                            self.initialize_execution_tasks(production_id)
                            update_production(production_id, status="running", stage="scene_frames", progress=0.36)
                            add_activity(production_id, "controller", "running", "Autonomous planning gate passed; scene-frame work is starting")
                            continue
                        pending = next((item for item in list_decisions(production_id) if item["stage"] == "planning_review" and item["status"] == "pending"), None)
                        if not pending:
                            add_decision(
                                production_id, "planning_review", "Council production plan",
                                "The treatment, storyboard, and execution manifest are ready. Approve to begin reference and scene-frame generation.",
                                {"contracts": ["visual_treatment.v1", "storyboard.v1", "execution_manifest.v1"]},
                            )
                        update_production(production_id, status="awaiting_user", stage="planning_review", progress=0.35)
                        add_activity(production_id, "controller", "waiting", "Planning deliverables are ready for user review")
                        add_message(
                            production_id, "system", "all", "status",
                            "Council planning is complete. Review the treatment, storyboard, and execution plan before media generation begins.",
                            {"pipeline": COUNCIL_PIPELINE, "gate": "planning_review"},
                        )
                        add_event(production_id, "council.planning_completed", {})
                    return
                queued = [item for item in tasks if item["state"] == "queued"]
                if queued:
                    blocked = ", ".join(str(item["task_type"]) for item in queued[:3])
                    detail = f"Council tasks are blocked by unresolved dependencies: {blocked}"
                    update_production(production_id, status="paused", error=detail)
                    add_activity(production_id, "controller", "blocked", detail)
                    add_message(production_id, "system", "user", "error", detail, {"task_ids": [item["id"] for item in queued]})
                    return
                add_activity(production_id, "controller", "waiting", "Controller is waiting for task dependencies")
                return
        finally:
            if running:
                await asyncio.gather(*(item[0] for item in running.values()), return_exceptions=True)

    @staticmethod
    def _eligible_seat(production_id: str, task: dict[str, Any]) -> dict[str, Any] | None:
        candidates = [
            seat for seat in list_seats(production_id, int(task["config_revision"]))
            if seat["active"] and task["role_id"] in seat["role_ids"]
        ]
        return candidates[0] if candidates else None

    @staticmethod
    def _requeue_interventions_for_task(
        interventions: list[dict[str, Any]], task_id: str, reason: str,
    ) -> None:
        for intervention in interventions:
            update_intervention(
                intervention["id"], "queued", queued_reason=reason,
                affected_task_ids=[task_id],
            )

    def _handle_task_failure(
        self, production: dict[str, Any], task: dict[str, Any], seat: dict[str, Any],
        role_label: str, attempt: int, interventions: list[dict[str, Any]], exc: Exception,
    ) -> None:
        """Persist one provider/handoff failure without leaving a task running."""
        production_id = str(production["id"])
        self._requeue_interventions_for_task(
            interventions, task["id"],
            "Provider turn ended before the intervention was applied",
        )
        detail = str(exc)
        if attempt < int(task["max_attempts"]):
            update_task(
                task["id"], state="queued", error_code="provider_or_contract_error",
                error_detail=detail, lease_token=None,
            )
            add_activity(
                production_id, "controller", "retrying",
                f"{role_label} failed validation; retry {attempt + 1}/{task['max_attempts']} is queued",
                task_id=task["id"], metadata={"error": detail},
            )
            add_event(
                production_id, "council.task_retry",
                {"task_id": task["id"], "attempt": attempt, "error": detail},
            )
            return
        update_task(
            task["id"], state="failed", error_code="provider_or_contract_error",
            error_detail=detail, finished_at=now_iso(), lease_token=None,
        )
        update_production(production_id, status="failed", stage=task["stage"], error=detail)
        add_activity(
            production_id, "agent", "failed", f"{seat['label']} · {role_label} · failed",
            worker_id=seat["id"], role_id=task["role_id"], task_id=task["id"],
            metadata={"error": detail},
        )
        add_message(
            production_id, "system", "all", "error", f"Council task failed: {detail}",
            {"task_id": task["id"], "role_id": task["role_id"]},
        )
        add_event(production_id, "council.task_failed", {"task_id": task["id"], "error": detail})

    async def _execute_task(self, production: dict[str, Any], task: dict[str, Any]) -> None:
        production_id = str(production["id"])
        # Public production payloads intentionally redact the song path. The
        # controller is the trusted internal worker and must reload the
        # private record before building media handoffs or agent prompts.
        production = get_production(production_id, private=True) or production
        seat = self._eligible_seat(production_id, task)
        if not seat:
            update_task(task["id"], state="failed", error_code="no_eligible_seat", error_detail=f"No eligible seat for {task['role_id']}", finished_at=now_iso())
            add_activity(production_id, "controller", "failed", f"No eligible seat for {task['role_id']}", task_id=task["id"])
            return

        lease = uuid.uuid4().hex
        attempt = int(task["attempt"]) + 1
        update_task(
            task["id"], assigned_seat_id=seat["id"], state="running", attempt=attempt,
            lease_token=lease, started_at=now_iso(), error_code=None, error_detail=None,
        )
        update_production(production_id, stage=task["stage"], status="running")
        role_label = str(task["role_id"]).replace("-", " ").title()
        add_activity(
            production_id, "agent", "running", f"{seat['label']} · {role_label} · working",
            worker_id=seat["id"], role_id=task["role_id"], task_id=task["id"],
            metadata={"runtime": seat["runtime"], "model": seat["model"], "attempt": attempt},
        )
        add_event(production_id, "council.task_started", {"task_id": task["id"], "seat_id": seat["id"], "role_id": task["role_id"]})

        session = get_session(production_id, seat["id"]) or {}
        # ``acknowledged`` means the HTTP intervention was accepted immediately
        # after cancelling an idle/controller turn. It is not yet applied: the
        # addressed saved session must consume it in this role turn.
        interventions = [
            item for item in list_interventions(production_id)
            if item["state"] in {"queued", "acknowledged"}
            and (not item["target_seat_ids"] or seat["id"] in item["target_seat_ids"])
        ]
        for intervention in interventions:
            update_intervention(intervention["id"], "delivered", delivered_at=now_iso(), affected_task_ids=[task["id"]])
            add_message(
                production_id, "system", seat["id"], "intervention_status",
                f"Intervention delivered to {seat['label']} for {role_label}.",
                {"intervention_id": intervention["id"], "state": "delivered", "task_id": task["id"]},
            )

        trace = self._trace_callback(production_id, seat, task)
        heartbeat = self._heartbeat_callback(production_id, seat, task)
        song_path = str(production.get("song_path") or "").strip()
        media_paths = self._task_media_paths(production_id, task)
        if task["task_type"] == "audio_analysis" and song_path:
            song = Path(song_path)
            if not song.is_file():
                raise RuntimeError(f"The production song is missing: {song}")
            analysis_dir = PRODUCTIONS / production_id / "analysis"
            analysis_dir.mkdir(parents=True, exist_ok=True)
            try:
                audio_metadata = await asyncio.to_thread(probe_audio_metadata, song)
            except (RuntimeError, OSError) as exc:
                audio_metadata = {"preflight_error": str(exc)}
            preflight_path = analysis_dir / "audio_preflight.json"
            preflight_path.write_text(
                json.dumps({
                    "song_path": str(song),
                    "metadata": audio_metadata,
                    "source": "backend.ffprobe",
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # This is the same carrier handoff used by Legacy. It preserves
            # the original WAV/MP3 for generation while giving AGY's existing
            # multimodal view_file tool a readable MP4 container.
            carrier = analysis_dir / "agy_audio_carrier.mp4"
            expected_duration = float(audio_metadata.get("duration_seconds") or 0)
            if not carrier.is_file() or carrier.stat().st_size == 0:
                await asyncio.to_thread(
                    prepare_agent_audio_carrier, song, carrier, expected_duration or None,
                )
            lyric_lines = [
                line.strip() for line in str(production.get("lyrics") or "").splitlines()
                if line.strip() and not line.strip().startswith("[")
            ]
            task_input = dict(task.get("input") or {})
            task_input.update({
                "agy_audio_carrier_path": str(carrier.resolve()),
                "audio_preflight_path": str(preflight_path.resolve()),
                "audio_expected_duration": expected_duration,
                "minimum_lyric_entries": max(1, min(12, len(lyric_lines))),
            })
            update_task_input(task["id"], task_input)
            task = {**task, "input": task_input}
            media_paths = [carrier]
        # Build the prompt after the media handoff so the exact carrier and
        # preflight paths are part of the request AGY receives.
        prompt = self._build_prompt(production, task, seat, interventions)
        extra_dirs = [Path(song_path).parent] if song_path else []
        extra_dirs.extend(path.parent for path in media_paths)
        try:
            result = await self._invoke_council_agent(
                production, task, seat, prompt,
                # Audio analysis must match Legacy: use a fresh AGY media
                # session rather than a conversational session that may have
                # lost the media handoff context.
                session_id=(None if task["task_type"] == "audio_analysis" else session.get("provider_session_id")),
                media_paths=media_paths, trace=trace, heartbeat=heartbeat,
                extra_dirs=extra_dirs,
            )
            update_session(
                production_id, seat["id"], provider_session_id=result.session_id,
                status="active", last_task_id=task["id"], handoff_summary=str(result.content.get("summary") or "")[:4000],
            )
            envelope = CouncilEnvelope.model_validate(result.content)
            self._validate_task_deliverable(task, envelope.content)
        except asyncio.CancelledError:
            # Cancellation is a safe checkpoint, not a task failure.  The
            # controller owner is being replaced by an intervention or a
            # stop/pause request, so leave the task requeueable and do not let
            # the scheduler report a false completed/failed turn.
            for intervention in interventions:
                update_intervention(
                    intervention["id"], "queued",
                    queued_reason="Provider turn was interrupted before the intervention was applied",
                    affected_task_ids=[task["id"]],
                )
            update_task(
                task["id"], state="queued", lease_token=None,
                error_code="interrupted", error_detail="Provider turn interrupted at a safe checkpoint",
            )
            add_activity(
                production_id, "agent", "queued",
                f"{seat['label']} · {role_label} · turn interrupted and requeued",
                worker_id=seat["id"], role_id=task["role_id"], task_id=task["id"],
            )
            raise
        except (AgentExecutionError, ValidationError, RuntimeError) as exc:
            self._handle_task_failure(production, task, seat, role_label, attempt, interventions, exc)
            return
            add_activity(production_id, "agent", "failed", f"{seat['label']} · {role_label} · failed", worker_id=seat["id"], role_id=task["role_id"], task_id=task["id"], metadata={"error": str(exc)})
            return

        review_task = task["task_type"] in {"technical_media_review", "av_sync_review", "final_media_review"}
        # A normal specialist disagreement is part of the autonomous revision
        # loop.  It must not become a user gate merely because the provider used
        # the word "escalate".  Only an explicit requires_user response, or an
        # exhausted bounded revision loop, may pause the production.
        requests_revision = envelope.decision in {"revise", "escalate"} and not envelope.requires_user
        retry_revision = requests_revision and attempt < int(task["max_attempts"]) and not review_task
        revision_exhausted = requests_revision and attempt >= int(task["max_attempts"]) and not review_task
        waiting = (envelope.requires_user or revision_exhausted) and not retry_revision
        if retry_revision:
            update_task(
                task["id"], state="queued", lease_token=None,
                error_code="agent_requested_revision",
                error_detail=envelope.summary,
            )
            add_activity(
                production_id, "controller", "retrying",
                f"{seat['label']} returned revision instructions; attempt {attempt + 1}/{task['max_attempts']} is queued",
                worker_id=seat["id"], role_id=task["role_id"], task_id=task["id"],
            )
        elif waiting and not review_task:
            delivered = save_deliverable(
                production_id, task["id"], task["role_id"], task["output_contract"], envelope.content,
            )
            update_task(task["id"], state="waiting", lease_token=None)
            update_production(production_id, status="awaiting_user", stage=task["stage"])
            decision = add_decision(
                production_id, task["stage"], f"Council input required · {role_label}",
                envelope.summary if not revision_exhausted else f"Council revision budget exhausted: {envelope.summary}",
                {
                    "task_id": task["id"], "deliverable_id": delivered["id"],
                    "role_id": task["role_id"], "decision": envelope.decision,
                    "revision_exhausted": revision_exhausted,
                    "requires_user": envelope.requires_user,
                    "issues": envelope.issues, "next_action": envelope.next_action,
                },
            )
            add_message(
                production_id, "system", "user", "decision",
                f"{role_label} needs your decision before Council execution can continue.",
                {"decision_id": decision["id"], "task_id": task["id"], "gate": task["stage"]},
            )
        else:
            delivered = save_deliverable(
                production_id, task["id"], task["role_id"], task["output_contract"], envelope.content,
            )
            if review_task:
                save_review(
                    production_id, task["id"], delivered["id"], seat["id"], task["task_type"],
                    envelope.decision, envelope.issues,
                    independent=True,
                )
            update_task(task["id"], state="completed", finished_at=now_iso(), lease_token=None)
            if task["task_type"] == "final_media_review":
                final_artifact = next((item for item in reversed(list_artifacts(production_id, private=True)) if item.get("kind") == "final_video"), None)
                decision = add_decision(
                    production_id, "final_review", "Final Council master", envelope.summary,
                    {"artifact_id": final_artifact["id"] if final_artifact else None,
                     "review_deliverable_id": delivered["id"], "recommendation": envelope.decision},
                )
                update_production(production_id, stage="final_review", progress=0.99)
                add_message(production_id, "system", "user", "decision",
                            "The final Council video is ready for your review.",
                            {"decision_id": decision["id"], "artifact_id": final_artifact["id"] if final_artifact else None})

        for intervention in interventions:
            update_intervention(intervention["id"], "applied", acknowledged_at=now_iso(), applied_at=now_iso(), affected_task_ids=[task["id"]])
            add_message(
                production_id, "system", seat["id"], "intervention_status",
                f"Intervention applied by {seat['label']} during {role_label}.",
                {"intervention_id": intervention["id"], "state": "applied", "task_id": task["id"]},
            )

        add_message(
            production_id, seat["runtime"], "all", "agent_response", envelope.summary,
            {
                "seat_id": seat["id"], "seat_label": seat["label"], "role_id": task["role_id"],
                "task_id": task["id"], "decision": envelope.decision, "content": envelope.content,
                "issues": envelope.issues, "next_action": envelope.next_action,
                "confidence": envelope.confidence, "requires_user": envelope.requires_user,
                "model": seat["model"], "effort": seat["effort"],
                "config_revision": int(task["config_revision"]),
            },
        )
        final_state = "completed" if review_task else "retrying" if retry_revision else "waiting" if waiting else "completed"
        add_activity(
            production_id, "agent", final_state, f"{seat['label']} · {role_label} · {envelope.decision}",
            worker_id=seat["id"], role_id=task["role_id"], task_id=task["id"],
        )
        add_event(
            production_id,
            "council.task_retry" if retry_revision else "council.task_waiting" if waiting else "council.task_completed",
            {"task_id": task["id"], "decision": envelope.decision},
        )

    @classmethod
    def _validate_task_deliverable(cls, task: dict[str, Any], content: Any) -> None:
        """Reject structurally valid envelopes whose task payload is unusable.

        The generic Council envelope proves only that an agent answered. These
        two execution roles feed image generation and ComfyUI directly, so a
        vague sentence or empty object must never be treated as a deliverable.
        """
        if task.get("task_type") == "audio_analysis":
            if not isinstance(content, dict):
                raise RuntimeError("audio_analysis.v1 content must be a JSON object")
            if content.get("analysis_complete") is not True:
                raise RuntimeError("audio_analysis.v1 must confirm analysis_complete=true")
            inspection = content.get("media_inspection")
            if not isinstance(inspection, dict) or inspection.get("decoded_audio") is not True:
                raise RuntimeError("audio_analysis.v1 must prove that AGY decoded the actual song audio")
            expected_carrier = str((task.get("input") or {}).get("agy_audio_carrier_path") or "")
            inspected_carrier = str(inspection.get("inspected_path") or "")
            if not expected_carrier or Path(inspected_carrier).resolve() != Path(expected_carrier).resolve():
                raise RuntimeError("audio_analysis.v1 must prove inspection of the exact AGY audio carrier")
            aliases = {
                "duration_seconds": ("duration", "audio_duration_seconds"),
                "bpm": ("estimated_bpm", "tempo_bpm"),
                "lyric_timeline": ("lyrics_timeline", "lyric_map"),
                "vocal_entrances": ("vocal_onsets", "first_vocal_onsets"),
            }
            for canonical, candidates in aliases.items():
                if content.get(canonical) not in (None, "", []):
                    continue
                for candidate in candidates:
                    if content.get(candidate) not in (None, "", []):
                        content[canonical] = content[candidate]
                        break
            try:
                duration = float(content.get("duration_seconds") or 0)
            except (TypeError, ValueError):
                duration = 0
            if duration <= 0:
                raise RuntimeError("audio_analysis.v1 must include the measured duration_seconds")
            expected_duration = float((task.get("input") or {}).get("audio_expected_duration") or 0)
            if expected_duration and abs(duration - expected_duration) > max(1.0, expected_duration * 0.01):
                raise RuntimeError(
                    f"audio_analysis.v1 duration {duration:.2f}s does not match the decoded source {expected_duration:.2f}s"
                )
            if content.get("bpm") in (None, "", []):
                raise RuntimeError("audio_analysis.v1 must include AGY's measured BPM")
            if not isinstance(content.get("sections"), list) or not content["sections"]:
                raise RuntimeError("audio_analysis.v1 must include non-empty timed sections")
            if not isinstance(content.get("vocal_entrances"), list) or not content["vocal_entrances"]:
                raise RuntimeError("audio_analysis.v1 must include vocal entrances from the audio")
            if not isinstance(content.get("lyric_timeline"), list):
                raise RuntimeError("audio_analysis.v1 must include a lyric timeline from the audio")
            minimum_entries = int((task.get("input") or {}).get("minimum_lyric_entries") or 1)
            if len(content["lyric_timeline"]) < minimum_entries:
                raise RuntimeError(
                    f"audio_analysis.v1 returned only {len(content['lyric_timeline'])} lyric timings; "
                    f"at least {minimum_entries} are required"
                )
            # Downstream Council planning uses vocal_windows; keep the Legacy
            # field as the source of truth while accepting its equivalent name.
            content.setdefault("vocal_windows", content["vocal_entrances"])
            return
        if task.get("task_type") not in {"scene_frame_design", "generation_prompt"}:
            return
        if not isinstance(content, dict):
            raise RuntimeError(f"{task['output_contract']} content must be a JSON object")
        if task["task_type"] == "scene_frame_design":
            prompt = cls._payload_text(content, "opening_frame_prompt", "prompt", "description")
            if len(prompt.split()) < 12:
                raise RuntimeError(
                    "scene_frame_plan.v1 requires a detailed shot-specific opening_frame_prompt"
                )
            reference_ids = (
                content.get("source_reference_ids")
                or content.get("selected_reference_ids")
                or content.get("reference_ids")
            )
            if reference_ids is not None and not isinstance(reference_ids, list):
                raise RuntimeError("scene_frame_plan.v1 source_reference_ids must be an array")
        else:
            prompt = cls._payload_text(content, "prompt", "video_prompt", "generation_prompt")
            if len(prompt.split()) < 12:
                raise RuntimeError("generation_prompt.v1 requires a detailed executable video prompt")

    @staticmethod
    def _short(value: Any, limit: int = 420) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else f"{text[:limit - 1].rstrip()}…"

    @classmethod
    def _stream_text(cls, value: Any) -> str:
        chunks: list[str] = []

        def collect(item: Any) -> None:
            if isinstance(item, str) and item.strip():
                chunks.append(item.strip())
            elif isinstance(item, list):
                for child in item:
                    collect(child)
            elif isinstance(item, dict):
                for key in ("text", "summary", "summary_text", "output_text", "message", "content", "parts", "delta"):
                    if key in item:
                        collect(item[key])

        collect(value)
        return cls._short(" ".join(chunks))

    @classmethod
    def _format_trace(cls, label: str, channel: str, line: str) -> tuple[str, str] | None:
        """Expose factual provider milestones, never inferred chain-of-thought."""
        stripped = line.strip()
        if not stripped:
            return None
        lowered = stripped.casefold()
        if channel == "stderr":
            harmless = (
                "responses_retry", "stream disconnected", "websocket closed",
                "shell snapshot", "falling back to http", "remote plugin catalog",
                "icon path with '..'", "after_agent hook failed",
            )
            if any(marker in lowered for marker in harmless) or re.search(r"\bwarn(?:ing)?\b", lowered):
                return None
            # Keep real provider failures visible, but do not turn routine CLI
            # stderr noise into fake Council work. Process exit handling still
            # remains authoritative for the final failure state.
            if any(marker in lowered for marker in ("error", "failed", "exception", "fatal", "denied")):
                return f"{label} error: {cls._short(stripped)}", "provider_error"
            return None
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            if lowered.startswith(("info", "debug", "trace", "event:", "item.completed")):
                return None
            return f"{label} update: {cls._short(stripped)}", "agent_update"
        if not isinstance(event, dict):
            return None

        event_type = str(event.get("type") or event.get("event") or "").casefold()
        step = event.get("step_update") if isinstance(event.get("step_update"), dict) else None
        if step:
            step_type = str(step.get("step_type") or "").casefold()
            state = str(step.get("state") or "").casefold()
            if step_type == "tool":
                info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
                name = step.get("tool_name") or info.get("name") or "production tool"
                verb = "started" if state == "active" else "completed" if state == "done" else "updated"
                return f"{label} {verb} {cls._short(name, 120)}.", "tool_activity"
            if step_type == "agent_response" and state == "done":
                return f"{label} completed its provider response; validating the result.", "agent_update"
        item = event.get("item") if isinstance(event.get("item"), dict) else event
        item_type = str(item.get("type") or "").casefold()
        if item_type in {"command_execution", "tool_call", "tool_use", "function_call", "web_search_call"}:
            name = item.get("name") or item.get("tool") or item.get("action") or "production tool"
            return f"{label} is using {cls._short(name, 120)}.", "tool_activity"
        if item_type in {"reasoning", "analysis", "thinking"}:
            summary = cls._stream_text(item)
            return (f"{label} reasoning summary: {summary}", "reasoning_summary") if summary else None
        if item_type in {"agent_message", "message", "assistant_message"}:
            response = cls._stream_text(item)
            if response and not response.lstrip().startswith(("{", "[")):
                return f"{label} response: {response}", "agent_update"
        if event_type in {
            "response.output_text.delta", "response.text.delta", "output_text.delta",
        }:
            response = cls._stream_text(event.get("delta") or event.get("text"))
            if response and not response.lstrip().startswith(("{", "[")):
                return f"{label} response: {response}", "agent_update"
        if event_type in {
            "response.reasoning_summary_text.delta", "reasoning_summary_text.delta",
        }:
            summary = cls._stream_text(event.get("delta") or event.get("text"))
            return (f"{label} reasoning summary: {summary}", "reasoning_summary") if summary else None
        if event_type in {"progress", "status", "step_update"}:
            detail = cls._stream_text(event.get("message") or event.get("step") or event.get("status"))
            if detail and detail.casefold() not in {"progress", "working", "in progress", "update"}:
                return f"{label} update: {detail}", "agent_update"
        return None

    def _trace_callback(self, production_id: str, seat: dict[str, Any], task: dict[str, Any], *, label: str | None = None):
        last_signature = ""
        seen_signatures: set[str] = set()
        trace_label = label
        label = f"{seat['label']} · {str(task['role_id']).replace('-', ' ').title()}"

        async def emit(channel: str, line: str) -> None:
            nonlocal last_signature
            log_dir = PRODUCTIONS / production_id / "logs"
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                with (log_dir / "council-cli-events.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "at": now_iso(), "seat_id": seat["id"], "runtime": seat["runtime"],
                        "task_id": task["id"], "channel": channel, "line": line.rstrip("\r\n"),
                    }, ensure_ascii=False) + "\n")
            except OSError:
                pass
            formatted = self._format_trace(trace_label or label, channel, line)
            if not formatted:
                return
            message, event_type = formatted
            signature = f"{event_type}:{message}"
            if signature == last_signature or signature in seen_signatures:
                return
            last_signature = signature
            seen_signatures.add(signature)
            if len(seen_signatures) > 256:
                # Keep memory bounded while retaining enough history to avoid
                # the repeated item.completed/agent_message cards seen in the
                # CLI streams.
                seen_signatures.clear()
                seen_signatures.add(signature)
            add_activity(
                production_id, "agent", "running", message, worker_id=seat["id"],
                role_id=task["role_id"], task_id=task["id"],
                metadata={"runtime": seat["runtime"], "model": seat["model"], "event_type": event_type},
            )
            add_message(
                production_id, seat["runtime"], "all", "agent_trace", message,
                {"live": True, "seat_id": seat["id"], "seat_label": seat["label"],
                 "role_id": task["role_id"], "task_id": task["id"], "event_type": event_type,
                 "model": seat["model"], "effort": seat["effort"]},
            )

        return emit

    @staticmethod
    def _heartbeat_callback(
        production_id: str, seat: dict[str, Any], task: dict[str, Any], *, label: str | None = None,
    ):
        last_bucket = -1

        async def emit(elapsed: float, idle: float, channel: str, line: str) -> None:
            nonlocal last_bucket
            bucket = int(elapsed // 30)
            if bucket == last_bucket:
                return
            last_bucket = bucket
            role = label or str(task["role_id"]).replace("-", " ").title()
            message = (
                f"{seat['label']} · {role} · provider process is running "
                f"({round(elapsed)}s elapsed, {round(idle)}s since its last CLI event)"
            )
            add_activity(
                production_id, "agent", "running", message, worker_id=seat["id"],
                role_id=task["role_id"], task_id=task["id"],
                metadata={"runtime": seat["runtime"], "model": seat["model"], "heartbeat": True},
            )

        return emit

    @staticmethod
    def _agy_contract_failure(exc: Exception) -> bool:
        """Match Legacy's bounded retry for AGY handoff/contract failures."""
        parts = [str(exc)]
        if isinstance(exc, AgentExecutionError):
            parts.extend([exc.stdout, exc.stderr])
        text = "\n".join(parts).casefold()
        if isinstance(exc, ValidationError):
            return True
        if "no valid structured response" in text:
            return True
        return "invalid arguments" in text and ("/issues" in text or "response" in text)

    @staticmethod
    def _agy_placeholder(result: Any) -> bool:
        """Reject AGY schema echoes and media-only acknowledgements."""
        payload = getattr(result, "content", result)
        if not isinstance(payload, dict):
            return True
        content = payload.get("content")
        text = " ".join(str(payload.get(key, "")) for key in ("decision", "next_action", "summary")).casefold()

        def schema_placeholder(value: Any) -> bool:
            if not isinstance(value, dict) or set(value) != {"type"}:
                return False
            descriptor = value.get("type")
            return descriptor in {"string", "number"} or (
                isinstance(descriptor, list)
                and all(item in {"string", "number", "null"} for item in descriptor)
            )

        echoed_schema = any(schema_placeholder(payload.get(key)) for key in ("summary", "decision", "content", "next_action"))
        echoed_issue_schema = payload.get("issues") == [{"type": ["string", "null"]}]
        complete_schema = isinstance(payload.get("properties"), dict) and isinstance(payload.get("type"), str)
        if echoed_schema or echoed_issue_schema or complete_schema:
            return True
        return content in (None, {}) and (
            "successfully read" in text or "read the requested" in text
        ) and "task is complete" in text

    async def _invoke_council_agent(
        self, production: dict[str, Any], task: dict[str, Any], seat: dict[str, Any],
        prompt: str, session_id: str | None, media_paths: list[Path],
        trace: Any, heartbeat: Any, extra_dirs: list[Path],
    ) -> Any:
        """Invoke one Council seat with Legacy's resumable AGY retry policy."""
        runtime = str(seat["runtime"])
        # Native project skills live above the production state directory.  Add
        # the repository explicitly so both Codex and AGY can read the role
        # skill and the user-selected specialist skills without prompt
        # injection.
        extra_dirs = [ROOT, *extra_dirs]
        invoke_args = {
            "runtime": runtime, "participant": seat["id"], "production_id": str(production["id"]),
            "prompt": prompt,
            "model": seat["model"], "effort": seat["effort"], "images": media_paths,
            "on_output": trace, "on_heartbeat": heartbeat, "extra_dirs": extra_dirs,
            "execution_key": f"{production['id']}:{seat['id']}",
        }
        retry_request = prompt + """

CORRECTION AFTER A REJECTED RESPONSE:
Perform the assigned task now. Do not describe, echo, or reproduce the response schema. Return only the
actual result for this task. Use plain strings for summary, decision, and next_action; put the real findings
or task payload in content; use issues: [] when there are no issues, otherwise use a JSON array of concrete
issue objects. Never use schema descriptors such as {"type": "string"} as values.
"""
        fresh_retry_used = False
        try:
            result = await process_manager.invoke(session_id=session_id, **invoke_args)
            if runtime == "agy":
                CouncilEnvelope.model_validate(result.content)
        except (AgentExecutionError, ValidationError, RuntimeError) as exc:
            if runtime != "agy" or not self._agy_contract_failure(exc):
                raise
            fresh_retry_used = True
            add_message(
                str(production["id"]), "agy", "all", "agent_trace",
                "AGY rejected the Council response contract; retrying once in a fresh saved-session handoff.",
                {"live": True, "runtime": runtime, "model": seat["model"], "effort": seat["effort"],
                 "stream": "system", "retry": "contract_fresh_session", "task_id": task["id"]},
            )
            result = await process_manager.invoke(
                session_id=None, **{**invoke_args, "prompt": retry_request},
            )
            if self._agy_placeholder(result):
                raise RuntimeError("AGY returned the response schema instead of the Council task result after a fresh-session retry")
            if runtime == "agy":
                CouncilEnvelope.model_validate(result.content)
        if runtime == "agy" and self._agy_placeholder(result):
            if fresh_retry_used:
                raise RuntimeError("AGY returned the response schema instead of the Council task result after one fresh-session retry")
            add_message(
                str(production["id"]), "agy", "all", "agent_trace",
                "AGY returned a schema placeholder instead of the Council task result; retrying once in a fresh conversation.",
                {"live": True, "runtime": runtime, "model": seat["model"], "effort": seat["effort"],
                 "stream": "system", "retry": "fresh_session", "task_id": task["id"]},
            )
            result = await process_manager.invoke(
                session_id=None, **{**invoke_args, "prompt": retry_request},
            )
            if self._agy_placeholder(result):
                raise RuntimeError("AGY returned the response schema instead of the Council task result after one fresh-session retry")
            CouncilEnvelope.model_validate(result.content)
        return result

    @staticmethod
    def _build_prompt(
        production: dict[str, Any], task: dict[str, Any], seat: dict[str, Any],
        interventions: list[dict[str, Any]],
    ) -> str:
        prior = list_deliverables(str(production["id"]))
        role_file = role_skill_path(str(task["role_id"]))
        selected_skills = selected_skill_manifest_context(
            [str(value) for value in production.get("skills", [])]
        )
        references = list_references(str(production["id"]), private=True)
        shot = None
        shot_id = task.get("input", {}).get("shot_id")
        if shot_id:
            shot = next((item for item in list_shots(str(production["id"]), private=True) if item["id"] == shot_id), None)
        payload = {
            "production": {
                "id": production["id"], "title": production["title"], "concept": production.get("concept", ""),
                "lyrics": production.get("lyrics", ""), "song_path": production.get("song_path"),
                "participation_mode": production.get("participation_mode"),
                "continuity_mode": production.get("continuity_mode"),
                "generation": {
                    "turbo_profile": production.get("generation_turbo_profile"),
                    "steps": production.get("generation_steps"),
                    "aspect_ratio": production.get("generation_aspect_ratio"),
                    "audio_mode": production.get("generation_audio_mode", "auto"),
                    "megapixel_rules": production.get("generation_megapixel_rules"),
                },
            },
            "task": {**{key: task[key] for key in ("id", "stage", "task_type", "role_id", "output_contract")},
                     "input": task.get("input", {})},
            "current_shot": shot,
            "available_references": [
                {
                    "id": item["id"], "name": item.get("name"), "kind": item.get("kind"),
                    "notes": item.get("notes"), "assigned_to_current_shot": bool(
                        shot and item["id"] in (shot.get("reference_ids") or [])
                    ),
                }
                for item in references
            ],
            "previous_deliverables": [
                {"contract": item["contract"], "version": item["version"], "payload": item["payload"]}
                for item in prior
            ],
            "interventions": [{"id": item["id"], "content": item["content"]} for item in interventions],
        }
        review_guidance = ""
        if task["task_type"] in {"technical_media_review", "av_sync_review", "final_media_review"}:
            review_guidance = """
REVIEW ROUTING
If revision is needed, return decision=revise and give concrete, actionable findings for the responsible specialist.
Do not set requires_user=true for an ordinary quality defect. Reserve requires_user=true for a genuinely missing creative choice or authority that the Council cannot resolve.
"""

        contract_guidance = ""
        if task["task_type"] == "scene_frame_design":
            contract_guidance = """
SCENE-FRAME CONTRACT
Design the NEW opening composition for current_shot. Planning references are anchors only and must not
be returned as the scene frame. In content return opening_frame_prompt, source_reference_ids, framing,
composition_notes, continuity_notes, requires_closing_frame, and optional closing_frame_prompt.
Choose only references relevant to this shot by exact ID. The opening_frame_prompt must describe the
actual first frame, subject placement/action, camera angle, framing, environment, and lighting.
CREATIVE DIRECTION
The frame must launch a specific, observable beat from the shot rather than depict a character merely
standing, posing, or performing in place. Identify the visual hook, the subject's physical action or
interaction with a prop/environment, and the changed end-state the video should build toward. Vary the
shot scale, angle, foreground/background relationship, lighting accent, or screen direction from adjacent
shots when the storyboard allows it. Keep the camera setup stable during the shot, but do not confuse
stable framing with static subject behavior. Honor low-MP close/medium-close guidance and all continuity
constraints.
"""
        elif task["task_type"] == "generation_prompt":
            contract_guidance = """
GENERATION-PROMPT CONTRACT
Write for the actual rendered opening/closing scene-frame artifacts supplied to this turn. In content
return prompt, shot_id, scene_frame_artifact_ids, and acceptance_criteria. The prompt must specify visible
action, intentional camera behavior, continuity, and unwanted behavior. Do not redesign the storyboard and
do not repeat lyrics for lip-sync shots.
CREATIVE ACTION REQUIREMENT
Make the prompt cinematic and shot-specific, not a generic performance description. It must contain one
primary physical action, one concrete interaction or environmental response, one camera/framing choice,
and a visible progression or end-state within the shot. Use a distinctive visual hook tied to the lyric,
beat, or approved treatment, and avoid repeating the same pose, location beat, camera angle, or "performs
to camera" wording used by adjacent shots. Movement should be purposeful and physically plausible; the
camera may use a deliberate push, track, pan, orbit, or handheld drift when compatible with continuity,
but the subject must still carry the action. For lip-sync, let the supplied audio drive the mouth while
the prompt directs expressive body/performance action; for non-lip-sync shots explicitly keep the mouth
resting and prohibit singing/talking.
"""
        elif task["task_type"] == "user_intervention":
            intervention_input = task.get("input") or {}
            media_note = ""
            if intervention_input.get("agy_audio_carrier_path"):
                media_note = f"""
The bridge attached the verified audio carrier at:
{intervention_input['agy_audio_carrier_path']}
If the user asks about the song, use the media tool on that exact file. Do not claim to have listened
unless the media inspection succeeds. The preflight report is only a cross-check, not a substitute for
listening.
"""
            contract_guidance = f"""
USER-INTERVENTION CONTRACT
This is a real user turn, not a status acknowledgement. Answer the user's message using the saved
conversation context and the current production/task state. If the user asks for a change, make a
concrete executable plan and return actions for the bridge to apply. Do not merely say that the request
was received. Do not invent a completed generation or approval.

Return content as an object with this exact shape:
{{
  "reply": "clear answer to the user",
  "actions": [
    {{"type": "analyze_song_audio"}},
    {{"type": "update_shot", "shot_index": 1, "changes": {{"prompt": "..."}}}},
    {{"type": "regenerate_shot", "shot_index": 1, "prompt": "..."}},
    {{"type": "update_production_config", "changes": {{}}}},
    {{"type": "add_production_note", "note": "..."}},
    {{"type": "ask_user", "question": "..."}},
    {{"type": "pause"}},
    {{"type": "resume"}}
  ],
  "resume_policy": "resume|pause|await_user|preserve",
  "requires_user": false
}}
Use an empty actions array when the user only needs an explanation. Use whole-number seconds for shot
duration changes, and preserve the production's selected aspect ratio, Turbo profile, steps, and integer
megapixel rules unless the user explicitly changes them. Use the user's exact requested recipient and
do not delegate a request silently. The bridge validates and applies actions; never claim an action was
applied unless it is present in the returned actions. If the user supplied a complete prompt or exact
wording, preserve it verbatim in the executable action; do not silently substitute an earlier suggestion.
An acknowledgement without an executable action is not a completed change and must not be followed by
resume.
{media_note}
"""
        if task["task_type"] == "audio_analysis":
            audio_input = task.get("input") or {}
            carrier_path = str(audio_input.get("agy_audio_carrier_path") or "[carrier path missing]")
            preflight_path = str(audio_input.get("audio_preflight_path") or "[preflight path missing]")
            contract_guidance = f"""
AUDIO-ANALYSIS CONTRACT
Use view_file on this exact MP4 and analyze the actual production song in its audio track:
{carrier_path}
The visual track is intentionally black and irrelevant; listen to and analyze the audio track.
This is the same AGY media handoff used by the Legacy production flow. Do not inspect the original
WAV/MP3 directly, do not infer timing from the filename, lyrics, or FFprobe metadata, and do not
substitute metadata-only or lyrics-only estimates for listening.

Return content as an object with analysis_complete=true, source, duration_seconds, bpm, meter, genre,
beat_bar_grid, sections (non-empty timed start/end/type/energy rows), energy_changes, vocal_entrances,
breaths, instrumental_breaks, transitions, lyric_timeline, phrase_safe_cut_points, and notes.
If lyrics were supplied, cover every supplied line in order, including ad-libs. If lyrics were not
supplied, transcribe the audible vocal lines as accurately as possible and mark genuinely uncertain
words; do not invent lyrics. Identify vocal versus instrumental windows, breaths/pauses, natural cut
points, and the exact audio ranges suitable for lip-sync shots.

The response must include this proof object with the exact inspected path:
"media_inspection": {{"decoded_audio": true, "inspected_path": "{carrier_path}"}}
The bridge preflight report is at {preflight_path}; use it only to cross-check duration and stream facts.
If view_file cannot decode/listen to the carrier, return a blocking failure. Do not claim success.
"""
        return f"""You are seat {seat['label']} acting only as {task['role_id']} for this turn.

ROLE SKILL (project-native; read before acting)
The role instructions are installed here:
{role_file}
Read that SKILL.md with your file tool before performing this task. The bridge
intentionally does not paste the skill body into the request.

SEAT-SPECIFIC INSTRUCTIONS
{seat.get('custom_instructions') or 'None.'}

USER-SELECTED PROJECT SKILLS
{selected_skills}
Only these user-selected skills are active for this production. Read their
listed files when relevant; do not activate unselected specialist skills.

TASK CONTEXT
{json.dumps(payload, ensure_ascii=False, indent=2)}

{review_guidance}
{contract_guidance}

Return exactly one JSON object with keys summary, decision, content, issues, next_action, confidence, and requires_user.
decision must be one of approve, approve_with_notes, revise, or escalate. issues must be an array.
Do not advance workflow state. Do not claim to inspect media you did not actually inspect.
"""

    def _task_media_paths(self, production_id: str, task: dict[str, Any]) -> list[Path]:
        paths: list[Path] = []
        if task["task_type"] in {"technical_media_review", "av_sync_review"}:
            generation_task = next(
                (item for item in list_tasks(production_id)
                 if item["task_type"] == "video_generation"
                 and item["input"].get("shot_id") == task["input"].get("shot_id")),
                None,
            )
            delivered = deliverable_for_task(generation_task["id"]) if generation_task else None
            if delivered:
                for artifact_id in [delivered["payload"].get("video_artifact_id"), *delivered["payload"].get("review_frame_artifact_ids", [])]:
                    path = self._artifact_path(production_id, artifact_id)
                    if path:
                        paths.append(path)
            if task["task_type"] == "av_sync_review":
                production = get_production(production_id, private=True)
                if production and Path(production["song_path"]).is_file():
                    paths.append(Path(production["song_path"]))
        elif task["task_type"] == "final_media_review":
            artifact = next((item for item in reversed(list_artifacts(production_id, private=True)) if item.get("kind") == "final_video"), None)
            if artifact and Path(artifact["path"]).is_file():
                paths.append(Path(artifact["path"]))
        elif task["task_type"] in {"scene_frame_design", "generation_prompt"}:
            shot_id = task.get("input", {}).get("shot_id")
            if shot_id:
                shot = self._shot(production_id, str(shot_id))
                for reference_id in shot.get("reference_ids", []):
                    reference = get_reference(production_id, reference_id, private=True)
                    if reference and Path(reference["path"]).is_file():
                        paths.append(Path(reference["path"]))
                if task["task_type"] == "generation_prompt":
                    render_task = next((item for item in list_tasks(production_id) if item["task_type"] == "scene_frame_render" and item["input"].get("shot_id") == shot_id), None)
                    rendered = deliverable_for_task(render_task["id"]) if render_task else None
                    if rendered:
                        for key in ("opening_artifact_id", "closing_artifact_id"):
                            path = self._artifact_path(production_id, rendered["payload"].get(key))
                            if path:
                                paths.append(path)
        unique: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            resolved = str(path.resolve())
            if resolved not in seen:
                seen.add(resolved)
                unique.append(path)
        return unique


council_controller = CouncilController()
