from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .config import (AGENT_TIMEOUT_SECONDS, AGY_COMMAND, CODEX_COMMAND,
                     AGY_DEFAULT_EFFORT, AGY_DEFAULT_MODEL, PRODUCTIONS, ROOT)


CODEX_FALLBACK_MODELS = [
    {"id": "gpt-5.6-sol", "name": "GPT-5.6 Sol", "efforts": ["none", "low", "medium", "high", "xhigh", "max"]},
    {"id": "gpt-5.6-terra", "name": "GPT-5.6 Terra", "efforts": ["none", "low", "medium", "high", "xhigh", "max"]},
    {"id": "gpt-5.6-luna", "name": "GPT-5.6 Luna", "efforts": ["none", "low", "medium", "high", "xhigh", "max"]},
]

AGENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "required": ["summary", "decision", "next_action"],
    "properties": {
        "summary": {"type": "string"},
        "decision": {"type": "string"},
        "content": {"type": ["object", "array", "string", "null"]},
        "issues": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
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


def _command_path(command: str) -> str | None:
    return shutil.which(command)


def agent_health() -> dict[str, Any]:
    return {
        "codex": {"installed": bool(_command_path(CODEX_COMMAND)), "command": CODEX_COMMAND},
        "agy": {"installed": bool(_command_path(AGY_COMMAND)), "command": AGY_COMMAND},
    }


def discover_codex_models() -> list[dict[str, Any]]:
    """Read the authenticated Codex client's model catalog.

    Codex CLI has no stable non-interactive `models` command. Its UI persists
    the server-provided catalog in CODEX_HOME/models_cache.json, including
    visibility and supported reasoning levels. A validated fallback keeps the
    app usable before the first Codex login/cache refresh.
    """
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    cache = codex_home / "models_cache.json"
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
        models = []
        for item in payload.get("models", []):
            if item.get("visibility") not in (None, "list") or not item.get("slug"):
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
                "source": "codex-cache",
            })
        if models:
            return models
    except (OSError, ValueError, TypeError, KeyError):
        pass
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
        models.append({"id": model_id, "name": display or model_id, "efforts": [encoded] if encoded else efforts})
    return models


def model_catalog() -> dict[str, Any]:
    return {
        "runtimes": [
            {"id": "codex", "name": "Codex CLI", "capabilities": ["text", "images"]},
            {"id": "agy", "name": "AGY CLI", "capabilities": ["text", "images", "audio", "video"]},
        ],
        "codex": discover_codex_models(), "agy": discover_agy_models(),
    }


def _schema_path(production_id: str) -> Path:
    folder = PRODUCTIONS / production_id / "agent-context"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "response.schema.json"
    if not path.exists():
        path.write_text(json.dumps(AGENT_SCHEMA, indent=2), encoding="utf-8")
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
    candidates = re.findall(r"\{(?:[^{}]|\{[^{}]*\})*\}", stripped, re.DOTALL)
    for candidate in reversed(candidates):
        try:
            value = json.loads(candidate)
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
        for key in ("result", "text", "output_text", "message", "content"):
            value = event.get(key) if isinstance(event, dict) else None
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, dict):
                for nested_key in ("text", "content"):
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


