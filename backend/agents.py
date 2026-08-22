from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from PIL import Image, UnidentifiedImageError

from .config import (AGENT_HEARTBEAT_SECONDS, AGENT_TIMEOUT_SECONDS, AGY_COMMAND, CODEX_COMMAND,
                     AGY_DEFAULT_EFFORT, AGY_DEFAULT_MODEL, PRODUCTIONS, ROOT)


CODEX_FALLBACK_MODELS = [
    {"id": "gpt-5.6-sol", "name": "GPT-5.6 Sol", "efforts": ["none", "low", "medium", "high", "xhigh", "max"]},
    {"id": "gpt-5.6-terra", "name": "GPT-5.6 Terra", "efforts": ["none", "low", "medium", "high", "xhigh", "max"]},
    {"id": "gpt-5.6-luna", "name": "GPT-5.6 Luna", "efforts": ["none", "low", "medium", "high", "xhigh", "max"]},
]

AGENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
}

# Keep this text in one place. The AGY CLI has rejected valid production turns
# when a field-level schema disagreed with the model's legacy response shape, so
# the transport schema above intentionally validates only the JSON object. This
# contract is the application-level validation instruction; the parser below
# normalizes legacy values at the bridge boundary.
AGY_RESPONSE_CONTRACT = """
Return exactly one actual task-result JSON object, never the response schema.
It must contain these keys:
summary (plain string), decision (plain string), content (the actual task
payload as an object/array/string/null), issues (an array of concrete issue
objects, or [] when there are no issues), next_action (plain string),
confidence (number or null), and requires_user (boolean).
Never return a field definition such as {\"type\":\"string\"}; never return
issues as a plain string; never wrap the object in Markdown fences or add
commentary outside the JSON.
Example shape only: {\"summary\":\"Reviewed\",\"decision\":\"APPROVE\",\"content\":{\"findings\":\"actual findings\"},\"issues\":[],\"next_action\":\"continue\",\"confidence\":0.9,\"requires_user\":false}
""".strip()

# Codex's ``--output-schema`` uses strict structured outputs.  Keep the
# executable production payload inside JSON-encoded strings so the schema can
# remain strict without trying to describe every pipeline-specific content
# object (treatment, references, shots, and so on).
CODEX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "decision", "content", "issues", "next_action", "confidence", "requires_user"],
    "properties": {
        "summary": {"type": "string"},
        "decision": {"type": "string"},
        "content": {"type": ["string", "null"]},
        "issues": {"type": ["string", "null"]},
        "next_action": {"type": "string"},
        "confidence": {"type": ["number", "null"]},
        "requires_user": {"type": "boolean"},
    },
}


@dataclass
class AgentResult:
    participant: str
    content: dict[str, Any]
    raw: str
    session_id: str | None
    model: str
    effort: str


