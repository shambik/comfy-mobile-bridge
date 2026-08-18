import asyncio
import ctypes
import json
import os
import secrets
import shutil
import subprocess
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import (ALLOWED_HOSTS, APP_HOST, APP_PORT, APP_VERSION,
                     AGY_DEFAULT_EFFORT, AGY_DEFAULT_MODEL, AGY_DEFAULT_RUNTIME,
                     CLIPPROJ_NODE_COMMIT, CLIPPROJ_NODE_DIR, COMFY_HOST, COMFY_PORT,
                     CLIPPROJ_PROJECTION, CLIPPROJ_TEXT_ENCODER, INPUT, LOGS, MODELS,
                     CODEX_DEFAULT_EFFORT, CODEX_DEFAULT_MODEL, CODEX_DEFAULT_RUNTIME,
                     MANAGED_SKILLS, PRODUCTIONS,
                     REF2VA_MODEL, REF2VA_TURBO_LORA, REFERENCE_10S_MARKER, ROOT,
                     SPECTRUM_NODE_DIR, SPECTRUM_NODE_VERSION, TURBO_LORAS)
from .db import (connect, get_job, get_sequence, init_db, list_jobs,
                 list_sequences, next_position, now_iso)
from .generation import normalize_generation_settings
from .library import (assign_asset, create_folder, create_project, delete_folder,
                      delete_project, init_library_db, list_library, remove_assignment,
                      rename_asset, rename_folder, rename_project, validate_location)
from .security import COOKIE, new_token, require_csrf
from .agents import agent_health, model_catalog
from .production import production_orchestrator
from .production_db import (add_config_revision, add_event, add_message, add_reference,
                            create_production, create_shot_attempt, delete_reference, ensure_agent_settings,
                            get_agent_settings, get_artifact, get_attempt_for_production,
                            get_production, get_reference, init_production_db, list_events,
                            import_completed_jobs, list_productions, list_references, list_shots,
                            replace_shot_plan, resolve_decision, update_agent_settings,
                            update_production, update_shot, update_shot_attempt)
from .skill_catalog import (discover_skills, get_skill, install_skill_zip,
                            list_skills, register_skill, remove_skill,
                            set_skill_enabled)
from .worker import QueueWorker

worker = QueueWorker()


