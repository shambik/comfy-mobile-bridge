from __future__ import annotations

import json
import math
import uuid
from typing import Any

from .db import connect, now_iso


ACTIVE_PRODUCTION_STATUSES = ("queued", "running", "pausing", "retrying", "stopping")

DEFAULT_GENERATION_MP_RULES = [
    {"max_duration": 5, "megapixels": 1.5},
    {"max_duration": 8, "megapixels": 1.0},
    {"max_duration": 10, "megapixels": 0.7},
    {"max_duration": 11, "megapixels": 0.6},
    {"max_duration": 15, "megapixels": 0.5},
]
GENERATION_ASPECT_RATIOS = {"16:9", "1:1", "9:16", "4:3", "3:4"}


def normalize_megapixel_rules(rules: Any = None) -> list[dict[str, Any]]:
    """Validate the duration-to-MP policy stored on a production."""
    if rules is None or rules == "" or rules == []:
        source = DEFAULT_GENERATION_MP_RULES
    elif isinstance(rules, str):
        try:
            source = json.loads(rules)
        except json.JSONDecodeError:
            raise ValueError("Megapixel rules must be a JSON array") from None
    else:
        source = rules
    if not isinstance(source, list) or not source:
        raise ValueError("Megapixel rules must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    previous_max = 0
    for rule in source:
        if not isinstance(rule, dict):
            raise ValueError("Each megapixel rule must be an object")
        raw_max = rule.get("max_duration", rule.get("max_seconds"))
        raw_mp = rule.get("megapixels", rule.get("mp"))
        try:
            max_duration_float = float(raw_max)
        except (TypeError, ValueError):
            raise ValueError("Each megapixel rule needs a whole-number duration") from None
        if not math.isfinite(max_duration_float) or not max_duration_float.is_integer():
            raise ValueError("Megapixel rule durations must be whole numbers")
        max_duration = int(max_duration_float)
        if max_duration < 1 or max_duration > 15 or max_duration <= previous_max:
            raise ValueError("Megapixel rule durations must increase from 1 through 15 seconds")
        try:
            megapixels = round(float(raw_mp), 1)
        except (TypeError, ValueError):
            raise ValueError("Each megapixel rule needs a numeric MP value") from None
        if not math.isfinite(megapixels) or not 0.1 <= megapixels <= 2.0:
            raise ValueError("Megapixel rule MP values must be between 0.1 and 2.0")
        normalized.append({"max_duration": max_duration, "megapixels": megapixels})
        previous_max = max_duration
    if normalized[-1]["max_duration"] != 15:
        raise ValueError("The last megapixel rule must cover through 15 seconds")
    return normalized


def megapixels_for_duration(duration: Any, rules: list[dict[str, Any]] | None = None) -> float:
    """Return the first MP rule whose upper duration bound covers a shot."""
    normalized = normalize_megapixel_rules(rules)
    try:
        value = float(duration)
    except (TypeError, ValueError):
        value = 5.0
    for rule in normalized:
        if value <= rule["max_duration"]:
            return float(rule["megapixels"])
    return float(normalized[-1]["megapixels"])


def normalize_production_generation(
    turbo_profile: Any = "v1", steps: Any = 4, megapixels: Any = 0.7,
    aspect_ratio: Any = "16:9", megapixel_rules: Any = None,
) -> dict[str, Any]:
    """Validate project-wide Turbo controls before a shot plan is created.

    Megapixels are deliberately stored as the user's requested value rounded
    to one decimal place.  The generation workflow calculates the final
    multiple-of-32 dimensions later; the project record must not display the
    resulting pixel-product (for example, ``0.692224``) as if it were the
    user's setting.
    """
    profile = str(turbo_profile or "v1").strip().lower()
    if profile not in {"v1", "v4"}:
        raise ValueError("Turbo profile must be v1 or v4")
    if isinstance(steps, bool):
        raise ValueError("Steps must be a whole number")
    try:
        resolved_steps = int(steps)
    except (TypeError, ValueError):
        raise ValueError("Steps must be a whole number") from None
    if resolved_steps < 4 or resolved_steps > (8 if profile == "v4" else 12):
        maximum = 8 if profile == "v4" else 12
        raise ValueError(f"Turbo {profile} steps must be between 4 and {maximum}")
    try:
        resolved_megapixels = round(float(megapixels), 1)
    except (TypeError, ValueError):
        raise ValueError("Megapixels must be a number") from None
    if not math.isfinite(resolved_megapixels) or not 0.1 <= resolved_megapixels <= 2.0:
        raise ValueError("Megapixels must be between 0.1 and 2.0")
    resolved_aspect_ratio = str(aspect_ratio or "16:9").strip()
    if resolved_aspect_ratio not in GENERATION_ASPECT_RATIOS:
        raise ValueError("Resolution shape must be one of 16:9, 1:1, 9:16, 4:3 or 3:4")
    return {
        "generation_turbo_profile": profile,
        "generation_steps": resolved_steps,
        "generation_megapixels": resolved_megapixels,
        "generation_aspect_ratio": resolved_aspect_ratio,
        "generation_megapixel_rules": normalize_megapixel_rules(megapixel_rules),
    }


def init_production_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_settings (
                id INTEGER PRIMARY KEY CHECK(id=1),
                codex_runtime TEXT NOT NULL DEFAULT 'codex',
                codex_model TEXT NOT NULL,
                codex_effort TEXT NOT NULL,
                agy_runtime TEXT NOT NULL DEFAULT 'agy',
                agy_model TEXT NOT NULL,
                agy_effort TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skills_catalog (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                managed INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                agents_json TEXT NOT NULL DEFAULT '["codex","agy"]',
                valid INTEGER NOT NULL DEFAULT 1,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS productions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                pipeline TEXT NOT NULL DEFAULT 'music_video_v1',
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                participation_mode TEXT NOT NULL,
                continuity_mode TEXT NOT NULL,
                concept TEXT NOT NULL DEFAULT '',
                lyrics TEXT NOT NULL,
                song_path TEXT NOT NULL,
                song_name TEXT NOT NULL,
                codex_runtime TEXT NOT NULL DEFAULT 'codex',
                codex_model TEXT NOT NULL,
                codex_effort TEXT NOT NULL,
                agy_runtime TEXT NOT NULL DEFAULT 'agy',
                agy_model TEXT NOT NULL,
                agy_effort TEXT NOT NULL,
                codex_session_id TEXT,
                agy_session_id TEXT,
                generation_turbo_profile TEXT NOT NULL DEFAULT 'v1',
                generation_steps INTEGER NOT NULL DEFAULT 4,
                generation_megapixels REAL NOT NULL DEFAULT 0.7,
                generation_aspect_ratio TEXT NOT NULL DEFAULT '16:9',
                generation_megapixel_rules_json TEXT NOT NULL DEFAULT '[]',
                skills_json TEXT NOT NULL DEFAULT '[]',
                approval_gates_json TEXT NOT NULL DEFAULT '[]',
                progress REAL NOT NULL DEFAULT 0,
                pause_requested INTEGER NOT NULL DEFAULT 0,
                stop_requested INTEGER NOT NULL DEFAULT 0,
                intervention_requested INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_productions_status ON productions(status, created_at);

            CREATE TABLE IF NOT EXISTS production_messages (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                participant TEXT NOT NULL,
                recipient TEXT NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(production_id, sequence),
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_production_messages ON production_messages(production_id, sequence);

            CREATE TABLE IF NOT EXISTS production_decisions (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                payload_json TEXT NOT NULL DEFAULT '{}',
                resolved_by TEXT,
                resolution TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS production_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                production_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_production_events ON production_events(production_id, id);

            CREATE TABLE IF NOT EXISTS production_shots (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                shot_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                mode TEXT NOT NULL,
                continuity TEXT NOT NULL DEFAULT 'hard_cut',
                audio_mode TEXT NOT NULL DEFAULT 'silent',
                audio_source TEXT NOT NULL DEFAULT 'song',
                audio_start REAL NOT NULL DEFAULT 0,
                audio_duration REAL,
                audio_reference_id TEXT,
                duration REAL NOT NULL,
                megapixels REAL NOT NULL,
                aspect_ratio TEXT NOT NULL DEFAULT '16:9',
                steps INTEGER NOT NULL DEFAULT 6,
                engine TEXT NOT NULL DEFAULT 'turbo',
                turbo_profile TEXT NOT NULL DEFAULT 'v1',
                status TEXT NOT NULL DEFAULT 'planned',
                accepted_attempt INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(production_id, shot_index),
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_production_shots
                ON production_shots(production_id, shot_index);

            CREATE TABLE IF NOT EXISTS production_shot_attempts (
                id TEXT PRIMARY KEY,
                shot_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                job_id TEXT,
                status TEXT NOT NULL,
                opening_frame_path TEXT,
                output_path TEXT,
                frames_json TEXT NOT NULL DEFAULT '[]',
                agy_review_json TEXT NOT NULL DEFAULT '{}',
                codex_review_json TEXT NOT NULL DEFAULT '{}',
                defect_key TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(shot_id, attempt),
                FOREIGN KEY(shot_id) REFERENCES production_shots(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_production_attempts
                ON production_shot_attempts(shot_id, attempt);

            CREATE TABLE IF NOT EXISTS production_artifacts (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(production_id, kind, path),
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS production_references (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('image','video','audio')),
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                comfy_path TEXT NOT NULL,
                comfy_name TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_production_references
                ON production_references(production_id, created_at);

            CREATE TABLE IF NOT EXISTS production_config_revisions (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                configuration_json TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(production_id, revision),
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );
            """
        )
        settings_columns = {row[1] for row in db.execute("PRAGMA table_info(agent_settings)").fetchall()}
        if "codex_runtime" not in settings_columns:
            db.execute("ALTER TABLE agent_settings ADD COLUMN codex_runtime TEXT NOT NULL DEFAULT 'codex'")
        if "agy_runtime" not in settings_columns:
            db.execute("ALTER TABLE agent_settings ADD COLUMN agy_runtime TEXT NOT NULL DEFAULT 'agy'")
        columns = {row[1] for row in db.execute("PRAGMA table_info(productions)").fetchall()}
        if "codex_session_id" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN codex_session_id TEXT")
        if "agy_session_id" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN agy_session_id TEXT")
        if "codex_runtime" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN codex_runtime TEXT NOT NULL DEFAULT 'codex'")
        if "agy_runtime" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN agy_runtime TEXT NOT NULL DEFAULT 'agy'")
        if "archived" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        if "generation_turbo_profile" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN generation_turbo_profile TEXT NOT NULL DEFAULT 'v1'")
        if "generation_steps" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN generation_steps INTEGER NOT NULL DEFAULT 4")
        if "generation_megapixels" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN generation_megapixels REAL NOT NULL DEFAULT 0.7")
        if "generation_aspect_ratio" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN generation_aspect_ratio TEXT NOT NULL DEFAULT '16:9'")
        if "generation_megapixel_rules_json" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN generation_megapixel_rules_json TEXT NOT NULL DEFAULT '[]'")
        if "intervention_requested" not in columns:
            db.execute("ALTER TABLE productions ADD COLUMN intervention_requested INTEGER NOT NULL DEFAULT 0")
        shot_columns = {row[1] for row in db.execute("PRAGMA table_info(production_shots)").fetchall()}
        if "reference_ids_json" not in shot_columns:
            db.execute("ALTER TABLE production_shots ADD COLUMN reference_ids_json TEXT NOT NULL DEFAULT '[]'")
        if "audio_mode" not in shot_columns:
            db.execute("ALTER TABLE production_shots ADD COLUMN audio_mode TEXT NOT NULL DEFAULT 'silent'")
        if "audio_source" not in shot_columns:
            db.execute("ALTER TABLE production_shots ADD COLUMN audio_source TEXT NOT NULL DEFAULT 'song'")
        if "audio_start" not in shot_columns:
            db.execute("ALTER TABLE production_shots ADD COLUMN audio_start REAL NOT NULL DEFAULT 0")
        if "audio_duration" not in shot_columns:
            db.execute("ALTER TABLE production_shots ADD COLUMN audio_duration REAL")
        if "audio_reference_id" not in shot_columns:
            db.execute("ALTER TABLE production_shots ADD COLUMN audio_reference_id TEXT")


def ensure_agent_settings(defaults: dict[str, str]) -> None:
    with connect() as db:
        db.execute(
            """INSERT OR IGNORE INTO agent_settings
               (id,codex_runtime,codex_model,codex_effort,agy_runtime,agy_model,agy_effort,updated_at)
               VALUES(1,?,?,?,?,?,?,?)""",
            (
                defaults.get("codex_runtime", "codex"),
                defaults["codex_model"], defaults["codex_effort"],
                defaults.get("agy_runtime", "agy"),
                defaults["agy_model"], defaults["agy_effort"], now_iso(),
            ),
        )


def get_agent_settings() -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM agent_settings WHERE id=1").fetchone()
    return dict(row) if row else {}


def update_agent_settings(**values: str) -> dict[str, Any]:
    allowed = {"codex_runtime", "codex_model", "codex_effort", "agy_runtime", "agy_model", "agy_effort"}
    clean = {key: str(value).strip() for key, value in values.items() if key in allowed and str(value).strip()}
    if clean:
        clean["updated_at"] = now_iso()
        assignments = ",".join(f"{key}=?" for key in clean)
        with connect() as db:
            db.execute(f"UPDATE agent_settings SET {assignments} WHERE id=1", (*clean.values(),))
    return get_agent_settings()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _text(value: Any) -> str:
    """Return a SQLite-safe display value for production text columns.

    Agent CLIs are expected to return a string summary, but some providers
    occasionally return a structured object or array there.  SQLite cannot
    bind those Python containers directly.  Preserve the data as readable
    JSON instead of letting one malformed agent field abort the production.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _decode_generation_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Expose normalized generation controls for both public and private reads."""
    raw_rules = item.pop("generation_megapixel_rules_json", "[]")
    try:
        parsed_rules = normalize_megapixel_rules(raw_rules)
    except ValueError:
        # Rows created before the rule table existed retain their old single
        # MP value rather than unexpectedly changing when they are reopened.
        parsed_rules = [{
            "max_duration": 15,
            "megapixels": round(float(item.get("generation_megapixels", 0.7)), 1),
        }]
    item["generation_megapixel_rules"] = parsed_rules
    item["generation_aspect_ratio"] = item.get("generation_aspect_ratio") or "16:9"
    return item


def _production_dict(
    row, *, include_messages: bool = False, message_limit: int | None = None,
    message_before: int | None = None,
) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    item["skills"] = json.loads(item.pop("skills_json") or "[]")
    item["approval_gates"] = json.loads(item.pop("approval_gates_json") or "[]")
    item = _decode_generation_fields(item)
    item["pause_requested"] = bool(item["pause_requested"])
    item["stop_requested"] = bool(item["stop_requested"])
    item["intervention_requested"] = bool(item.get("intervention_requested", 0))
    item["archived"] = bool(item.get("archived", 0))
    item.pop("song_path", None)
    if include_messages:
        item["messages"] = list_messages(
            item["id"], limit=message_limit, before=message_before,
        )
        if message_limit is not None:
            item["message_total"] = count_messages(item["id"])
            item["message_oldest_sequence"] = item["messages"][0]["sequence"] if item["messages"] else None
            item["messages_has_older"] = bool(
                item["messages"] and item["messages"][0]["sequence"] > 1
            )
        item["decisions"] = list_decisions(item["id"])
        item["shots"] = list_shots(item["id"])
        item["artifacts"] = list_artifacts(item["id"])
        item["references"] = list_references(item["id"])
        item["configuration_revisions"] = list_config_revisions(item["id"])
    return item


def create_production(values: dict[str, Any]) -> dict[str, Any]:
    production_id = values.get("id") or uuid.uuid4().hex
    now = now_iso()
    with connect() as db:
        db.execute(
            """INSERT INTO productions
               (id,title,pipeline,status,stage,participation_mode,continuity_mode,
                concept,lyrics,song_path,song_name,codex_runtime,codex_model,codex_effort,
                agy_runtime,agy_model,agy_effort,generation_turbo_profile,generation_steps,
                generation_megapixels,generation_aspect_ratio,generation_megapixel_rules_json,
                skills_json,approval_gates_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                production_id, values["title"], values.get("pipeline", "music_video_v1"),
                "draft", "intake", values["participation_mode"], values["continuity_mode"],
                values.get("concept", ""), values["lyrics"], values["song_path"], values["song_name"],
                values.get("codex_runtime", "codex"), values["codex_model"], values["codex_effort"],
                values.get("agy_runtime", "agy"), values["agy_model"], values["agy_effort"],
                values.get("generation_turbo_profile", "v1"), values.get("generation_steps", 4),
                values.get("generation_megapixels", 0.7),
                values.get("generation_aspect_ratio", "16:9"),
                _json(values.get("generation_megapixel_rules", DEFAULT_GENERATION_MP_RULES)),
                _json(values.get("skills", [])), _json(values.get("approval_gates", [])), now, now,
            ),
        )
    add_event(production_id, "production.created", {"stage": "intake"})
    add_message(production_id, "system", "all", "status", "Production created. Review the intake and start when ready.")
    return get_production(production_id, include_messages=True)


def list_productions() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM productions ORDER BY archived,created_at DESC").fetchall()
    return [_production_dict(row) for row in rows]


def get_production(
    production_id: str, *, include_messages: bool = False, private: bool = False,
    message_limit: int | None = None, message_before: int | None = None,
) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM productions WHERE id=?", (production_id,)).fetchone()
    if private:
        if not row:
            return None
        item = dict(row)
        item["skills"] = json.loads(item.pop("skills_json") or "[]")
        item["approval_gates"] = json.loads(item.pop("approval_gates_json") or "[]")
        item = _decode_generation_fields(item)
        item["archived"] = bool(item.get("archived", 0))
        item["intervention_requested"] = bool(item.get("intervention_requested", 0))
        return item
    return _production_dict(
        row, include_messages=include_messages, message_limit=message_limit,
        message_before=message_before,
    )


def update_production(production_id: str, **values: Any) -> None:
    if not values:
        return
    if "skills" in values:
        values["skills_json"] = _json(values.pop("skills"))
    if "approval_gates" in values:
        values["approval_gates_json"] = _json(values.pop("approval_gates"))
    if "generation_megapixel_rules" in values:
        values["generation_megapixel_rules_json"] = _json(
            normalize_megapixel_rules(values.pop("generation_megapixel_rules"))
        )
    values["updated_at"] = now_iso()
    assignments = ",".join(f"{key}=?" for key in values)
    with connect() as db:
        db.execute(f"UPDATE productions SET {assignments} WHERE id=?", (*values.values(), production_id))


def add_message(
    production_id: str, participant: str, recipient: str, kind: str,
    content: str, metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Keep all values bound to the TEXT columns SQLite-safe.  In particular,
    # an agent may return a structured ``summary`` even though the contract
    # asks for text; that value is the seventh SQL parameter (reported by
    # sqlite3 as parameter 6 because its diagnostic is zero-based).
    participant = _text(participant)
    recipient = _text(recipient)
    kind = _text(kind)
    content = _text(content)
    message_id = uuid.uuid4().hex
    with connect() as db:
        sequence = int(db.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM production_messages WHERE production_id=?",
            (production_id,),
        ).fetchone()[0])
        created = now_iso()
        db.execute(
            """INSERT INTO production_messages
               (id,production_id,sequence,participant,recipient,kind,content,metadata_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (message_id, production_id, sequence, participant, recipient, kind, content, _json(metadata or {}), created),
        )
    add_event(production_id, "message.created", {"message_id": message_id, "sequence": sequence})
    return {"id": message_id, "sequence": sequence, "participant": participant, "recipient": recipient,
            "kind": kind, "content": content, "metadata": metadata or {}, "created_at": created}


def count_messages(production_id: str) -> int:
    with connect() as db:
        return int(db.execute(
            "SELECT COUNT(*) FROM production_messages WHERE production_id=?", (production_id,),
        ).fetchone()[0])


def list_messages(
    production_id: str, *, limit: int | None = None, before: int | None = None,
) -> list[dict[str, Any]]:
    with connect() as db:
        params: list[Any] = [production_id]
        query = "SELECT * FROM production_messages WHERE production_id=?"
        if before is not None:
            query += " AND sequence<?"
            params.append(int(before))
        if limit is None:
            query += " ORDER BY sequence"
        else:
            safe_limit = max(1, min(int(limit), 500))
            query += " ORDER BY sequence DESC LIMIT ?"
            params.append(safe_limit)
        rows = db.execute(query, tuple(params)).fetchall()
    if limit is not None:
        rows = list(reversed(rows))
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        item.pop("production_id", None)
        result.append(item)
    return result


def add_decision(production_id: str, stage: str, title: str, summary: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    # Agent summaries are contractually text, but a provider may occasionally
    # return a structured object. Serialize it instead of aborting the stage
    # with SQLite's zero-based "parameter 4" binding error.
    stage = _text(stage)
    title = _text(title)
    summary = _text(summary)
    decision_id = uuid.uuid4().hex
    created = now_iso()
    with connect() as db:
        db.execute(
            """INSERT INTO production_decisions
               (id,production_id,stage,title,summary,payload_json,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (decision_id, production_id, stage, title, summary, _json(payload or {}), created),
        )
    add_event(production_id, "decision.created", {"decision_id": decision_id, "stage": stage})
    return {"id": decision_id, "stage": stage, "title": title, "summary": summary,
            "status": "pending", "payload": payload or {}, "created_at": created}


def list_decisions(production_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM production_decisions WHERE production_id=? ORDER BY created_at", (production_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        item.pop("production_id", None)
        result.append(item)
    return result


def resolve_decision(production_id: str, decision_id: str, status: str, resolved_by: str, resolution: str) -> bool:
    with connect() as db:
        result = db.execute(
            """UPDATE production_decisions SET status=?,resolved_by=?,resolution=?,resolved_at=?
               WHERE id=? AND production_id=? AND status='pending'""",
            (status, resolved_by, resolution, now_iso(), decision_id, production_id),
        )
    if result.rowcount:
        add_event(production_id, "decision.resolved", {"decision_id": decision_id, "status": status})
    return bool(result.rowcount)


def add_event(production_id: str, event_type: str, payload: dict[str, Any] | None = None) -> int:
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO production_events(production_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
            (production_id, event_type, _json(payload or {}), now_iso()),
        )
        return int(cursor.lastrowid)


def list_events(production_id: str, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            """SELECT * FROM production_events WHERE production_id=? AND id>?
               ORDER BY id LIMIT ?""",
            (production_id, after, min(max(limit, 1), 500)),
        ).fetchall()
    return [{"id": row["id"], "type": row["event_type"],
             "payload": json.loads(row["payload_json"] or "{}"), "created_at": row["created_at"]} for row in rows]


def recover_productions() -> None:
    with connect() as db:
        rows = db.execute(
            "SELECT id FROM productions WHERE status IN ('running','pausing','retrying','stopping')"
        ).fetchall()
        now = now_iso()
        db.execute(
            """UPDATE productions SET status='paused',pause_requested=0,stop_requested=0,
               intervention_requested=0,error='Recovered after bridge restart',updated_at=?
               WHERE status IN ('running','pausing','retrying','stopping')""",
            (now,),
        )
    for row in rows:
        add_event(row["id"], "production.recovered", {"status": "paused"})


def replace_shot_plan(production_id: str, shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = now_iso()
    with connect() as db:
        existing = db.execute(
            "SELECT COUNT(*) FROM production_shot_attempts a JOIN production_shots s ON s.id=a.shot_id WHERE s.production_id=?",
            (production_id,),
        ).fetchone()[0]
        if existing:
            raise RuntimeError("A shot plan with generation attempts cannot be replaced")
        db.execute("DELETE FROM production_shots WHERE production_id=?", (production_id,))
        for index, shot in enumerate(shots, 1):
            db.execute(
                """INSERT INTO production_shots
                   (id,production_id,shot_index,title,prompt,mode,continuity,
                    audio_mode,audio_source,audio_start,audio_duration,audio_reference_id,duration,
                    megapixels,aspect_ratio,steps,engine,turbo_profile,reference_ids_json,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'planned',?,?)""",
                (
                    uuid.uuid4().hex, production_id, index, shot["title"], shot["prompt"], shot["mode"],
                    shot.get("continuity", "hard_cut"), shot.get("audio_mode", "silent"),
                    shot.get("audio_source", "song"), shot.get("audio_start", 0), shot.get("audio_duration"),
                    shot.get("audio_reference_id"), shot["duration"], shot["megapixels"],
                    shot.get("aspect_ratio", "16:9"), shot.get("steps", 6), shot.get("engine", "turbo"),
                    shot.get("turbo_profile", "v1"), _json(shot.get("reference_ids", [])), now, now,
                ),
            )
    add_event(production_id, "shots.planned", {"count": len(shots)})
    return list_shots(production_id)


def list_shots(production_id: str, *, private: bool = False) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM production_shots WHERE production_id=? ORDER BY shot_index", (production_id,),
        ).fetchall()
        attempts = db.execute(
            """SELECT a.* FROM production_shot_attempts a
               JOIN production_shots s ON s.id=a.shot_id WHERE s.production_id=?
               ORDER BY s.shot_index,a.attempt""", (production_id,),
        ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in attempts:
        item = dict(row)
        item["frames"] = json.loads(item.pop("frames_json") or "[]")
        item["agy_review"] = json.loads(item.pop("agy_review_json") or "{}")
        item["codex_review"] = json.loads(item.pop("codex_review_json") or "{}")
        if not private:
            for key in ("opening_frame_path", "output_path"):
                if item.get(key):
                    item[key] = f"/api/productions/{production_id}/artifacts/attempt/{item['id']}/{key}"
            item["frames"] = [f"/api/productions/{production_id}/artifacts/attempt/{item['id']}/frame/{i}" for i in range(len(item["frames"]))]
        grouped.setdefault(item["shot_id"], []).append(item)
    result = []
    for row in rows:
        item = dict(row)
        item.pop("production_id", None)
        item["reference_ids"] = json.loads(item.pop("reference_ids_json") or "[]")
        item["attempts"] = grouped.get(item["id"], [])
        result.append(item)
    return result


def create_shot_attempt(shot_id: str, attempt: int, opening_frame_path: str | None = None) -> dict[str, Any]:
    attempt_id = uuid.uuid4().hex
    now = now_iso()
    with connect() as db:
        db.execute(
            """INSERT INTO production_shot_attempts
               (id,shot_id,attempt,status,opening_frame_path,created_at,updated_at)
               VALUES(?,?,?,'queued',?,?,?)""",
            (attempt_id, shot_id, attempt, opening_frame_path, now, now),
        )
        db.execute("UPDATE production_shots SET status='queued',updated_at=? WHERE id=?", (now, shot_id))
    return get_shot_attempt(attempt_id) or {}


def get_shot_attempt(attempt_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM production_shot_attempts WHERE id=?", (attempt_id,)).fetchone()
    return dict(row) if row else None


def update_shot_attempt(attempt_id: str, **values: Any) -> None:
    if "frames" in values:
        values["frames_json"] = _json(values.pop("frames"))
    if "agy_review" in values:
        values["agy_review_json"] = _json(values.pop("agy_review"))
    if "codex_review" in values:
        values["codex_review_json"] = _json(values.pop("codex_review"))
    values["updated_at"] = now_iso()
    with connect() as db:
        db.execute(
            f"UPDATE production_shot_attempts SET {','.join(f'{key}=?' for key in values)} WHERE id=?",
            (*values.values(), attempt_id),
        )


def update_shot(shot_id: str, **values: Any) -> None:
    if "reference_ids" in values:
        values["reference_ids_json"] = _json(values.pop("reference_ids"))
    values["updated_at"] = now_iso()
    with connect() as db:
        db.execute(
            f"UPDATE production_shots SET {','.join(f'{key}=?' for key in values)} WHERE id=?",
            (*values.values(), shot_id),
        )


def add_artifact(production_id: str, kind: str, path: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    artifact_id = uuid.uuid4().hex
    created = now_iso()
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO production_artifacts(id,production_id,kind,path,metadata_json,created_at) VALUES(?,?,?,?,?,?)",
            (artifact_id, production_id, kind, path, _json(metadata or {}), created),
        )
        row = db.execute(
            "SELECT * FROM production_artifacts WHERE production_id=? AND kind=? AND path=?",
            (production_id, kind, path),
        ).fetchone()
    return {**dict(row), "metadata": json.loads(row["metadata_json"] or "{}")} if row else {}


def list_artifacts(production_id: str, *, private: bool = False) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM production_artifacts WHERE production_id=? ORDER BY created_at", (production_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        item.pop("production_id", None)
        if not private:
            item.pop("path", None)
            item["url"] = f"/api/productions/{production_id}/artifacts/{item['id']}"
        result.append(item)
    return result


def get_artifact(production_id: str, artifact_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM production_artifacts WHERE id=? AND production_id=?", (artifact_id, production_id),
        ).fetchone()
    return dict(row) if row else None


def get_attempt_for_production(production_id: str, attempt_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """SELECT a.* FROM production_shot_attempts a JOIN production_shots s ON s.id=a.shot_id
               WHERE a.id=? AND s.production_id=?""", (attempt_id, production_id),
        ).fetchone()
    return dict(row) if row else None


def add_reference(
    production_id: str, kind: str, name: str, path: str, comfy_path: str,
    comfy_name: str, notes: str = "",
) -> dict[str, Any]:
    reference_id = uuid.uuid4().hex
    created = now_iso()
    with connect() as db:
        db.execute(
            """INSERT INTO production_references
               (id,production_id,kind,name,path,comfy_path,comfy_name,notes,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (reference_id, production_id, kind, name, path, comfy_path, comfy_name, notes, created),
        )
    add_event(production_id, "reference.created", {"reference_id": reference_id, "kind": kind})
    return get_reference(production_id, reference_id, private=True) or {}


def get_reference(production_id: str, reference_id: str, *, private: bool = False) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM production_references WHERE id=? AND production_id=?",
            (reference_id, production_id),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if not private:
        item.pop("path", None)
        item.pop("comfy_path", None)
        item["url"] = f"/api/productions/{production_id}/references/{reference_id}/file"
    item.pop("production_id", None)
    return item


def list_references(production_id: str, *, private: bool = False) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT id FROM production_references WHERE production_id=? ORDER BY created_at", (production_id,),
        ).fetchall()
    return [item for row in rows if (item := get_reference(production_id, row["id"], private=private))]


def delete_reference(production_id: str, reference_id: str) -> dict[str, Any] | None:
    reference = get_reference(production_id, reference_id, private=True)
    if not reference:
        return None
    with connect() as db:
        used = db.execute(
            "SELECT id,reference_ids_json FROM production_shots WHERE production_id=?", (production_id,),
        ).fetchall()
        if any(reference_id in json.loads(row["reference_ids_json"] or "[]") for row in used):
            raise RuntimeError("Reference is assigned to one or more shots")
        db.execute("DELETE FROM production_references WHERE id=?", (reference_id,))
    add_event(production_id, "reference.deleted", {"reference_id": reference_id})
    return reference


def add_config_revision(production_id: str, configuration: dict[str, Any], reason: str = "") -> int:
    with connect() as db:
        revision = int(db.execute(
            "SELECT COALESCE(MAX(revision),0)+1 FROM production_config_revisions WHERE production_id=?",
            (production_id,),
        ).fetchone()[0])
        db.execute(
            """INSERT INTO production_config_revisions
               (id,production_id,revision,configuration_json,reason,created_at)
               VALUES(?,?,?,?,?,?)""",
            (uuid.uuid4().hex, production_id, revision, _json(configuration), reason, now_iso()),
        )
    add_event(production_id, "configuration.revised", {"revision": revision})
    return revision


def list_config_revisions(production_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM production_config_revisions WHERE production_id=? ORDER BY revision",
            (production_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["configuration"] = json.loads(item.pop("configuration_json") or "{}")
        item.pop("production_id", None)
        result.append(item)
    return result


def import_completed_jobs(production_id: str, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = now_iso()
    with connect() as db:
        start = int(db.execute(
            "SELECT COALESCE(MAX(shot_index),0) FROM production_shots WHERE production_id=?",
            (production_id,),
        ).fetchone()[0])
        for offset, job in enumerate(jobs, 1):
            shot_id = uuid.uuid4().hex
            attempt_id = uuid.uuid4().hex
            index = start + offset
            mode = job.get("mode") or "text"
            db.execute(
                """INSERT INTO production_shots
                   (id,production_id,shot_index,title,prompt,mode,continuity,
                    audio_mode,audio_source,audio_start,audio_duration,audio_reference_id,duration,megapixels,
                    aspect_ratio,steps,engine,turbo_profile,reference_ids_json,status,accepted_attempt,
                    created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'accepted',1,?,?)""",
                (shot_id, production_id, index, f"Imported shot {index}", job["prompt"], mode,
                 "hard_cut", "lip_sync" if mode == "lip_sync" else "silent",
                 "reference" if job.get("reference_audio_name") else "song", job.get("audio_start") or 0,
                 job["duration"] if mode == "lip_sync" else None, None, job["duration"], job.get("megapixels") or .31,
                 job.get("aspect_ratio") or "16:9", job["steps"], job["engine"],
                 job.get("turbo_profile") or "v1", "[]", now, now),
            )
            db.execute(
                """INSERT INTO production_shot_attempts
                   (id,shot_id,attempt,job_id,status,output_path,created_at,updated_at)
                   VALUES(?,?,1,?,'accepted',?,?,?)""",
                (attempt_id, shot_id, job["id"], job["output_path"], now, now),
            )
    add_event(production_id, "shots.imported", {"count": len(jobs)})
    return list_shots(production_id)
