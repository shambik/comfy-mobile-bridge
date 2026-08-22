from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from .config import OUTPUT, PROJECTS
from .db import connect, now_iso


_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_ACTIVE = {"queued", "starting", "running", "verifying"}
_FILE_LOCK_RETRIES = 10

# Generated assets are identified by (source_type, source_id).  Absolute paths
# are still retained for compatibility with the existing database, but every
# move/rename updates all registered consumers of those paths.  Keeping this
# inventory in one place prevents production review records from retaining a
# stale ComfyUI output path after the Studio organizes a file.
_PATH_COLUMNS: dict[str, tuple[str, ...]] = {
    "jobs": (
        "input_path", "reference_audio_path", "source_audio_path",
        "first_frame_path", "last_frame_path", "output_path",
    ),
    "sequences": ("output_path",),
    "sequence_items": ("clip_path", "continuity_frame_path"),
    "productions": ("song_path",),
    "production_shot_attempts": ("opening_frame_path", "output_path"),
    "production_artifacts": ("path",),
    "production_references": ("path", "comfy_path"),
}
_JSON_PATH_COLUMNS: dict[str, tuple[str, ...]] = {
    "production_shot_attempts": ("frames_json",),
}


def _is_transient_file_lock(exc: OSError) -> bool:
    """Return whether Windows reported a file that is temporarily in use."""
    return getattr(exc, "winerror", None) in {32, 33}


def _move_with_retry(source: Path, target: Path) -> None:
    """Move an asset while tolerating short-lived video-preview/file locks."""
    for attempt in range(_FILE_LOCK_RETRIES):
        try:
            shutil.move(str(source), str(target))
            return
        except OSError as exc:
            if not _is_transient_file_lock(exc) or attempt == _FILE_LOCK_RETRIES - 1:
                raise
            # A browser range request or a just-finished encoder normally
            # releases the handle within a few seconds.  Back off without
            # masking a real permission or path error.
            time.sleep(0.25 * (attempt + 1))


def _replace_with_retry(source: Path, target: Path) -> None:
    """Replace/rename an asset while tolerating short-lived file locks."""
    for attempt in range(_FILE_LOCK_RETRIES):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            if not _is_transient_file_lock(exc) or attempt == _FILE_LOCK_RETRIES - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def validate_library_name(value: str, label: str = "Name") -> str:
    name = value.strip()
    if not name or len(name) > 100:
        raise ValueError(f"{label} must contain between 1 and 100 characters")
    if name in {".", ".."} or name.endswith((" ", ".")) or _INVALID_NAME.search(name):
        raise ValueError(f"{label} contains characters Windows cannot use in a folder or filename")
    if name.split(".", 1)[0].upper() in _RESERVED:
        raise ValueError(f"{label} is a reserved Windows name")
    return name


def _table_exists(db, table: str) -> bool:
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone())


def _table_columns_for(db, table: str) -> set[str]:
    if not _table_exists(db, table):
        return set()
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _path_key(value: str | Path) -> str:
    """Normalize a database path for case-insensitive Windows comparisons."""
    try:
        # ``Path.resolve()`` also expands Windows 8.3 aliases such as
        # ``DAVIDS~1``.  ComfyUI and the bridge can obtain the same file from
        # different APIs and otherwise compare those spellings as different
        # assets.
        normalized = str(Path(value).resolve())
    except OSError:
        normalized = os.path.abspath(os.path.normpath(str(value)))
    return os.path.normcase(os.path.normpath(normalized))


def _rewrite_path_value(value: Any, old: Path, new: Path, *, prefix: bool) -> Any:
    if not isinstance(value, str) or not value:
        return value
    current = _path_key(value)
    old_key = _path_key(old)
    if current == old_key:
        return str(new)
    if not prefix:
        return value
    try:
        if os.path.commonpath((current, old_key)) != old_key:
            return value
        relative = os.path.relpath(os.path.normpath(value), os.path.normpath(str(old)))
        if relative == "." or relative.startswith(".." + os.sep) or relative == "..":
            return value
        return str(Path(new) / relative)
    except (OSError, ValueError):
        return value


def _rewrite_json_paths(value: Any, old: Path, new: Path, *, prefix: bool) -> Any:
    if isinstance(value, str):
        return _rewrite_path_value(value, old, new, prefix=prefix)
    if isinstance(value, list):
        return [_rewrite_json_paths(item, old, new, prefix=prefix) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_json_paths(item, old, new, prefix=prefix) for key, item in value.items()}
    return value


