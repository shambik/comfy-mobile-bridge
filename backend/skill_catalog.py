from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .config import MANAGED_SKILLS, ROOT
from .db import connect, now_iso


FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _frontmatter_value(block: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*[\"']?(.*?)[\"']?\s*$", block, re.MULTILINE)
    return match.group(1).strip() if match else ""


def inspect_skill(path: Path) -> dict[str, Any]:
    skill_file = path / "SKILL.md"
    if not skill_file.is_file():
        return {"valid": False, "name": path.name, "description": "", "error": "SKILL.md is missing"}
    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        return {"valid": False, "name": path.name, "description": "", "error": str(exc)}
    match = FRONTMATTER.match(text)
    if not match:
        return {"valid": False, "name": path.name, "description": "", "error": "YAML frontmatter is missing"}
    name = _frontmatter_value(match.group(1), "name") or path.name
    description = _frontmatter_value(match.group(1), "description")
    return {"valid": True, "name": name, "description": description, "error": None}


def _skill_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:24]


def upsert_skill(path: Path, source: str, managed: bool = False, *, enabled: bool | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    details = inspect_skill(resolved)
    skill_id = _skill_id(resolved)
    now = now_iso()
    with connect() as db:
        existing = db.execute("SELECT enabled,created_at FROM skills_catalog WHERE id=?", (skill_id,)).fetchone()
        effective_enabled = bool(existing["enabled"]) if existing and enabled is None else (True if enabled is None else enabled)
        created = existing["created_at"] if existing else now
        db.execute(
            """INSERT OR REPLACE INTO skills_catalog
               (id,name,description,path,source,managed,enabled,agents_json,valid,error,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (skill_id, details["name"], details["description"], str(resolved), source, int(managed),
             int(effective_enabled), '["codex","agy"]', int(details["valid"]), details["error"], created, now),
        )
    return get_skill(skill_id) or {}


def discover_skills() -> list[dict[str, Any]]:
    roots = [(ROOT / "skills", "repository", False), (MANAGED_SKILLS, "managed", True)]
    for root, source, managed in roots:
        if not root.exists():
            continue
        for path in root.iterdir():
            if path.is_dir() and (path / "SKILL.md").exists():
                upsert_skill(path, source, managed)
    return list_skills()


def _row_dict(row) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    item["managed"] = bool(item["managed"])
    item["enabled"] = bool(item["enabled"])
    item["valid"] = bool(item["valid"])
    item["agents"] = json.loads(item.pop("agents_json") or "[]")
    return item


def list_skills() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM skills_catalog ORDER BY source,name COLLATE NOCASE").fetchall()
    return [_row_dict(row) for row in rows]


def get_skill(skill_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM skills_catalog WHERE id=?", (skill_id,)).fetchone()
    return _row_dict(row)


def set_skill_enabled(skill_id: str, enabled: bool) -> dict[str, Any] | None:
    with connect() as db:
        db.execute(
            "UPDATE skills_catalog SET enabled=?,updated_at=? WHERE id=?",
            (int(enabled), now_iso(), skill_id),
        )
    return get_skill(skill_id)


def register_skill(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Skill folder does not exist")
    return upsert_skill(path, "external", False)


def install_skill_zip(zip_path: Path) -> dict[str, Any]:
    target = MANAGED_SKILLS / f"skill-{uuid.uuid4().hex[:12]}"
    target.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            files = [entry for entry in archive.infolist() if not entry.is_dir()]
            if not files or len(files) > 500:
                raise ValueError("Skill package must contain between 1 and 500 files")
            for entry in files:
                destination = (target / entry.filename).resolve()
                if target.resolve() not in destination.parents:
                    raise ValueError("Skill package contains an unsafe path")
                if entry.file_size > 20 * 1024 * 1024:
                    raise ValueError("A skill file is larger than 20 MB")
            archive.extractall(target)
        candidates = [path.parent for path in target.rglob("SKILL.md")]
        if len(candidates) != 1:
            raise ValueError("Skill package must contain exactly one SKILL.md")
        skill_root = candidates[0]
        if skill_root != target:
            temporary = target.with_name(target.name + "-content")
            skill_root.rename(temporary)
            shutil.rmtree(target)
            temporary.rename(target)
        skill = upsert_skill(target, "managed", True)
        if not skill.get("valid"):
            raise ValueError(skill.get("error") or "Skill is invalid")
        return skill
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def remove_skill(skill_id: str, mode: str) -> None:
    skill = get_skill(skill_id)
    if not skill:
        raise KeyError("Skill not found")
    if mode == "complete":
        if not skill["managed"]:
            raise PermissionError("Only app-managed skills can be deleted completely")
        path = Path(skill["path"]).resolve()
        managed_root = MANAGED_SKILLS.resolve()
        if managed_root not in path.parents:
            raise PermissionError("Skill is outside the managed skills directory")
        shutil.rmtree(path)
    elif mode != "unregister":
        raise ValueError("Delete mode must be unregister or complete")
    with connect() as db:
        db.execute("DELETE FROM skills_catalog WHERE id=?", (skill_id,))


def selected_skill_context(skill_ids: list[str], limit: int = 80_000) -> str:
    chunks: list[str] = []
    used = 0
    for skill_id in skill_ids:
        skill = get_skill(skill_id)
        if not skill or not skill["enabled"] or not skill["valid"]:
            continue
        path = Path(skill["path"]) / "SKILL.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        remaining = limit - used
        if remaining <= 0:
            break
        excerpt = text[:remaining]
        chunks.append(f"\n## Enabled skill: {skill['name']}\n{excerpt}")
        used += len(excerpt)
    return "\n".join(chunks)
