from __future__ import annotations

import asyncio
import json
import re
import secrets
import shutil
import uuid
from pathlib import Path
from typing import Any

from .agents import AgentResult, discover_codex_models, process_manager
from .config import INPUT, PRODUCTIONS, PRODUCTION_CONCURRENCY
from .db import connect, get_job, next_position, now_iso
from .generation import normalize_generation_settings
from .media import (assemble_clips, attach_song, extract_last_frame, extract_review_frames,
                    prepare_audio_segment, probe_audio_metadata)
from .production_db import (add_artifact, add_decision, add_event, add_message, add_reference,
                            create_shot_attempt, get_production, list_messages, list_shots,
                            get_reference, list_references, recover_productions, replace_shot_plan, resolve_decision,
                            update_production, update_shot, update_shot_attempt)
from .skill_catalog import selected_skill_context


class ProductionOrchestrator:
    """Persistent user/Codex/AGY production coordinator.

    The orchestrator intentionally owns all side effects. Agents only return
    structured creative decisions; they cannot submit ComfyUI jobs or mutate
    application state directly.
    """

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.wake = asyncio.Event()
        self.stopping = False
        self.production_tasks: dict[str, asyncio.Task] = {}
        self.current_jobs: dict[str, str] = {}
        self.queue_worker: Any | None = None

    @property
    def active_productions(self) -> list[str]:
        return list(self.production_tasks)

    @property
    def current_production(self) -> str | None:
        """Compatibility field for older clients; all IDs are in active_productions."""
        return next(iter(self.production_tasks), None)

    @property
    def current_job(self) -> str | None:
        """Compatibility field for older clients; jobs are tracked per production."""
        return next(iter(self.current_jobs.values()), None)

    def bind_queue(self, worker: Any) -> None:
        self.queue_worker = worker

    def start(self) -> None:
        recover_productions()
        self.task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        self.stopping = True
        self.wake.set()
        await asyncio.gather(
            *(process_manager.cancel(production_id) for production_id in list(self.production_tasks)),
            return_exceptions=True,
        )
        for task in self.production_tasks.values():
            task.cancel()
        if self.task:
            await self.task

    def notify(self) -> None:
        self.wake.set()

    async def cancel_agents(self, production_id: str) -> None:
        await process_manager.cancel(production_id)

    async def cancel_generation(self, production_id: str) -> bool:
        job_id = self.current_jobs.get(production_id)
        if not job_id or not self.queue_worker:
            return False
        return bool(await self.queue_worker.cancel(job_id))

    def _next(self, excluded: set[str] | None = None) -> dict[str, Any] | None:
        from .db import connect
        excluded = excluded or set()
        with connect() as db:
            if excluded:
                placeholders = ",".join("?" for _ in excluded)
                row = db.execute(
                    f"SELECT id FROM productions WHERE status='queued' AND id NOT IN ({placeholders}) "
                    "ORDER BY updated_at LIMIT 1", tuple(excluded),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT id FROM productions WHERE status='queued' ORDER BY updated_at LIMIT 1"
                ).fetchone()
        return get_production(row["id"], private=True) if row else None

    async def loop(self) -> None:
        while not self.stopping:
            for production_id, task in list(self.production_tasks.items()):
                if task.done():
                    self.production_tasks.pop(production_id, None)
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        # _run_production records failures; consuming the task
                        # exception here prevents noisy unhandled-task warnings.
                        pass
            while len(self.production_tasks) < PRODUCTION_CONCURRENCY and not self.stopping:
                production = self._next(set(self.production_tasks))
                if not production:
                    break
                production_id = production["id"]
                update_production(
                    production_id, status="running", error=None,
                    started_at=production.get("started_at") or now_iso(),
                )
                add_event(production_id, "production.started", {"stage": production["stage"]})
                self.production_tasks[production_id] = asyncio.create_task(
                    self._run_production(production_id), name=f"production-{production_id}",
                )
            if not self.production_tasks:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass
                continue
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
        if self.production_tasks:
            await asyncio.gather(*self.production_tasks.values(), return_exceptions=True)
        self.production_tasks.clear()

    async def _run_production(self, production_id: str) -> None:
        try:
            await self._run_stage(production_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            current = get_production(production_id, private=True)
            if current and current.get("stop_requested"):
                update_production(production_id, status="stopped", stop_requested=0, error=None)
                add_message(production_id, "system", "all", "status", "Production stopped. The checkpoint was preserved.")
            elif current and current.get("pause_requested"):
                update_production(production_id, status="paused", pause_requested=0, error=None)
                add_message(production_id, "system", "all", "status", "Production paused at a safe checkpoint.")
            else:
                update_production(production_id, status="failed", error=str(exc)[:8000])
                add_message(production_id, "system", "user", "error", f"Production stage failed: {exc}")
                add_event(production_id, "production.failed", {"error": str(exc)[:2000]})
        finally:
            self.current_jobs.pop(production_id, None)
            self.wake.set()

    def _folder(self, production_id: str) -> Path:
        folder = PRODUCTIONS / production_id
        for child in ("intake", "analysis", "treatment", "references", "shots", "assembly", "logs", "agent-context"):
            (folder / child).mkdir(parents=True, exist_ok=True)
        return folder

    def _base_context(self, production: dict[str, Any]) -> str:
        skills = selected_skill_context(production.get("skills", []))
        references = list_references(production["id"], private=True)
        reference_context = json.dumps([
            {
                "id": item["id"], "kind": item["kind"], "name": item["name"],
                "path": item["path"], "notes": item.get("notes", ""),
            }
            for item in references
        ], ensure_ascii=False, indent=2)
        user_messages = [
            message for message in list_messages(production["id"])
            if message["participant"] == "user" and message["kind"] in {"intervention", "decision", "control"}
        ][-20:]
        instructions = "\n".join(f"- {message['content']}" for message in user_messages)
        return f"""
You are one member of a professional production council consisting of the User, Codex, and AGY.
The user is the creative owner and final authority. Codex and AGY are equal co-producers.
Do not execute commands, submit generation jobs, or modify files. Return only the required structured JSON.

Production title: {production['title']}
Pipeline: {production['pipeline']}
Participation: {production['participation_mode']}
Continuity: {production['continuity_mode']}
Concept: {production['concept']}
Lyrics:
{production['lyrics']}
Song file: {production['song_path']}

User-provided and approved production references (optional; use these as source constraints,
and fill only missing categories with new references):
{reference_context or '(none; develop the visual bible from the user description)'}

Latest user instructions and decisions (highest priority):
{instructions or '(none beyond intake)'}

Enabled production skills:
{skills or '(none)'}
""".strip()

    @staticmethod
    def _reference_image_paths(production: dict[str, Any]) -> list[Path]:
        return [
            Path(item["path"])
            for item in list_references(production["id"], private=True)
            if item.get("kind") == "image" and Path(item["path"]).is_file()
        ]

    async def _codex(self, production: dict[str, Any], request: str, images: list[Path] | None = None) -> AgentResult:
        runtime = production.get("codex_runtime") or "codex"
        images = self._reference_image_paths(production) if images is None else images
        result = await process_manager.invoke(
            runtime, "codex", production["id"], self._base_context(production) + "\n\nTASK:\n" + request,
            production["codex_model"], production["codex_effort"], production.get("codex_session_id"), images,
        )
        update_production(production["id"], codex_session_id=result.session_id)
        add_message(production["id"], "codex", "all", "agent", result.content.get("summary", ""), {
            "model": result.model, "effort": result.effort, "session_id": result.session_id,
            "runtime": runtime,
            "decision": result.content.get("decision"), "next_action": result.content.get("next_action"),
            "content": result.content.get("content"), "issues": result.content.get("issues", []),
        })
        return result

    async def _agy(self, production: dict[str, Any], request: str, images: list[Path] | None = None) -> AgentResult:
        runtime = production.get("agy_runtime") or "agy"
        images = self._reference_image_paths(production) if images is None else images
        result = await process_manager.invoke(
            runtime, "agy", production["id"], self._base_context(production) + "\n\nTASK:\n" + request,
            production["agy_model"], production["agy_effort"], production.get("agy_session_id"), images,
        )
        update_production(production["id"], agy_session_id=result.session_id)
        add_message(production["id"], "agy", "all", "agent", result.content.get("summary", ""), {
            "model": result.model, "effort": result.effort, "session_id": result.session_id,
            "runtime": runtime,
            "decision": result.content.get("decision"), "next_action": result.content.get("next_action"),
            "content": result.content.get("content"), "issues": result.content.get("issues", []),
        })
        return result

    async def _media_agent(self, production: dict[str, Any], request: str) -> AgentResult:
        """Use a seat backed by AGY for real audio/video inspection."""
        if (production.get("agy_runtime") or "agy") == "agy":
            return await self._agy(production, request)
        if (production.get("codex_runtime") or "codex") == "agy":
            return await self._codex(production, request)
        raise RuntimeError("Music-video production requires at least one producer using the AGY runtime")

    async def _other_agent(
        self, production: dict[str, Any], media_result: AgentResult, request: str,
        images: list[Path] | None = None,
    ) -> AgentResult:
        return await (self._codex(production, request, images) if media_result.participant == "agy"
                      else self._agy(production, request, images))

    def _checkpoint(self, production_id: str) -> None:
        production = get_production(production_id, include_messages=True)
        if not production:
            return
        folder = self._folder(production_id)
        (folder / "state.json").write_text(json.dumps(production, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [f"# {production['title']} production transcript", ""]
        for message in production.get("messages", []):
            lines.append(f"## {message['sequence']}. {message['participant'].upper()} → {message['recipient']}")
            lines.append("")
            lines.append(message["content"])
            lines.append("")
        (folder / "production_transcript.md").write_text("\n".join(lines), encoding="utf-8")

    def _control_requested(self, production_id: str) -> bool:
        current = get_production(production_id, private=True)
        if not current:
            return True
        if current.get("stop_requested"):
            update_production(production_id, status="stopped", stop_requested=0, finished_at=now_iso())
            add_message(production_id, "system", "all", "status", "Production stopped. The checkpoint was preserved.")
            self._checkpoint(production_id)
            return True
        if current.get("pause_requested"):
            update_production(production_id, status="paused", pause_requested=0)
            add_message(production_id, "system", "all", "status", "Production paused at a safe checkpoint.")
            self._checkpoint(production_id)
            return True
        return False

    @staticmethod
    def _content_dict(result: AgentResult) -> dict[str, Any]:
        value = result.content.get("content")
        return value if isinstance(value, dict) else {}

    @classmethod
    def _find_shots(cls, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            shots = value.get("shots")
            if isinstance(shots, list) and shots and all(isinstance(item, dict) for item in shots):
                return shots
            for nested in value.values():
                found = cls._find_shots(nested)
                if found:
                    return found
        if isinstance(value, list):
            for nested in value:
                found = cls._find_shots(nested)
                if found:
                    return found
        return []

    @classmethod
    def _find_reference_specs(cls, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            references = value.get("references")
            if isinstance(references, list):
                return [item for item in references if isinstance(item, dict)]
            for nested in value.values():
                found = cls._find_reference_specs(nested)
                if found:
                    return found
        if isinstance(value, list):
            for nested in value:
                found = cls._find_reference_specs(nested)
                if found:
                    return found
        return []

    async def _generate_reference_stills(
        self, production: dict[str, Any], package: dict[str, Any], provider: str = "auto",
    ) -> list[dict[str, Any]]:
        specs = self._find_reference_specs(package)
        if not specs:
            raise RuntimeError("The approved reference package contains no executable references array")
        existing_images = [item for item in list_references(production["id"], private=True) if item["kind"] == "image"]
        source_images = [Path(item["path"]) for item in existing_images if Path(item["path"]).is_file()]
        existing_by_name = {
            str(item["name"]).strip().casefold(): item for item in existing_images if item.get("name")
        }
        available_slots = max(0, 9 - len(existing_images))
        if not available_slots:
            return existing_images
        generated: list[dict[str, Any]] = []
        image_model = production["codex_model"] if production.get("codex_runtime", "codex") == "codex" else discover_codex_models()[0]["id"]
        image_effort = production["codex_effort"] if production.get("codex_runtime", "codex") == "codex" else "high"
        for index, spec in enumerate(specs, 1):
            if len(generated) >= available_slots:
                break
            kind = str(spec.get("kind") or "image").lower()
            if kind not in {"image", "still", "character", "location", "vehicle", "prop"}:
                continue
            name = str(spec.get("name") or f"Reference {index}").strip()[:160]
            existing = existing_by_name.get(name.casefold())
            if existing:
                generated.append(existing)
                continue
            image_prompt = str(spec.get("image_prompt") or spec.get("prompt") or spec.get("description") or "").strip()
            if not image_prompt:
                continue
            accepted_path: Path | None = None
            review_summary = ""
            for attempt in range(1, 3):
                path = self._folder(production["id"]) / "references" / "generated" / f"reference_{index:02d}_attempt_{attempt}.png"
                if provider == "auto":
                    await process_manager.generate_reference_image(
                        production["id"], image_prompt, path, image_model, image_effort,
                        source_images=source_images,
                    )
                else:
                    await process_manager.generate_reference_image(
                        production["id"], image_prompt, path, image_model, image_effort,
                        provider=provider, agy_model=production["agy_model"],
                        agy_effort=production["agy_effort"], source_images=source_images,
                    )
                refreshed = get_production(production["id"], private=True) or production
                agy = await self._agy(refreshed, f"""
Inspect this generated reference still as a practical human viewer. Check recurring identity usability,
composition for I2V, obvious anatomy/glitches, and only clearly readable gibberish on prominent signs,
vehicle badges or license plates. Do not reject tiny, blurred, incidental, or unreadable background marks.
Reference name: {name}
Intended prompt: {image_prompt}
Image path: {path}
Return APPROVE or REVISE and concrete corrections.
""", [path])
                refreshed = get_production(production["id"], private=True) or refreshed
                codex = await self._codex(refreshed, f"""
Review the same reference image and AGY's findings as equal co-producer. Approve usable work; request a
revision only for an obvious defect that would harm continuity or generation. If revising, return a
corrected_prompt in content.
AGY review: {json.dumps(agy.content, ensure_ascii=False)}
""", [path])
                if self._agent_approved(agy) and self._agent_approved(codex):
                    accepted_path = path
                    review_summary = str(codex.content.get("summary") or agy.content.get("summary") or "Jointly approved")
                    break
                corrected = self._content_dict(codex).get("corrected_prompt")
                if isinstance(corrected, str) and corrected.strip():
                    image_prompt = corrected.strip()
            if not accepted_path:
                raise RuntimeError(f"Reference image '{name}' did not pass joint Codex + AGY review")
            comfy_name = f"production_ref_{uuid.uuid4().hex}.png"
            comfy_path = INPUT / comfy_name
            shutil.copy2(accepted_path, comfy_path)
            reference = add_reference(
                production["id"], "image", name, str(accepted_path), str(comfy_path), comfy_name,
                json.dumps({"prompt": image_prompt, "review": review_summary}, ensure_ascii=False),
            )
            generated.append(reference)
        if not generated:
            raise RuntimeError("The reference package did not contain any generatable image specifications")
        return generated

    async def generate_manual_reference(
        self, production_id: str, name: str, prompt: str, provider: str = "auto",
    ) -> dict[str, Any]:
        production = get_production(production_id, private=True)
        if not production:
            raise KeyError("Production not found")
        generated = await self._generate_reference_stills(production, {
            "references": [{"name": name, "kind": "image", "image_prompt": prompt}],
        }, provider=provider)
        reference = generated[-1]
        add_message(
            production_id, "system", "all", "status",
            f"Manual reference image generated and jointly approved: {reference['name']}.",
            {"reference_id": reference["id"], "provider": provider},
        )
        self._checkpoint(production_id)
        return reference

    @staticmethod
    def _recommended_megapixels(duration: float) -> float:
        if duration <= 5:
            return 1.5
        if duration <= 7:
            return 1.0
        if duration <= 8:
            return 1.0
        if duration <= 10:
            return 0.7
        if duration <= 11:
            return 0.6
        return 0.5

    def _normalize_shots(
        self, raw: list[dict[str, Any]], continuity_mode: str,
        references: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if not raw:
            raise RuntimeError("The joint prompt package did not contain a shots array")
        references = references or []
        reference_by_id = {str(item["id"]): item for item in references}
        reference_by_name = {
            str(item["name"]).strip().casefold(): item for item in references if item.get("name")
        }

        def resolve_reference_ids(item: dict[str, Any], key: str = "reference_ids") -> list[str]:
            values: list[Any] = []
            raw_ids = item.get(key)
            if isinstance(raw_ids, list):
                values.extend(raw_ids)
            selectors = item.get("reference_names") or item.get("references")
            if isinstance(selectors, (str, dict)):
                selectors = [selectors]
            if isinstance(selectors, list):
                values.extend(selectors)
            resolved: list[str] = []
            for value in values:
                candidate = value.get("id") if isinstance(value, dict) else value
                name = value.get("name") if isinstance(value, dict) else value
                match = reference_by_id.get(str(candidate)) or reference_by_name.get(str(name).strip().casefold())
                if match and match["id"] not in resolved:
                    resolved.append(match["id"])
            return resolved

        result = []
        timeline_cursor = 0.0
        for index, item in enumerate(raw, 1):
            prompt = str(item.get("prompt") or item.get("video_prompt") or "").strip()
            if not prompt:
                raise RuntimeError(f"Shot {index} has no video prompt")
            try:
                duration = min(15.0, max(0.5, float(item.get("duration", 5))))
            except (TypeError, ValueError):
                duration = 5.0
            try:
                megapixels = float(item.get("megapixels", self._recommended_megapixels(duration)))
            except (TypeError, ValueError):
                megapixels = self._recommended_megapixels(duration)
            megapixels = min(2.0, max(0.1, megapixels))
            continuity = str(item.get("continuity") or item.get("transition") or "").lower()
            sequential = continuity in {"sequential", "continue", "continuation", "last_frame"}
            if continuity_mode == "sequential":
                sequential = index > 1
            elif continuity_mode == "hard_cut":
                sequential = False
            requested_mode = str(item.get("mode") or item.get("visual_mode") or "").lower()
            reference_ids = resolve_reference_ids(item)
            # Production intentionally does not use R2V yet. If the agents
            # mention it, treat the selected image reference as an I2V
            # opening frame instead of silently routing the shot to R2V.
            if requested_mode in {"reference", "r2v", "ref2v"}:
                mode = "opening" if reference_ids else "text"
            elif requested_mode in {"opening", "i2v", "image_to_video"}:
                mode = "opening"
            else:
                has_image_reference = any(
                    reference_by_id.get(reference_id, {}).get("kind") == "image"
                    for reference_id in reference_ids
                )
                mode = "opening" if has_image_reference or (sequential and index > 1) else "text"

            raw_audio_mode = str(item.get("audio_mode") or item.get("audio") or "silent").lower()
            audio_mode = "lip_sync" if raw_audio_mode in {"lip_sync", "lipsync", "lip-sync", "dialogue"} else "silent"
            raw_audio_source = str(item.get("audio_source") or "song").lower()
            audio_source = "reference" if raw_audio_source in {"reference", "uploaded", "ref"} else "song"
            try:
                audio_start = max(0.0, float(item.get("audio_start", item.get("song_start", timeline_cursor))))
            except (TypeError, ValueError):
                audio_start = timeline_cursor
            try:
                audio_duration = min(60.0, max(0.5, float(item.get("audio_duration", duration))))
            except (TypeError, ValueError):
                audio_duration = duration
            audio_reference_value = item.get("audio_reference_id") or item.get("audio_reference")
            audio_reference = reference_by_id.get(str(audio_reference_value)) or reference_by_name.get(str(audio_reference_value).strip().casefold())
            audio_reference_id = audio_reference["id"] if audio_reference and audio_reference.get("kind") == "audio" else None
            timeline_cursor = max(timeline_cursor, audio_start + audio_duration)
            try:
                steps = int(item.get("steps") or (4 if audio_mode == "lip_sync" else 6))
            except (TypeError, ValueError):
                steps = 4 if audio_mode == "lip_sync" else 6
            result.append({
                "title": str(item.get("title") or item.get("name") or f"Shot {index}"),
                "prompt": prompt, "mode": mode,
                "continuity": "sequential" if sequential else "hard_cut",
                "audio_mode": audio_mode, "audio_source": audio_source,
                "audio_start": audio_start, "audio_duration": audio_duration,
                "audio_reference_id": audio_reference_id,
                "duration": duration, "megapixels": megapixels,
                "aspect_ratio": str(item.get("aspect_ratio") or "16:9"),
                "steps": steps,
                "engine": "turbo", "turbo_profile": "v1",
                "reference_ids": reference_ids,
            })
        return result

    def _queue_job(self, shot: dict[str, Any], opening_frame: Path | None) -> str:
        if not self.queue_worker:
            raise RuntimeError("The production orchestrator is not connected to the ComfyUI queue")
        production = get_production(shot["production_id"], private=True)
        if not production:
            raise RuntimeError("The production no longer exists")
        visual_mode = shot["mode"]
        audio_mode = shot.get("audio_mode") or "silent"
        if audio_mode not in {"silent", "lip_sync"}:
            raise RuntimeError(f"Unsupported production audio mode: {audio_mode}")
        if audio_mode == "lip_sync" and visual_mode == "reference":
            raise RuntimeError(
                "Production R2V + lip-sync is reserved for a future workflow. "
                "Use T2V or I2V for a lip-sync shot."
            )
        job_mode = "lip_sync" if audio_mode == "lip_sync" else visual_mode
        settings = normalize_generation_settings(
            job_mode, engine=shot["engine"], steps=int(shot["steps"]),
            megapixels=float(shot["megapixels"]), aspect_ratio=shot["aspect_ratio"],
            turbo_profile=shot["turbo_profile"],
        )
        job_id = uuid.uuid4().hex
        now = now_iso()
        references = [
            reference for reference_id in shot.get("reference_ids", [])
            if (reference := get_reference(shot["production_id"], reference_id, private=True))
        ]
        if shot["mode"] == "opening" and not opening_frame:
            image_reference = next((item for item in references if item["kind"] == "image"), None)
            if image_reference:
                opening_frame = Path(image_reference["comfy_path"])
        if shot["mode"] == "reference" and not references:
            raise RuntimeError(f"{shot['title']} is R2V but has no assigned references")
        audio_path = None
        audio_name = None
        audio_reference = next(
            (item for item in references if item["id"] == shot.get("audio_reference_id") and item["kind"] == "audio"),
            None,
        )
        if not audio_reference and shot.get("audio_source") == "reference":
            audio_reference = next((item for item in references if item["kind"] == "audio"), None)
        if audio_mode == "lip_sync":
            if shot.get("audio_source") == "reference":
                if not audio_reference:
                    raise RuntimeError(f"{shot['title']} uses a reference audio source but no audio reference is assigned")
                source_audio = Path(audio_reference["path"])
            else:
                source_audio = Path(production["song_path"])
            prepared = INPUT / f"production_{shot['production_id']}_shot_{shot['shot_index']:03d}_audio.wav"
            prepare_audio_segment(
                source_audio, prepared, float(shot.get("audio_start") or 0),
                float(shot.get("audio_duration") or shot["duration"]),
            )
            audio_path, audio_name = str(prepared), prepared.name
        first_path = str(opening_frame) if opening_frame else None
        first_name = opening_frame.name if opening_frame else None
        image_names = [item["comfy_name"] for item in references if item["kind"] == "image"]
        video_names = [item["comfy_name"] for item in references if item["kind"] == "video"]
        input_reference = next((item for item in references if item["kind"] == "image"), None)
        with connect() as db:
            db.execute(
                """INSERT INTO jobs
                   (id,prompt,mode,duration,audio_start,engine,turbo_profile,encoder,steps,width,height,
                    megapixels,aspect_ratio,seed,status,position,no_audio,input_path,input_name,
                    reference_images_json,reference_videos_json,reference_audio_path,reference_audio_name,
                    first_frame_path,first_frame_name,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id, shot["prompt"], job_mode, shot["duration"], 0,
                    settings.engine, settings.turbo_profile, settings.encoder, settings.steps, settings.width,
                    settings.height, settings.megapixels, settings.aspect_ratio,
                    str(secrets.randbits(64)), next_position(db), int(audio_mode != "lip_sync"),
                    input_reference["comfy_path"] if input_reference else None,
                    input_reference["comfy_name"] if input_reference else None,
                    json.dumps(image_names), json.dumps(video_names),
                    audio_path, audio_name,
                    first_path, first_name, now, now,
                ),
            )
        self.queue_worker.notify()
        add_event(shot["production_id"], "shot.queued", {"shot_id": shot["id"], "job_id": job_id})
        return job_id

    async def _wait_for_job(self, production_id: str, job_id: str) -> dict[str, Any]:
        self.current_jobs[production_id] = job_id
        previous_state: tuple[Any, ...] | None = None
        try:
            while True:
                job = get_job(job_id, public=False)
                if not job:
                    raise RuntimeError("The queued ComfyUI job disappeared")
                state = (job["status"], job["phase"], job["step"], job["total_steps"])
                if state != previous_state:
                    add_event(production_id, "shot.progress", {
                        "job_id": job_id, "status": job["status"], "phase": job["phase"],
                        "progress": job["progress"], "step": job["step"], "total_steps": job["total_steps"],
                    })
                    previous_state = state
                if job["status"] == "completed":
                    return job
                if job["status"] in {"failed", "canceled"}:
                    raise RuntimeError(job.get("error") or f"Generation {job['status']}")
                await asyncio.sleep(5)
        finally:
            self.current_jobs.pop(production_id, None)

    @staticmethod
    def _agent_approved(result: AgentResult) -> bool:
        text = " ".join(str(result.content.get(key, "")) for key in ("decision", "next_action", "summary")).lower()
        negative = ("reject", "regenerate", "retry", "fail", "not approved", "needs correction")
        return not any(token in text for token in negative) and any(token in text for token in ("approve", "accept", "pass", "valid"))

    @staticmethod
    def _defect_key(*results: AgentResult) -> str:
        issues: list[str] = []
        for result in results:
            for issue in result.content.get("issues", []):
                if isinstance(issue, dict):
                    issues.append(str(issue.get("code") or issue.get("issue") or issue.get("summary") or ""))
                else:
                    issues.append(str(issue))
        normalized = re.sub(r"\W+", "-", "|".join(issues).lower()).strip("-")
        return normalized[:240] or "unapproved-quality-review"

    async def _review_shot(
        self, production: dict[str, Any], shot: dict[str, Any], video: Path, frames: list[Path],
        previous_video: Path | None,
    ) -> tuple[AgentResult, AgentResult]:
        previous = str(previous_video) if previous_video else "none (hard cut or first shot)"
        agy = await self._media_agent(production, f"""
Inspect the actual generated MP4 at {video} and every extracted frame in {video.parent / 'review_frames'}.
Planned shot: {json.dumps(shot, ensure_ascii=False)}
Previous accepted clip: {previous}
Judge real motion (no sliding/backwards car movement or frozen walking), anatomy, glitches, lyric/story fit,
identity/location continuity when required, camera direction and cut compatibility. Check visible text only when
it is plainly readable to a normal viewer on a car, plate, sign, billboard, or garment; do not reject tiny or
incidental texture. Return APPROVE or REGENERATE and precise defects.
""")
        production = get_production(production["id"], private=True) or production
        codex = await self._other_agent(production, agy, f"""
Act as the equal co-producer and review the attached sampled frames together with AGY's full-video analysis.
Planned shot: {json.dumps(shot, ensure_ascii=False)}
AGY review: {json.dumps(agy.content, ensure_ascii=False)}
Approve only if the actual shot is usable in the music video. If regeneration is needed, produce a corrected
complete video prompt in content.corrected_prompt and identify the same concrete defects. Do not over-police
text that a normal viewer cannot read.
""", images=frames)
        return agy, codex

    async def _run_stage(self, production_id: str) -> None:
        production = get_production(production_id, private=True)
        if not production:
            return
        self._folder(production_id)
        stage = production["stage"]

        if stage == "song_analysis":
            add_message(production_id, "system", "all", "status", "AGY is analyzing the song and lyric timing.")
            try:
                audio_metadata = await asyncio.to_thread(probe_audio_metadata, Path(production["song_path"]))
            except (RuntimeError, OSError) as exc:
                audio_metadata = {"preflight_error": str(exc)}
            analysis_request = f"""
Analyze the actual song file and lyrics. Return duration, BPM and confidence, meter, genre, sections,
energy curve, vocal entrances, instrumental breaks, transitions, estimated timestamped lyric map,
and concrete visual opportunities. Mark uncertain timing as estimated. Put the full analysis in content.
The bridge already performed this basic audio preflight:
{json.dumps(audio_metadata, ensure_ascii=False)}
Use your media/audio inspection capability if available, but do not run shell commands or ask for command
permission; use the provided file path and metadata. Put the full analysis in content.
"""
            try:
                analysis = await self._media_agent(production, analysis_request)
            except RuntimeError as exc:
                if "permission check failed" not in str(exc).lower():
                    raise
                fallback = {
                    "summary": "AGY shell inspection was unavailable; continuing with backend audio metadata.",
                    "decision": "continue",
                    "next_action": "continue",
                    "content": {
                        "audio_metadata": audio_metadata,
                        "analysis_limitation": "BPM, genre, sections, and lyric timing still require agent/media review.",
                    },
                    "issues": [{"type": "agent_permission", "message": str(exc)[-1200:]}],
                    "requires_user": False,
                }
                analysis = AgentResult(
                    "agy", fallback, "backend audio preflight fallback", None,
                    production.get("agy_model", ""), production.get("agy_effort", ""),
                )
                add_message(
                    production_id, "system", "all", "status",
                    "AGY could not inspect the song through its media tools; backend audio metadata was preserved and the pipeline continued.",
                    {"fallback": True, "reason": str(exc)[-1200:]},
                )
            (self._folder(production_id) / "analysis" / "song_analysis.json").write_text(
                json.dumps(analysis.content, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            update_production(production_id, stage="treatment_consultation", progress=0.2)
            self._checkpoint(production_id)
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True)
            stage = "treatment_consultation"

        if stage == "treatment_consultation":
            analysis_path = self._folder(production_id) / "analysis" / "song_analysis.json"
            analysis_text = analysis_path.read_text(encoding="utf-8") if analysis_path.exists() else "{}"
            codex = await self._codex(production, f"""
Using AGY's song analysis below, propose a professional treatment, visual language, character/location bible,
continuity map, timestamped storyboard, shot durations, I2V/T2V choice, camera movement, transitions,
megapixel policy, and acceptance criteria. Keep the story connected to the lyrics.
The production context includes optional user-provided references. Treat those files as the user's visual
constraints and use them wherever relevant; invent only the missing characters, locations, props, or wardrobe.
AGY analysis: {analysis_text}
""")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True)
            agy = await self._media_agent(production, f"""
Critique Codex's proposed treatment as an equal co-producer. Check lyric timing, pacing, visual variety,
character continuity, camera physics, backwards motion risk, obvious text/signage risk, and whether enough
story action occurs. Return concrete revisions and approval status.
Codex proposal: {json.dumps(codex.content, ensure_ascii=False)}
""")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True)
            final = await self._codex(production, f"""
Respond point by point to AGY and produce the revised joint treatment and storyboard. Preserve useful
disagreement in issues. The user is final authority. Return the complete decision package in content.
Original proposal: {json.dumps(codex.content, ensure_ascii=False)}
AGY critique: {json.dumps(agy.content, ensure_ascii=False)}
""")
            production = get_production(production_id, private=True)
            confirmation = await self._agy(production, f"""
Confirm or counter Codex's revised treatment as equal co-producer. Approve unless a concrete unresolved
timing, continuity, story, or feasibility defect remains.
Revised treatment: {json.dumps(final.content, ensure_ascii=False)}
""")
            if self._control_requested(production_id):
                return
            treatment_path = self._folder(production_id) / "treatment" / "joint_treatment.json"
            treatment_package = {"codex_draft": codex.content, "agy_critique": agy.content,
                                 "codex_revision": final.content, "agy_confirmation": confirmation.content}
            treatment_path.write_text(json.dumps(treatment_package, ensure_ascii=False, indent=2), encoding="utf-8")
            decision = add_decision(
                production_id, "treatment_consultation", "Joint treatment and storyboard",
                final.content.get("summary", final.content.get("decision", "Codex and AGY completed the treatment consultation.")),
                {"artifact": "treatment/joint_treatment.json", **treatment_package},
            )
            if production["participation_mode"] == "autonomous":
                from .production_db import resolve_decision
                resolve_decision(production_id, decision["id"], "approved", "codex+agy", "Autonomous joint approval")
                update_production(production_id, status="queued", stage="reference_development", progress=0.35)
            else:
                update_production(production_id, status="awaiting_user", stage="treatment_review", progress=0.35)
                add_message(production_id, "system", "user", "decision", "Codex and AGY finished the joint treatment. Review their decision before references are developed.")
            self._checkpoint(production_id)
            return

        if stage == "reference_development":
            treatment_path = self._folder(production_id) / "treatment" / "joint_treatment.json"
            treatment = treatment_path.read_text(encoding="utf-8") if treatment_path.exists() else "{}"
            codex = await self._codex(production, f"""
Create detailed original reference briefs for every recurring character, location, vehicle, prop, wardrobe
and continuity anchor in this treatment: {treatment}
The top-level content object MUST include a `references` array. Every item must include `name`, `kind`,
`description`, and a complete `image_prompt` for a polished 16:9 still. Avoid visible text unless the exact
text is narratively required. The production context lists optional user-provided reference files. Preserve
their identity, wardrobe, location, and prop details; do not recreate a user-supplied reference as a duplicate.
Create new reference briefs only for categories the user did not provide. Mark user files as source references
in the returned package so the later shot plan can select them by name.
""")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True)
            agy = await self._agy(production, f"Review these reference briefs for identity consistency, composition usability, visible text risk and shot coverage. Suggest precise corrections: {json.dumps(codex.content, ensure_ascii=False)}")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True)
            revision = await self._codex(production, f"""
Apply AGY's concrete corrections and return the complete revised reference package. The top-level content
object MUST preserve the full executable `references` array with name, kind, description and image_prompt.
AGY review: {json.dumps(agy.content, ensure_ascii=False)}
Original: {json.dumps(codex.content, ensure_ascii=False)}
""")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True)
            confirmation = await self._agy(production, f"Confirm or counter the revised reference package. Approve unless a concrete identity, coverage, or visible-text defect remains: {json.dumps(revision.content, ensure_ascii=False)}")
            if self._control_requested(production_id):
                return
            package = {"codex_draft": codex.content, "agy_review": agy.content,
                       "codex_revision": revision.content, "agy_confirmation": confirmation.content}
            (self._folder(production_id) / "references" / "reference_plan.json").write_text(
                json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            decision = add_decision(production_id, "reference_development", "Reference development plan",
                                    confirmation.content.get("summary", "Reference briefs are ready for user review."),
                                    {"artifact": "references/reference_plan.json", **package})
            if production["participation_mode"] == "autonomous":
                from .production_db import resolve_decision
                resolve_decision(production_id, decision["id"], "approved", "codex+agy", "Autonomous joint approval")
                update_production(production_id, status="queued", stage="reference_generation", progress=0.5)
            else:
                update_production(production_id, status="awaiting_user", stage="reference_review", progress=0.5)
            self._checkpoint(production_id)
            return

        if stage == "reference_generation":
            plan_path = self._folder(production_id) / "references" / "reference_plan.json"
            if not plan_path.is_file():
                raise RuntimeError("The approved reference plan is missing")
            package = json.loads(plan_path.read_text(encoding="utf-8"))
            approved = package.get("codex_revision") if isinstance(package, dict) else None
            if not isinstance(approved, dict):
                raise RuntimeError("The approved reference plan has no executable Codex revision")
            generated = await self._generate_reference_stills(production, approved)
            add_message(production_id, "system", "all", "status",
                        f"Generated and jointly approved {len(generated)} production reference stills.")
            update_production(production_id, status="queued", stage="prompt_consultation", progress=0.55)
            self._checkpoint(production_id)
            return

        if stage == "prompt_consultation":
            codex = await self._codex(production, """
Create the complete shot-by-shot MiniMax H3 prompt package from the approved treatment and references.
The top-level content object MUST contain a non-empty `shots` array. Every shot must contain title, prompt,
duration (0.5-15 seconds), continuity (hard_cut or sequential), megapixels, aspect_ratio, camera movement,
visible action, lyric timestamps, and acceptance criteria. Use I2V/sequential only when the previous accepted
last frame should open the next shot; use T2V for intentional visual resets. Production does not use R2V yet:
if a scene needs a reference, select the relevant image by its exact `reference_names` (or `reference_ids`)
and use I2V. Every shot must also include `audio_mode` (`silent` or `lip_sync`), `audio_source` (`song` or
`reference`), `audio_start`, and `audio_duration`; use lip_sync only for shots where visible mouth performance
is required. For a reference audio source, include its exact `audio_reference` name. Every generation uses
turbo and no generated audio unless `audio_mode` is lip_sync. Ensure total shot duration covers the analyzed song.
""")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True)
            agy = await self._agy(production, f"Review every proposed video prompt for lyric fit, action clarity, visual variety, camera continuity, character visibility and text risk. Return corrections: {json.dumps(codex.content, ensure_ascii=False)}")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True)
            final = await self._codex(production, f"""
Apply AGY's corrections and return the final executable prompt package. The top-level content object MUST
contain the complete `shots` array, not a summary or reference to an earlier response.
Draft: {json.dumps(codex.content, ensure_ascii=False)}
AGY review: {json.dumps(agy.content, ensure_ascii=False)}
""")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True)
            confirmation = await self._agy(production, f"""
Confirm the final package is executable, timed to the song, visually varied, and obeys the continuity plan.
Return APPROVE unless there is a concrete blocking defect; do not rewrite it merely for stylistic preference.
Final package: {json.dumps(final.content, ensure_ascii=False)}
""")
            if self._control_requested(production_id):
                return
            raw_shots = self._find_shots(final.content)
            shots = self._normalize_shots(
                raw_shots, production["continuity_mode"],
                list_references(production_id, private=True),
            )
            for shot in shots:
                shot["production_id"] = production_id
            replace_shot_plan(production_id, shots)
            package = {"codex_draft": codex.content, "agy_review": agy.content,
                       "codex_final": final.content, "agy_confirmation": confirmation.content,
                       "normalized_shots": shots}
            (self._folder(production_id) / "shots" / "prompt_package.json").write_text(
                json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            decision = add_decision(production_id, "prompt_consultation", "Video prompt package",
                                    confirmation.content.get("summary", "The video prompt package is ready for review."),
                                    {"artifact": "shots/prompt_package.json", **package})
            if production["participation_mode"] == "autonomous":
                from .production_db import resolve_decision
                resolve_decision(production_id, decision["id"], "approved", "codex+agy", "Autonomous joint approval")
                update_production(production_id, status="queued", stage="shot_generation", progress=0.65)
            else:
                update_production(production_id, status="awaiting_user", stage="prompt_review", progress=0.65)
            self._checkpoint(production_id)
            return

        if stage == "shot_generation":
            shots = list_shots(production_id, private=True)
            if not shots:
                raise RuntimeError("No approved shot plan is available")
            previous_video: Path | None = None
            for shot in shots:
                if shot["status"] == "accepted" and shot.get("accepted_attempt"):
                    accepted = next((item for item in shot["attempts"] if item["attempt"] == shot["accepted_attempt"]), None)
                    if accepted and accepted.get("output_path"):
                        previous_video = Path(accepted["output_path"])
                        continue
                existing = shot["attempts"][-1] if shot["attempts"] else None
                attempt_number = int(existing["attempt"] if existing else 0)
                pending_attempt = existing if existing and existing["status"] in {"queued", "generating"} and existing.get("job_id") else None
                pending_review = existing if existing and existing["status"] == "reviewing" and existing.get("output_path") else None
                defect_counts: dict[str, int] = {}
                for old in shot["attempts"]:
                    if old.get("defect_key"):
                        defect_counts[old["defect_key"]] = defect_counts.get(old["defect_key"], 0) + 1
                while True:
                    if self._control_requested(production_id):
                        return
                    production = get_production(production_id, private=True) or production
                    video: Path | None = None
                    frames: list[Path] = []
                    if pending_review:
                        attempt = pending_review
                        attempt_number = int(attempt["attempt"])
                        video = Path(attempt["output_path"])
                        frames = [Path(value) for value in attempt.get("frames", [])]
                        if not frames or any(not path.exists() for path in frames):
                            review_dir = self._folder(production_id) / "shots" / f"shot_{shot['shot_index']:03d}" / f"attempt_{attempt_number:02d}" / "review_frames"
                            frames = await asyncio.to_thread(extract_review_frames, video, review_dir, 1.0, 48)
                            update_shot_attempt(attempt["id"], frames=[str(path) for path in frames])
                        pending_review = None
                        add_message(production_id, "system", "all", "status",
                                    f"Resuming joint review of {shot['title']} · attempt {attempt_number}.")
                    elif pending_attempt:
                        attempt = pending_attempt
                        attempt_number = int(attempt["attempt"])
                        job_id = attempt["job_id"]
                        pending_attempt = None
                        update_shot(shot["id"], status="generating")
                        add_message(production_id, "system", "all", "status",
                                    f"Reattached to {shot['title']} · attempt {attempt_number} after resume.")
                    else:
                        attempt_number += 1
                        opening_frame: Path | None = None
                        if shot["mode"] == "opening":
                            if previous_video and previous_video.exists() and shot["continuity"] == "sequential":
                                opening_frame = INPUT / f"production_{production_id}_shot_{shot['shot_index'] - 1:03d}_last.png"
                                dimensions = normalize_generation_settings(
                                    "opening", engine=shot["engine"], steps=int(shot["steps"]),
                                    megapixels=float(shot["megapixels"]), aspect_ratio=shot["aspect_ratio"],
                                    turbo_profile=shot["turbo_profile"],
                                )
                                await asyncio.to_thread(
                                    extract_last_frame, previous_video, opening_frame, dimensions.width, dimensions.height,
                                )
                            elif not any(
                                (reference := get_reference(production_id, reference_id, private=True))
                                and reference["kind"] == "image" for reference_id in shot.get("reference_ids", [])
                            ):
                                raise RuntimeError(f"{shot['title']} requires an opening image or previous accepted clip")
                        attempt = create_shot_attempt(shot["id"], attempt_number, str(opening_frame) if opening_frame else None)
                        queued_shot = {**shot, "production_id": production_id}
                        job_id = self._queue_job(queued_shot, opening_frame)
                        update_shot_attempt(attempt["id"], job_id=job_id, status="generating")
                        update_shot(shot["id"], status="generating")
                        add_message(production_id, "system", "all", "status",
                                    f"Generating {shot['title']} · attempt {attempt_number} · {shot['duration']}s · {shot['megapixels']} MP")
                    if video is None:
                        try:
                            job = await self._wait_for_job(production_id, job_id)
                        except Exception as exc:
                            update_shot_attempt(attempt["id"], status="failed", error=str(exc)[:8000])
                            update_shot(shot["id"], status="failed")
                            raise
                        video = Path(job["output_path"])
                        review_dir = self._folder(production_id) / "shots" / f"shot_{shot['shot_index']:03d}" / f"attempt_{attempt_number:02d}" / "review_frames"
                        frames = await asyncio.to_thread(extract_review_frames, video, review_dir, 1.0, 48)
                        update_shot_attempt(attempt["id"], status="reviewing", output_path=str(video), frames=[str(path) for path in frames])
                        update_shot(shot["id"], status="reviewing")
                        add_event(production_id, "shot.reviewing", {"shot_id": shot["id"], "attempt": attempt_number})
                    agy, codex = await self._review_shot(production, shot, video, frames, previous_video)
                    approved = self._agent_approved(agy) and self._agent_approved(codex)
                    defect_key = None if approved else self._defect_key(agy, codex)
                    update_shot_attempt(attempt["id"], status="accepted" if approved else "rejected",
                                        agy_review=agy.content, codex_review=codex.content, defect_key=defect_key)
                    if approved:
                        update_shot(shot["id"], status="accepted", accepted_attempt=attempt_number)
                        previous_video = video
                        add_message(production_id, "system", "all", "status", f"{shot['title']} passed joint Codex + AGY review.")
                        break
                    defect_counts[defect_key] = defect_counts.get(defect_key, 0) + 1
                    corrected = self._content_dict(codex).get("corrected_prompt")
                    if isinstance(corrected, str) and corrected.strip():
                        shot["prompt"] = corrected.strip()
                        update_shot(shot["id"], prompt=shot["prompt"], status="retrying")
                    if defect_counts[defect_key] >= 3 or attempt_number >= 5:
                        update_production(production_id, status="awaiting_user", stage="shot_review")
                        add_decision(
                            production_id, "shot_review", f"Generation loop on {shot['title']}",
                            "Codex and AGY could not accept this shot without repeating a defect. User direction is required.",
                            {"shot_id": shot["id"], "attempt": attempt_number, "defect_key": defect_key,
                             "agy": agy.content, "codex": codex.content},
                        )
                        self._checkpoint(production_id)
                        return
                    update_production(production_id, status="retrying")
                    add_message(production_id, "system", "all", "status",
                                f"Regenerating {shot['title']} after joint review: {defect_key}")
                update_production(production_id, status="running", progress=0.65 + 0.2 * shot["shot_index"] / len(shots))
                self._checkpoint(production_id)

            update_production(production_id, status="queued", stage="assembly", progress=0.87)
            self.notify()
            return

        if stage == "assembly":
            shots = list_shots(production_id, private=True)
            clips: list[Path] = []
            for shot in shots:
                accepted = next((item for item in shot["attempts"] if item["attempt"] == shot.get("accepted_attempt")), None)
                if not accepted or not accepted.get("output_path"):
                    raise RuntimeError(f"{shot['title']} has no accepted clip")
                clips.append(Path(accepted["output_path"]))
            assembly_dir = self._folder(production_id) / "assembly"
            silent = assembly_dir / "silent_master.mp4"
            final_video = assembly_dir / "final_with_song.mp4"
            if len(clips) == 1:
                shutil.copy2(clips[0], silent)
            else:
                await asyncio.to_thread(assemble_clips, clips, silent)
            production = get_production(production_id, private=True) or production
            await asyncio.to_thread(attach_song, silent, Path(production["song_path"]), final_video)
            add_artifact(production_id, "silent_master", str(silent), {"clips": len(clips)})
            add_artifact(production_id, "final_video", str(final_video), {"clips": len(clips)})
            update_production(production_id, status="queued", stage="final_review", progress=0.94)
            add_message(production_id, "system", "all", "status", "All accepted shots were assembled and the original song was attached.")
            self._checkpoint(production_id)
            self.notify()
            return

        if stage == "final_review":
            production = get_production(production_id, private=True) or production
            final_video = self._folder(production_id) / "assembly" / "final_with_song.mp4"
            frames = await asyncio.to_thread(
                extract_review_frames, final_video, self._folder(production_id) / "assembly" / "review_frames", 0.5, 80,
            )
            agy = await self._media_agent(production, f"""
Inspect the complete final music video with its original song at {final_video}. Review synchronization,
story/lyric alignment, pacing, cuts, continuity, motion, visible text, audio presence, and overall watchability.
Return APPROVE or NEEDS_FIXES with timestamps and concrete changes. Do not reject for tiny imperceptible text.
""")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True) or production
            codex = await self._other_agent(production, agy, f"""
Review the attached frames and AGY's complete audio/video report as equal co-producer. Decide whether the
final film is ready to show the user and list only concrete fixes if not.
AGY report: {json.dumps(agy.content, ensure_ascii=False)}
""", images=frames)
            decision = add_decision(
                production_id, "final_review", "Final music video",
                codex.content.get("summary", "The final video has completed joint review."),
                {"artifact_kind": "final_video", "agy": agy.content, "codex": codex.content,
                 "joint_approved": self._agent_approved(agy) and self._agent_approved(codex)},
            )
            update_production(production_id, status="awaiting_user", stage="user_review", progress=0.99)
            add_message(production_id, "system", "user", "decision",
                        "The final video is ready. Watch it and make the final approval decision.",
                        {"decision_id": decision["id"], "artifact_kind": "final_video"})
            self._checkpoint(production_id)
            return

        if stage == "revision_consultation":
            shots = list_shots(production_id, private=True)
            production = get_production(production_id, private=True) or production
            codex = await self._codex(production, f"""
The user rejected the final video and their latest decision is in the high-priority context. Propose the
smallest concrete repair plan. Return content.shots as an array containing only shots that must regenerate;
each item must include shot_index and a complete corrected_prompt. Include downstream sequential shots when
their opening-frame continuity would be invalidated.
Current shots: {json.dumps(shots, ensure_ascii=False)}
""")
            if self._control_requested(production_id):
                return
            production = get_production(production_id, private=True) or production
            agy = await self._agy(production, f"""
Review Codex's repair plan against the actual final video and the user's rejection. Confirm or amend exactly
which shot indexes need regeneration and provide corrected prompts. Return the final list in content.shots.
Codex plan: {json.dumps(codex.content, ensure_ascii=False)}
""")
            if self._control_requested(production_id):
                return
            revisions = self._find_shots(agy.content) or self._find_shots(codex.content)
            if not revisions:
                raise RuntimeError("The agents did not identify any shots to revise")
            by_index = {int(shot["shot_index"]): shot for shot in shots}
            selected: set[int] = set()
            for revision in revisions:
                try:
                    index = int(revision.get("shot_index") or revision.get("index"))
                except (TypeError, ValueError):
                    continue
                shot = by_index.get(index)
                if not shot:
                    continue
                prompt = str(revision.get("corrected_prompt") or revision.get("prompt") or "").strip()
                if prompt:
                    update_shot(shot["id"], prompt=prompt, status="planned", accepted_attempt=None)
                    selected.add(index)
            if not selected:
                raise RuntimeError("The repair plan did not contain valid shot indexes and corrected prompts")
            first_changed = min(selected)
            for index, shot in by_index.items():
                if index > first_changed and shot["continuity"] == "sequential":
                    update_shot(shot["id"], status="planned", accepted_attempt=None)
                    selected.add(index)
            add_message(production_id, "system", "all", "status",
                        "Joint revision plan will regenerate shots: " + ", ".join(map(str, sorted(selected))))
            update_production(production_id, status="queued", stage="shot_generation", progress=0.65)
            self._checkpoint(production_id)
            self.notify()
            return

        update_production(production_id, status="failed", error=f"Unsupported production stage: {stage}")
        add_message(production_id, "system", "user", "error", f"The production cannot continue from the unknown stage {stage}.")
        self._checkpoint(production_id)


production_orchestrator = ProductionOrchestrator()