def _rewrite_registered_paths(db, old: Path, new: Path, *, prefix: bool = False) -> int:
    """Rewrite all persisted references to a moved file or directory.

    The update happens in the caller's SQLite transaction, so a failed move or
    database operation cannot leave the job table and production tables
    disagreeing about where the same generated asset lives.
    """
    changed = 0
    old = Path(old).resolve()
    new = Path(new).resolve()
    for table, columns in _PATH_COLUMNS.items():
        available = _table_columns_for(db, table)
        selected = [column for column in columns if column in available]
        selected_json = [column for column in _JSON_PATH_COLUMNS.get(table, ()) if column in available]
        if not selected and not selected_json:
            continue
        fields = [*selected, *selected_json]
        rows = db.execute(f"SELECT rowid, {','.join(fields)} FROM {table}").fetchall()
        for row in rows:
            updates: dict[str, Any] = {}
            for column in selected:
                replacement = _rewrite_path_value(row[column], old, new, prefix=prefix)
                if replacement != row[column]:
                    updates[column] = replacement
            for column in selected_json:
                raw = row[column]
                if not raw:
                    continue
                try:
                    decoded = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                rewritten = _rewrite_json_paths(decoded, old, new, prefix=prefix)
                if rewritten != decoded:
                    updates[column] = json.dumps(rewritten, ensure_ascii=False)
            if not updates:
                continue
            if "updated_at" in available:
                updates["updated_at"] = now_iso()
            db.execute(
                f"UPDATE {table} SET {','.join(f'{key}=?' for key in updates)} WHERE rowid=?",
                (*updates.values(), row["rowid"]),
            )
            changed += 1
    return changed


