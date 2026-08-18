from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .config import OUTPUT, PROJECTS
from .db import connect, now_iso


_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_ACTIVE = {"queued", "starting", "running", "verifying"}


def validate_library_name(value: str, label: str = "Name") -> str:
    name = value.strip()
    if not name or len(name) > 100:
        raise ValueError(f"{label} must contain between 1 and 100 characters")
    if name in {".", ".."} or name.endswith((" ", ".")) or _INVALID_NAME.search(name):
        raise ValueError(f"{label} contains characters Windows cannot use in a folder or filename")
    if name.split(".", 1)[0].upper() in _RESERVED:
        raise ValueError(f"{label} is a reserved Windows name")
    return name


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
    table = "jobs" if source_type == "job" else "sequences"
    db.execute(f"UPDATE {table} SET output_path=?,updated_at=? WHERE id=?", (str(new), now_iso(), source_id))
    if source_type == "job":
        db.execute("UPDATE sequence_items SET clip_path=? WHERE source_job_id=? AND clip_path=?",
                   (str(new), source_id, str(old)))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_shot_attempts'").fetchone():
            db.execute("UPDATE production_shot_attempts SET output_path=?,updated_at=? WHERE job_id=? AND output_path=?",
                       (str(new), now_iso(), source_id, str(old)))
    else:
        db.execute("UPDATE sequence_items SET clip_path=? WHERE source_sequence_id=? AND clip_path=?",
                   (str(new), source_id, str(old)))


def assign_asset(source_type: str, source_id: str, project_id: str | None, folder_id: str | None = None) -> dict[str, Any] | None:
    moved: tuple[Path, Path] | None = None
    with connect() as db:
        _, source = _source(db, source_type, source_id)
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
        old = Path(source["output_path"]).resolve() if source["output_path"] else None
        filename = (existing["filename"] if existing and existing["filename"] else None) or (old.name if old else None)
        new = None
        if old:
            if not old.is_file():
                raise FileNotFoundError("The generated video file is missing")
            new = _unique_target(target_dir, filename or old.name, old)
            try:
                if new.resolve() != old:
                    shutil.move(str(old), str(new))
                    moved = (old, new)
                    _update_source_path(db, source_type, source_id, old, new)
                filename = new.name
            except Exception:
                if moved and moved[1].exists():
                    shutil.move(str(moved[1]), str(moved[0]))
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
                shutil.move(str(moved[1]), str(moved[0]))
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
        _, source = _source(db, source_type, source_id)
        assignment = db.execute("SELECT * FROM asset_assignments WHERE source_type=? AND source_id=?",
                                (source_type, source_id)).fetchone()
        if not assignment:
            raise RuntimeError("Assign the asset to a project before renaming it")
        if source["status"] in _ACTIVE:
            raise RuntimeError("An active asset cannot be renamed")
        old = Path(source["output_path"] or "")
        if not old.is_file():
            raise FileNotFoundError("The generated video file is missing")
        new = old.with_name(base + old.suffix.lower())
        if new.exists() and new.resolve() != old.resolve():
            raise FileExistsError("An asset with this filename already exists")
        if new.resolve() != old.resolve():
            os.replace(old, new)
            try:
                _update_source_path(db, source_type, source_id, old, new)
                db.execute("UPDATE asset_assignments SET filename=?,updated_at=? WHERE source_type=? AND source_id=?",
                           (new.name, now_iso(), source_type, source_id))
            except Exception:
                os.replace(new, old)
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
        os.replace(old_root, new_root)
        try:
            db.execute("UPDATE asset_projects SET name=?,updated_at=? WHERE id=?", (name, now_iso(), project_id))
            rows = db.execute("SELECT source_type,source_id FROM asset_assignments WHERE project_id=?", (project_id,)).fetchall()
            for row in rows:
                _, source = _source(db, row["source_type"], row["source_id"])
                if source["output_path"]:
                    old = Path(source["output_path"])
                    new = new_root / old.relative_to(old_root)
                    _update_source_path(db, row["source_type"], row["source_id"], old, new)
        except Exception:
            os.replace(new_root, old_root)
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
        os.replace(old_root, new_root)
        try:
            db.execute("UPDATE asset_folders SET name=?,updated_at=? WHERE id=?", (name, now_iso(), folder_id))
            rows = db.execute("SELECT source_type,source_id FROM asset_assignments WHERE folder_id=?", (folder_id,)).fetchall()
            for row in rows:
                _, source = _source(db, row["source_type"], row["source_id"])
                if source["output_path"]:
                    old = Path(source["output_path"])
                    new = new_root / old.name
                    _update_source_path(db, row["source_type"], row["source_id"], old, new)
        except Exception:
            os.replace(new_root, old_root)
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
