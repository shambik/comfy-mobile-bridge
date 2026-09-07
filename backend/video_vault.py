"""Persistent, path-safe storage for videos that should be downloadable in the app.

The vault is intentionally separate from generated jobs and library projects. A
video can therefore be kept as a durable hand-off artifact without creating a
new project or synthetic sequence record for every upload.
"""

from __future__ import annotations

import hashlib
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from .comfy import media_probe
from .config import VIDEO_VAULT
from .db import connect, now_iso

MAX_VIDEO_BYTES = 500 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024

CONTENT_TYPE_SUFFIXES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/mpeg": ".mpeg",
}
EXTENSION_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
}


def _vault_root() -> Path:
    root = VIDEO_VAULT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_display_name(value: str | None, fallback: str, suffix: str) -> str:
    candidate = Path(value or fallback).name
    candidate = "".join(character for character in candidate if character.isprintable() and character not in {"\x00", "\r", "\n"})
    if not candidate or candidate in {".", ".."}:
        candidate = fallback
    if Path(candidate).suffix.lower() not in EXTENSION_CONTENT_TYPES:
        candidate = f"{candidate}{suffix}"
    return candidate[:240]


def _upload_format(upload: UploadFile) -> tuple[str, str, str]:
    filename = Path(upload.filename or "video.mp4").name
    extension = Path(filename).suffix.lower()
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    suffix = CONTENT_TYPE_SUFFIXES.get(content_type)
    if suffix is None and extension in EXTENSION_CONTENT_TYPES:
        suffix = extension if extension != ".mpg" else ".mpeg"
        content_type = EXTENSION_CONTENT_TYPES[extension]
    if suffix is None or content_type not in CONTENT_TYPE_SUFFIXES:
        raise ValueError("Supported video types are MP4, MOV, WebM, MKV, and MPEG")
    return filename, suffix, content_type


def _safe_item_path(stored_name: str) -> Path:
    root = _vault_root()
    candidate = (root / stored_name).resolve()
    if candidate.parent != root or candidate.name != stored_name or candidate.suffix.lower() not in EXTENSION_CONTENT_TYPES:
        raise RuntimeError("Stored video path is invalid")
    return candidate


def _row_to_public(row: Any) -> dict[str, Any]:
    stored_name = str(row["stored_name"])
    path = _safe_item_path(stored_name)
    item_id = str(row["id"])
    return {
        "id": item_id,
        "original_name": str(row["original_name"]),
        "content_type": str(row["content_type"]),
        "size": int(row["size"]),
        "sha256": str(row["sha256"]),
        "duration": float(row["duration"]),
        "width": int(row["width"]),
        "height": int(row["height"]),
        "frame_rate": row["frame_rate"],
        "created_at": str(row["created_at"]),
        "available": path.is_file(),
        "video_url": f"/api/video-vault/{item_id}/video",
        "download_url": f"/api/video-vault/{item_id}/download",
        "delete_url": f"/api/video-vault/{item_id}",
    }


def _get_row(item_id: str):
    with connect() as db:
        return db.execute(
            "SELECT id,original_name,stored_name,content_type,size,sha256,duration,width,height,frame_rate,created_at "
            "FROM video_vault_items WHERE id=?",
            (item_id,),
        ).fetchone()


def get_video_item(item_id: str) -> dict[str, Any] | None:
    row = _get_row(item_id)
    return _row_to_public(row) if row else None


def list_video_vault() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT id,original_name,stored_name,content_type,size,sha256,duration,width,height,frame_rate,created_at "
            "FROM video_vault_items ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [_row_to_public(row) for row in rows]


def _metadata(probe: dict[str, Any]) -> tuple[float, int, int, str | None]:
    format_info = probe.get("format") or {}
    try:
        duration = float(format_info.get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("Video has no valid duration")
    stream = next((item for item in probe.get("streams", []) if item.get("codec_type") == "video"), None)
    if not stream:
        raise RuntimeError("Video has no video stream")
    try:
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
    except (TypeError, ValueError):
        width = height = 0
    if width <= 0 or height <= 0:
        raise RuntimeError("Video dimensions could not be read")
    frame_rate = str(stream.get("r_frame_rate") or "") or None
    return duration, width, height, frame_rate


async def store_video(upload: UploadFile, display_name: str | None = None) -> dict[str, Any]:
    filename, suffix, content_type = _upload_format(upload)
    root = _vault_root()
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    final_path = root / stored_name
    part_path = root / f".{stored_name}.part"
    digest = hashlib.sha256()
    size = 0

    try:
        with part_path.open("wb") as handle:
            while True:
                chunk = await upload.read(READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise ValueError(f"Video exceeds the {MAX_VIDEO_BYTES // (1024 * 1024)}MB upload limit")
                handle.write(chunk)
                digest.update(chunk)
        if size == 0:
            raise ValueError("The uploaded video is empty")
        os.replace(part_path, final_path)
        try:
            probe = media_probe(final_path, require_audio=False)
            duration, width, height, frame_rate = _metadata(probe)
        except Exception as exc:
            raise RuntimeError(f"Video validation failed: {exc}") from exc

        item_id = uuid.uuid4().hex
        original_name = _safe_display_name(display_name, filename, suffix)
        created_at = now_iso()
        with connect() as db:
            db.execute(
                """
                INSERT INTO video_vault_items
                (id,original_name,stored_name,content_type,size,sha256,duration,width,height,frame_rate,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (item_id, original_name, stored_name, content_type, size, digest.hexdigest(), duration, width, height, frame_rate, created_at),
            )
            row = db.execute(
                "SELECT id,original_name,stored_name,content_type,size,sha256,duration,width,height,frame_rate,created_at "
                "FROM video_vault_items WHERE id=?",
                (item_id,),
            ).fetchone()
        return _row_to_public(row)
    except Exception:
        for path in (part_path, final_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise


def video_file(item_id: str) -> tuple[dict[str, Any], Path] | None:
    row = _get_row(item_id)
    if not row:
        return None
    path = _safe_item_path(str(row["stored_name"]))
    if not path.is_file():
        raise FileNotFoundError("The stored video file is missing")
    return _row_to_public(row), path


def _unlink_with_retry(path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(8):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            if attempt < 7:
                time.sleep(0.25)
    if last_error:
        raise last_error


def delete_video_item(item_id: str) -> dict[str, Any]:
    row = _get_row(item_id)
    if not row:
        raise KeyError("Video not found")
    path = _safe_item_path(str(row["stored_name"]))
    file_deleted = False
    if path.is_file():
        _unlink_with_retry(path)
        file_deleted = True
    with connect() as db:
        db.execute("DELETE FROM video_vault_items WHERE id=?", (item_id,))
    return {"deleted": True, "file_deleted": file_deleted, "item_id": item_id}
