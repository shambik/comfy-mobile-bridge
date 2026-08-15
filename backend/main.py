import asyncio
import json
import secrets
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import (ALLOWED_HOSTS, APP_HOST, APP_PORT, APP_VERSION,
                     CLIPPROJ_NODE_COMMIT, CLIPPROJ_NODE_DIR, COMFY_HOST, COMFY_PORT,
                     CLIPPROJ_PROJECTION, CLIPPROJ_TEXT_ENCODER, INPUT, LOGS, MODELS,
                     REF2VA_MODEL, REF2VA_TURBO_LORA, REFERENCE_10S_MARKER, ROOT,
                     SPECTRUM_NODE_DIR, SPECTRUM_NODE_VERSION, TURBO_LORAS)
from .db import (connect, get_job, get_sequence, init_db, list_jobs,
                 list_sequences, next_position, now_iso)
from .generation import normalize_generation_settings
from .security import COOKIE, new_token, require_csrf
from .worker import QueueWorker

worker = QueueWorker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker.start()
    yield
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


def clipproj_ready() -> bool:
    return all((
        (CLIPPROJ_NODE_DIR / "clipproj_nodes.py").exists(),
        (MODELS / "text_encoders" / CLIPPROJ_TEXT_ENCODER).exists(),
        (MODELS / "clip_projections" / CLIPPROJ_PROJECTION).exists(),
    ))


def public_health():
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
        "pid": worker.comfy.process.pid if worker.comfy.process and worker.comfy.process.poll() is None else None,
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


@app.get("/api/jobs")
async def jobs():
    return {"jobs": list_jobs(), "sequences": list_sequences(), **public_health()}


@app.get("/api/events")
async def events(request: Request):
    async def stream():
        while not await request.is_disconnected():
            payload = {"jobs": list_jobs(), "sequences": list_sequences(), **public_health()}
            yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            await asyncio.sleep(4)
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
    encoder: str | None = Form(None), turbo_profile: str | None = Form(None),
    batch: bool = Form(False),
    connected: bool = Form(False), image: UploadFile | None = File(None),
    reference_images: list[UploadFile] = File(default=[]),
    reference_videos: list[UploadFile] = File(default=[]),
    reference_audio: UploadFile | None = File(None),
    no_audio: bool = Form(False),
    first_frame: UploadFile | None = File(None), last_frame: UploadFile | None = File(None),
):
    require_csrf(request)
    if mode not in ("text", "opening", "closing", "frames", "reference") or not 0.5 <= duration <= 60:
        raise HTTPException(400, "Duration must be between 0.5 and 60 seconds")
    try:
        generation = normalize_generation_settings(
            mode, engine, steps, resolution, encoder, turbo_profile,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if generation.encoder == "clipproj" and not clipproj_ready():
        raise HTTPException(409, "ClipProj is not fully installed yet")
    if connected and (not batch or mode != "text"):
        raise HTTPException(400, "Connected generation requires multiple prompts in text mode")
    if mode == "text" and any((image, reference_audio, first_frame, last_frame)):
        raise HTTPException(400, "Text mode does not accept reference media")
    if mode == "frames" and (image or not first_frame or not last_frame):
        raise HTTPException(400, "Combined frame mode requires an opening and a closing image")
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
                       (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,seed,
                        sequence_id,sequence_index,sequence_total,status,position,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?)""",
                    (job_id, text, "text", duration, generation.engine, generation.turbo_profile, generation.encoder,
                     generation.steps, generation.width, generation.height,
                     str(secrets.randbits(64)), sequence_id, index + 1, len(prompts),
                     position, now, now),
                )
                db.execute(
                    """INSERT INTO sequence_items
                       (sequence_id,item_index,prompt,job_id,status)
                       VALUES(?,?,?,?, 'queued')""",
                    (sequence_id, index + 1, text, job_id),
                )
            else:
                db.execute("""INSERT INTO jobs
                  (id,prompt,mode,duration,engine,turbo_profile,encoder,steps,width,height,seed,status,position,input_path,input_name,
                   reference_images_json,reference_videos_json,no_audio,
                   reference_audio_path,reference_audio_name,
                   first_frame_path,first_frame_name,last_frame_path,last_frame_name,
                   created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (job_id, text, mode, duration, generation.engine, generation.turbo_profile, generation.encoder,
                   generation.steps, generation.width, generation.height,
                   str(secrets.randbits(64)), position + index,
                   input_path, input_name, json.dumps(reference_image_names), json.dumps(reference_video_names), int(no_audio),
                   reference_audio_path, reference_audio_name,
                   first_frame_path, first_frame_name,
                   last_frame_path, last_frame_name, now, now))
            created.append(job_id)
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