class AgentExecutionError(RuntimeError):
    """A CLI agent failed or did not return the required structured result.

    The CLI streams useful diagnostics through stdout, especially AGY's
    ``result.status == ERROR`` event.  Keep those streams attached to the
    exception so the production orchestrator can persist them without exposing
    the entire event stream in the browser.
    """

    def __init__(
        self,
        message: str,
        *,
        runtime: str,
        command: list[str],
        stdout: str = "",
        stderr: str = "",
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.runtime = runtime
        self.command = list(command)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


AgentOutputCallback = Callable[[str, str], Awaitable[None]]
AgentHeartbeatCallback = Callable[[float, float, str, str], Awaitable[None]]


def _event_label(channel: str, line: str) -> str:
    """Return a safe event label for timeout diagnostics.

    Do not include raw CLI output here: it can contain structured agent text or
    private reasoning. The live callback is responsible for any approved
    user-facing summary.
    """
    stripped = line.strip()
    if not stripped:
        return "no CLI output"
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return f"{channel or 'CLI'} output"
    if not isinstance(event, dict):
        return f"{channel or 'CLI'} event"
    event_type = str(event.get("type") or event.get("event") or "event").replace("_", " ")
    item = event.get("item") if isinstance(event.get("item"), dict) else event
    item_type = str(item.get("type") or "").replace("_", " ") if isinstance(item, dict) else ""
    return f"{event_type}{f' / {item_type}' if item_type and item_type != event_type else ''}"


def _structured_agent_error(stdout: str) -> str | None:
    """Extract a concise error from a streamed CLI result event."""

    def message_from(value: Any) -> str:
        if isinstance(value, str):
            try:
                return message_from(json.loads(value))
            except json.JSONDecodeError:
                return value
        if isinstance(value, dict):
            nested = value.get("error")
            if nested is not None:
                return message_from(nested)
            return str(value.get("message") or value.get("detail") or value)
        return str(value)

    for line in reversed(stdout.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") in {"error", "turn.failed"}:
            detail = event.get("message") or event.get("error") or "Agent returned an error"
            return message_from(detail)
        result = event.get("result") if isinstance(event, dict) else None
        if not isinstance(result, dict) or str(result.get("status", "")).upper() != "ERROR":
            continue
        message = str(result.get("error") or "Agent returned an error")
        conversation = result.get("conversation_id")
        if conversation:
            return f"{message} (conversation {conversation})"
        return message
    return None


def _agent_failure_message(runtime: str, stdout: str, stderr: str, returncode: int | None) -> str:
    structured = _structured_agent_error(stdout)
    if structured:
        return f"{runtime} CLI failed: {structured}"
    details = (stderr or stdout).strip()
    if details:
        return f"{runtime} CLI failed: {details[-2000:]}"
    if returncode is not None:
        return f"{runtime} CLI exited with code {returncode}"
    return f"{runtime} CLI failed without diagnostic output"


def _command_path(command: str) -> str | None:
    return shutil.which(command)


def agent_health() -> dict[str, Any]:
    return {
        "codex": {"installed": bool(_command_path(CODEX_COMMAND)), "command": CODEX_COMMAND},
        "agy": {"installed": bool(_command_path(AGY_COMMAND)), "command": AGY_COMMAND},
    }


MODEL_CATALOG_TTL_SECONDS = 300
_catalog_lock = threading.Lock()
_catalog_snapshot: dict[str, Any] | None = None
_catalog_fetched_at = 0.0


def _json_payload(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from CLI output that contains models."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            payload, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("models"), list):
            return payload
    return None


def _run_model_command(command: list[str], timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace", shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def discover_codex_models(timeout: int = 30) -> list[dict[str, Any]]:
    """Query the authenticated Codex CLI's live model catalog.

    `codex debug models` is the CLI's machine-readable catalog command. The
    persistent models cache is intentionally not read; the caller gets the
    current catalog returned by the installed CLI.
    """
    executable = _command_path(CODEX_COMMAND)
    if executable:
        payload = _json_payload(_run_model_command([executable, "debug", "models"], timeout))
        if payload:
            models = []
            for item in payload["models"]:
                # The CLI can mark a model as hidden while still exposing it
                # for API/CLI use.  The Production settings page should show
                # every model the installed CLI reports as usable; only
                # entries explicitly marked unavailable are excluded.
                if item.get("supported_in_api") is False or not item.get("slug"):
                    continue
                efforts = [
                    str(level["effort"]) for level in item.get("supported_reasoning_levels", [])
                    if isinstance(level, dict) and level.get("effort")
                ]
                models.append({
                    "id": str(item["slug"]),
                    "name": str(item.get("display_name") or item["slug"]),
                    "efforts": efforts or ["low", "medium", "high"],
                    "default_effort": str(item.get("default_reasoning_level") or (efforts[0] if efforts else "medium")),
                    "source": "codex-cli",
                })
            if models:
                return models
    return [{**item, "source": "fallback"} for item in CODEX_FALLBACK_MODELS]


def discover_agy_models(timeout: int = 20) -> list[dict[str, Any]]:
    executable = _command_path(AGY_COMMAND)
    if not executable:
        return []
    try:
        result = subprocess.run(
            [executable, "models"], capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return []
    models = []
    for line in result.stdout.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        model_id, display = line.split("\t", 1)
        model_id = model_id.strip()
        display = display.strip()
        efforts = ["low", "medium", "high"]
        encoded = next((value for value in ("low", "medium", "high") if model_id.endswith("-" + value)), None)
        models.append({"id": model_id, "name": display or model_id, "efforts": [encoded] if encoded else efforts, "source": "agy-cli"})
    return models


def model_catalog(force_refresh: bool = False) -> dict[str, Any]:
    """Return a live CLI catalog, reusing only a short-lived in-memory snapshot."""
    global _catalog_snapshot, _catalog_fetched_at
    now = time.monotonic()
    if not force_refresh and _catalog_snapshot and now - _catalog_fetched_at < MODEL_CATALOG_TTL_SECONDS:
        return _catalog_snapshot
    with _catalog_lock:
        now = time.monotonic()
        if not force_refresh and _catalog_snapshot and now - _catalog_fetched_at < MODEL_CATALOG_TTL_SECONDS:
            return _catalog_snapshot
        snapshot = {
        "runtimes": [
            {"id": "codex", "name": "Codex CLI", "capabilities": ["text", "images", "audio", "video"]},
            {"id": "agy", "name": "AGY CLI", "capabilities": ["text", "images", "audio", "video"]},
        ],
        "codex": discover_codex_models(), "agy": discover_agy_models(),
        "fetched_at": time.time(),
        "sources": {"codex": "codex-cli", "agy": "agy-cli"},
        }
        _catalog_snapshot = snapshot
        _catalog_fetched_at = time.monotonic()
        return snapshot


def _schema_path(production_id: str) -> Path:
    folder = PRODUCTIONS / production_id / "agent-context"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "response.schema.json"
    # Refresh the checkpoint copy on every invocation. Older productions may
    # contain the pre-strict schema, which some AGY backends reject before the
    # task starts.
    path.write_text(json.dumps(AGENT_SCHEMA, indent=2), encoding="utf-8")
    return path


def _codex_schema_path(production_id: str) -> Path:
    folder = PRODUCTIONS / production_id / "agent-context"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "codex-response.schema.json"
    path.write_text(json.dumps(CODEX_SCHEMA, indent=2), encoding="utf-8")
    return path


def _extract_session(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("thread_id", "conversation_id", "session_id", "project_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = _extract_session(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _extract_session(value)
            if found:
                return found
    return None


def _json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    try:
        value = json.loads(stripped)
        if isinstance(value, dict) and "summary" in value:
            return value
    except json.JSONDecodeError:
        pass

    # Some CLI runtimes append a second JSON finish/tool marker after the
    # actual task result.  ``json.loads`` correctly rejects that concatenated
    # stream, while the old regex could not reliably match nested payloads.
    # Decode complete JSON values from every object boundary and keep the
    # first actual task result; trailing markers such as ``toolAction`` are
    # intentionally ignored.
    decoder = json.JSONDecoder()
    for index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(stripped, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "summary" in value:
            return value
    return None


def _extract_result(stdout: str) -> tuple[dict[str, Any], str | None]:
    session_id = None
    texts: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            texts.append(line)
            continue
        session_id = session_id or _extract_session(event)
        sources: list[dict[str, Any]] = [event] if isinstance(event, dict) else []
        item = event.get("item") if isinstance(event, dict) else None
        if isinstance(item, dict):
            sources.append(item)
        result = event.get("result") if isinstance(event, dict) else None
        if isinstance(result, dict):
            # AGY's final envelope stores the actual JSON task result in
            # ``result.response`` rather than in the top-level event.
            sources.append(result)
        for source in sources:
            for key in ("result", "response", "text", "output_text", "message", "content"):
                value = source.get(key)
                if isinstance(value, str):
                    texts.append(value)
                elif isinstance(value, dict):
                    for nested_key in ("response", "text", "content"):
                        nested = value.get(nested_key)
                        if isinstance(nested, str):
                            texts.append(nested)
        direct = _json_object(json.dumps(event, ensure_ascii=False))
        if direct:
            return direct, session_id
    for text in reversed(texts + [stdout]):
        parsed = _json_object(text)
        if parsed:
            return parsed, session_id
    raise RuntimeError("Agent returned no valid structured response")


def _decode_structured_value(value: Any) -> Any:
    """Decode JSON strings and common CLI text wrappers inside agent payloads."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped[0] not in "[{":
            return value
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError as error:
            candidates = []
            # Some resumed CLI turns serialize JSON with Python-style escaped
            # apostrophes (\\') inside otherwise valid JSON strings.
            if "\\'" in stripped:
                candidates.append(stripped.replace("\\'", "'"))
            # Codex has also emitted an extra object closer immediately before
            # an array closer (``}],`` instead of ``],``). Recover that safe,
            # localized typo so a saved checkpoint remains resumable.
            if error.pos + 1 < len(stripped) and stripped[error.pos:error.pos + 2] == "}]":
                candidates.append(stripped[:error.pos] + stripped[error.pos + 1:])
            decoded = None
            for candidate in candidates:
                try:
                    decoded = json.loads(candidate)
                    break
                except json.JSONDecodeError:
                    continue
            if decoded is None:
                return value
        return _decode_structured_value(decoded)
    if isinstance(value, dict):
        if len(value) == 1:
            for wrapper in ("text", "content", "output_text"):
                wrapped = value.get(wrapper)
                if isinstance(wrapped, str):
                    decoded = _decode_structured_value(wrapped)
                    if isinstance(decoded, (dict, list)):
                        return decoded
        return {key: _decode_structured_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_structured_value(item) for item in value]
    return value


def _normalize_codex_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Decode strict-schema string fields into the legacy production shape."""
    normalized = dict(payload)
    raw_content = _decode_structured_value(normalized.get("content"))
    if raw_content is None:
        normalized["content"] = {}
    elif isinstance(raw_content, str):
        try:
            decoded = json.loads(raw_content)
        except json.JSONDecodeError:
            decoded = {"text": raw_content}
        normalized["content"] = decoded if isinstance(decoded, dict) else {"value": decoded}
    elif isinstance(raw_content, (dict, list)):
        normalized["content"] = raw_content
    elif not isinstance(raw_content, dict):
        normalized["content"] = {"value": raw_content}

    raw_issues = normalized.get("issues")
    if raw_issues is None:
        normalized["issues"] = []
    elif isinstance(raw_issues, str):
        try:
            decoded_issues = json.loads(raw_issues)
        except json.JSONDecodeError:
            decoded_issues = [{"message": raw_issues}]
        normalized["issues"] = decoded_issues if isinstance(decoded_issues, list) else [decoded_issues]
    elif not isinstance(raw_issues, list):
        normalized["issues"] = [raw_issues]
    return normalized


class AgentProcessManager:
    def __init__(self) -> None:
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    def has_active_process(self, production_id: str) -> bool:
        """Return whether this manager still owns an agent subprocess."""
        return production_id in self.processes

    async def cancel(self, production_id: str) -> bool:
        """Stop an agent and every process it spawned.

        On Windows the configured Codex command commonly resolves to an npm
        ``.cmd`` shim.  Terminating that shim alone leaves the child
        ``node/codex.exe`` process alive with the agent's stdout pipes open;
        the production task then waits forever and an intervention appears to
        be ignored.  ``taskkill /T`` is deliberately scoped to this tracked
        process PID so it cannot affect ComfyUI or another production.
        """
        process = self.processes.get(production_id)
        if not process:
            return False
        pid = process.pid
        if os.name == "nt":
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                # Fall through to the asyncio process handle below.  This is
                # mainly a fallback for restricted Windows environments where
                # taskkill is unavailable.
                pass
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
        try:
            await asyncio.wait_for(process.wait(), timeout=8)
        except asyncio.TimeoutError:
            if os.name == "nt":
                try:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
            else:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
            if process.returncode is None:
                process.kill()
            await process.wait()
        return True

    async def _run(
        self,
        production_id: str,
        command: list[str],
        prompt: str | None = None,
        cwd: Path | None = None,
        on_output: AgentOutputCallback | None = None,
        on_heartbeat: AgentHeartbeatCallback | None = None,
    ) -> str:
        lock = self.locks.setdefault(production_id, asyncio.Lock())
        async with lock:
            return await self._run_locked(production_id, command, prompt, cwd, on_output, on_heartbeat)

    async def _run_locked(
        self,
        production_id: str,
        command: list[str],
        prompt: str | None = None,
        cwd: Path | None = None,
        on_output: AgentOutputCallback | None = None,
        on_heartbeat: AgentHeartbeatCallback | None = None,
    ) -> str:
        env = os.environ.copy()
        spawn_options: dict[str, Any] = {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": str((cwd or ROOT).resolve()),
            "env": env,
        }
        if os.name != "nt":
            # Give cancellation a process group to terminate, including any
            # CLI child processes created by a runtime wrapper.
            spawn_options["start_new_session"] = True
        process = await asyncio.create_subprocess_exec(*command, **spawn_options)
        self.processes[production_id] = process
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        started_at = time.monotonic()
        last_output_at = started_at
        last_output_channel = ""
        last_output_line = ""

        async def consume(stream: asyncio.StreamReader, target: list[str], channel: str) -> None:
            nonlocal last_output_at, last_output_channel, last_output_line
            while True:
                chunk = await stream.readline()
                if not chunk:
                    return
                line = chunk.decode("utf-8", errors="replace")
                target.append(line)
                if line.strip():
                    last_output_at = time.monotonic()
                    last_output_channel = channel
                    last_output_line = line
                if on_output:
                    try:
                        await on_output(channel, line)
                    except Exception:
                        # A UI trace must never terminate the agent process.
                        pass

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(AGENT_HEARTBEAT_SECONDS)
                if not on_heartbeat:
                    continue
                elapsed = max(0.0, time.monotonic() - started_at)
                idle = max(0.0, time.monotonic() - last_output_at)
                try:
                    await on_heartbeat(elapsed, idle, last_output_channel, last_output_line)
                except Exception:
                    # A status update must never terminate the agent process.
                    pass

        heartbeat_task: asyncio.Task | None = None
        try:
            if process.stdin is not None:
                if prompt is not None:
                    process.stdin.write(prompt.encode("utf-8"))
                    await process.stdin.drain()
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionError):
                    pass
            stdout_task = asyncio.create_task(consume(process.stdout, stdout_lines, "stdout"))
            stderr_task = asyncio.create_task(consume(process.stderr, stderr_lines, "stderr"))
            if on_heartbeat:
                heartbeat_task = asyncio.create_task(heartbeat())
            try:
                await asyncio.wait_for(
                    asyncio.gather(stdout_task, stderr_task, process.wait()),
                    timeout=AGENT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                stdout_task.cancel()
                stderr_task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                raise
        except asyncio.TimeoutError as exc:
            elapsed = max(0.0, time.monotonic() - started_at)
            idle = max(0.0, time.monotonic() - last_output_at)
            label = _event_label(last_output_channel, last_output_line)
            raise RuntimeError(
                f"Agent timed out after {AGENT_TIMEOUT_SECONDS} seconds; "
                f"last event: {label}; no new CLI output for {round(idle)} seconds"
            ) from exc
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            self.processes.pop(production_id, None)
        out = "".join(stdout_lines)
        err = "".join(stderr_lines)
        if process.returncode:
            raise AgentExecutionError(
                _agent_failure_message(Path(command[0]).name, out, err, process.returncode),
                runtime=Path(command[0]).name,
                command=command,
                stdout=out,
                stderr=err,
                returncode=process.returncode,
            )
        return out

    async def invoke_codex(
        self, production_id: str, prompt: str, model: str, effort: str,
        session_id: str | None = None, images: list[Path] | None = None,
        on_output: AgentOutputCallback | None = None,
        on_heartbeat: AgentHeartbeatCallback | None = None,
        extra_dirs: list[Path] | None = None,
    ) -> AgentResult:
        executable = _command_path(CODEX_COMMAND)
        if not executable:
            raise RuntimeError("Codex CLI is not installed or not on PATH")
        schema = _codex_schema_path(production_id)
        if session_id:
            command = [executable, "exec", "resume", session_id, "--json",
                       "--output-schema", str(schema)]
        else:
            # Current Codex CLI versions no longer accept the old
            # ``--ask-for-approval never`` pair.  Read-only sandboxing already
            # prevents production agents from mutating the workspace, so do
            # not add an approval flag that would either fail validation or
            # widen the sandbox.
            command = [executable, "exec", "--json", "--output-schema", str(schema),
                       "--sandbox", "read-only",
                       "--skip-git-repo-check", "-C", str(PRODUCTIONS / production_id)]
        command.extend(["--model", model, "-c", f'model_reasoning_effort="{effort}"'])
        for directory in extra_dirs or []:
            resolved = Path(directory).resolve()
            if resolved.is_dir() and str(resolved) != str(PRODUCTIONS / production_id):
                command.extend(["--add-dir", str(resolved)])
        for image in images or []:
            command.extend(["--image", str(image)])
        command.append("-")
        prompt = prompt.rstrip() + """

CLI response contract: return only one valid JSON object with the keys
summary, decision, content, issues, next_action, confidence, and requires_user.
The strict output schema requires `content` to be a JSON-encoded string containing
the complete structured payload, and `issues` to be a JSON-encoded string containing
an array of issue objects. Use null when either has no value. Do not wrap the object
in Markdown fences or add commentary outside the JSON.
"""
        raw = await self._run(
            production_id, command, prompt, PRODUCTIONS / production_id, on_output, on_heartbeat,
        )
        try:
            content, found_session = _extract_result(raw)
            content = _normalize_codex_result(content)
        except RuntimeError as exc:
            raise AgentExecutionError(
                f"codex CLI returned no valid structured response: {exc}",
                runtime="codex", command=command, stdout=raw, returncode=0,
            ) from exc
        return AgentResult("codex", content, raw, found_session or session_id, model, effort)

    async def invoke_agy(
        self, production_id: str, prompt: str, model: str, effort: str,
        session_id: str | None = None,
        on_output: AgentOutputCallback | None = None,
        on_heartbeat: AgentHeartbeatCallback | None = None,
        extra_dirs: list[Path] | None = None,
    ) -> AgentResult:
        executable = _command_path(AGY_COMMAND)
        if not executable:
            raise RuntimeError("AGY CLI is not installed or not on PATH")
        schema = _schema_path(production_id)
        request_dir = PRODUCTIONS / production_id / "agent-context"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_path = request_dir / f"agy-request-{uuid.uuid4().hex}.md"
        # Production is an explicitly user-authorized local workflow. AGY must be
        # able to inspect audio/video with its own tools without stopping for an
        # interactive approval prompt that the bridge cannot answer. Do not put
        # this invocation in the restricted sandbox: the production folder is
        # still the only workspace exposed to the agent through --add-dir.
        command = [executable, "--print", f"Read {request_path} and return only the required structured response.",
                   "--output-format", "stream-json", "--json-schema", str(schema),
                   "--model", model, "--effort", effort, "--mode", "accept-edits",
                   "--dangerously-skip-permissions", "--add-dir", str(PRODUCTIONS / production_id),
                   "--print-timeout", f"{AGENT_TIMEOUT_SECONDS}s"]
        for directory in extra_dirs or []:
            resolved = Path(directory).resolve()
            if resolved.is_dir() and str(resolved) != str((PRODUCTIONS / production_id).resolve()):
                command.extend(["--add-dir", str(resolved)])
        if session_id:
            command.extend(["--conversation", session_id])
        request_path.write_text(prompt.rstrip() + "\n\n" + AGY_RESPONSE_CONTRACT + "\n", encoding="utf-8")
        raw = await self._run(
            production_id, command, cwd=PRODUCTIONS / production_id,
            on_output=on_output, on_heartbeat=on_heartbeat,
        )
        try:
            content, found_session = _extract_result(raw)
            content = _normalize_codex_result(content)
        except RuntimeError as exc:
            raise AgentExecutionError(
                f"agy CLI returned no valid structured response: {exc}",
                runtime="agy", command=command, stdout=raw, returncode=0,
            ) from exc
        return AgentResult("agy", content, raw, found_session or session_id, model, effort)

    async def invoke(
        self, runtime: str, participant: str, production_id: str, prompt: str,
        model: str, effort: str, session_id: str | None = None,
        images: list[Path] | None = None,
        on_output: AgentOutputCallback | None = None,
        on_heartbeat: AgentHeartbeatCallback | None = None,
        extra_dirs: list[Path] | None = None,
    ) -> AgentResult:
        if runtime == "codex":
            result = await self.invoke_codex(
                production_id, prompt, model, effort, session_id, images, on_output, on_heartbeat, extra_dirs,
            )
        elif runtime == "agy":
            # AGY reads media by path from the production directory. Image
            # paths are also included explicitly in the task when supplied.
            if images:
                prompt += "\n\nAttached image paths:\n" + "\n".join(str(path) for path in images)
            result = await self.invoke_agy(
                production_id, prompt, model, effort, session_id, on_output, on_heartbeat, extra_dirs,
            )
        else:
            raise RuntimeError(f"Unsupported agent runtime: {runtime}")
        result.participant = participant
        return result

    async def generate_reference_image(
        self, production_id: str, prompt: str, output_path: Path, model: str, effort: str,
        provider: str = "auto", agy_model: str | None = None, agy_effort: str | None = None,
        source_images: list[Path] | None = None,
    ) -> Path:
        """Generate a project-bound still with Codex ImageGen or AGY fallback."""
        if provider not in {"auto", "codex", "agy"}:
            raise ValueError("Image provider must be auto, codex, or agy")
        failures: list[str] = []
        if provider in {"auto", "codex"}:
            try:
                return await self._generate_reference_image_codex(
                    production_id, prompt, output_path, model, effort, source_images or [],
                )
            except Exception as exc:
                if provider == "codex":
                    raise
                failures.append(f"Codex ImageGen: {exc}")
        if provider in {"auto", "agy"}:
            try:
                return await self._generate_reference_image_agy(
                    production_id, prompt, output_path,
                    agy_model or AGY_DEFAULT_MODEL, agy_effort or AGY_DEFAULT_EFFORT,
                    source_images or [],
                )
            except Exception as exc:
                if provider == "agy":
                    raise
                failures.append(f"AGY ImageGen: {exc}")
        raise RuntimeError("No image provider completed the reference still. " + " | ".join(failures))

    @staticmethod
    def _validate_generated_image(target: Path, provider: str) -> Path:
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"{provider} completed without producing the requested reference image")
        try:
            with Image.open(target) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"{provider} produced an invalid image file") from exc
        return target

    @staticmethod
    def _image_snapshot(root: Path, excluded: list[Path]) -> dict[Path, tuple[int, int]]:
        """Record image files before a provider starts writing.

        Image-capable CLIs do not all honor the requested filename. A snapshot
        lets the handoff locate a newly written file without accidentally
        reusing an older rejected attempt or a user-supplied reference.
        """
        excluded_paths = {path.resolve() for path in excluded}
        roots = [root / "references", root / "agent-context"]
        try:
            roots.extend(path for path in root.iterdir() if path.is_file())
        except OSError:
            pass
        snapshot: dict[Path, tuple[int, int]] = {}
        for candidate_root in roots:
            paths = [candidate_root] if candidate_root.is_file() else candidate_root.rglob("*") if candidate_root.is_dir() else []
            for path in paths:
                if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    continue
                try:
                    resolved = path.resolve()
                    if resolved in excluded_paths:
                        continue
                    stat = path.stat()
                    snapshot[resolved] = (stat.st_size, stat.st_mtime_ns)
                except OSError:
                    continue
        return snapshot

    @staticmethod
    def _image_candidates(root: Path, before: dict[Path, tuple[int, int]], started_at: int, target: Path) -> list[Path]:
        candidates: list[Path] = []
        roots = [root / "references", root / "agent-context"]
        try:
            roots.extend(path for path in root.iterdir() if path.is_file())
        except OSError:
            pass
        seen: set[Path] = set()
        for candidate_root in roots:
            paths = [candidate_root] if candidate_root.is_file() else candidate_root.rglob("*") if candidate_root.is_dir() else []
            for path in paths:
                if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    continue
                try:
                    resolved = path.resolve()
                    if resolved in seen or resolved == target.resolve():
                        continue
                    stat = path.stat()
                    previous = before.get(resolved)
                    changed = previous is None or previous != (stat.st_size, stat.st_mtime_ns)
                    if changed and stat.st_mtime_ns >= started_at - 1_000_000_000:
                        seen.add(resolved)
                        candidates.append(path)
                except OSError:
                    continue
        return sorted(candidates, key=lambda path: path.stat().st_mtime_ns, reverse=True)

    @staticmethod
    def _materialize_png(source: Path, target: Path) -> Path:
        """Copy/convert a provider result to the exact requested PNG path."""
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with Image.open(source) as image:
                image.load()
                mode = "RGBA" if "A" in image.getbands() else "RGB"
                image.convert(mode).save(temporary, format="PNG")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return AgentProcessManager._validate_generated_image(target, "Image provider")

    def _finalize_generated_image(
        self, target: Path, provider: str, production_root: Path,
        before: dict[Path, tuple[int, int]], started_at: int,
    ) -> Path | None:
        """Find and atomically normalize a provider result, if one exists."""
        if target.is_file() and target.stat().st_size:
            try:
                return self._materialize_png(target, target)
            except (UnidentifiedImageError, OSError):
                target.unlink(missing_ok=True)
        for candidate in self._image_candidates(production_root, before, started_at, target):
            try:
                with Image.open(candidate) as image:
                    image.verify()
                return self._materialize_png(candidate, target)
            except (UnidentifiedImageError, OSError):
                continue
        return None

    async def _generate_reference_image_codex(
        self, production_id: str, prompt: str, output_path: Path, model: str, effort: str,
        source_images: list[Path],
    ) -> Path:
        executable = _command_path(CODEX_COMMAND)
        if not executable:
            raise RuntimeError("Codex CLI is not installed or not on PATH")
        production_root = (PRODUCTIONS / production_id).resolve()
        target = output_path.resolve()
        if production_root not in target.parents:
            raise RuntimeError("Generated reference target is outside the production folder")
        target.parent.mkdir(parents=True, exist_ok=True)
        before = self._image_snapshot(production_root, source_images)
        started_at = time.time_ns()
        target.unlink(missing_ok=True)
        task = f"""
Use the installed imagegen skill and its default built-in image generation tool to create exactly one
production reference still from the specification below. This is a project-bound raster asset.

SPECIFICATION:
{prompt}

SOURCE REFERENCE IMAGES (preserve their relevant identity, wardrobe, props, and setting):
{chr(10).join(str(path) for path in source_images) or '(none)'}

Requirements:
- Generate a polished 16:9 reference still suitable as MiniMax H3 I2V input.
- Do not add visible text, logos, license-plate characters, captions, or watermarks unless the specification
  contains exact required text in quotation marks.
- Inspect the generated image for obvious anatomy, identity, composition, and text defects.
- Copy the selected final image to this exact PNG path: {target}
- Do not modify any other project file.
- Finish only after that exact file exists.
""".strip()
        command = [
            executable, "exec", "--json", "--sandbox", "workspace-write",
            "--approve-for-me", "--skip-git-repo-check", "--ephemeral",
            "-C", str(production_root), "--model", model,
            "-c", f'model_reasoning_effort="{effort}"',
        ]
        for image in source_images:
            command.extend(["--image", str(image)])
        command.append("-")
        run_error: Exception | None = None
        try:
            await self._run(production_id, command, task, cwd=PRODUCTIONS / production_id)
        except Exception as exc:
            # Image generation can finish and write the file immediately before
            # the CLI connection closes. Verify the handoff before discarding
            # that useful result.
            run_error = exc
        finalized = self._finalize_generated_image(target, "Codex ImageGen", production_root, before, started_at)
        if finalized:
            return finalized
        if run_error:
            raise RuntimeError(f"Codex ImageGen did not deliver an image: {run_error}") from run_error
        raise RuntimeError("Codex ImageGen completed without producing the requested reference image")

    async def _generate_reference_image_agy(
        self, production_id: str, prompt: str, output_path: Path, model: str, effort: str,
        source_images: list[Path],
    ) -> Path:
        executable = _command_path(AGY_COMMAND)
        if not executable:
            raise RuntimeError("AGY CLI is not installed or not on PATH")
        production_root = (PRODUCTIONS / production_id).resolve()
        target = output_path.resolve()
        if production_root not in target.parents:
            raise RuntimeError("Generated reference target is outside the production folder")
        target.parent.mkdir(parents=True, exist_ok=True)
        before = self._image_snapshot(production_root, source_images)
        started_at = time.time_ns()
        target.unlink(missing_ok=True)
        task = f"""
Use your image-generation capability to create exactly one polished 16:9 production reference still.

SPECIFICATION:
{prompt}

SOURCE REFERENCE IMAGES (inspect these and preserve relevant identity, wardrobe, props, and setting):
{chr(10).join(str(path) for path in source_images) or '(none)'}

Requirements:
- Suitable as a MiniMax H3 I2V opening/reference image.
- No visible text, logos, plate characters, captions, or watermarks unless exact text is quoted above.
- Inspect the image for obvious anatomy, identity, composition, and readable-text defects.
- Save or copy the accepted final PNG to this exact path: {target}
- Do not modify any other file, and finish only after that exact file exists.
""".strip()
        command = [
            executable, "--print", task, "--output-format", "text",
            "--model", model, "--effort", effort, "--mode", "accept-edits",
            "--dangerously-skip-permissions", "--add-dir", str(production_root),
            "--print-timeout", f"{AGENT_TIMEOUT_SECONDS}s",
        ]
        run_error: Exception | None = None
        try:
            await self._run(production_id, command, cwd=PRODUCTIONS / production_id)
        except Exception as exc:
            run_error = exc
        finalized = self._finalize_generated_image(target, "AGY ImageGen", production_root, before, started_at)
        if finalized:
            return finalized
        if run_error:
            raise RuntimeError(f"AGY ImageGen did not deliver an image: {run_error}") from run_error
        raise RuntimeError("AGY ImageGen completed without producing the requested reference image")


process_manager = AgentProcessManager()
