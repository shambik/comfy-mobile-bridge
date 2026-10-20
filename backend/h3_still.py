"""Isolated MiniMax H3 still generation support.

This module deliberately does not use the production video-job tables or
workflow builders. It submits small, standalone H3 graphs and saves only the
first decoded frame. The same controller supports text, image-guide, and
reference-image experiments while reporting ComfyUI sampler progress.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .comfy import ComfyClient
from .config import (
    AUDIO_VAE,
    H3_STILL_WORKFLOW,
    OUTPUT,
    REF2VA_MODEL,
    REF2VA_TURBO_LORA,
    TURBO_LORAS,
)

ASPECT_LABELS = {
    "1:1": "1:1 (Square)",
    "16:9": "16:9 (Widescreen)",
    "9:16": "9:16 (Portrait Widescreen)",
    "4:3": "4:3 (Standard)",
    "3:4": "3:4 (Portrait Standard)",
}
ALLOWED_ASPECTS = frozenset(ASPECT_LABELS)
ALLOWED_INPUT_MODES = frozenset({"text", "edit", "reference"})
ALLOWED_ENGINES = frozenset({"standard", "turbo"})
ALLOWED_REF_SIZES = frozenset({"match", "max"})


class H3StillError(RuntimeError):
    """A controlled error from the isolated H3 still experiment."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class H3StillRun:
    id: str
    prompt_id: str
    client_id: str
    prefix: str
    seed: int
    prompt: str
    input_mode: str
    engine: str
    steps: int
    aspect_ratio: str
    megapixels: float
    reference_count: int = 0
    ref_image_size: str = "max"
    status: str = "queued"
    phase: str = "queued"
    step: int = 0
    total_steps: int = 0
    progress: float = 0.0
    eta_seconds: float | None = None
    error: str | None = None
    image_path: Path | None = None
    created_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    generation_seconds: float | None = None
    _created_clock: float = field(default_factory=time.monotonic, repr=False)
    _started_clock: float | None = field(default=None, repr=False)
    _finished_clock: float | None = field(default=None, repr=False)
    _stop_event: asyncio.Event | None = field(default=None, repr=False)

    def _elapsed(self) -> float:
        end = self._finished_clock or time.monotonic()
        start = self._started_clock or self._created_clock
        return max(0.0, end - start)

    def mark_started(self, phase: str = "starting") -> None:
        if self._started_clock is None:
            self._started_clock = time.monotonic()
            self.started_at = _now_iso()
        if self.status not in {"completed", "failed"}:
            self.status = "running"
            self.phase = phase

    def mark_finished(self, status: str, *, phase: str | None = None) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError(f"Unsupported terminal H3 still status: {status}")
        if self._finished_clock is None:
            self._finished_clock = time.monotonic()
            self.finished_at = _now_iso()
        self.status = status
        self.phase = phase or status
        if self._started_clock is not None:
            self.generation_seconds = round(max(0.0, self._finished_clock - self._started_clock), 1)
        self.eta_seconds = 0.0 if status == "completed" else None

    def public(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "prompt_id": self.prompt_id,
            "prompt": self.prompt,
            "seed": str(self.seed),
            "input_mode": self.input_mode,
            "engine": self.engine,
            "steps": self.steps,
            "aspect_ratio": self.aspect_ratio,
            "megapixels": self.megapixels,
            "reference_count": self.reference_count,
            "ref_image_size": self.ref_image_size,
            "status": self.status,
            "phase": self.phase,
            "step": self.step,
            "total_steps": self.total_steps or self.steps,
            "progress": round(min(1.0, max(0.0, self.progress)), 4),
            "eta_seconds": self.eta_seconds,
            "elapsed_seconds": round(self._elapsed(), 1),
            "generation_seconds": self.generation_seconds,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }
        if self.image_path:
            payload["image_url"] = f"/api/h3-still/{self.id}/image"
            payload["image_filename"] = self.image_path.name
        return payload


_runs: dict[str, H3StillRun] = {}
_watchers: dict[str, asyncio.Task[None]] = {}
_submit_lock = asyncio.Lock()