def fortnite_running() -> bool:
    """Detect the Windows Fortnite client without touching or stopping it."""
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq FortniteClient-Win64-Shipping.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=3,
        )
        return "FortniteClient-Win64-Shipping.exe".lower() in result.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def stop_fortnite() -> bool:
    """Stop only the Fortnite game process; leave the bridge and ComfyUI alone."""
    if os.name != "nt" or not fortnite_running():
        return False
    try:
        result = subprocess.run(
            ["taskkill", "/IM", "FortniteClient-Win64-Shipping.exe", "/T", "/F"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def lock_windows() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.user32.LockWorkStation())
    except (AttributeError, OSError):
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_library_db()
    init_production_db()
    ensure_agent_settings({
        "codex_runtime": CODEX_DEFAULT_RUNTIME,
        "codex_model": CODEX_DEFAULT_MODEL, "codex_effort": CODEX_DEFAULT_EFFORT,
        "agy_runtime": AGY_DEFAULT_RUNTIME,
        "agy_model": AGY_DEFAULT_MODEL, "agy_effort": AGY_DEFAULT_EFFORT,
    })
    # Reconcile stale defaults after Codex/AGY refresh their authenticated
    # catalogs. This prevents an old hardcoded model from lingering in the UI.
    catalog = await asyncio.to_thread(model_catalog)
    current_settings = get_agent_settings()
    reconciled: dict[str, str] = {}
    for seat, default_runtime in (("codex", "codex"), ("agy", "agy")):
        runtime = str(current_settings.get(f"{seat}_runtime") or default_runtime)
        if seat == "agy":
            runtime = "agy"
        if runtime not in {"codex", "agy"} or not catalog.get(runtime):
            runtime = default_runtime
        options = catalog.get(runtime) or []
        model = str(current_settings.get(f"{seat}_model") or "")
        option = next((item for item in options if item["id"] == model), options[0] if options else None)
        if option:
            effort = str(current_settings.get(f"{seat}_effort") or option.get("default_effort") or "medium")
            if effort not in option.get("efforts", []):
                effort = str(option.get("default_effort") or option["efforts"][0])
            reconciled.update({f"{seat}_runtime": runtime, f"{seat}_model": option["id"], f"{seat}_effort": effort})
    if reconciled:
        update_agent_settings(**reconciled)
    discover_skills()
    worker.start()
    production_orchestrator.bind_queue(worker)
    production_orchestrator.start()
    yield
    await production_orchestrator.stop()
    await worker.stop()


app = FastAPI(title="H3 Mobile Bridge", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class OrderBody(BaseModel):
    ids: list[str]


class JoinBody(BaseModel):
    ids: list[str]


class AgentSettingsBody(BaseModel):
    codex_runtime: str = "codex"
    codex_model: str
    codex_effort: str
    agy_runtime: str = "agy"
    agy_model: str
    agy_effort: str


class SkillBody(BaseModel):
    enabled: bool


class RegisterSkillBody(BaseModel):
    path: str


class ProductionControlBody(BaseModel):
    cancel_generation: bool = False


class InterventionBody(BaseModel):
    content: str
    recipient: str = "both"


class DecisionBody(BaseModel):
    resolution: str = ""


class ProductionSettingsBody(BaseModel):
    participation_mode: str | None = None
    continuity_mode: str | None = None
    codex_runtime: str | None = None
    codex_model: str | None = None
    codex_effort: str | None = None
    agy_runtime: str | None = None
    agy_model: str | None = None
    agy_effort: str | None = None
    skills: list[str] | None = None
    reason: str = ""


class ShotEditBody(BaseModel):
    title: str | None = None
    prompt: str | None = None
    mode: str | None = None
    continuity: str | None = None
    duration: float | None = None
    megapixels: float | None = None
    aspect_ratio: str | None = None
    steps: int | None = None
    engine: str | None = None
    turbo_profile: str | None = None
    reference_ids: list[str] | None = None


class RetryShotBody(BaseModel):
    prompt: str | None = None
    regenerate_downstream: bool = True


class ImportJobsBody(BaseModel):
    job_ids: list[str]


class ReferenceGenerateBody(BaseModel):
    name: str
    prompt: str
    provider: str = "auto"


class ArchiveBody(BaseModel):
    archived: bool = True


class LibraryNameBody(BaseModel):
    name: str


class AssetMoveBody(BaseModel):
    project_id: str | None = None
    folder_id: str | None = None


def raise_library_error(exc: Exception) -> None:
    if isinstance(exc, KeyError):
        raise HTTPException(404, str(exc).strip("'")) from exc
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(410, str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(400, str(exc)) from exc
    raise HTTPException(409, str(exc)) from exc


def clipproj_ready() -> bool:
    return all((
        (CLIPPROJ_NODE_DIR / "clipproj_nodes.py").exists(),
        (MODELS / "text_encoders" / CLIPPROJ_TEXT_ENCODER).exists(),
        (MODELS / "clip_projections" / CLIPPROJ_PROJECTION).exists(),
    ))


def public_health():
    conflict = fortnite_running()
    return {
        "ok": True,
        "version": APP_VERSION,
        "app_host": APP_HOST,
        "app_port": APP_PORT,
        "comfy_host": COMFY_HOST,
        "comfy_port": COMFY_PORT,
        "reference_ready": (MODELS / "diffusion_models" / REF2VA_MODEL).exists(),
        "reference_10s_ready": REFERENCE_10S_MARKER.exists(),
        "spectrum_ready": (SPECTRUM_NODE_DIR / "nodes.py").exists(),
        "spectrum_version": SPECTRUM_NODE_VERSION,
        "clipproj_ready": clipproj_ready(),
        "clipproj_version": CLIPPROJ_NODE_COMMIT[:12],
        "turbo_v4_ready": (MODELS / "loras" / TURBO_LORAS["v4"]).exists(),
        "reference_turbo_ready": (MODELS / "loras" / REF2VA_TURBO_LORA).exists(),
        "active_job": worker.current_job,
        "active_sequence": worker.current_sequence,
        "gpu_conflict": conflict,
        "gpu_conflict_process": "Fortnite" if conflict else None,
    }


@app.get("/api/health")
async def health():
    return public_health()


@app.get("/api/session")
async def session(request: Request):
    token = request.cookies.get(COOKIE) or new_token()
    response = JSONResponse({"csrf_token": token, **public_health()})
    response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=86400 * 30)
    return response


def read_comfy_log(limit: int = 300) -> list[str]:
    path = LOGS / "comfy-8190.log"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max(1, min(limit, 1000)):]


@app.get("/api/comfy/status")
async def comfy_status():
    return {
        "running": await worker.comfy.ready(),
        "pid": worker.comfy.discovered_pid(),
        "host": COMFY_HOST,
        "port": COMFY_PORT,
    }


@app.get("/api/comfy/logs")
async def comfy_logs(request: Request):
    try:
        limit = int(request.query_params.get("tail", "300"))
    except ValueError:
        limit = 300
    return {"running": await worker.comfy.ready(), "lines": read_comfy_log(limit)}


@app.post("/api/comfy/start")
async def start_comfy(request: Request):
    require_csrf(request)
    try:
        await worker.comfy.ensure_started()
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc
    return await comfy_status()


@app.post("/api/comfy/stop")
async def stop_comfy(request: Request):
    require_csrf(request)
    await worker.comfy.shutdown()
    return await comfy_status()


@app.post("/api/gpu/fortnite/stop")
async def stop_fortnite_route(request: Request):
    require_csrf(request)
    stopped = await asyncio.to_thread(stop_fortnite)
    if not stopped and fortnite_running():
        raise HTTPException(503, "Fortnite could not be closed")
    return {"stopped": stopped, **public_health()}


@app.post("/api/system/lock")
async def lock_system(request: Request):
    require_csrf(request)
    if not await asyncio.to_thread(lock_windows):
        raise HTTPException(503, "Windows could not be locked")
    return {"locked": True}


@app.get("/api/jobs")
async def jobs():
    return {"jobs": list_jobs(), "sequences": list_sequences(), "library": list_library(), **public_health()}


@app.get("/api/library")
async def asset_library():
    return list_library()


@app.post("/api/library/projects")
async def create_library_project(request: Request, body: LibraryNameBody):
    require_csrf(request)
    try:
        return create_project(body.name)
    except (KeyError, ValueError, FileExistsError, RuntimeError) as exc:
        raise_library_error(exc)


@app.patch("/api/library/projects/{project_id}")
async def rename_library_project(project_id: str, request: Request, body: LibraryNameBody):
    require_csrf(request)
    try:
        return rename_project(project_id, body.name)
    except (KeyError, ValueError, FileExistsError, RuntimeError, OSError) as exc:
        raise_library_error(exc)


@app.delete("/api/library/projects/{project_id}")
async def delete_library_project(project_id: str, request: Request):
    require_csrf(request)
    try:
        delete_project(project_id)
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        raise_library_error(exc)
    return {"deleted": True}


@app.post("/api/library/projects/{project_id}/folders")
async def create_library_folder(project_id: str, request: Request, body: LibraryNameBody):
    require_csrf(request)
    try:
        return create_folder(project_id, body.name)
    except (KeyError, ValueError, FileExistsError, RuntimeError, OSError) as exc:
        raise_library_error(exc)


@app.patch("/api/library/projects/{project_id}/folders/{folder_id}")
async def rename_library_folder(project_id: str, folder_id: str, request: Request, body: LibraryNameBody):
    require_csrf(request)
    try:
        return rename_folder(project_id, folder_id, body.name)
    except (KeyError, ValueError, FileExistsError, RuntimeError, OSError) as exc:
        raise_library_error(exc)


@app.delete("/api/library/projects/{project_id}/folders/{folder_id}")
async def delete_library_folder(project_id: str, folder_id: str, request: Request):
    require_csrf(request)
    try:
        delete_folder(project_id, folder_id)
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        raise_library_error(exc)
    return {"deleted": True}


@app.patch("/api/library/assets/{source_type}/{source_id}/location")
async def move_library_asset(source_type: str, source_id: str, request: Request, body: AssetMoveBody):
    require_csrf(request)
    try:
        return {"assignment": assign_asset(source_type, source_id, body.project_id, body.folder_id)}
    except (KeyError, ValueError, FileExistsError, FileNotFoundError, RuntimeError, OSError) as exc:
        raise_library_error(exc)


@app.patch("/api/library/assets/{source_type}/{source_id}/name")
async def rename_library_asset(source_type: str, source_id: str, request: Request, body: LibraryNameBody):
    require_csrf(request)
    try:
        return rename_asset(source_type, source_id, body.name)
    except (KeyError, ValueError, FileExistsError, FileNotFoundError, RuntimeError, OSError) as exc:
        raise_library_error(exc)


@app.get("/api/events")
async def events(request: Request):
    async def stream():
        while not await request.is_disconnected():
            payload = {"jobs": list_jobs(), "sequences": list_sequences(), "library": list_library(), **public_health()}
            yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            await asyncio.sleep(4)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@app.get("/api/agents/status")
async def agents_status():
    return {"agents": agent_health(), "settings": get_agent_settings()}


@app.get("/api/agents/models")
async def agent_models():
    return await asyncio.to_thread(model_catalog)


@app.get("/api/settings/agents")
async def agent_settings():
    return get_agent_settings()


@app.patch("/api/settings/agents")
async def save_agent_settings(request: Request, body: AgentSettingsBody):
    require_csrf(request)
    efforts = {"none", "low", "medium", "high", "xhigh", "max", "ultra"}
    if body.codex_effort not in efforts or body.agy_effort not in efforts:
        raise HTTPException(400, "Unsupported reasoning level")
    if body.codex_runtime not in {"codex", "agy"} or body.agy_runtime not in {"codex", "agy"}:
        raise HTTPException(400, "Agent runtime must be codex or agy")
    if body.agy_runtime != "agy":
        raise HTTPException(400, "The media-analysis seat must use AGY")
    if not body.codex_model.strip() or not body.agy_model.strip():
        raise HTTPException(400, "Both agent models are required")
    catalog = await asyncio.to_thread(model_catalog)
    for runtime, model in ((body.codex_runtime, body.codex_model), (body.agy_runtime, body.agy_model)):
        if model not in {item["id"] for item in catalog[runtime]}:
            raise HTTPException(400, f"Model {model} is not available through {runtime}")
    return update_agent_settings(**body.model_dump())


@app.get("/api/skills")
async def skills():
    return {"skills": discover_skills()}


@app.post("/api/skills/register")
async def register_skill_route(request: Request, body: RegisterSkillBody):
    require_csrf(request)
    try:
        return register_skill(body.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/skills/upload")
async def upload_skill_route(request: Request, package: UploadFile = File(...)):
    require_csrf(request)
    if not package.filename or not package.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Skill package must be a ZIP file")
    data = await package.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(400, "Skill package is larger than 50 MB")
    upload = MANAGED_SKILLS / f".upload-{uuid.uuid4().hex}.zip"
    upload.write_bytes(data)
    try:
        return install_skill_zip(upload)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        upload.unlink(missing_ok=True)


@app.patch("/api/skills/{skill_id}")
async def update_skill_route(skill_id: str, request: Request, body: SkillBody):
    require_csrf(request)
    skill = set_skill_enabled(skill_id, body.enabled)
    if not skill:
        raise HTTPException(404, "Skill not found")
    return skill


@app.delete("/api/skills/{skill_id}")
async def delete_skill_route(skill_id: str, request: Request):
    require_csrf(request)
    mode = request.query_params.get("mode", "unregister")
    try:
        remove_skill(skill_id, mode)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": True, "mode": mode}


@app.get("/api/productions")
async def productions():
    return {
        "productions": list_productions(),
        "active_production": production_orchestrator.current_production,
        "active_productions": production_orchestrator.active_productions,
    }


@app.get("/api/productions/{production_id}")
async def production_detail(production_id: str):
    production = get_production(production_id, include_messages=True)
    if not production:
        raise HTTPException(404, "Production not found")
    return production


@app.patch("/api/productions/{production_id}/settings")
async def update_production_settings_route(
    production_id: str, request: Request, body: ProductionSettingsBody,
):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    if production["status"] not in {"draft", "paused", "stopped", "failed", "awaiting_user"}:
        raise HTTPException(409, "Pause the production before changing its configuration")
    values = {key: value for key, value in body.model_dump(exclude={"reason"}).items() if value is not None}
    if values.get("participation_mode") not in {None, "autonomous", "interactive"}:
        raise HTTPException(400, "Unsupported participation mode")
    if values.get("continuity_mode") not in {None, "sequential", "hard_cut", "segmented", "hybrid"}:
        raise HTTPException(400, "Unsupported continuity mode")
    for key in ("codex_runtime", "agy_runtime"):
        if values.get(key) not in {None, "codex", "agy"}:
            raise HTTPException(400, "Agent runtime must be codex or agy")
    merged = {**production, **values}
    if merged.get("agy_runtime", "agy") != "agy":
        raise HTTPException(400, "The media-analysis seat must use AGY")
    catalog = await asyncio.to_thread(model_catalog)
    for seat in ("codex", "agy"):
        runtime = merged.get(f"{seat}_runtime") or seat
        model = merged[f"{seat}_model"]
        option = next((item for item in catalog[runtime] if item["id"] == model), None)
        if not option:
            raise HTTPException(400, f"Model {model} is unavailable through {runtime}")
        if merged[f"{seat}_effort"] not in option.get("efforts", []):
            raise HTTPException(400, f"Unsupported thinking level for {model}")
    if "skills" in values:
        for skill_id in values["skills"]:
            skill = get_skill(str(skill_id))
            if not skill or not skill["enabled"] or not skill["valid"]:
                raise HTTPException(400, f"Selected skill is unavailable: {skill_id}")
    session_fields = {}
    for seat in ("codex", "agy"):
        if any(key in values for key in (f"{seat}_runtime", f"{seat}_model")):
            session_fields[f"{seat}_session_id"] = None
    revision_config = {key: merged[key] for key in (
        "participation_mode", "continuity_mode", "codex_runtime", "codex_model", "codex_effort",
        "agy_runtime", "agy_model", "agy_effort", "skills",
    )}
    revision = add_config_revision(production_id, revision_config, body.reason.strip())
    update_production(production_id, **values, **session_fields)
    add_message(production_id, "user", "both", "configuration",
                f"Updated production configuration (revision {revision}).",
                {"revision": revision, "reason": body.reason.strip()})
    return get_production(production_id, include_messages=True)


@app.post("/api/productions/{production_id}/references")
async def upload_production_reference(
    production_id: str, request: Request, media: UploadFile = File(...), notes: str = Form(""),
):
    require_csrf(request)
    if not get_production(production_id, private=True):
        raise HTTPException(404, "Production not found")
    content_type = media.content_type or ""
    if content_type.startswith("image/"):
        kind = "image"
    elif content_type.startswith("video/"):
        kind = "video"
    elif content_type.startswith("audio/") or content_type == "application/ogg":
        kind = "audio"
    else:
        raise HTTPException(400, "Reference must be an image, video, or audio file")
    counts = {value: 0 for value in ("image", "video", "audio")}
    for reference in list_references(production_id, private=True):
        counts[reference["kind"]] = counts.get(reference["kind"], 0) + 1
    limits = {"image": 9, "video": 3, "audio": 1}
    if counts[kind] >= limits[kind]:
        raise HTTPException(409, f"A production supports at most {limits[kind]} {kind} reference file(s)")
    saved = await {"image": save_image, "video": save_video, "audio": save_audio}[kind](media)
    comfy_path, comfy_name = saved
    if not comfy_path or not comfy_name:
        raise HTTPException(400, "Reference upload is empty")
    folder = PRODUCTIONS / production_id / "references" / "media"
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{uuid.uuid4().hex}{Path(comfy_name).suffix}"
    shutil.copy2(comfy_path, stored)
    return add_reference(
        production_id, kind, media.filename or stored.name, str(stored), comfy_path, comfy_name,
        notes.strip()[:4000],
    )


@app.post("/api/productions/{production_id}/references/generate")
async def generate_production_reference(
    production_id: str, request: Request, body: ReferenceGenerateBody,
):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    if production["status"] in {"queued", "running", "pausing", "retrying", "stopping"}:
        raise HTTPException(409, "Pause or stop the production before manually generating a reference")
    name = body.name.strip()
    prompt = body.prompt.strip()
    if not name or len(name) > 160:
        raise HTTPException(400, "Reference name is required and must be at most 160 characters")
    if not prompt or len(prompt) > 12_000:
        raise HTTPException(400, "Reference prompt is required and must be at most 12,000 characters")
    if body.provider not in {"auto", "codex", "agy"}:
        raise HTTPException(400, "Image provider must be auto, codex, or agy")
    if sum(1 for item in list_references(production_id, private=True) if item["kind"] == "image") >= 9:
        raise HTTPException(409, "A production supports at most 9 image references")
    try:
        reference = await production_orchestrator.generate_manual_reference(
            production_id, name, prompt, body.provider,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'")) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"reference": reference, "production": get_production(production_id, include_messages=True)}


@app.get("/api/productions/{production_id}/references/{reference_id}/file")
async def production_reference_file(production_id: str, reference_id: str):
    reference = get_reference(production_id, reference_id, private=True)
    if not reference:
        raise HTTPException(404, "Reference not found")
    path = Path(reference["path"])
    if not path.is_file():
        raise HTTPException(410, "Reference file is missing")
    return FileResponse(path, filename=reference["name"])


@app.delete("/api/productions/{production_id}/references/{reference_id}")
async def delete_production_reference(production_id: str, reference_id: str, request: Request):
    require_csrf(request)
    try:
        reference = delete_reference(production_id, reference_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not reference:
        raise HTTPException(404, "Reference not found")
    Path(reference["path"]).unlink(missing_ok=True)
    Path(reference["comfy_path"]).unlink(missing_ok=True)
    return {"deleted": True}


@app.patch("/api/productions/{production_id}/shots/{shot_id}")
async def edit_production_shot(production_id: str, shot_id: str, request: Request, body: ShotEditBody):
    require_csrf(request)
    production = get_production(production_id, private=True)
    shots = list_shots(production_id, private=True)
    shot = next((item for item in shots if item["id"] == shot_id), None)
    if not production or not shot:
        raise HTTPException(404, "Production shot not found")
    if production["status"] not in {"draft", "paused", "stopped", "failed", "awaiting_user"}:
        raise HTTPException(409, "Pause the production before editing shots")
    values = {key: value for key, value in body.model_dump().items() if value is not None}
    merged = {**shot, **values}
    if merged["mode"] not in {"text", "opening", "reference"}:
        raise HTTPException(400, "Shot mode must be text, opening, or reference")
    if merged["continuity"] not in {"hard_cut", "sequential"}:
        raise HTTPException(400, "Shot continuity must be hard_cut or sequential")
    if not str(merged["title"]).strip() or not str(merged["prompt"]).strip():
        raise HTTPException(400, "Shot title and prompt are required")
    reference_ids = [str(value) for value in merged.get("reference_ids", [])]
    references = [get_reference(production_id, value, private=True) for value in reference_ids]
    if any(item is None for item in references):
        raise HTTPException(400, "One or more references do not belong to this production")
    if merged["mode"] == "reference" and not reference_ids:
        raise HTTPException(400, "R2V shots require at least one reference")
    if merged["mode"] == "opening" and merged["continuity"] != "sequential" and not any(item["kind"] == "image" for item in references):
        raise HTTPException(400, "Independent I2V shots require an image reference")
    try:
        normalized = normalize_generation_settings(
            merged["mode"], merged["engine"], int(merged["steps"]),
            turbo_profile=merged["turbo_profile"], megapixels=float(merged["megapixels"]),
            aspect_ratio=merged["aspect_ratio"],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    values.update({"title": str(merged["title"]).strip(), "prompt": str(merged["prompt"]).strip(),
                   "steps": normalized.steps, "megapixels": normalized.megapixels,
                   "aspect_ratio": normalized.aspect_ratio, "reference_ids": reference_ids})
    if shot.get("accepted_attempt"):
        values.update({"status": "planned", "accepted_attempt": None})
    update_shot(shot_id, **values)
    add_event(production_id, "shot.updated", {"shot_id": shot_id})
    return get_production(production_id, include_messages=True)


@app.post("/api/productions/{production_id}/shots/{shot_id}/retry")
async def retry_production_shot(production_id: str, shot_id: str, request: Request, body: RetryShotBody):
    require_csrf(request)
    production = get_production(production_id, private=True)
    shots = list_shots(production_id, private=True)
    shot = next((item for item in shots if item["id"] == shot_id), None)
    if not production or not shot:
        raise HTTPException(404, "Production shot not found")
    if production["status"] in {"queued", "running", "pausing", "retrying", "stopping"}:
        raise HTTPException(409, "Pause or stop the production before retrying a shot")
    updates: dict[str, object] = {"status": "planned", "accepted_attempt": None}
    if body.prompt is not None:
        if not body.prompt.strip():
            raise HTTPException(400, "Retry prompt cannot be empty")
        updates["prompt"] = body.prompt.strip()
    update_shot(shot_id, **updates)
    if body.regenerate_downstream:
        for later in shots:
            if later["shot_index"] > shot["shot_index"] and later["continuity"] == "sequential":
                update_shot(later["id"], status="planned", accepted_attempt=None)
    update_production(production_id, status="queued", stage="shot_generation", progress=.65, error=None)
    add_message(production_id, "user", "both", "control", f"Retry {shot['title']} and affected sequential shots.")
    production_orchestrator.notify()
    return get_production(production_id, include_messages=True)


@app.post("/api/productions/{production_id}/imports/jobs")
async def import_jobs_into_production(production_id: str, request: Request, body: ImportJobsBody):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    if production["status"] in {"queued", "running", "pausing", "retrying", "stopping"}:
        raise HTTPException(409, "Pause the production before importing results")
    if not body.job_ids or len(body.job_ids) > 50 or len(set(body.job_ids)) != len(body.job_ids):
        raise HTTPException(400, "Choose between 1 and 50 unique jobs")
    jobs = [get_job(job_id, public=False) for job_id in body.job_ids]
    if any(not job or job["status"] != "completed" or not job.get("output_path") or not Path(job["output_path"]).is_file() for job in jobs):
        raise HTTPException(409, "Every imported job must be completed and its video must exist")
    import_completed_jobs(production_id, jobs)
    return get_production(production_id, include_messages=True)


@app.patch("/api/productions/{production_id}/archive")
async def archive_production(production_id: str, request: Request, body: ArchiveBody):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    if production["status"] in {"queued", "running", "pausing", "retrying", "stopping"}:
        raise HTTPException(409, "An active production cannot be archived")
    update_production(production_id, archived=int(body.archived))
    add_event(production_id, "production.archived" if body.archived else "production.unarchived")
    return get_production(production_id, include_messages=True)


@app.post("/api/productions/{production_id}/duplicate")
async def duplicate_production(production_id: str, request: Request):
    require_csrf(request)
    source = get_production(production_id, private=True)
    if not source:
        raise HTTPException(404, "Production not found")
    duplicate_id = uuid.uuid4().hex
    intake = PRODUCTIONS / duplicate_id / "intake"
    intake.mkdir(parents=True, exist_ok=False)
    song_source = Path(source["song_path"])
    song_target = intake / song_source.name
    shutil.copy2(song_source, song_target)
    try:
        duplicate = create_production({
            "id": duplicate_id, "title": source["title"] + " (copy)", "lyrics": source["lyrics"],
            "song_path": str(song_target), "song_name": source["song_name"], "concept": source["concept"],
            "participation_mode": source["participation_mode"], "continuity_mode": source["continuity_mode"],
            "codex_runtime": source.get("codex_runtime", "codex"), "codex_model": source["codex_model"],
            "codex_effort": source["codex_effort"], "agy_runtime": source.get("agy_runtime", "agy"),
            "agy_model": source["agy_model"], "agy_effort": source["agy_effort"],
            "skills": source["skills"], "approval_gates": source["approval_gates"],
        })
        # Duplicate reusable reference media, never generated attempts/results.
        reference_map: dict[str, str] = {}
        for reference in list_references(production_id, private=True):
            suffix = Path(reference["path"]).suffix
            stored_dir = PRODUCTIONS / duplicate_id / "references" / "media"
            stored_dir.mkdir(parents=True, exist_ok=True)
            stored = stored_dir / f"{uuid.uuid4().hex}{suffix}"
            comfy = INPUT / f"production_ref_{uuid.uuid4().hex}{suffix}"
            shutil.copy2(reference["path"], stored)
            shutil.copy2(reference["path"], comfy)
            copied = add_reference(duplicate_id, reference["kind"], reference["name"], str(stored), str(comfy), comfy.name, reference["notes"])
            reference_map[reference["id"]] = copied["id"]
        source_shots = list_shots(production_id, private=True)
        if source_shots:
            replace_shot_plan(duplicate_id, [{
                "title": shot["title"], "prompt": shot["prompt"], "mode": shot["mode"],
                "continuity": shot["continuity"], "duration": shot["duration"],
                "megapixels": shot["megapixels"], "aspect_ratio": shot["aspect_ratio"],
                "steps": shot["steps"], "engine": shot["engine"],
                "turbo_profile": shot["turbo_profile"],
                "reference_ids": [reference_map[value] for value in shot.get("reference_ids", []) if value in reference_map],
            } for shot in source_shots])
        return get_production(duplicate_id, include_messages=True) or duplicate
    except (KeyError, ValueError, FileExistsError, FileNotFoundError, RuntimeError, OSError) as exc:
        shutil.rmtree(PRODUCTIONS / duplicate_id, ignore_errors=True)
        with connect() as db:
            db.execute("DELETE FROM productions WHERE id=?", (duplicate_id,))
        raise


@app.get("/api/productions/{production_id}/export")
async def export_production(production_id: str):
    production = get_production(production_id, include_messages=True)
    private = get_production(production_id, private=True)
    if not production or not private:
        raise HTTPException(404, "Production not found")
    folder = PRODUCTIONS / production_id
    export_path = folder / f"{production_id}-export.zip"
    manifest = folder / "export-manifest.json"
    manifest.write_text(json.dumps(production, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in folder.rglob("*"):
            if path.is_file() and path != export_path:
                archive.write(path, path.relative_to(folder))
    return FileResponse(export_path, filename=f"{production['title']}-production.zip", media_type="application/zip")


@app.delete("/api/productions/{production_id}")
async def delete_production_route(production_id: str, request: Request):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    if production["status"] in {"queued", "running", "pausing", "retrying", "stopping"}:
        raise HTTPException(409, "Stop the production before deleting it")
    references = list_references(production_id, private=True)
    target = (PRODUCTIONS / production_id).resolve()
    if target.parent != PRODUCTIONS.resolve():
        raise HTTPException(400, "Invalid production folder")
    with connect() as db:
        db.execute("DELETE FROM productions WHERE id=?", (production_id,))
    for reference in references:
        Path(reference["comfy_path"]).unlink(missing_ok=True)
    shutil.rmtree(target, ignore_errors=True)
    return {"deleted": True}


@app.post("/api/productions")
async def create_production_route(
    request: Request,
    title: str = Form(...),
    lyrics: str = Form(...),
    song: UploadFile = File(...),
    concept: str = Form(""),
    participation_mode: str = Form("interactive"),
    continuity_mode: str = Form("hybrid"),
    codex_runtime: str = Form(""),
    codex_model: str = Form(""),
    codex_effort: str = Form(""),
    agy_runtime: str = Form(""),
    agy_model: str = Form(""),
    agy_effort: str = Form(""),
    skills_json: str = Form("[]"),
    approval_gates_json: str = Form("[]"),
):
    require_csrf(request)
    if not title.strip() or len(title) > 160:
        raise HTTPException(400, "Production title is required and must be at most 160 characters")
    if not lyrics.strip() or len(lyrics) > 200_000:
        raise HTTPException(400, "Lyrics are required and must be at most 200,000 characters")
    if participation_mode not in {"autonomous", "interactive"}:
        raise HTTPException(400, "Participation mode must be autonomous or interactive")
    if continuity_mode not in {"sequential", "hard_cut", "segmented", "hybrid"}:
        raise HTTPException(400, "Unsupported continuity mode")
    allowed_audio = {
        "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac",
        "audio/flac": ".flac", "audio/ogg": ".ogg",
    }
    suffix = allowed_audio.get(song.content_type or "")
    if not suffix:
        raise HTTPException(400, "Song must be WAV, MP3, M4A, AAC, FLAC or OGG")
    data = await song.read(250 * 1024 * 1024 + 1)
    if len(data) > 250 * 1024 * 1024:
        raise HTTPException(400, "Song is larger than 250 MB")
    try:
        selected_skills = json.loads(skills_json)
        approval_gates = json.loads(approval_gates_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Skills and approval gates must be JSON arrays") from exc
    if not isinstance(selected_skills, list) or not isinstance(approval_gates, list):
        raise HTTPException(400, "Skills and approval gates must be arrays")
    for skill_id in selected_skills:
        skill = get_skill(str(skill_id))
        if not skill or not skill["enabled"] or not skill["valid"]:
            raise HTTPException(400, f"Selected skill is unavailable: {skill_id}")
    settings = get_agent_settings()
    selected_codex_runtime = codex_runtime.strip() or settings.get("codex_runtime", "codex")
    selected_agy_runtime = agy_runtime.strip() or settings.get("agy_runtime", "agy")
    if selected_codex_runtime not in {"codex", "agy"} or selected_agy_runtime not in {"codex", "agy"}:
        raise HTTPException(400, "Agent runtime must be codex or agy")
    if selected_agy_runtime != "agy":
        raise HTTPException(400, "The media-analysis seat must use AGY")
    catalog = await asyncio.to_thread(model_catalog)
    codex_options = {item["id"]: item for item in catalog[selected_codex_runtime]}
    agy_options = {item["id"]: item for item in catalog[selected_agy_runtime]}
    codex_available = set(codex_options)
    agy_available = set(agy_options)
    selected_codex_model = codex_model.strip() or settings["codex_model"]
    selected_agy_model = agy_model.strip() or settings["agy_model"]
    if not codex_model.strip() and selected_codex_model not in codex_available and catalog[selected_codex_runtime]:
        selected_codex_model = catalog[selected_codex_runtime][0]["id"]
    if not agy_model.strip() and selected_agy_model not in agy_available and catalog[selected_agy_runtime]:
        selected_agy_model = catalog[selected_agy_runtime][0]["id"]
    if selected_codex_model not in codex_available:
        raise HTTPException(400, f"Model {selected_codex_model} is unavailable through {selected_codex_runtime}")
    if selected_agy_model not in agy_available:
        raise HTTPException(400, f"Model {selected_agy_model} is unavailable through {selected_agy_runtime}")
    selected_codex_effort = codex_effort.strip() or settings["codex_effort"]
    selected_agy_effort = agy_effort.strip() or settings["agy_effort"]
    if selected_codex_effort not in codex_options[selected_codex_model].get("efforts", []):
        if codex_effort.strip():
            raise HTTPException(400, f"Unsupported thinking level for {selected_codex_model}")
        selected_codex_effort = codex_options[selected_codex_model].get("default_effort") or codex_options[selected_codex_model]["efforts"][0]
    if selected_agy_effort not in agy_options[selected_agy_model].get("efforts", []):
        if agy_effort.strip():
            raise HTTPException(400, f"Unsupported thinking level for {selected_agy_model}")
        selected_agy_effort = agy_options[selected_agy_model].get("default_effort") or agy_options[selected_agy_model]["efforts"][0]
    production_id = uuid.uuid4().hex
    intake = PRODUCTIONS / production_id / "intake"
    intake.mkdir(parents=True, exist_ok=False)
    song_path = intake / ("song" + suffix)
    song_path.write_bytes(data)
    try:
        return create_production({
            "id": production_id, "title": title.strip(), "lyrics": lyrics.strip(),
            "song_path": str(song_path), "song_name": song.filename or song_path.name,
            "concept": concept.strip(), "participation_mode": participation_mode,
            "continuity_mode": continuity_mode,
            "codex_runtime": selected_codex_runtime,
            "codex_model": selected_codex_model,
            "codex_effort": selected_codex_effort,
            "agy_runtime": selected_agy_runtime,
            "agy_model": selected_agy_model,
            "agy_effort": selected_agy_effort,
            "skills": [str(value) for value in selected_skills],
            "approval_gates": [str(value) for value in approval_gates],
        })
    except Exception:
        shutil.rmtree(PRODUCTIONS / production_id, ignore_errors=True)
        raise


@app.post("/api/productions/{production_id}/start")
async def start_production(production_id: str, request: Request):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    if production["status"] not in {"draft", "paused", "stopped", "failed"}:
        raise HTTPException(409, "Production cannot be started from its current state")
    stage = "song_analysis" if production["status"] == "draft" else production["stage"]
    update_production(production_id, status="queued", stage=stage, pause_requested=0, stop_requested=0, error=None)
    add_message(production_id, "user", "both", "control", "Start or resume production.")
    production_orchestrator.notify()
    return get_production(production_id, include_messages=True)


@app.post("/api/productions/{production_id}/pause")
async def pause_production(production_id: str, request: Request):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    if production["status"] in {"queued", "running", "retrying"}:
        update_production(production_id, status="pausing" if production["status"] == "running" else "paused", pause_requested=1 if production["status"] == "running" else 0)
        if production["status"] == "running":
            await production_orchestrator.cancel_agents(production_id)
    return get_production(production_id, include_messages=True)


@app.post("/api/productions/{production_id}/resume")
async def resume_production(production_id: str, request: Request):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    if production["status"] not in {"paused", "stopped", "failed"}:
        raise HTTPException(409, "Production is not paused")
    update_production(production_id, status="queued", pause_requested=0, stop_requested=0, error=None)
    add_message(production_id, "user", "both", "control", "Resume from the last checkpoint.")
    production_orchestrator.notify()
    return get_production(production_id, include_messages=True)


@app.post("/api/productions/{production_id}/stop")
async def stop_production(production_id: str, request: Request, body: ProductionControlBody):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    active = production["status"] in {"running", "retrying", "pausing"}
    update_production(production_id, status="stopping" if active else "stopped", stop_requested=1 if active else 0)
    if active:
        await production_orchestrator.cancel_agents(production_id)
    if body.cancel_generation:
        await production_orchestrator.cancel_generation(production_id)
    add_message(production_id, "user", "both", "control", "Stop production and preserve the current checkpoint.")
    return get_production(production_id, include_messages=True)


@app.post("/api/productions/{production_id}/interventions")
async def production_intervention(production_id: str, request: Request, body: InterventionBody):
    require_csrf(request)
    if body.recipient not in {"both", "codex", "agy"}:
        raise HTTPException(400, "Recipient must be both, codex or agy")
    if not body.content.strip() or len(body.content) > 20_000:
        raise HTTPException(400, "Message is required and must be at most 20,000 characters")
    if not get_production(production_id, private=True):
        raise HTTPException(404, "Production not found")
    message = add_message(production_id, "user", body.recipient, "intervention", body.content.strip(), {"priority": "user"})
    return {"message": message, "production": get_production(production_id, include_messages=True)}


@app.post("/api/productions/{production_id}/decisions/{decision_id}/approve")
async def approve_production_decision(production_id: str, decision_id: str, request: Request, body: DecisionBody):
    require_csrf(request)
    production = get_production(production_id, private=True)
    if not production:
        raise HTTPException(404, "Production not found")
    if not resolve_decision(production_id, decision_id, "approved", "user", body.resolution):
        raise HTTPException(409, "Decision is not pending")
    if production["stage"] == "user_review":
        update_production(production_id, status="completed", stage="completed", progress=1,
                          finished_at=now_iso(), error=None)
        add_message(production_id, "user", "both", "decision", body.resolution.strip() or "Final video approved.")
        return get_production(production_id, include_messages=True)
    next_stage = {"treatment_review": "reference_development", "reference_review": "reference_generation",
                  "prompt_review": "shot_generation", "shot_review": "shot_generation"}.get(production["stage"])
    if next_stage:
        update_production(production_id, status="queued", stage=next_stage, error=None)
        production_orchestrator.notify()
    add_message(production_id, "user", "both", "decision", body.resolution.strip() or "Approved.")
    return get_production(production_id, include_messages=True)


@app.post("/api/productions/{production_id}/decisions/{decision_id}/reject")
async def reject_production_decision(production_id: str, decision_id: str, request: Request, body: DecisionBody):
    require_csrf(request)
    if not body.resolution.strip():
        raise HTTPException(400, "A rejection reason is required")
    if not resolve_decision(production_id, decision_id, "rejected", "user", body.resolution.strip()):
        raise HTTPException(409, "Decision is not pending")
    production = get_production(production_id, private=True)
    stage = {
        "treatment_review": "treatment_consultation",
        "reference_review": "reference_development",
        "prompt_review": "prompt_consultation",
        "shot_review": "shot_generation",
        "user_review": "revision_consultation",
    }.get(production["stage"] if production else "", production["stage"] if production else "intake")
    update_production(production_id, status="paused", stage=stage, error=None)
    add_message(production_id, "user", "both", "decision", "Rejected: " + body.resolution.strip())
    return get_production(production_id, include_messages=True)


@app.get("/api/productions/{production_id}/artifacts/{artifact_id}")
async def production_artifact(production_id: str, artifact_id: str):
    artifact = get_artifact(production_id, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    path = Path(artifact["path"])
    if not path.is_file():
        raise HTTPException(410, "Artifact file is missing")
    return FileResponse(path, filename=path.name, media_type="video/mp4" if path.suffix.lower() == ".mp4" else None)


@app.get("/api/productions/{production_id}/artifacts/attempt/{attempt_id}/{field}")
async def production_attempt_artifact(production_id: str, attempt_id: str, field: str):
    if field not in {"opening_frame_path", "output_path"}:
        raise HTTPException(404, "Unknown attempt artifact")
    attempt = get_attempt_for_production(production_id, attempt_id)
    if not attempt or not attempt.get(field):
        raise HTTPException(404, "Attempt artifact not found")
    path = Path(attempt[field])
    if not path.is_file():
        raise HTTPException(410, "Attempt artifact file is missing")
    return FileResponse(path, filename=path.name)


@app.get("/api/productions/{production_id}/artifacts/attempt/{attempt_id}/frame/{frame_index}")
async def production_attempt_frame(production_id: str, attempt_id: str, frame_index: int):
    attempt = get_attempt_for_production(production_id, attempt_id)
    if not attempt:
        raise HTTPException(404, "Attempt not found")
    try:
        frames = json.loads(attempt.get("frames_json") or "[]")
        path = Path(frames[frame_index])
    except (IndexError, TypeError, json.JSONDecodeError):
        raise HTTPException(404, "Review frame not found") from None
    if not path.is_file():
        raise HTTPException(410, "Review frame file is missing")
    return FileResponse(path, filename=path.name, media_type="image/jpeg")


@app.get("/api/productions/{production_id}/events")
async def production_events(production_id: str, request: Request):
    if not get_production(production_id):
        raise HTTPException(404, "Production not found")
    try:
        cursor = int(request.headers.get("last-event-id") or request.query_params.get("after") or 0)
    except ValueError:
        cursor = 0

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            events = list_events(production_id, cursor)
            for event in events:
                cursor = event["id"]
                yield f"id: {cursor}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


async def save_image(upload: UploadFile | None) -> tuple[str | None, str | None]:
    if not upload or not upload.filename:
        return None, None
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if upload.content_type not in allowed:
        raise HTTPException(400, "Only JPG, PNG or WebP images are allowed")
    data = await upload.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "Image is larger than 20 MB")
    suffix = allowed[upload.content_type]
    name = f"upload_{uuid.uuid4().hex}{suffix}"
    target = INPUT / name
    target.write_bytes(data)
    try:
        with Image.open(target) as image:
            image.verify()
    except (UnidentifiedImageError, OSError):
        target.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded file is not a valid image")
    return str(target), name


async def save_audio(upload: UploadFile | None) -> tuple[str | None, str | None]:
    if not upload or not upload.filename:
        return None, None
    allowed = {
        "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac",
        "audio/flac": ".flac", "audio/ogg": ".ogg", "application/ogg": ".ogg",
    }
    if upload.content_type not in allowed:
        raise HTTPException(400, "Only WAV, MP3, M4A, AAC, FLAC or OGG audio is allowed")
    data = await upload.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(400, "Audio is larger than 50 MB")
    name = f"audio_{uuid.uuid4().hex}{allowed[upload.content_type]}"
    target = INPUT / name
    target.write_bytes(data)
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        target.unlink(missing_ok=True)
        raise HTTPException(503, "ffprobe is required to validate reference audio")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", str(target)],
            capture_output=True, text=True, timeout=30,
        )
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
        duration = float(payload.get("format", {}).get("duration") or 0)
        has_audio = any(stream.get("codec_type") == "audio" for stream in payload.get("streams", []))
        if not has_audio or not 0.1 <= duration <= 60:
            raise ValueError
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired):
        target.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded file is not valid audio between 0.1 and 60 seconds")
    return str(target), name


async def save_video(upload: UploadFile | None) -> tuple[str | None, str | None]:
    if not upload or not upload.filename:
        return None, None
    allowed = {
        "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
        "video/x-matroska": ".mkv", "video/mpeg": ".mpeg",
    }
    if upload.content_type not in allowed:
        raise HTTPException(400, "Only MP4, MOV, WebM or MKV videos are allowed")
    data = await upload.read(500 * 1024 * 1024 + 1)
    if len(data) > 500 * 1024 * 1024:
        raise HTTPException(400, "Reference video is larger than 500 MB")
    name = f"reference_video_{uuid.uuid4().hex}{allowed[upload.content_type]}"
    target = INPUT / name
    target.write_bytes(data)
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        target.unlink(missing_ok=True)
        raise HTTPException(503, "ffprobe is required to validate reference video")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", str(target)], capture_output=True, text=True, timeout=60,
        )
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
        duration = float(payload.get("format", {}).get("duration") or 0)
        has_video = any(stream.get("codec_type") == "video" for stream in payload.get("streams", []))
        if not has_video or not 2 <= duration <= 15:
            raise ValueError
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired):
        target.unlink(missing_ok=True)
        raise HTTPException(400, "Reference video must contain video and be between 2 and 15 seconds")
    return str(target), name


def parse_prompts(raw: str, batch: bool) -> list[str]:
    raw = raw.strip()
    if not raw:
        raise HTTPException(400, "Prompt is required")
    prompts = [part.strip() for part in raw.replace("\r\n", "\n").split("\n\n") if part.strip()] if batch else [raw]
    if len(prompts) > 20:
        raise HTTPException(400, "Batch is limited to 20 prompts")
    if any(len(prompt) > 4000 for prompt in prompts):
        raise HTTPException(400, "Each prompt is limited to 4,000 characters")
    return prompts


@app.post("/api/jobs")
async def create_jobs(
    request: Request,
    prompt: str = Form(...), mode: str = Form("text"), duration: float = Form(5),
    engine: str | None = Form(None), steps: int | None = Form(None),
    resolution: str | None = Form(None),
    megapixels: float | None = Form(None), aspect_ratio: str | None = Form(None),
    encoder: str | None = Form(None), turbo_profile: str | None = Form(None),
    batch: bool = Form(False),
    connected: bool = Form(False), image: UploadFile | None = File(None),
    reference_images: list[UploadFile] = File(default=[]),
    reference_videos: list[UploadFile] = File(default=[]),
    reference_audio: UploadFile | None = File(None),
    no_audio: bool = Form(False),
    first_frame: UploadFile | None = File(None), last_frame: UploadFile | None = File(None),
    project_id: str = Form(""), folder_id: str = Form(""),
):
    require_csrf(request)
    if mode not in ("text", "opening", "closing", "frames", "reference") or not 0.5 <= duration <= 60:
        raise HTTPException(400, "Duration must be between 0.5 and 60 seconds")
    selected_project = project_id.strip() or None
    selected_folder = folder_id.strip() or None
    try:
        validate_location(selected_project, selected_folder)
    except (KeyError, ValueError) as exc:
        raise_library_error(exc)
    try:
        generation = normalize_generation_settings(
            mode, engine, steps, resolution, encoder, turbo_profile,
            megapixels=megapixels, aspect_ratio=aspect_ratio,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if generation.encoder == "clipproj" and not clipproj_ready():
        raise HTTPException(409, "ClipProj is not fully installed yet")
    if connected and (not batch or mode != "text"):
        raise HTTPException(400, "Connected generation requires multiple prompts in text mode")
    if mode == "text" and any((image, reference_audio, first_frame, last_frame)):
        raise HTTPException(400, "Text mode does not accept reference media")
    if mode == "frames" and (image or not first_frame):
        raise HTTPException(400, "I2V mode requires an opening image; the closing image is optional")
    if mode in ("opening", "closing") and not image:
        raise HTTPException(400, "This mode requires one image")
    if mode == "reference" and not (image or reference_images or reference_videos):
        raise HTTPException(400, "Reference mode requires at least one image or video")
    if mode in ("opening", "closing", "reference") and (first_frame or last_frame):
        raise HTTPException(400, "This mode accepts one image only")
    if mode != "reference" and (reference_images or reference_videos):
        raise HTTPException(400, "Reference images and videos are available in reference mode only")
    if len(reference_images) + (1 if image and mode == "reference" else 0) > 9:
        raise HTTPException(400, "Reference mode supports up to 9 images")
    if len(reference_videos) > 3:
        raise HTTPException(400, "Reference mode supports up to 3 videos")
    if mode != "reference" and reference_audio:
        raise HTTPException(400, "Reference audio is available in reference mode only")
    if mode != "reference" and generation.turbo_profile == "v4" and not (MODELS / "loras" / TURBO_LORAS["v4"]).exists():
        raise HTTPException(409, "Turbo v4 is not installed yet")
    if mode == "reference" and generation.engine == "turbo" and not (MODELS / "loras" / REF2VA_TURBO_LORA).exists():
        raise HTTPException(409, "Ref2VA Turbo LoRA is not installed yet")
    if mode == "reference" and duration > 5 and not REFERENCE_10S_MARKER.exists():
        raise HTTPException(409, "Reference mode above 5 seconds is not ready")
    prompts = parse_prompts(prompt, batch)
    if connected and len(prompts) < 2:
        raise HTTPException(400, "Connected generation requires at least two prompts")
    input_path = input_name = None
    reference_audio_path = reference_audio_name = None
    first_frame_path = first_frame_name = None
    last_frame_path = last_frame_name = None
    saved_paths: list[str] = []
    reference_image_names: list[str] = []
    reference_video_names: list[str] = []
    try:
        if image:
            input_path, input_name = await save_image(image)
            if input_path:
                saved_paths.append(input_path)
                if mode == "reference" and input_name:
                    reference_image_names.append(input_name)
        for reference_image in reference_images:
            path, name = await save_image(reference_image)
            if path and name:
                saved_paths.append(path)
                reference_image_names.append(name)
        for reference_video in reference_videos:
            path, name = await save_video(reference_video)
            if path and name:
                saved_paths.append(path)
                reference_video_names.append(name)
        if reference_audio:
            reference_audio_path, reference_audio_name = await save_audio(reference_audio)
            if reference_audio_path:
                saved_paths.append(reference_audio_path)
        if first_frame:
            first_frame_path, first_frame_name = await save_image(first_frame)
            if first_frame_path:
                saved_paths.append(first_frame_path)
        if last_frame:
            last_frame_path, last_frame_name = await save_image(last_frame)
            if last_frame_path:
                saved_paths.append(last_frame_path)
    except Exception:
        for path in saved_paths:
            Path(path).unlink(missing_ok=True)
        raise
    created = []
    with connect() as db:
        position = next_position(db)
        sequence_id = None
        if connected:
            sequence_id = uuid.uuid4().hex
            now = now_iso()
            title = f"רצף מחובר · {len(prompts)} שוטים"
            db.execute(
                """INSERT INTO sequences
                       (id,kind,title,status,position,engine,encoder,steps,width,height,duration,
                        progress,phase,current_item,total_items,created_at,updated_at)
                   VALUES(?,'connected',?,'queued',?,?,?,?,?,?,?,0,'queued',0,?,?,?)""",
                (sequence_id, title, position, generation.engine, generation.encoder,
                 generation.steps, generation.width, generation.height, duration,
                 len(prompts), now, now),
            )
        for index, text in enumerate(prompts):
            job_id = uuid.uuid4().hex
            now = now_iso()
            if connected:
                db.execute(
                    """INSERT INTO jobs
                       (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,megapixels,aspect_ratio,seed,
                        sequence_id,sequence_index,sequence_total,status,position,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?)""",
                    (job_id, text, "text", duration, generation.engine, generation.turbo_profile, generation.encoder,
                     generation.steps, generation.width, generation.height, generation.megapixels, generation.aspect_ratio,
                     str(secrets.randbits(64)), sequence_id, index + 1, len(prompts), position, now, now),
                )
            else:
                db.execute("""INSERT INTO jobs
                  (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,megapixels,aspect_ratio,seed,status,position,input_path,input_name,
                   reference_images_json,reference_videos_json,no_audio,
                   reference_audio_path,reference_audio_name,
                   first_frame_path,first_frame_name,last_frame_path,last_frame_name,
                   created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (job_id, text, mode, duration, generation.engine, generation.turbo_profile, generation.encoder,
                   generation.steps, generation.width, generation.height, generation.megapixels, generation.aspect_ratio,
                   str(secrets.randbits(64)), position + index,
                   input_path, input_name, json.dumps(reference_image_names), json.dumps(reference_video_names), int(no_audio),
                   reference_audio_path, reference_audio_name,
                   first_frame_path, first_frame_name,
                   last_frame_path, last_frame_name, now, now))
            created.append(job_id)
    try:
        if selected_project:
            if sequence_id:
                assign_asset("sequence", sequence_id, selected_project, selected_folder)
            else:
                for job_id in created:
                    assign_asset("job", job_id, selected_project, selected_folder)
    except Exception as exc:
        with connect() as db:
            db.executemany(
                "DELETE FROM asset_assignments WHERE source_type='job' AND source_id=?",
                [(job_id,) for job_id in created],
            )
            if sequence_id:
                db.execute("DELETE FROM asset_assignments WHERE source_type='sequence' AND source_id=?", (sequence_id,))
                db.execute("DELETE FROM jobs WHERE sequence_id=?", (sequence_id,))
                db.execute("DELETE FROM sequences WHERE id=?", (sequence_id,))
            else:
                for job_id in created:
                    db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        for path in saved_paths:
            Path(path).unlink(missing_ok=True)
        raise_library_error(exc)
    worker.notify()
    return {"created": created, "sequence_id": sequence_id}


@app.patch("/api/queue/order")
async def reorder(request: Request, body: OrderBody):
    require_csrf(request)
    if len(body.ids) != len(set(body.ids)):
        raise HTTPException(400, "Duplicate job id")
    with connect() as db:
        rows = db.execute(
            """SELECT id,position FROM jobs
               WHERE status='queued' AND sequence_id IS NULL ORDER BY position"""
        ).fetchall()
        queued = {row["id"] for row in rows}
        if set(body.ids) != queued:
            raise HTTPException(409, "Order must contain every standalone queued job exactly once")
        positions = sorted(row["position"] for row in rows)
        for pos, job_id in zip(positions, body.ids):
            db.execute("UPDATE jobs SET position=?,updated_at=? WHERE id=?", (pos, now_iso(), job_id))
    return {"ok": True}


@app.post("/api/sequences/join")
async def join_history(request: Request, body: JoinBody):
    require_csrf(request)
    if not 2 <= len(body.ids) <= 20:
        raise HTTPException(400, "Choose between 2 and 20 completed videos")
    if len(body.ids) != len(set(body.ids)):
        raise HTTPException(400, "The same result cannot be selected twice")

    sources = []
    with connect() as db:
        for reference in body.ids:
            source_type, separator, source_id = reference.partition(":")
            if not separator:
                source_type, source_id = "job", reference
            if source_type == "job":
                row = db.execute(
                    "SELECT id,prompt,status,output_path FROM jobs WHERE id=?", (source_id,)
                ).fetchone()
                if not row or row["status"] != "completed" or not row["output_path"]:
                    raise HTTPException(409, "Every selected job must be completed")
                sources.append({
                    "prompt": row["prompt"], "path": row["output_path"],
                    "source_job_id": row["id"], "source_sequence_id": None,
                })
            elif source_type == "sequence":
                row = db.execute(
                    "SELECT id,title,status,output_path FROM sequences WHERE id=?", (source_id,)
                ).fetchone()
                if not row or row["status"] != "completed" or not row["output_path"]:
                    raise HTTPException(409, "Every selected sequence must be completed")
                sources.append({
                    "prompt": row["title"], "path": row["output_path"],
                    "source_job_id": None, "source_sequence_id": row["id"],
                })
            else:
                raise HTTPException(400, "Unknown result type")

        if any(not Path(source["path"]).exists() for source in sources):
            raise HTTPException(409, "One of the selected video files is missing")

        sequence_id = uuid.uuid4().hex
        now = now_iso()
        position = next_position(db)
        title = f"חיבור מההיסטוריה · {len(sources)} קטעים"
        db.execute(
            """INSERT INTO sequences
               (id,kind,title,status,position,progress,phase,current_item,total_items,created_at,updated_at)
               VALUES(?,'history',?,'queued',?,0,'queued',0,?,?,?)""",
            (sequence_id, title, position, len(sources), now, now),
        )
        for index, source in enumerate(sources, 1):
            db.execute(
                """INSERT INTO sequence_items
                   (sequence_id,item_index,prompt,source_job_id,source_sequence_id,clip_path,status)
                   VALUES(?,?,?,?,?,?,'ready')""",
                (sequence_id, index, source["prompt"], source["source_job_id"],
                 source["source_sequence_id"], source["path"]),
            )
    worker.notify()
    return {"sequence_id": sequence_id}


@app.post("/api/sequences/{sequence_id}/cancel")
async def cancel_sequence(request: Request, sequence_id: str):
    require_csrf(request)
    if not await worker.cancel_sequence(sequence_id):
        raise HTTPException(409, "Sequence cannot be canceled at this stage")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str):
    require_csrf(request)
    if not await worker.cancel(job_id):
        raise HTTPException(409, "Job cannot be canceled")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
async def delete_job(request: Request, job_id: str):
    require_csrf(request)
    job = get_job(job_id, public=False)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] in ("running", "starting", "verifying"):
        raise HTTPException(409, "Cancel the running job first")
    with connect() as db:
        in_active_assembly = db.execute(
            """SELECT COUNT(*) FROM sequence_items i JOIN sequences s ON s.id=i.sequence_id
               WHERE i.source_job_id=? AND s.status IN ('queued','starting','running','verifying')""",
            (job_id,),
        ).fetchone()[0]
    if in_active_assembly:
        raise HTTPException(409, "This video is currently used by an active join")
    input_paths = {
        job.get(key) for key in (
            "input_path", "reference_audio_path", "first_frame_path", "last_frame_path",
        ) if job.get(key)
    }
    remove_assignment("job", job_id)
    with connect() as db:
        db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        for path in input_paths:
            remaining = db.execute("""
                SELECT COUNT(*) FROM jobs
                WHERE input_path=? OR reference_audio_path=? OR first_frame_path=? OR last_frame_path=?
            """, (path, path, path, path)).fetchone()[0]
            if remaining == 0:
                Path(path).unlink(missing_ok=True)
    if job.get("output_path"):
        Path(job["output_path"]).unlink(missing_ok=True)
    return {"ok": True}


@app.delete("/api/sequences/{sequence_id}")
async def delete_sequence(request: Request, sequence_id: str):
    require_csrf(request)
    sequence = get_sequence(sequence_id, public=False)
    if not sequence:
        raise HTTPException(404, "Sequence not found")
    if sequence["status"] in ("queued", "starting", "running", "verifying"):
        raise HTTPException(409, "Cancel the active sequence first")

    paths: set[str] = {sequence["output_path"]} if sequence.get("output_path") else set()
    with connect() as db:
        in_active_assembly = db.execute(
            """SELECT COUNT(*) FROM sequence_items i JOIN sequences s ON s.id=i.sequence_id
               WHERE i.source_sequence_id=? AND s.status IN ('queued','starting','running','verifying')""",
            (sequence_id,),
        ).fetchone()[0]
    if in_active_assembly:
        raise HTTPException(409, "This sequence is currently used by an active join")
    remove_assignment("sequence", sequence_id)
    with connect() as db:
        if sequence["kind"] == "connected":
            child_rows = db.execute(
                """SELECT output_path,first_frame_path,last_frame_path,input_path,reference_audio_path
                   FROM jobs WHERE sequence_id=?""",
                (sequence_id,),
            ).fetchall()
            for row in child_rows:
                paths.update(path for path in row if path)
            db.execute("DELETE FROM jobs WHERE sequence_id=?", (sequence_id,))
        db.execute("DELETE FROM sequences WHERE id=?", (sequence_id,))
    for path in paths:
        Path(path).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/video")
async def video(job_id: str):
    job = get_job(job_id, public=False)
    if not job or job["status"] != "completed" or not job.get("output_path"):
        raise HTTPException(404, "Video not found")
    path = Path(job["output_path"])
    if not path.exists():
        raise HTTPException(404, "Video file is missing")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/artifacts/final-video")
async def final_video_artifact():
    path = ROOT / "state" / "e2e_belly_of_the_beast" / "belly_of_the_beast_final.mp4"
    if not path.exists():
        raise HTTPException(404, "The final video has not been created")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/sequences/{sequence_id}/video")
async def sequence_video(sequence_id: str):
    sequence = get_sequence(sequence_id, public=False)
    if not sequence or sequence["status"] != "completed" or not sequence.get("output_path"):
        raise HTTPException(404, "Joined video not found")
    path = Path(sequence["output_path"])
    if not path.exists():
        raise HTTPException(404, "Joined video file is missing")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


dist = ROOT / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        candidate = (dist / path).resolve()
        if path and candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
