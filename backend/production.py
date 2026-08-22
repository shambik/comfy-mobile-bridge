from __future__ import annotations

import asyncio
import json
import re
import secrets
import shutil
import uuid
from pathlib import Path
from typing import Any

from .agents import (AgentExecutionError, AgentHeartbeatCallback, AgentOutputCallback, AgentResult,
                     _decode_structured_value, discover_codex_models, process_manager)
from .config import AGENT_TIMEOUT_SECONDS, INPUT, PRODUCTIONS, PRODUCTION_CONCURRENCY
from .db import connect, get_job, next_position, now_iso
from .generation import normalize_generation_settings
from .library import resolve_asset_path
from .media import (assemble_clips, attach_song, extract_last_frame, extract_review_frames,
                    prepare_audio_segment, probe_audio_metadata)
from .production_db import (add_artifact, add_decision, add_event, add_message, add_reference,
                            create_shot_attempt, get_production, list_messages, list_shots,
                            get_reference, list_references, recover_productions, replace_shot_plan, resolve_decision,
                             normalize_production_generation, megapixels_for_duration,
                             update_production, update_shot, update_shot_attempt)
from .skill_catalog import selected_skill_context


class ReferenceGenerationError(RuntimeError):
    """A reference attempt can be retried without losing the production checkpoint."""


class ProductionInterruption(RuntimeError):
    """The user interrupted an active production and it should resume safely."""


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

    def has_active_work(self, production_id: str) -> bool:
        """Report in-memory work even when the database status is ``queued``.

        An intervention changes the persisted status to ``queued`` before the
        current agent task has unwound.  The task and/or its CLI subprocess can
        therefore still be active for a short time; treating the database
        status as the only source of truth makes a second intervention take the
        non-interrupting path.
        """
        task = self.production_tasks.get(production_id)
        return bool(
            (task and not task.done())
            or production_id in self.current_jobs
            or process_manager.has_active_process(production_id)
        )

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
            elif current and current.get("intervention_requested"):
                update_production(
                    production_id, status="queued", intervention_requested=0, error=None,
                )
                add_message(
                    production_id, "system", "all", "status",
                    "Intervention received. Current work was stopped; resuming from the last safe checkpoint with each agent's saved session.",
                    {"intervention": True, "resumed_from_checkpoint": True},
                )
                add_event(production_id, "production.intervention_resumed", {
                    "stage": current.get("stage"),
                    "codex_session_id": bool(current.get("codex_session_id")),
                    "agy_session_id": bool(current.get("agy_session_id")),
                })
                self._checkpoint(production_id)
            elif isinstance(exc, ReferenceGenerationError):
                update_production(production_id, status="awaiting_user", error=str(exc)[:8000])
                add_message(
                    production_id, "system", "user", "error",
                    f"Reference generation needs a retry. Existing approved references and numbered attempts were preserved. {exc}",
                    {"retryable": True, "stage": "reference_generation"},
                )
                add_event(production_id, "production.reference_generation_retryable", {"error": str(exc)[:2000]})
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

    def _base_context(self, production: dict[str, Any], participant: str | None = None) -> str:
        skills = selected_skill_context(production.get("skills", []))
        references = list_references(production["id"], private=True)
        reference_context = json.dumps([
            {
                "id": item["id"], "kind": item["kind"], "name": item["name"],
                "path": item["path"], "notes": item.get("notes", ""),
            }
            for item in references
        ], ensure_ascii=False, indent=2)
        user_messages = []
        for message in list_messages(production["id"]):
            if message["participant"] != "user" or message["kind"] not in {"intervention", "decision", "control"}:
                continue
            recipient = str(message.get("recipient") or "both").lower()
            if participant and recipient not in {"both", "all", participant}:
                continue
            user_messages.append(message)
        user_messages = user_messages[-20:]
        instructions = "\n".join(
            f"- {'[USER INTERVENTION — ADDRESS THIS BEFORE CONTINUING] ' if message['kind'] == 'intervention' else ''}"
            f"{message['content']}"
            for message in user_messages
        )
        intervention_note = (
            "A user intervention is present above. Address the user's requirement or question first, "
            "then continue the production from the saved checkpoint. Do not ignore it or silently continue "
            "the previous plan."
            if any(message["kind"] == "intervention" for message in user_messages)
            else "No pending user intervention applies to this agent."
        )
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