class AgentProcessManager:
    def __init__(self) -> None:
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    async def cancel(self, production_id: str) -> None:
        process = self.processes.get(production_id)
        if not process or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _run(self, production_id: str, command: list[str], prompt: str | None = None) -> str:
        lock = self.locks.setdefault(production_id, asyncio.Lock())
        async with lock:
            return await self._run_locked(production_id, command, prompt)

    async def _run_locked(self, production_id: str, command: list[str], prompt: str | None = None) -> str:
        env = os.environ.copy()
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ROOT), env=env,
        )
        self.processes[production_id] = process
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8") if prompt is not None else None), timeout=AGENT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError(f"Agent timed out after {AGENT_TIMEOUT_SECONDS} seconds") from exc
        finally:
            self.processes.pop(production_id, None)
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        if process.returncode:
            raise RuntimeError((err or out or f"Agent exited with code {process.returncode}")[-8000:])
        return out

    async def invoke_codex(
        self, production_id: str, prompt: str, model: str, effort: str,
        session_id: str | None = None, images: list[Path] | None = None,
    ) -> AgentResult:
        executable = _command_path(CODEX_COMMAND)
        if not executable:
            raise RuntimeError("Codex CLI is not installed or not on PATH")
        schema = _schema_path(production_id)
        if session_id:
            command = [executable, "exec", "resume", session_id, "--json", "--output-schema", str(schema)]
        else:
            command = [executable, "exec", "--json", "--output-schema", str(schema), "--sandbox", "read-only",
                       "--ask-for-approval", "never", "--skip-git-repo-check", "-C", str(PRODUCTIONS / production_id)]
        command.extend(["--model", model, "-c", f'model_reasoning_effort="{effort}"'])
        for image in images or []:
            command.extend(["--image", str(image)])
        command.append("-")
        raw = await self._run(production_id, command, prompt)
        content, found_session = _extract_result(raw)
        return AgentResult("codex", content, raw, found_session or session_id, model, effort)

    async def invoke_agy(
        self, production_id: str, prompt: str, model: str, effort: str,
        session_id: str | None = None,
    ) -> AgentResult:
        executable = _command_path(AGY_COMMAND)
        if not executable:
            raise RuntimeError("AGY CLI is not installed or not on PATH")
        schema = _schema_path(production_id)
        request_dir = PRODUCTIONS / production_id / "agent-context"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_path = request_dir / f"agy-request-{uuid.uuid4().hex}.md"
        request_path.write_text(prompt, encoding="utf-8")
        command = [executable, "--print", f"Read {request_path} and return only the required structured response.",
                   "--output-format", "stream-json", "--json-schema", str(schema),
                   "--model", model, "--effort", effort, "--mode", "plan", "--sandbox",
                   "--add-dir", str(PRODUCTIONS / production_id), "--print-timeout", f"{AGENT_TIMEOUT_SECONDS}s"]
        if session_id:
            command.extend(["--conversation", session_id])
        raw = await self._run(production_id, command)
        content, found_session = _extract_result(raw)
        return AgentResult("agy", content, raw, found_session or session_id, model, effort)

    async def invoke(
        self, runtime: str, participant: str, production_id: str, prompt: str,
        model: str, effort: str, session_id: str | None = None,
        images: list[Path] | None = None,
    ) -> AgentResult:
        if runtime == "codex":
            result = await self.invoke_codex(production_id, prompt, model, effort, session_id, images)
        elif runtime == "agy":
            # AGY reads media by path from the production directory. Image
            # paths are also included explicitly in the task when supplied.
            if images:
                prompt += "\n\nAttached image paths:\n" + "\n".join(str(path) for path in images)
            result = await self.invoke_agy(production_id, prompt, model, effort, session_id)
        else:
            raise RuntimeError(f"Unsupported agent runtime: {runtime}")
        result.participant = participant
        return result

    async def generate_reference_image(
        self, production_id: str, prompt: str, output_path: Path, model: str, effort: str,
        provider: str = "auto", agy_model: str | None = None, agy_effort: str | None = None,
    ) -> Path:
        """Generate a project-bound still with Codex ImageGen or AGY fallback."""
        if provider not in {"auto", "codex", "agy"}:
            raise ValueError("Image provider must be auto, codex, or agy")
        failures: list[str] = []
        if provider in {"auto", "codex"}:
            try:
                return await self._generate_reference_image_codex(
                    production_id, prompt, output_path, model, effort,
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

    async def _generate_reference_image_codex(
        self, production_id: str, prompt: str, output_path: Path, model: str, effort: str,
    ) -> Path:
        executable = _command_path(CODEX_COMMAND)
        if not executable:
            raise RuntimeError("Codex CLI is not installed or not on PATH")
        production_root = (PRODUCTIONS / production_id).resolve()
        target = output_path.resolve()
        if production_root not in target.parents:
            raise RuntimeError("Generated reference target is outside the production folder")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        task = f"""
Use the installed imagegen skill and its default built-in image generation tool to create exactly one
production reference still from the specification below. This is a project-bound raster asset.

SPECIFICATION:
{prompt}

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
            "--ask-for-approval", "never", "--skip-git-repo-check", "--ephemeral",
            "-C", str(production_root), "--model", model,
            "-c", f'model_reasoning_effort="{effort}"', "-",
        ]
        await self._run(production_id, command, task)
        return self._validate_generated_image(target, "Codex ImageGen")

    async def _generate_reference_image_agy(
        self, production_id: str, prompt: str, output_path: Path, model: str, effort: str,
    ) -> Path:
        executable = _command_path(AGY_COMMAND)
        if not executable:
            raise RuntimeError("AGY CLI is not installed or not on PATH")
        production_root = (PRODUCTIONS / production_id).resolve()
        target = output_path.resolve()
        if production_root not in target.parents:
            raise RuntimeError("Generated reference target is outside the production folder")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        task = f"""
Use your image-generation capability to create exactly one polished 16:9 production reference still.

SPECIFICATION:
{prompt}

Requirements:
- Suitable as a MiniMax H3 I2V opening/reference image.
- No visible text, logos, plate characters, captions, or watermarks unless exact text is quoted above.
- Inspect the image for obvious anatomy, identity, composition, and readable-text defects.
- Save or copy the accepted final PNG to this exact path: {target}
- Do not modify any other file, and finish only after that exact file exists.
""".strip()
        command = [
            executable, "--print", task, "--output-format", "text",
            "--model", model, "--effort", effort, "--mode", "accept-edits", "--sandbox",
            "--add-dir", str(production_root), "--print-timeout", f"{AGENT_TIMEOUT_SECONDS}s",
        ]
        await self._run(production_id, command)
        return self._validate_generated_image(target, "AGY ImageGen")


process_manager = AgentProcessManager()