def _load_workflow() -> dict[str, Any]:
    try:
        payload = json.loads(H3_STILL_WORKFLOW.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise H3StillError(f"The H3 still workflow could not be read: {H3_STILL_WORKFLOW}") from exc
    if not isinstance(payload, dict):
        raise H3StillError("The H3 still workflow must be an API graph object")
    for node_id in ("9", "10", "13", "14", "15", "16", "104", "115", "201"):
        if not isinstance(payload.get(node_id), dict):
            raise H3StillError(f"The H3 still workflow is missing node {node_id}")
    return deepcopy(payload)


def _configure_turbo(workflow: dict[str, Any], *, reference: bool, turbo_profile: str) -> None:
    if reference:
        lora_name = REF2VA_TURBO_LORA
    else:
        if turbo_profile not in TURBO_LORAS:
            raise H3StillError("Turbo profile must be v1 or v4")
        lora_name = TURBO_LORAS[turbo_profile]
    workflow["18"] = {
        "class_type": "MiniMaxH3TurboLoRA",
        "inputs": {
            "model": ["6", 0],
            "lora_name": lora_name,
            "strength": 1.0,
            "low_vram": True,
        },
        "_meta": {"title": "H3 Turbo LoRA"},
    }
    workflow["19"] = {
        "class_type": "MiniMaxH3SigmaShift",
        "inputs": {"model": ["18", 0], "shift_video": 12.0, "shift_audio": 3.0},
        "_meta": {"title": "H3 Turbo sigma shift"},
    }
    workflow["20"] = {
        "class_type": "MiniMaxH3TurboSampler",
        "inputs": {},
        "_meta": {"title": "H3 Turbo sampler"},
    }
    workflow["9"]["inputs"]["model"] = ["19", 0]
    workflow["16"]["inputs"]["model"] = ["19", 0]
    workflow["14"]["inputs"]["sampler"] = ["20", 0]


def _configure_reference(
    workflow: dict[str, Any],
    prompt: str,
    reference_names: list[str],
    *,
    ref_image_size: str,
) -> None:
    if not reference_names:
        raise H3StillError("Reference mode requires at least one image")
    workflow.pop("104", None)
    workflow["6"] = {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": REF2VA_MODEL, "weight_dtype": "default"},
        "_meta": {"title": "H3 Ref2VA model"},
    }
    workflow["24"] = {
        "class_type": "VAELoader",
        "inputs": {"vae_name": AUDIO_VAE},
        "_meta": {"title": "H3 audio VAE for Ref2VA"},
    }
    workflow["136"] = {
        "class_type": "MiniMaxH3ReferenceToVideo",
        "inputs": {
            "clip": ["13", 0],
            "vae": ["11", 0],
            "audio_vae": ["24", 0],
            "prompt": prompt,
            "width": ["115", 0],
            "height": ["115", 1],
            "length": 5,
            "ref_image_size": ref_image_size,
            "ref_images": {},
        },
        "_meta": {"title": "H3 reference-image conditioning"},
    }
    for index, name in enumerate(reference_names[:9]):
        node_id = str(137 + index)
        workflow[node_id] = {
            "class_type": "LoadImage",
            "inputs": {"image": name},
            "_meta": {"title": f"Reference image {index + 1}"},
        }
        workflow["136"]["inputs"]["ref_images"][f"ref_image_{index}"] = [node_id, 0]
    workflow["16"]["inputs"]["conditioning"] = ["136", 0]
    workflow["14"]["inputs"]["latent_image"] = ["136", 1]


def _build_workflow(
    *,
    prompt: str,
    input_mode: str,
    engine: str,
    steps: int,
    aspect_ratio: str,
    megapixels: float,
    seed: int,
    prefix: str,
    image_name: str | None,
    reference_names: list[str],
    ref_image_size: str,
    turbo_profile: str,
) -> dict[str, Any]:
    workflow = _load_workflow()
    workflow["9"]["inputs"]["steps"] = steps
    workflow["115"]["inputs"]["aspect_ratio"] = ASPECT_LABELS[aspect_ratio]
    workflow["115"]["inputs"]["megapixels"] = megapixels
    workflow["15"]["inputs"]["noise_seed"] = seed
    workflow["201"]["inputs"]["filename_prefix"] = prefix
    workflow["104"]["inputs"]["prompt"] = prompt

    if input_mode == "reference":
        _configure_reference(workflow, prompt, reference_names, ref_image_size=ref_image_size)
    elif input_mode == "edit":
        if not image_name:
            raise H3StillError("Image-edit mode requires one input image")
        workflow["202"] = {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
            "_meta": {"title": "Image-edit input"},
        }
        workflow["104"]["inputs"]["first_frame"] = ["202", 0]
    elif input_mode != "text":
        raise H3StillError("Input mode must be text, edit, or reference")

    if engine == "turbo":
        _configure_turbo(workflow, reference=input_mode == "reference", turbo_profile=turbo_profile)
    elif engine != "standard":
        raise H3StillError("Engine must be standard or turbo")
    return workflow


def _resolve_output_image(image: dict[str, Any]) -> Path | None:
    filename = str(image.get("filename") or "").strip()
    if not filename:
        return None
    subfolder = str(image.get("subfolder") or "")
    output_root = OUTPUT.resolve()
    candidate = (output_root / subfolder / Path(filename).name).resolve()
    if not candidate.is_relative_to(output_root) or not candidate.is_file():
        return None
    return candidate


def _history_image(history: dict[str, Any]) -> Path | None:
    outputs = history.get("outputs") or {}
    if not isinstance(outputs, dict):
        return None
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for image in node_output.get("images") or []:
            if isinstance(image, dict):
                path = _resolve_output_image(image)
                if path:
                    return path
    return None


def _history_error(history: dict[str, Any]) -> str | None:
    status = history.get("status") or {}
    messages = status.get("messages") or []
    errors = [item for item in messages if isinstance(item, list) and item and item[0] == "execution_error"]
    if errors:
        return json.dumps(errors[-1][1], ensure_ascii=False)[:4000]
    if status.get("status_str") == "error":
        return "ComfyUI reported an execution error"
    return None


def _set_progress(run: H3StillRun, value: float, total: int) -> None:
    if total > 0:
        run.total_steps = total
    run.step = min(run.total_steps or total, max(0, int(round(value))))
    denominator = run.total_steps or total
    run.progress = min(1.0, max(0.0, value / denominator)) if denominator else 0.0
    if value > 0 and denominator:
        elapsed = run._elapsed()
        run.eta_seconds = round(max(0.0, (denominator - value) * elapsed / value), 1)


async def inspect_h3_still(comfy: ComfyClient, run_id: str) -> H3StillRun:
    run = _runs.get(run_id)
    if not run:
        raise KeyError(run_id)
    if run.status in {"completed", "failed"}:
        return run
    try:
        history = await comfy.history(run.prompt_id)
    except Exception:
        # History can time out while H3 is using the GPU. Keep the run alive;
        # WebSocket progress and the next poll will reconcile it.
        if run.status == "queued":
            run.phase = "starting"
        return run
    if not history:
        try:
            queue_state = ComfyClient.prompt_queue_state(await comfy.queue(), run.prompt_id)
        except Exception:
            queue_state = None
        if queue_state == "queue_pending":
            run.status = "queued"
            run.phase = "queued"
        elif queue_state == "queue_running":
            run.mark_started("starting")
        return run
    error = _history_error(history)
    if error:
        run.error = error
        run.mark_finished("failed")
        return run
    image_path = _history_image(history)
    if image_path:
        run.image_path = image_path
        run.progress = 1.0
        run.step = run.total_steps or run.steps
        run.total_steps = run.total_steps or run.steps
        run.mark_finished("completed")
        return run
    status = history.get("status") or {}
    if status.get("completed") or status.get("status_str") == "success":
        run.error = "ComfyUI completed without producing the H3 still image"
        run.mark_finished("failed")
        return run
    run.mark_started(run.phase if run.phase != "queued" else "starting")
    return run


async def _watch_h3_still(comfy: ComfyClient, run: H3StillRun) -> None:
    stop = asyncio.Event()
    run._stop_event = stop
    ws_ready = asyncio.Event()

    async def on_message(message: dict[str, Any]) -> None:
        data = message.get("data") or {}
        if str(data.get("prompt_id") or "") != run.prompt_id:
            return
        event_type = message.get("type")
        if event_type == "execution_start":
            run.mark_started("starting")
        elif event_type == "executing":
            node_id = str(data.get("node")) if data.get("node") is not None else ""
            if node_id in {"14", "20"}:
                run.mark_started("sampling")
            elif run._started_clock is not None:
                run.phase = "processing"
        elif event_type == "progress":
            try:
                value = float(data.get("value", 0))
                total = int(float(data.get("max", 0)))
            except (TypeError, ValueError):
                return
            if total > 0:
                run.mark_started("sampling")
                _set_progress(run, value, total)
        elif event_type == "executed" and str(data.get("node")) in {"14", "20"}:
            run.phase = "processing"
            run.progress = max(run.progress, 0.99)

    monitor = asyncio.create_task(comfy.monitor_progress(run.client_id, on_message, ws_ready, stop))
    try:
        while run.status not in {"completed", "failed"}:
            await inspect_h3_still(comfy, run.id)
            if run.status in {"completed", "failed"}:
                break
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if run.status not in {"completed", "failed"}:
            run.error = str(exc)
            run.mark_finished("failed")
    finally:
        stop.set()
        try:
            await asyncio.wait_for(monitor, timeout=3)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        finally:
            _watchers.pop(run.id, None)


def has_active_h3_still() -> bool:
    return any(run.status in {"queued", "running"} for run in _runs.values())


async def start_h3_still(
    comfy: ComfyClient,
    *,
    prompt: str,
    aspect_ratio: str,
    megapixels: float,
    seed: int | None,
    input_mode: str = "text",
    engine: str = "standard",
    steps: int = 20,
    image_name: str | None = None,
    reference_names: list[str] | None = None,
    ref_image_size: str = "max",
    turbo_profile: str = "v1",
) -> H3StillRun:
    prompt = prompt.strip()
    reference_names = list(reference_names or [])
    if not prompt:
        raise H3StillError("Prompt is required")
    if len(prompt) > 4000:
        raise H3StillError("Prompt must be at most 4,000 characters")
    if input_mode not in ALLOWED_INPUT_MODES:
        raise H3StillError("Input mode must be text, edit, or reference")
    if engine not in ALLOWED_ENGINES:
        raise H3StillError("Engine must be standard or turbo")
    if engine == "standard" and not 8 <= steps <= 30:
        raise H3StillError("Standard H3 steps must be between 8 and 30")
    if engine == "turbo" and not 4 <= steps <= 12:
        raise H3StillError("Turbo H3 steps must be between 4 and 12")
    if aspect_ratio not in ALLOWED_ASPECTS:
        raise H3StillError("Aspect ratio must be one of 1:1, 16:9, 9:16, 4:3 or 3:4")
    if not 0.1 <= megapixels <= 2.0:
        raise H3StillError("Megapixels must be between 0.1 and 2.0 for the H3 still experiment")
    if ref_image_size not in ALLOWED_REF_SIZES:
        raise H3StillError("Reference sizing must be match or max")
    if input_mode == "text" and (image_name or reference_names):
        raise H3StillError("Text mode does not accept input images")
    if input_mode == "edit" and (not image_name or reference_names):
        raise H3StillError("Image-edit mode requires exactly one input image")
    if input_mode == "reference" and (image_name or not reference_names):
        raise H3StillError("Reference mode requires one or more reference images")
    if len(reference_names) > 9:
        raise H3StillError("Reference mode supports up to 9 images")
    if has_active_h3_still():
        raise H3StillError("An H3 still generation is already running")

    actual_seed = int(seed) if seed is not None else secrets.randbits(64)
    run_id = uuid.uuid4().hex
    prefix = f"image/h3_still_{input_mode}_{engine}_{run_id}"
    workflow = _build_workflow(
        prompt=prompt,
        input_mode=input_mode,
        engine=engine,
        steps=steps,
        aspect_ratio=aspect_ratio,
        megapixels=megapixels,
        seed=actual_seed,
        prefix=prefix,
        image_name=image_name,
        reference_names=reference_names,
        ref_image_size=ref_image_size,
        turbo_profile=turbo_profile,
    )
    client_id = f"h3-still-{run_id}"
    async with _submit_lock:
        try:
            prompt_id = await comfy.submit(workflow, client_id)
        except Exception as exc:
            raise H3StillError(f"ComfyUI rejected the H3 still workflow: {exc}") from exc

    run = H3StillRun(
        id=run_id,
        prompt_id=prompt_id,
        client_id=client_id,
        prefix=prefix,
        seed=actual_seed,
        prompt=prompt,
        input_mode=input_mode,
        engine=engine,
        steps=steps,
        aspect_ratio=aspect_ratio,
        megapixels=megapixels,
        reference_count=len(reference_names),
        ref_image_size=ref_image_size,
    )
    _runs[run_id] = run
    _watchers[run_id] = asyncio.create_task(_watch_h3_still(comfy, run))
    return run


def get_h3_still(run_id: str) -> H3StillRun | None:
    return _runs.get(run_id)


def delete_h3_still(run_id: str) -> None:
    run = _runs.get(run_id)
    if not run:
        raise KeyError(run_id)
    if run.status in {"queued", "running"}:
        raise H3StillError("The H3 still is still generating and cannot be deleted yet")
    if run.image_path:
        try:
            run.image_path.unlink(missing_ok=True)
        except OSError as exc:
            raise H3StillError(f"The generated H3 still is in use and could not be deleted: {exc}") from exc
    _runs.pop(run_id, None)