Intervention handling:
{intervention_note}

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

    @staticmethod
    def _agent_dirs(paths: list[Path] | None) -> list[Path]:
        """Return unique parent directories that contain media being reviewed."""
        directories: dict[str, Path] = {}
        for value in paths or []:
            path = Path(value)
            directory = path if path.is_dir() else path.parent
            try:
                resolved = directory.resolve()
            except OSError:
                continue
            if resolved.is_dir():
                directories.setdefault(str(resolved).casefold(), resolved)
        return list(directories.values())

    @staticmethod
    def _current_job_video(job_id: str | None, recorded_path: str | None = None) -> Path | None:
        """Resolve a generated job by stable ID, repairing legacy stale paths."""
        if job_id:
            try:
                path = resolve_asset_path("job", job_id)
            except (KeyError, OSError, ValueError):
                path = None
            if path and path.is_file():
                return path
        if recorded_path:
            candidate = Path(recorded_path)
            if candidate.is_file():
                return candidate.resolve()
        return None

    @classmethod
    def _current_attempt_video(cls, attempt: dict[str, Any]) -> Path | None:
        path = cls._current_job_video(attempt.get("job_id"), attempt.get("output_path"))
        if path and str(path) != str(attempt.get("output_path") or ""):
            update_shot_attempt(attempt["id"], output_path=str(path))
        return path

    async def _codex(
        self, production: dict[str, Any], request: str, images: list[Path] | None = None,
        media_paths: list[Path] | None = None,
    ) -> AgentResult:
        runtime = production.get("codex_runtime") or "codex"
        images = self._reference_image_paths(production) if images is None else images
        trace = self._agent_trace_callback(production, "codex", runtime)
        heartbeat = self._agent_heartbeat_callback(production, "codex", runtime)
        saved_session = production.get("codex_session_id")
        session_note = "resuming saved Codex session" if saved_session else "starting a new Codex session"
        add_message(
            production["id"], "codex", "all", "agent_trace",
            f"CODEX started via {runtime.upper()} CLI ({production['codex_model']} · {production['codex_effort']}; {session_note}).",
            {"live": True, "runtime": runtime, "model": production["codex_model"], "effort": production["codex_effort"], "stream": "system"},
        )
        try:
            result = await process_manager.invoke(
                runtime, "codex", production["id"], self._base_context(production, "codex") + "\n\nTASK:\n" + request,
                production["codex_model"], production["codex_effort"], saved_session, images,
                trace, heartbeat, self._agent_dirs([*(images or []), *(media_paths or [])]),
            )
        except Exception as exc:
            if self._control_pending(production["id"]):
                raise
            add_message(
                production["id"], "codex", "all", "agent_trace",
                f"CODEX failed: {str(exc)[:1600]}",
                {"live": True, "runtime": runtime, "model": production["codex_model"], "effort": production["codex_effort"], "stream": "error"},
            )
            self._record_agent_failure(production["id"], f"{production.get('stage', 'agent')}_codex", exc)
            raise
        update_production(production["id"], codex_session_id=result.session_id)
        add_message(production["id"], "codex", "all", "agent", result.content.get("summary", ""), {
            "model": result.model, "effort": result.effort, "session_id": result.session_id,
            "runtime": runtime,
            "decision": result.content.get("decision"), "next_action": result.content.get("next_action"),
            "content": result.content.get("content"), "issues": result.content.get("issues", []),
        })
        self._record_agent_reply(production, result)
        return result

    async def _agy(
        self, production: dict[str, Any], request: str, images: list[Path] | None = None,
        media_paths: list[Path] | None = None,
    ) -> AgentResult:
        runtime = production.get("agy_runtime") or "agy"
        images = self._reference_image_paths(production) if images is None else images
        trace = self._agent_trace_callback(production, "agy", runtime)
        heartbeat = self._agent_heartbeat_callback(production, "agy", runtime)
        saved_session = production.get("agy_session_id")
        session_note = "resuming saved AGY session" if saved_session else "starting a new AGY session"
        add_message(
            production["id"], "agy", "all", "agent_trace",
            f"AGY started via {runtime.upper()} CLI ({production['agy_model']} · {production['agy_effort']}; {session_note}).",
            {"live": True, "runtime": runtime, "model": production["agy_model"], "effort": production["agy_effort"], "stream": "system"},
        )
        try:
            base_prompt = self._base_context(production, "agy") + "\n\nTASK:\n"
            retry_request = request + """

CORRECTION AFTER A REJECTED RESPONSE:
Your previous turn did not produce the requested task result. Perform the task now. Do not describe, echo, or reproduce the response schema. Return only the actual JSON result. Use plain strings for summary, decision, and next_action; put the real findings or task payload in content; use issues: [] when there are no issues, otherwise use a JSON array of concrete issue objects. Never use schema descriptors such as {\"type\": \"string\"} as values.
"""
            fresh_retry_used = False
            try:
                result = await process_manager.invoke(
                    runtime, "agy", production["id"], base_prompt + request,
                    production["agy_model"], production["agy_effort"], saved_session, images,
                    trace, heartbeat, self._agent_dirs([*(images or []), *(media_paths or [])]),
                )
            except Exception as exc:
                if runtime != "agy" or not self._agy_contract_failure(exc):
                    raise
                fresh_retry_used = True
                add_message(
                    production["id"], "agy", "all", "agent_trace",
                    "AGY rejected the current response contract; retrying once in a fresh conversation with the required result format.",
                    {"live": True, "runtime": runtime, "model": production["agy_model"],
                     "effort": production["agy_effort"], "stream": "system", "retry": "contract_fresh_session"},
                )
                result = await process_manager.invoke(
                    runtime, "agy", production["id"], base_prompt + retry_request,
                    production["agy_model"], production["agy_effort"], None, images,
                    trace, heartbeat, self._agent_dirs([*(images or []), *(media_paths or [])]),
                )
            if runtime == "agy" and self._agy_placeholder(result):
                if fresh_retry_used:
                    raise RuntimeError(
                        "AGY returned the response schema instead of a task result after a fresh-session retry"
                    )
                add_message(
                    production["id"], "agy", "all", "agent_trace",
                    "AGY returned a schema placeholder instead of the task response; retrying once in a fresh conversation.",
                    {"live": True, "runtime": runtime, "model": production["agy_model"],
                     "effort": production["agy_effort"], "stream": "system", "retry": "fresh_session"},
                )
                fresh_retry_used = True
                result = await process_manager.invoke(
                    runtime, "agy", production["id"], base_prompt + retry_request,
                    production["agy_model"], production["agy_effort"], None, images,
                    trace, heartbeat, self._agent_dirs([*(images or []), *(media_paths or [])]),
                )
                if self._agy_placeholder(result):
                    raise RuntimeError(
                        "AGY returned the response schema instead of a task result after one fresh-session retry"
                    )
        except Exception as exc:
            if self._control_pending(production["id"]):
                raise
            add_message(
                production["id"], "agy", "all", "agent_trace",
                f"AGY failed: {str(exc)[:1600]}",
                {"live": True, "runtime": runtime, "model": production["agy_model"], "effort": production["agy_effort"], "stream": "error"},
            )
            self._record_agent_failure(production["id"], f"{production.get('stage', 'agent')}_agy", exc)
            raise
        update_production(production["id"], agy_session_id=result.session_id)
        add_message(production["id"], "agy", "all", "agent", result.content.get("summary", ""), {
            "model": result.model, "effort": result.effort, "session_id": result.session_id,
            "runtime": runtime,
            "decision": result.content.get("decision"), "next_action": result.content.get("next_action"),
            "content": result.content.get("content"), "issues": result.content.get("issues", []),
        })
        self._record_agent_reply(production, result)
        return result

    async def _media_agent(
        self, production: dict[str, Any], request: str, media_paths: list[Path] | None = None,
    ) -> AgentResult:
        """Use a seat backed by AGY for real audio/video inspection."""
        if (production.get("agy_runtime") or "agy") == "agy":
            return await self._agy(production, request, media_paths=media_paths)
        if (production.get("codex_runtime") or "codex") == "agy":
            return await self._codex(production, request, media_paths=media_paths)
        raise RuntimeError("Music-video production requires at least one producer using the AGY runtime")

    async def _other_agent(
        self, production: dict[str, Any], media_result: AgentResult, request: str,
        images: list[Path] | None = None,
        media_paths: list[Path] | None = None,
    ) -> AgentResult:
        return await (self._codex(production, request, images, media_paths) if media_result.participant == "agy"
                      else self._agy(production, request, images, media_paths))

    @staticmethod
    def _trace_value(value: Any, limit: int = 900) -> str:
        if isinstance(value, str):
            text = " ".join(value.split())
        elif value is None:
            return ""
        else:
            text = str(value)
        return text[:limit] + ("…" if len(text) > limit else "")

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total = max(0, int(seconds))
        minutes, remainder = divmod(total, 60)
        return f"{minutes}m {remainder:02d}s" if minutes else f"{remainder}s"

    @classmethod
    def _stream_item_text(cls, item: dict[str, Any]) -> str:
        """Extract agent-visible text from a stream item.

        CLIs may expose a short reasoning summary or an assistant message in
        several equivalent shapes.  We intentionally read only explicit text
        or summary fields; hidden chain-of-thought is never forwarded to the
        production UI.
        """
        chunks: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, str):
                text = " ".join(value.split()).strip()
                if text and text not in chunks:
                    chunks.append(text)
                return
            if isinstance(value, dict):
                for key in ("text", "summary_text", "output_text", "message", "content", "parts", "delta"):
                    if key in value:
                        collect(value.get(key))
                return
            if isinstance(value, list):
                for entry in value:
                    collect(entry)

        for key in ("summary", "summary_text", "text", "output_text", "message", "content", "parts", "delta"):
            if key in item:
                collect(item.get(key))
        return " ".join(chunks)

    @classmethod
    def _format_agent_trace(cls, participant: str, runtime: str, channel: str, line: str) -> tuple[str, str] | None:
        """Turn a CLI stream event into a safe, useful activity message.

        The UI receives operational progress (sessions, tools, file/media work,
        and errors), not hidden chain-of-thought or the raw JSON stream.
        """
        seat = participant.upper()
        cli = runtime.upper()
        stripped = line.strip()
        if not stripped:
            return None
        normalized_line = stripped.lower()
        if channel == "stderr":
            if any(marker in normalized_line for marker in (
                "responses_retry", "stream disconnected", "websocket closed by server",
                "before response.completed", "shell_snapshot: failed to create shell snapshot",
                "shell snapshot not supported yet for powershell",
                "falling back to http", "after_agent hook failed; continuing",
                "codex_skills::interface: ignoring interface.icon_small",
                "codex_skills::interface: ignoring interface.icon_large",
                "icon path with '..' must resolve under plugin assets/",
                "failed to refresh cached remote plugin catalog",
                "remote plugin catalog request",
                "codex_core_plugins::manager",
            )):
                # These are recoverable CLI/plugin transport diagnostics, not
                # production decisions or media-analysis responses.
                return None
            if re.search(r"\bwarn(?:ing)?\b", normalized_line):
                return None
            if not any(marker in normalized_line for marker in (
                "error", "failed", "exception", "traceback", "fatal", "panic",
            )):
                # INFO/debug/progress chatter belongs in the CLI log, not the
                # production conversation. Keep actionable failures visible.
                return None
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            if channel == "stderr":
                return f"{seat} ({cli}) diagnostic: {cls._trace_value(stripped)}", "stderr"
            if re.match(r"^\s*(?:\[[^\]]+\]\s*)?(?:info|debug|trace|warn(?:ing)?)(?:[:\s]|$)", normalized_line):
                return None
            if normalized_line.startswith(("event:", "item.completed", "reported progress")):
                return None
            return f"{seat} ({cli}) update: {cls._trace_value(stripped)}", "agent_update"
        if not isinstance(event, dict):
            return None

        event_type = str(event.get("type") or event.get("event") or "").strip()
        result = event.get("result")
        if isinstance(result, dict) and result.get("status"):
            status = str(result.get("status")).lower()
            if status in {"error", "failed"}:
                return f"{seat} ({cli}) reported an error: {cls._trace_value(result.get('error') or result.get('message') or 'unknown error')}", "error"

        if event_type in {"error", "turn.failed", "session.error", "thread.error"}:
            detail = event.get("message") or event.get("error") or event.get("detail")
            if not detail:
                # Some CLI versions emit a bare `event: error` after a stream
                # retry. The process-level failure handler will report a real
                # failure if the command ultimately exits unsuccessfully.
                return None
            detail_text = cls._trace_value(detail)
            if any(marker in detail_text.lower() for marker in (
                "stream disconnected", "websocket closed by server", "response.completed",
            )):
                return None
            return f"{seat} ({cli}) reported an error: {detail_text}", "error"

        item = event.get("item") if isinstance(event.get("item"), dict) else event
        item_type = str(item.get("type") or "").lower()
        if event_type == "item.completed" and not (
            (isinstance(result, dict) and str(result.get("status", "")).lower() in {"error", "failed"})
            or item_type in {"reasoning", "analysis", "thinking", "agent_message", "message", "assistant_message"}
        ):
            return None
        if event_type in {"step_update", "progress", "status"}:
            detail = cls._trace_value(event.get("message") or event.get("step") or event.get("status"))
            if not detail or detail.casefold() in {"progress", "reported progress", "working", "in progress", "status", "update", "step update"}:
                return None
            return f"{seat} ({cli}) update: {detail}", "agent_update"
        if event_type in {"thread.started", "session.started", "turn.started", "turn.completed", "session.completed", "thread.completed"}:
            # These are protocol lifecycle events. The background activity card
            # and heartbeat already show liveness without filling the council
            # with messages that do not describe production work.
            return None
        if item_type in {"command_execution", "tool_call", "tool_use", "function_call", "web_search_call"}:
            tool = item.get("name") or item.get("tool") or item.get("action")
            if not isinstance(tool, str) or not tool.strip():
                command = str(item.get("command") or "").casefold()
                if any(marker in command for marker in ("ffmpeg", "audio", "video", "media")):
                    tool = "media inspection"
                elif any(marker in command for marker in ("image", "vision", "reference")):
                    tool = "reference-image inspection"
                else:
                    tool = "production tool"
            return f"{seat} ({cli}) is using {cls._trace_value(tool, 180)}.", "tool_activity"
        if item_type in {"reasoning", "analysis", "thinking"}:
            summary = cls._stream_item_text(item)
            if summary:
                return f"{seat} ({cli}) reasoning summary: {cls._trace_value(summary)}", "reasoning_summary"
            return None
        if item_type in {"agent_message", "message", "assistant_message"}:
            text = cls._stream_item_text(item)
            # Structured JSON is rendered by the completed response card. Do
            # not duplicate it as raw JSON in the live stream.
            if text and not text.lstrip().startswith(("{", "[")):
                return f"{seat} ({cli}) response: {cls._trace_value(text)}", "agent_response"
            return None
        if "delta" in event_type.casefold():
            return None
        detail = cls._stream_item_text(event)
        if detail and not detail.lstrip().startswith(("{", "[")):
            return f"{seat} ({cli}) update: {cls._trace_value(detail)}", "agent_update"
        return None

    def _agent_heartbeat_callback(
        self, production: dict[str, Any], participant: str, runtime: str,
    ) -> AgentHeartbeatCallback:
        """Report meaningful liveness while a CLI turn has not completed.

        The CLI may emit only ``init``/``progress`` and then stay silent while
        it works. These updates keep the production card honest without
        exposing raw output or hidden chain-of-thought.
        """
        last_signature = ""
        stage = str(production.get("stage") or "agent work").replace("_", " ")

        async def emit(elapsed: float, idle: float, channel: str, line: str) -> None:
            nonlocal last_signature
            formatted = self._format_agent_trace(participant, runtime, channel, line)
            last_event = formatted[0] if formatted else "no new CLI event received"
            content = (
                f"{participant.upper()} is still working on {stage} · "
                f"elapsed {self._format_elapsed(elapsed)} · "
                f"last activity: {last_event} · quiet for {self._format_elapsed(idle)}"
            )
            if content == last_signature:
                return
            last_signature = content
            add_message(
                production["id"], participant, "all", "agent_trace", content,
                {
                    "live": True, "heartbeat": True, "runtime": runtime,
                    "model": production.get(f"{participant}_model", ""),
                    "effort": production.get(f"{participant}_effort", ""),
                    "stream": "heartbeat", "event_type": "heartbeat",
                    "elapsed_seconds": round(elapsed, 1), "idle_seconds": round(idle, 1),
                    "timeout_seconds": AGENT_TIMEOUT_SECONDS,
                },
            )

        return emit

    def _agent_trace_callback(self, production: dict[str, Any], participant: str, runtime: str) -> AgentOutputCallback:
        last_signature = ""

        async def emit(channel: str, line: str) -> None:
            nonlocal last_signature
            formatted = self._format_agent_trace(participant, runtime, channel, line)
            if not formatted:
                return
            content, event_type = formatted
            signature = f"{channel}:{content}"
            if signature == last_signature:
                return
            last_signature = signature
            add_message(
                production["id"], participant, "all", "agent_trace", content,
                {
                    "live": True, "runtime": runtime, "model": production.get(f"{participant}_model", ""),
                    "effort": production.get(f"{participant}_effort", ""), "stream": channel,
                    "event_type": event_type,
                },
            )

        return emit

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
        if current.get("intervention_requested"):
            update_production(production_id, status="queued", intervention_requested=0, error=None)
            add_message(
                production_id, "system", "all", "status",
                "Intervention received at a safe checkpoint. The next Codex and AGY turns will address it using their saved sessions.",
                {"intervention": True, "resumed_from_checkpoint": True},
            )
            add_event(production_id, "production.intervention_resumed", {
                "stage": current.get("stage"),
                "codex_session_id": bool(current.get("codex_session_id")),
                "agy_session_id": bool(current.get("agy_session_id")),
            })
            self._checkpoint(production_id)
            return True
        return False

    @staticmethod
    def _control_pending(production_id: str) -> bool:
        current = get_production(production_id, private=True)
        return bool(current and (
            current.get("intervention_requested")
            or current.get("stop_requested")
            or current.get("pause_requested")
        ))

    def _record_agent_failure(self, production_id: str, stage: str, exc: Exception) -> Path:
        """Persist agent diagnostics without putting the raw stream in the UI."""
        folder = self._folder(production_id) / "logs"
        path = folder / f"{stage}_agent_failure_{uuid.uuid4().hex}.json"
        payload: dict[str, Any] = {
            "stage": stage,
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
        if isinstance(exc, AgentExecutionError):
            payload.update({
                "runtime": exc.runtime,
                "command": exc.command,
                "returncode": exc.returncode,
                "stdout": exc.stdout,
                "stderr": exc.stderr,
            })
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        add_event(production_id, "agent.failed", {
            "stage": stage,
            "runtime": payload.get("runtime"),
            "message": str(exc)[:1600],
            "diagnostic_path": str(path),
        })
        return path

    @staticmethod
    def _limited_audio_analysis(audio_metadata: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Return a valid analysis package when the media seat cannot inspect audio."""
        return {
            "summary": "AGY audio inspection failed; continuing with backend audio preflight.",
            "decision": "continue",
            "next_action": "Continue with limited audio analysis and treat BPM, sections, and lyric timing as estimated.",
            "confidence": None,
            "requires_user": False,
            "content": {
                "analysis_status": "limited",
                "analysis_source": "backend_audio_preflight",
                "audio_metadata": audio_metadata,
                "bpm": None,
                "bpm_confidence": 0,
                "meter": None,
                "sections": [],
                "energy_curve": [],
                "vocal_entrances": [],
                "instrumental_breaks": [],
                "lyric_timeline": [],
                "analysis_limitation": "The AGY CLI terminated while inspecting the binary audio file. Backend metadata is valid, but musical timing still needs a successful media-agent pass.",
                "agent_error": str(exc)[:1600],
            },
            "issues": [{
                "type": "agent_audio_inspection",
                "severity": "warning",
                "message": str(exc)[:1600],
            }],
        }

    @staticmethod
    def _content_dict(result: AgentResult) -> dict[str, Any]:
        value = _decode_structured_value(result.content.get("content"))
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
        value = _decode_structured_value(value)
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
            attempt_failures: list[str] = []
            for attempt in range(1, 3):
                path = self._folder(production["id"]) / "references" / "generated" / f"reference_{index:02d}_attempt_{attempt}.png"
                try:
                    if provider == "auto":
                        await process_manager.generate_reference_image(
                            production["id"], image_prompt, path, image_model, image_effort,
                            source_images=list(source_images),
                        )
                    else:
                        await process_manager.generate_reference_image(
                            production["id"], image_prompt, path, image_model, image_effort,
                            provider=provider, agy_model=production["agy_model"],
                            agy_effort=production["agy_effort"], source_images=list(source_images),
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
                    joint_status, joint_note = self._joint_review_status(agy, codex)
                    if joint_status == "approved":
                        accepted_path = path
                        review_summary = str(codex.content.get("summary") or agy.content.get("summary") or "Jointly approved")
                        if joint_note:
                            add_message(
                                production["id"], "system", "all", "status", joint_note,
                                {"reference_name": name, "attempt": attempt},
                            )
                        break
                    if joint_status == "pending":
                        attempt_failures.append(f"attempt {attempt}: review response was incomplete; no rejection was recorded")
                        continue
                    corrected = self._content_dict(codex).get("corrected_prompt")
                    if isinstance(corrected, str) and corrected.strip():
                        image_prompt = corrected.strip()
                    attempt_failures.append(f"attempt {attempt}: joint review requested a revision")
                except Exception as exc:
                    detail = str(exc).replace("\n", " ").strip()[:1200]
                    attempt_failures.append(f"attempt {attempt}: {detail}")
                    diagnostic_path = self._record_agent_failure(
                        production["id"], f"reference_generation_{index:02d}_attempt_{attempt}", exc,
                    )
                    add_message(
                        production["id"], "system", "all", "status",
                        f"Reference {name} attempt {attempt} could not complete; preserving it and retrying with a fresh handoff.",
                        {"reference_name": name, "attempt": attempt, "retry": attempt < 2,
                         "diagnostic_path": str(diagnostic_path), "reason": detail},
                    )
                    if attempt < 2:
                        continue
            if not accepted_path:
                details = " | ".join(attempt_failures) or "no provider result or review was accepted"
                raise ReferenceGenerationError(
                    f"Reference image '{name}' could not be completed after two fresh attempts. {details}"
                )
            comfy_name = f"production_ref_{uuid.uuid4().hex}.png"
            comfy_path = INPUT / comfy_name
            shutil.copy2(accepted_path, comfy_path)
            reference = add_reference(
                production["id"], "image", name, str(accepted_path), str(comfy_path), comfy_name,
                json.dumps({"prompt": image_prompt, "review": review_summary}, ensure_ascii=False),
            )
            generated.append(reference)
            source_images.append(accepted_path)
        if not generated:
            raise RuntimeError("The reference package did not contain any generatable image specifications")
        return generated

    async def _generate_shot_opening_frame(
        self, production: dict[str, Any], shot: dict[str, Any], attempt_number: int,
        previous_last_frame: Path | None = None,
    ) -> tuple[Path, Path]:
        """Create the shot-specific I2V opening frame from assigned image anchors.

        The uploaded/generated production references are creative inputs for the
        agents. They are deliberately not passed directly to the H3 I2V node.
        When the shot is sequential, the previous accepted last frame may be
        supplied as continuity context, but it is never allowed to replace the
        assigned scene references. The generated result is always a new,
        shot-specific opening frame.
        The returned pair is (production artifact path, Comfy input path).
        """
        source_images: list[Path] = []
        for reference_id in shot.get("reference_ids", []):
            reference = get_reference(production["id"], reference_id, private=True)
            if not reference or reference.get("kind") != "image":
                continue
            path = Path(reference.get("path") or "")
            if path.is_file():
                source_images.append(path)
        if not source_images:
            raise RuntimeError(
                f"{shot['title']} has assigned references, but none of its image anchors are available "
                "to create an I2V opening frame"
            )

        image_model = (
            production.get("codex_model")
            if production.get("codex_runtime", "codex") == "codex"
            else discover_codex_models()[0]["id"]
        )
        image_effort = (
            production.get("codex_effort")
            if production.get("codex_runtime", "codex") == "codex"
            else "high"
        )
        shot_dir = self._folder(production["id"]) / "shots" / f"shot_{int(shot['shot_index']):03d}" / f"attempt_{attempt_number:02d}"
        scene_path = shot_dir / "opening_frame.png"
        input_path = INPUT / f"production_{production['id']}_shot_{int(shot['shot_index']):03d}_attempt_{attempt_number:02d}_opening.png"
        continuity_frame = previous_last_frame if previous_last_frame and previous_last_frame.is_file() else None
        generation_sources = [*source_images, *( [continuity_frame] if continuity_frame else [] )]
        continuity_instruction = (
            f"Previous accepted shot last frame (continuity context only): {continuity_frame}"
            if continuity_frame else
            "Previous accepted shot last frame: none"
        )
        scene_prompt = f"""
Create exactly one polished opening frame for this MiniMax H3 I2V shot.
Use the assigned source images as creative anchors for the identity, wardrobe, location, props, lighting,
and art direction of THIS shot. Do not make a collage, do not copy one source image as the scene, and do
not simply reproduce a reference board: compose the actual shot described below from the combined
references and the shot prompt. {continuity_instruction}. If a continuity frame is supplied, preserve
identity, screen geography, and the unfinished action from it only where compatible with this shot; do
not let it override the assigned scene, location, or action. The output must be a new scene frame, not a
direct copy of any input. Establish the first instant of the action with a stable camera position; only
natural micro-motion should be implied. Do not add captions, logos, watermarks, readable signs, or
invented text. Preserve correct forward screen geography and leave a clean, usable frame for video motion.

Shot title: {shot['title']}
Shot prompt:
{shot['prompt']}
""".strip()
        add_message(
            production["id"], "system", "all", "status",
            f"Creating a new I2V opening frame for {shot['title']} from its assigned scene references"
            + (" with the previous accepted last frame as continuity context." if continuity_frame else "."),
            {"shot_id": shot["id"], "attempt": attempt_number,
             "source_reference_count": len(source_images),
             "continuity_frame_included": bool(continuity_frame)},
        )
        await process_manager.generate_reference_image(
            production["id"], scene_prompt, scene_path, image_model, image_effort,
            provider="auto", agy_model=production.get("agy_model"), agy_effort=production.get("agy_effort"),
            source_images=generation_sources,
        )
        input_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(scene_path, input_path)
        add_event(production["id"], "shot.opening_frame.created", {
            "shot_id": shot["id"], "attempt": attempt_number,
            "reference_count": len(source_images), "continuity_frame_included": bool(continuity_frame),
        })
        add_message(
            production["id"], "system", "all", "status",
            f"Opening frame ready for {shot['title']}; the generated scene frame will be sent to I2V.",
            {"shot_id": shot["id"], "attempt": attempt_number, "opening_frame": str(scene_path),
             "source": "assigned_references_plus_previous_last_frame" if continuity_frame else "assigned_references"},
        )
        return scene_path, input_path

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
        generation_defaults: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not raw:
            raise RuntimeError("The joint prompt package did not contain a shots array")
        references = references or []
        generation_defaults = generation_defaults or {}
        project_generation: dict[str, Any] | None = None
        if any(key in generation_defaults for key in (
            "generation_turbo_profile", "generation_steps", "generation_megapixels",
            "generation_aspect_ratio", "generation_megapixel_rules",
        )):
            project_generation = normalize_production_generation(
                generation_defaults.get("generation_turbo_profile", "v1"),
                generation_defaults.get("generation_steps", 4),
                generation_defaults.get("generation_megapixels", 0.7),
                generation_defaults.get("generation_aspect_ratio", "16:9"),
                generation_defaults.get("generation_megapixel_rules"),
            )
        reference_by_id = {str(item["id"]): item for item in references}
        reference_by_name = {
            str(item["name"]).strip().casefold(): item for item in references if item.get("name")
        }
        image_references = [item for item in references if item.get("kind") == "image" and item.get("id")]
        reference_stop_words = {
            "the", "and", "with", "from", "this", "that", "shot", "scene", "master", "anchor",
            "image", "reference", "approved", "production", "frame", "still",
        }

        def choose_fallback_image(item: dict[str, Any]) -> str | None:
            """Choose a visual anchor when an agent forgets to assign one.

            A production with approved image references should not silently turn
            a shot into T2V. Prefer the anchor whose name/brief overlaps the
            shot description; otherwise use the first image reference, which is
            normally the primary character reference.
            """
            if not image_references:
                return None
            shot_text = " ".join(str(item.get(key) or "") for key in ("title", "prompt", "video_prompt", "visible_action"))
            shot_tokens = set(re.findall(r"[a-z0-9]+", shot_text.casefold()))
            scored: list[tuple[int, int, str]] = []
            for order, reference in enumerate(image_references):
                reference_text = f"{reference.get('name', '')} {reference.get('notes', '')}"[:2400]
                reference_tokens = {
                    token for token in re.findall(r"[a-z0-9]+", reference_text.casefold())
                    if len(token) > 2 and token not in reference_stop_words
                }
                score = sum(1 for token in reference_tokens if token in shot_tokens)
                scored.append((score, -order, str(reference["id"])))
            return max(scored)[2]

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
            if project_generation and "generation_megapixel_rules" in generation_defaults:
                # Project controls are authoritative for the initial plan.
                # Shot settings can still be edited explicitly before start.
                megapixels = megapixels_for_duration(
                    duration, project_generation["generation_megapixel_rules"]
                )
            elif project_generation:
                # Keep callers using the pre-rule API compatible. New
                # production records always carry the explicit rule table.
                megapixels = project_generation["generation_megapixels"]
            else:
                try:
                    megapixels = round(float(item.get("megapixels", self._recommended_megapixels(duration))), 1)
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
            if image_references and not any(
                reference_by_id.get(reference_id, {}).get("kind") == "image"
                for reference_id in reference_ids
            ):
                fallback_image = choose_fallback_image(item)
                if fallback_image:
                    reference_ids.append(fallback_image)
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
            if project_generation:
                steps = project_generation["generation_steps"]
                turbo_profile = project_generation["generation_turbo_profile"]
            else:
                try:
                    steps = int(item.get("steps") or (4 if audio_mode == "lip_sync" else 6))
                except (TypeError, ValueError):
                    steps = 4 if audio_mode == "lip_sync" else 6
                turbo_profile = "v1"
            result.append({
                "title": str(item.get("title") or item.get("name") or f"Shot {index}"),
                "prompt": prompt, "mode": mode,
                "continuity": "sequential" if sequential else "hard_cut",
                "audio_mode": audio_mode, "audio_source": audio_source,
                "audio_start": audio_start, "audio_duration": audio_duration,
                "audio_reference_id": audio_reference_id,
                "duration": duration, "megapixels": megapixels,
                "aspect_ratio": (
                    project_generation["generation_aspect_ratio"]
                    if project_generation else str(item.get("aspect_ratio") or "16:9")
                ),
                "steps": steps,
                "engine": "turbo", "turbo_profile": turbo_profile,
                "reference_ids": reference_ids,
            })
        return result

    @classmethod
    def _agent_reply_preview(cls, result: AgentResult) -> str:
        """Create a concise user-facing reply from the structured result.

        This intentionally exposes the agent's returned summary/decision and
        selected task findings only.  It never forwards hidden chain-of-thought
        or raw streaming events to the browser.
        """
        payload = result.content if isinstance(result.content, dict) else {}
        parts: list[str] = []
        summary = payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            parts.append(summary.strip())
        decision = payload.get("decision")
        if isinstance(decision, str) and decision.strip():
            parts.append(f"Decision: {decision.strip()}")
        next_action = payload.get("next_action")
        if isinstance(next_action, str) and next_action.strip():
            parts.append(f"Next: {next_action.strip()}")
        content = payload.get("content")
        if not parts and isinstance(content, str) and content.strip():
            parts.append(content.strip())
        if isinstance(content, dict):
            for key in ("rationale", "reason", "findings", "corrections", "notes"):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(f"{key.replace('_', ' ').capitalize()}: {value.strip()}")
                    break
        return cls._trace_value(" ".join(parts), 1200)

    def _record_agent_reply(self, production: dict[str, Any], result: AgentResult) -> None:
        preview = self._agent_reply_preview(result)
        if not preview:
            return
        participant = result.participant
        add_message(
            production["id"], participant, "all", "agent_trace",
            f"{participant.upper()} reply: {preview}",
            {
                "live": True,
                "runtime": production.get(f"{participant}_runtime", participant),
                "model": result.model,
                "effort": result.effort,
                "stream": "response",
                "event_type": "agent_response",
                "decision": result.content.get("decision"),
                "next_action": result.content.get("next_action"),
            },
        )

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
        if shot["mode"] == "opening" and not opening_frame and any(item["kind"] == "image" for item in references):
            raise RuntimeError(
                f"{shot['title']} has image references but no generated opening frame. "
                "The production will not send an original reference directly to I2V."
            )
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
        image_references = [item for item in references if item["kind"] == "image"]
        # The current production workflow is I2V, not R2V. Keep the full
        # assignment in the production plan for agent/context review, but
        # never pass the original references directly to an I2V job. The
        # orchestrator must first create a shot-specific opening frame from
        # those anchors. R2V keeps its reference names for future support.
        image_names = [item["comfy_name"] for item in image_references] if shot["mode"] == "reference" else []
        video_names = (
            [item["comfy_name"] for item in references if item["kind"] == "video"]
            if shot["mode"] == "reference" else []
        )
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
                    str(opening_frame) if opening_frame else None,
                    opening_frame.name if opening_frame else None,
                    json.dumps(image_names if not opening_frame else []), json.dumps(video_names),
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
                    current = get_production(production_id, private=True)
                    if current and current.get("intervention_requested"):
                        raise ProductionInterruption("Generation interrupted by user intervention")
                    raise RuntimeError(job.get("error") or f"Generation {job['status']}")
                await asyncio.sleep(5)
        finally:
            self.current_jobs.pop(production_id, None)

    @classmethod
    def _agent_review_status(cls, result: AgentResult) -> str:
        """Classify a review by its decision token, not words in its explanation.

        A valid approval often explains that something is *not* a reason for
        rejection. Searching the whole paragraph for ``reject`` therefore
        incorrectly turned approvals into retries.
        """
        if cls._agy_placeholder(result):
            return "unavailable"
        decision = result.content.get("decision")
        decision_text = decision.strip().lower() if isinstance(decision, str) else ""
        head = re.split(r"[.:\n]", decision_text, maxsplit=1)[0].strip()
        if re.match(
            r"^(approve|approved|accept|accepted)[_-]with[_-]test[_-]exception\b",
            head,
        ):
            return "approved_exception"
        if re.match(r"^(approve|approved|accept|accepted|pass|passed)\b", head):
            return "approved"
        if re.match(r"^(reject|rejected|revise|regenerate|retry|fail|failed|blocked|request)\b", head):
            return "rejected"
        text = " ".join(
            str(result.content.get(key, "")) for key in ("decision", "next_action", "summary")
        ).lower()
        if re.search(r"\b(?:not approved|needs correction|reject(?:ed|ion)?|regenerat(?:e|ion)|retry|fail(?:ed|ure)?|blocked)\b", text):
            return "rejected"
        if re.search(r"\b(?:approve(?:d)?|accept(?:ed)?|pass(?:ed)?|valid|usable|ready|success)\b", text):
            return "approved"
        return "unknown"

    @classmethod
    def _agent_approved(cls, result: AgentResult) -> bool:
        return cls._agent_review_status(result) in {"approved", "approved_exception"}

    @classmethod
    def _joint_review_status(cls, agy: AgentResult, codex: AgentResult) -> tuple[str, str]:
        agy_status = cls._agent_review_status(agy)
        codex_status = cls._agent_review_status(codex)
        if codex_status == "approved_exception":
            return "approved", (
                "Codex accepted the asset under the user's explicit test exception; "
                "AGY's findings were preserved without triggering regeneration."
            )
        if agy_status == "rejected" or codex_status == "rejected":
            return "rejected", ""
        if agy_status == "approved" and codex_status == "approved":
            return "approved", ""
        if agy_status == "approved" and codex_status == "unavailable":
            return "approved", "Codex review was unavailable; AGY approved the asset, so no automatic regeneration was triggered."
        if codex_status == "approved" and agy_status == "unavailable":
            return "approved", "AGY review was unavailable; Codex approved the asset, so no automatic regeneration was triggered."
        return "pending", ""

    @staticmethod
    def _agy_contract_failure(exc: Exception) -> bool:
        """Recognize AGY responses rejected before the bridge can normalize them."""
        parts = [str(exc)]
        if isinstance(exc, AgentExecutionError):
            parts.extend([exc.stdout, exc.stderr])
        text = "\n".join(parts).lower()
        if "no valid structured response" in text:
            return True
        return "invalid arguments" in text and ("/issues" in text or "response" in text)

    @staticmethod
    def _agy_placeholder(result: AgentResult) -> bool:
        """Identify cached acknowledgements and echoed schemas instead of task results."""
        content = result.content.get("content")
        text = " ".join(str(result.content.get(key, "")) for key in ("decision", "next_action", "summary")).lower()
        def schema_placeholder(value: Any) -> bool:
            if not isinstance(value, dict) or set(value) != {"type"}:
                return False
            descriptor = value.get("type")
            return descriptor == "string" or descriptor == "number" or (
                isinstance(descriptor, list) and all(item in {"string", "number", "null"} for item in descriptor)
            )

        echoed_schema = any(schema_placeholder(result.content.get(key)) for key in ("summary", "decision", "content", "next_action"))
        echoed_issue_schema = result.content.get("issues") == [{"type": ["string", "null"]}]
        # Some AGY versions return the complete schema object rather than the
        # final result. It must never be persisted as a review or treated as an
        # approval, even when the object happens to contain a ``summary`` key.
        complete_schema = isinstance(result.content.get("properties"), dict) and isinstance(result.content.get("type"), str)
        if echoed_schema or echoed_issue_schema or complete_schema:
            return True
        return content in (None, {}) and (
            "successfully read" in text or "read the requested" in text
        ) and "task is complete" in text

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
        frame_paths = "\n".join(f"- {path}" for path in frames) or "- none"
        agy = await self._media_agent(production, f"""
Inspect the actual generated MP4 at {video}. The exact extracted review frames are:
{frame_paths}
Planned shot: {json.dumps(shot, ensure_ascii=False)}
Previous accepted clip: {previous}
Judge real motion (no sliding/backwards car movement or frozen walking), anatomy, glitches, lyric/story fit,
identity/location continuity when required, camera direction and cut compatibility. Check visible text only when
it is plainly readable to a normal viewer on a car, plate, sign, billboard, or garment; do not reject tiny or
incidental texture. Return APPROVE or REGENERATE and precise defects.
""", media_paths=[video, *frames])
        production = get_production(production["id"], private=True) or production
        codex = await self._other_agent(production, agy, f"""
Act as the equal co-producer and review the attached sampled frames together with AGY's full-video analysis.
Planned shot: {json.dumps(shot, ensure_ascii=False)}
AGY review: {json.dumps(agy.content, ensure_ascii=False)}
Approve only if the actual shot is usable in the music video. If regeneration is needed, produce a corrected
complete video prompt in content.corrected_prompt and identify the same concrete defects. Do not over-police
text that a normal viewer cannot read.
        """, images=frames, media_paths=[video, *frames])
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
            analysis_dir = self._folder(production_id) / "analysis"
            preflight_path = analysis_dir / "audio_preflight.json"
            preflight_path.write_text(
                json.dumps({
                    "song_path": production["song_path"],
                    "metadata": audio_metadata,
                    "source": "backend.ffprobe",
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            analysis_request = f"""
Analyze the actual song file and lyrics. Return duration, BPM and confidence, meter, genre, sections,
energy curve, vocal entrances, instrumental breaks, transitions, estimated timestamped lyric map,
and concrete visual opportunities. Mark uncertain timing as estimated. Put the full analysis in content.
The bridge already performed this basic audio preflight:
{json.dumps(audio_metadata, ensure_ascii=False)}
The preflight report is also saved at {preflight_path}. Use a native media/audio capability only if it
can actually decode the file. Do not use view_file on the binary MP3; if native audio inspection is not
available, use the preflight report and lyrics, mark BPM/sections/lyric timing as estimated, and still
return the required structured response. Do not run shell commands or ask for command permission.
Put the full analysis in content.
"""
            try:
                analysis = await self._media_agent(production, analysis_request)
            except Exception as exc:
                diagnostic_path = self._record_agent_failure(production_id, "song_analysis", exc)
                add_message(
                    production_id, "system", "all", "status",
                    "AGY could not complete song inspection; the backend audio preflight was preserved and the production will continue with limited analysis.",
                    {"fallback": True, "diagnostic_path": str(diagnostic_path), "reason": str(exc)[:1600]},
                )
                fallback = self._limited_audio_analysis(audio_metadata, exc)
                analysis = AgentResult(
                    "agy", fallback, "backend audio preflight fallback", None,
                    production.get("agy_model", ""), production.get("agy_effort", ""),
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
            codex = await self._codex(production, f"""
Create the complete shot-by-shot MiniMax H3 prompt package from the approved treatment and references.
The user selected project-wide generation defaults: Turbo {production.get('generation_turbo_profile', 'v1')},
{production.get('generation_steps', 4)} whole steps, resolution shape {production.get('generation_aspect_ratio', '16:9')},
and this duration-to-MP policy: {json.dumps(production.get('generation_megapixel_rules', []), ensure_ascii=False)}.
Treat these as authoritative for every initial shot; do not replace the requested MP with a calculated
pixel-product and do not choose a different Turbo profile, step count, resolution shape, or duration rule.
For each shot, choose the MP from the first rule whose max_duration covers the shot's whole-number duration.
The top-level content object MUST contain a non-empty `shots` array. Every shot must contain title, prompt,
duration (0.5-15 seconds), continuity (hard_cut or sequential), megapixels, aspect_ratio, camera movement,
visible action, lyric timestamps, and acceptance criteria. Use I2V for every shot that has an approved image
reference, including hard-cut location resets; use sequential continuity only when the previous accepted last
frame should open the next shot. Use T2V only when the production has no usable image reference for that shot.
Production does not use R2V yet: if a scene needs a reference, select the relevant image by its exact
`reference_names` (or `reference_ids`) and use I2V. Every shot must include at least one relevant image
reference whenever approved image references exist; never label a reference-backed shot as T2V. Every shot must also include `audio_mode` (`silent` or `lip_sync`), `audio_source` (`song` or
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
                production,
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
            available_image_references = [
                reference for reference in list_references(production_id, private=True)
                if reference.get("kind") == "image"
            ]
            previous_video: Path | None = None
            for shot in shots:
                # A running production may edit future planned shots. Reload
                # each shot immediately before processing it so those edits
                # are not lost to the snapshot taken at stage start.
                latest_shot = next(
                    (item for item in list_shots(production_id, private=True) if item["id"] == shot["id"]),
                    None,
                )
                if latest_shot:
                    shot = latest_shot
                if shot["status"] == "accepted" and shot.get("accepted_attempt"):
                    accepted = next((item for item in shot["attempts"] if item["attempt"] == shot["accepted_attempt"]), None)
                    accepted_path = self._current_attempt_video(accepted) if accepted else None
                    if accepted_path:
                        previous_video = accepted_path
                        continue
                assigned_image_references = [
                    reference for reference_id in shot.get("reference_ids", [])
                    if (reference := get_reference(production_id, reference_id, private=True))
                    and reference.get("kind") == "image"
                ]
                if available_image_references and not assigned_image_references:
                    # Migrate shot plans created before reference assignments
                    # became explicit. The primary image anchor is used only
                    # to create a shot-specific opening frame; it is never
                    # sent directly to the I2V workflow.
                    shot = {**shot, "reference_ids": [available_image_references[0]["id"]]}
                    assigned_image_references = [available_image_references[0]]
                    update_shot(shot["id"], reference_ids=shot["reference_ids"])
                    add_message(
                        production_id, "system", "all", "status",
                        f"Assigned the primary visual reference to {shot['title']} so its I2V opening scene can be prepared.",
                        {"shot_id": shot["id"], "reference_id": available_image_references[0]["id"], "migrated": True},
                    )
                if assigned_image_references and shot["mode"] in {"text", "reference"}:
                    # A shot with assigned visual anchors is an I2V shot in
                    # this production flow. T2V remains available only when
                    # the shot intentionally has no image anchors.
                    shot = {**shot, "mode": "opening"}
                    update_shot(shot["id"], mode="opening")
                    add_message(
                        production_id, "system", "all", "status",
                        f"{shot['title']} has assigned visual references; preparing a generated I2V opening frame instead of T2V.",
                        {"shot_id": shot["id"], "reference_count": len(assigned_image_references)},
                    )
                existing = shot["attempts"][-1] if shot["attempts"] else None
                attempt_number = int(existing["attempt"] if existing else 0)
                pending_attempt = existing if existing and existing["status"] in {"queued", "generating"} and existing.get("job_id") else None
                pending_review = (
                    existing if existing and existing["status"] == "reviewing"
                    and self._current_attempt_video(existing) else None
                )
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
                        video = self._current_attempt_video(attempt)
                        if not video:
                            raise RuntimeError(f"{shot['title']} review video is missing from its current asset location")
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
                        # Mark the current shot before preparing its opening
                        # frame. This closes the small race where an active
                        # shot still looked planned while its scene reference
                        # was being composed, while future planned shots stay
                        # editable from the UI.
                        update_shot(shot["id"], status="preparing")
                        shot = {**shot, "status": "preparing"}
                        attempt_number += 1
                        opening_frame: Path | None = None
                        opening_frame_artifact: Path | None = None
                        if shot["mode"] == "opening":
                            continuity_frame: Path | None = None
                            if previous_video and previous_video.exists() and shot["continuity"] == "sequential":
                                continuity_frame = INPUT / f"production_{production_id}_shot_{shot['shot_index'] - 1:03d}_last.png"
                                dimensions = normalize_generation_settings(
                                    "opening", engine=shot["engine"], steps=int(shot["steps"]),
                                    megapixels=float(shot["megapixels"]), aspect_ratio=shot["aspect_ratio"],
                                    turbo_profile=shot["turbo_profile"],
                                )
                                await asyncio.to_thread(
                                    extract_last_frame, previous_video, continuity_frame, dimensions.width, dimensions.height,
                                )
                            if assigned_image_references:
                                # A sequential shot still needs the previous
                                # last frame for continuity, but assigned scene
                                # references must be composed into a fresh
                                # opening frame instead of being bypassed.
                                opening_frame_artifact, opening_frame = await self._generate_shot_opening_frame(
                                    production, shot, attempt_number, continuity_frame,
                                )
                            elif continuity_frame:
                                # With no assigned scene references, the prior
                                # accepted last frame is the only valid I2V
                                # opening source.
                                opening_frame = continuity_frame
                                opening_frame_artifact = continuity_frame
                            else:
                                raise RuntimeError(f"{shot['title']} requires an opening image or previous accepted clip")
                        attempt = create_shot_attempt(
                            shot["id"], attempt_number,
                            str(opening_frame_artifact or opening_frame) if (opening_frame_artifact or opening_frame) else None,
                        )
                        queued_shot = {**shot, "production_id": production_id}
                        job_id = self._queue_job(queued_shot, opening_frame)
                        update_shot_attempt(attempt["id"], job_id=job_id, status="generating")
                        update_shot(shot["id"], status="generating")
                        add_message(production_id, "system", "all", "status",
                                    f"Generating {shot['title']} · attempt {attempt_number} · {shot['duration']}s · {shot['megapixels']} MP")
                    if video is None:
                        try:
                            job = await self._wait_for_job(production_id, job_id)
                        except ProductionInterruption:
                            update_shot_attempt(
                                attempt["id"], status="interrupted",
                                error="Generation interrupted by user intervention",
                            )
                            update_shot(shot["id"], status="planned")
                            raise
                        except Exception as exc:
                            update_shot_attempt(attempt["id"], status="failed", error=str(exc)[:8000])
                            update_shot(shot["id"], status="failed")
                            raise
                        video = self._current_job_video(job.get("id"), job.get("output_path"))
                        if not video:
                            raise RuntimeError(f"{shot['title']} completed but its video is missing from its current asset location")
                        review_dir = self._folder(production_id) / "shots" / f"shot_{shot['shot_index']:03d}" / f"attempt_{attempt_number:02d}" / "review_frames"
                        frames = await asyncio.to_thread(extract_review_frames, video, review_dir, 1.0, 48)
                        update_shot_attempt(attempt["id"], status="reviewing", output_path=str(video), frames=[str(path) for path in frames])
                        update_shot(shot["id"], status="reviewing")
                        add_event(production_id, "shot.reviewing", {"shot_id": shot["id"], "attempt": attempt_number})
                    if self._control_requested(production_id):
                        return
                    agy, codex = await self._review_shot(production, shot, video, frames, previous_video)
                    review_status, review_note = self._joint_review_status(agy, codex)
                    approved = review_status == "approved"
                    defect_key = None if approved else self._defect_key(agy, codex)
                    update_shot_attempt(attempt["id"], status="accepted" if approved else "rejected",
                                        agy_review=agy.content, codex_review=codex.content, defect_key=defect_key)
                    if approved:
                        update_shot(shot["id"], status="accepted", accepted_attempt=attempt_number)
                        previous_video = video
                        add_message(
                            production_id, "system", "all", "status",
                            f"{shot['title']} passed review. {review_note or 'Codex and AGY approved the shot.'}",
                            {"shot_id": shot["id"], "attempt": attempt_number, "review_status": review_status},
                        )
                        break
                    if review_status == "pending":
                        update_shot_attempt(
                            attempt["id"], status="review_pending", defect_key="incomplete-agent-review",
                        )
                        update_shot(shot["id"], status="review_pending")
                        update_production(production_id, status="awaiting_user", stage="shot_review")
                        add_decision(
                            production_id, "shot_review", f"Incomplete review for {shot['title']}",
                            "The generated shot was preserved, but one or both agent reviews did not return a clear approval or rejection. User direction is required; it was not automatically regenerated.",
                            {"shot_id": shot["id"], "attempt": attempt_number,
                             "agy_status": self._agent_review_status(agy),
                             "codex_status": self._agent_review_status(codex),
                             "agy": agy.content, "codex": codex.content},
                        )
                        self._checkpoint(production_id)
                        return
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
                clip = self._current_attempt_video(accepted) if accepted else None
                if not clip:
                    raise RuntimeError(f"{shot['title']} has no accepted clip")
                clips.append(clip)
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
""", media_paths=[final_video, *frames])
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
            final_video = self._folder(production_id) / "assembly" / "final_with_song.mp4"
            review_dir = self._folder(production_id) / "assembly" / "review_frames"
            review_frames = sorted(
                path for path in review_dir.glob("*")
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            )
            if final_video.is_file() and not review_frames:
                review_frames = await asyncio.to_thread(
                    extract_review_frames, final_video, review_dir, 0.5, 24,
                )
            # AGY must receive the actual artifact it is asked to review. Keep
            # a small representative frame set for the visual context and keep
            # the full MP4 path explicit so it can inspect the complete film.
            if len(review_frames) > 12:
                stride = max(1, len(review_frames) // 12)
                review_frames = review_frames[::stride][:12]
            review_media = self._reference_image_paths(production) + review_frames
            seen_media: set[str] = set()
            review_media = [
                path for path in review_media
                if not (str(path.resolve()) in seen_media or seen_media.add(str(path.resolve())))
            ]
            agy = await self._agy(production, f"""
Review Codex's repair plan against the actual final video and the user's rejection. The complete final video
is at {final_video}. Representative review frames are attached from {review_dir}. Inspect the actual media,
then confirm or amend exactly which shot indexes need regeneration and provide corrected prompts. Return the
final list in content.shots.
Codex plan: {json.dumps(codex.content, ensure_ascii=False)}
""", images=review_media)
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