def init_library_db() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS asset_projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asset_folders (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, name),
            FOREIGN KEY(project_id) REFERENCES asset_projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS asset_assignments (
            source_type TEXT NOT NULL CHECK(source_type IN ('job','sequence')),
            source_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            folder_id TEXT,
            filename TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(source_type, source_id),
            FOREIGN KEY(project_id) REFERENCES asset_projects(id) ON DELETE CASCADE,
            FOREIGN KEY(folder_id) REFERENCES asset_folders(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_asset_assignments_location
            ON asset_assignments(project_id, folder_id);
        """)
    PROJECTS.mkdir(parents=True, exist_ok=True)


def _project(db, project_id: str):
    return db.execute("SELECT * FROM asset_projects WHERE id=?", (project_id,)).fetchone()


def _folder(db, project_id: str, folder_id: str | None):
    if not folder_id:
        return None
    row = db.execute("SELECT * FROM asset_folders WHERE id=? AND project_id=?", (folder_id, project_id)).fetchone()
    if not row:
        raise KeyError("Folder not found in this project")
    return row


def _project_path(name: str) -> Path:
    path = (PROJECTS / name).resolve()
    if path.parent != PROJECTS.resolve():
        raise ValueError("Invalid project path")
    return path


def _location_path(project_name: str, folder_name: str | None) -> Path:
    root = _project_path(project_name)
    path = (root / folder_name).resolve() if folder_name else root
    if path != root and path.parent != root:
        raise ValueError("Invalid folder path")
    return path


def _source(db, source_type: str, source_id: str):
    table = "jobs" if source_type == "job" else "sequences" if source_type == "sequence" else None
    if not table:
        raise ValueError("Asset type must be job or sequence")
    row = db.execute(f"SELECT id,status,output_path FROM {table} WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise KeyError("Generated asset not found")
    return table, row


def _assignment_target(db, source_type: str, source_id: str) -> Path | None:
    # The core job/production database is also used by callers that have not
    # initialized the Studio asset-library tables (for example, production
    # import tests and older installations).  An absent assignment table just
    # means there is no Studio override; it must not make stable-path
    # resolution fail.
    if not all(_table_exists(db, table) for table in ("asset_assignments", "asset_projects", "asset_folders")):
        return None
    assignment = db.execute(
        """
        SELECT a.filename,p.name AS project_name,f.name AS folder_name
        FROM asset_assignments a
        JOIN asset_projects p ON p.id=a.project_id
        LEFT JOIN asset_folders f ON f.id=a.folder_id
        WHERE a.source_type=? AND a.source_id=?
        """,
        (source_type, source_id),
    ).fetchone()
    if not assignment or not assignment["filename"]:
        return None
    return _location_path(assignment["project_name"], assignment["folder_name"]) / assignment["filename"]


def _repair_source_path(db, source_type: str, source_id: str, table: str,
                        recorded: Path | None, current: Path) -> Path:
    current = current.resolve()
    if recorded is None:
        db.execute(
            f"UPDATE {table} SET output_path=?,updated_at=? WHERE id=?",
            (str(current), now_iso(), source_id),
        )
    elif _path_key(recorded) != _path_key(current):
        _rewrite_registered_paths(db, recorded, current)
    return current


def _resolve_source_path(db, source_type: str, source_id: str, table: str, source) -> Path | None:
    """Resolve an asset from its stable ID and repair stale legacy paths."""
    raw = source["output_path"]
    recorded = Path(raw).resolve() if raw else None

    # An assignment is the authoritative location after Studio organization.
    assigned = _assignment_target(db, source_type, source_id)
    if assigned and assigned.is_file():
        return _repair_source_path(db, source_type, source_id, table, recorded, assigned)
    if recorded and recorded.is_file():
        return recorded

    filename = recorded.name if recorded else None
    if filename:
        candidates: list[Path] = []
        for candidate in (OUTPUT / filename,):
            if candidate.is_file():
                candidates.append(candidate.resolve())
        if PROJECTS.is_dir():
            try:
                candidates.extend(path.resolve() for path in PROJECTS.rglob(filename) if path.is_file())
            except OSError:
                pass
        unique = {_path_key(path): path for path in candidates}
        if len(unique) == 1:
            return _repair_source_path(db, source_type, source_id, table, recorded, next(iter(unique.values())))
    return None


def resolve_asset_path(source_type: str, source_id: str) -> Path | None:
    """Return the current on-disk path for a generated asset.

    Callers use the stable asset identity rather than caching an old absolute
    path.  If a legacy/manual move left the database stale, the assigned
    project location (or a unique filename match) is repaired here.
    """
    with connect() as db:
        table, source = _source(db, source_type, source_id)
        return _resolve_source_path(db, source_type, source_id, table, source)


def _assignment_public(db, row) -> dict[str, Any]:
    item = dict(row)
    return {
        "source_type": item["source_type"], "source_id": item["source_id"],
        "project_id": item["project_id"], "project_name": item["project_name"],
        "folder_id": item["folder_id"], "folder_name": item["folder_name"],
        "filename": item["filename"],
    }


def list_library() -> dict[str, Any]:
    with connect() as db:
        projects = [dict(row) for row in db.execute(
            "SELECT id,name,created_at,updated_at FROM asset_projects ORDER BY name COLLATE NOCASE"
        ).fetchall()]
        folders = [dict(row) for row in db.execute(
            "SELECT id,project_id,name,created_at,updated_at FROM asset_folders ORDER BY name COLLATE NOCASE"
        ).fetchall()]
        rows = db.execute("""
            SELECT a.source_type,a.source_id,a.project_id,p.name AS project_name,
                   a.folder_id,f.name AS folder_name,a.filename
            FROM asset_assignments a
            JOIN asset_projects p ON p.id=a.project_id
            LEFT JOIN asset_folders f ON f.id=a.folder_id
            ORDER BY p.name COLLATE NOCASE,f.name COLLATE NOCASE,a.filename COLLATE NOCASE
        """).fetchall()
        assignments = [_assignment_public(db, row) for row in rows]
    folder_map: dict[str, list[dict[str, Any]]] = {project["id"]: [] for project in projects}
    for folder in folders:
        folder_map.setdefault(folder["project_id"], []).append(folder)
    for project in projects:
        project["folders"] = folder_map.get(project["id"], [])
        project["asset_count"] = sum(1 for item in assignments if item["project_id"] == project["id"])
    return {"projects": projects, "assignments": assignments, "root": str(PROJECTS)}


def validate_location(project_id: str | None, folder_id: str | None = None) -> None:
    if not project_id:
        if folder_id:
            raise ValueError("A folder cannot be selected without a project")
        return
    with connect() as db:
        if not _project(db, project_id):
            raise KeyError("Project not found")
        _folder(db, project_id, folder_id)


def create_project(name: str) -> dict[str, Any]:
    name = validate_library_name(name, "Project name")
    path = _project_path(name)
    if path.exists():
        raise FileExistsError("A filesystem folder with this project name already exists")
    project_id, timestamp = uuid.uuid4().hex, now_iso()
    path.mkdir(parents=False)
    try:
        with connect() as db:
            db.execute("INSERT INTO asset_projects(id,name,created_at,updated_at) VALUES(?,?,?,?)",
                       (project_id, name, timestamp, timestamp))
    except Exception:
        path.rmdir()
        raise
    return next(item for item in list_library()["projects"] if item["id"] == project_id)


def create_folder(project_id: str, name: str) -> dict[str, Any]:
    name = validate_library_name(name, "Folder name")
    with connect() as db:
        project = _project(db, project_id)
        if not project:
            raise KeyError("Project not found")
        path = _location_path(project["name"], name)
        if path.exists():
            raise FileExistsError("A filesystem folder with this name already exists")
        folder_id, timestamp = uuid.uuid4().hex, now_iso()
        path.mkdir(parents=False)
        try:
            db.execute("INSERT INTO asset_folders(id,project_id,name,created_at,updated_at) VALUES(?,?,?,?,?)",
                       (folder_id, project_id, name, timestamp, timestamp))
        except Exception:
            path.rmdir()
            raise
    return next(folder for project in list_library()["projects"] if project["id"] == project_id
                for folder in project["folders"] if folder["id"] == folder_id)


def _unique_target(directory: Path, filename: str, current: Path | None = None) -> Path:
    target = directory / filename
    if not target.exists() or (current and target.resolve() == current.resolve()):
        return target
    stem, suffix = Path(filename).stem, Path(filename).suffix
    for index in range(2, 1000):
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError("Could not choose a unique filename")


def _update_source_path(db, source_type: str, source_id: str, old: Path, new: Path) -> None:
    _rewrite_registered_paths(db, old, new)


def assign_asset(source_type: str, source_id: str, project_id: str | None, folder_id: str | None = None) -> dict[str, Any] | None:
    moved: tuple[Path, Path] | None = None
    with connect() as db:
        table, source = _source(db, source_type, source_id)
        if source["status"] in {"starting", "running", "verifying"}:
            raise RuntimeError("An active asset cannot be moved")
        existing = db.execute("SELECT * FROM asset_assignments WHERE source_type=? AND source_id=?",
                              (source_type, source_id)).fetchone()
        if not project_id:
            if not existing:
                return None
            target_dir = OUTPUT.resolve()
            project = folder = None
        else:
            project = _project(db, project_id)
            if not project:
                raise KeyError("Project not found")
            folder = _folder(db, project_id, folder_id)
            target_dir = _location_path(project["name"], folder["name"] if folder else None)
        target_dir.mkdir(parents=True, exist_ok=True)
        old = _resolve_source_path(db, source_type, source_id, table, source)
        filename = (existing["filename"] if existing and existing["filename"] else None) or (old.name if old else None)
        new = None
        if old:
            if not old.is_file():
                raise FileNotFoundError("The generated video file is missing")
            new = _unique_target(target_dir, filename or old.name, old)
            try:
                if new.resolve() != old:
                    _move_with_retry(old, new)
                    moved = (old, new)
                    _update_source_path(db, source_type, source_id, old, new)
                filename = new.name
            except Exception:
                if moved and moved[1].exists():
                    _move_with_retry(moved[1], moved[0])
                raise
        timestamp = now_iso()
        try:
            if project_id:
                db.execute("""INSERT INTO asset_assignments
                    (source_type,source_id,project_id,folder_id,filename,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(source_type,source_id) DO UPDATE SET
                    project_id=excluded.project_id,folder_id=excluded.folder_id,
                    filename=excluded.filename,updated_at=excluded.updated_at""",
                    (source_type, source_id, project_id, folder_id, filename,
                     existing["created_at"] if existing else timestamp, timestamp))
            else:
                db.execute("DELETE FROM asset_assignments WHERE source_type=? AND source_id=?", (source_type, source_id))
        except Exception:
            if moved and moved[1].exists():
                _move_with_retry(moved[1], moved[0])
            raise
    if not project_id:
        return None
    return next(item for item in list_library()["assignments"]
                if item["source_type"] == source_type and item["source_id"] == source_id)


def finalize_completed_asset(source_type: str, source_id: str) -> Path | None:
    with connect() as db:
        assignment = db.execute("SELECT project_id,folder_id FROM asset_assignments WHERE source_type=? AND source_id=?",
                                (source_type, source_id)).fetchone()
    if not assignment:
        return None
    result = assign_asset(source_type, source_id, assignment["project_id"], assignment["folder_id"])
    if not result:
        return None
    with connect() as db:
        _, source = _source(db, source_type, source_id)
        return Path(source["output_path"]) if source["output_path"] else None


def rename_asset(source_type: str, source_id: str, requested_name: str) -> dict[str, Any]:
    base = validate_library_name(Path(requested_name).stem, "Asset name")
    with connect() as db:
        table, source = _source(db, source_type, source_id)
        assignment = db.execute("SELECT * FROM asset_assignments WHERE source_type=? AND source_id=?",
                                (source_type, source_id)).fetchone()
        if not assignment:
            raise RuntimeError("Assign the asset to a project before renaming it")
        if source["status"] in _ACTIVE:
            raise RuntimeError("An active asset cannot be renamed")
        old = _resolve_source_path(db, source_type, source_id, table, source)
        if not old or not old.is_file():
            raise FileNotFoundError("The generated video file is missing")
        new = old.with_name(base + old.suffix.lower())
        if new.exists() and new.resolve() != old.resolve():
            raise FileExistsError("An asset with this filename already exists")
        if new.resolve() != old.resolve():
            _replace_with_retry(old, new)
            try:
                _update_source_path(db, source_type, source_id, old, new)
                db.execute("UPDATE asset_assignments SET filename=?,updated_at=? WHERE source_type=? AND source_id=?",
                           (new.name, now_iso(), source_type, source_id))
            except Exception:
                _replace_with_retry(new, old)
                raise
    return next(item for item in list_library()["assignments"]
                if item["source_type"] == source_type and item["source_id"] == source_id)


def remove_assignment(source_type: str, source_id: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM asset_assignments WHERE source_type=? AND source_id=?", (source_type, source_id))


def rename_project(project_id: str, name: str) -> dict[str, Any]:
    name = validate_library_name(name, "Project name")
    with connect() as db:
        project = _project(db, project_id)
        if not project:
            raise KeyError("Project not found")
        old_root, new_root = _project_path(project["name"]), _project_path(name)
        if new_root.exists() and new_root.resolve() != old_root.resolve():
            raise FileExistsError("A filesystem folder with this project name already exists")
        _replace_with_retry(old_root, new_root)
        try:
            db.execute("UPDATE asset_projects SET name=?,updated_at=? WHERE id=?", (name, now_iso(), project_id))
            _rewrite_registered_paths(db, old_root, new_root, prefix=True)
        except Exception:
            _replace_with_retry(new_root, old_root)
            raise
    return next(item for item in list_library()["projects"] if item["id"] == project_id)


def rename_folder(project_id: str, folder_id: str, name: str) -> dict[str, Any]:
    name = validate_library_name(name, "Folder name")
    with connect() as db:
        project = _project(db, project_id)
        if not project:
            raise KeyError("Project not found")
        folder = _folder(db, project_id, folder_id)
        old_root = _location_path(project["name"], folder["name"])
        new_root = _location_path(project["name"], name)
        if new_root.exists() and new_root.resolve() != old_root.resolve():
            raise FileExistsError("A filesystem folder with this name already exists")
        _replace_with_retry(old_root, new_root)
        try:
            db.execute("UPDATE asset_folders SET name=?,updated_at=? WHERE id=?", (name, now_iso(), folder_id))
            _rewrite_registered_paths(db, old_root, new_root, prefix=True)
        except Exception:
            _replace_with_retry(new_root, old_root)
            raise
    return next(folder for project in list_library()["projects"] if project["id"] == project_id
                for folder in project["folders"] if folder["id"] == folder_id)


def delete_folder(project_id: str, folder_id: str) -> None:
    with connect() as db:
        project = _project(db, project_id)
        folder = _folder(db, project_id, folder_id) if project else None
        if not project or not folder:
            raise KeyError("Folder not found")
        if db.execute("SELECT COUNT(*) FROM asset_assignments WHERE folder_id=?", (folder_id,)).fetchone()[0]:
            raise RuntimeError("Move or delete every asset in this folder first")
        path = _location_path(project["name"], folder["name"])
        if path.exists() and any(path.iterdir()):
            raise RuntimeError("The filesystem folder contains unmanaged files")
        db.execute("DELETE FROM asset_folders WHERE id=?", (folder_id,))
        if path.exists():
            path.rmdir()


def delete_project(project_id: str) -> None:
    with connect() as db:
        project = _project(db, project_id)
        if not project:
            raise KeyError("Project not found")
        if db.execute("SELECT COUNT(*) FROM asset_assignments WHERE project_id=?", (project_id,)).fetchone()[0]:
            raise RuntimeError("Move or delete every asset in this project first")
        if db.execute("SELECT COUNT(*) FROM asset_folders WHERE project_id=?", (project_id,)).fetchone()[0]:
            raise RuntimeError("Delete every folder in this project first")
        path = _project_path(project["name"])
        if path.exists() and any(path.iterdir()):
            raise RuntimeError("The filesystem project folder contains unmanaged files")
        db.execute("DELETE FROM asset_projects WHERE id=?", (project_id,))
        if path.exists():
            path.rmdir()
