from __future__ import annotations

import json
import uuid
from typing import Any

from ..db import connect, now_iso
from .contracts import CouncilConfig, CouncilValidation


TASK_STATES = {"queued", "starting", "running", "validating", "completed", "waiting", "failed", "cancelled"}
INTERVENTION_STATES = {"queued", "delivered", "acknowledged", "applied", "failed"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def init_council_db() -> None:
    """Create Council-owned tables without altering Legacy production tables."""
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS council_config_revisions (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('solo','multi')),
                self_review_policy TEXT NOT NULL,
                revision_budget INTEGER NOT NULL,
                config_json TEXT NOT NULL,
                validation_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(production_id, revision),
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS council_seats (
                id TEXT NOT NULL,
                production_id TEXT NOT NULL,
                config_revision INTEGER NOT NULL,
                label TEXT NOT NULL,
                runtime TEXT NOT NULL CHECK(runtime IN ('codex','agy')),
                model TEXT NOT NULL,
                effort TEXT NOT NULL,
                role_ids_json TEXT NOT NULL,
                user_capabilities_json TEXT NOT NULL,
                effective_capabilities_json TEXT NOT NULL,
                capability_evidence_json TEXT NOT NULL,
                priority INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                custom_instructions TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY(production_id, config_revision, id),
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_council_seats_production
                ON council_seats(production_id, config_revision, active, priority);

            CREATE TABLE IF NOT EXISTS council_agent_sessions (
                production_id TEXT NOT NULL,
                seat_id TEXT NOT NULL,
                provider_session_id TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                last_task_id TEXT,
                handoff_summary TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(production_id, seat_id),
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS council_tasks (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                config_revision INTEGER NOT NULL,
                stage TEXT NOT NULL,
                task_type TEXT NOT NULL,
                role_id TEXT NOT NULL,
                worker_type TEXT NOT NULL DEFAULT 'agent',
                assigned_seat_id TEXT,
                state TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 2,
                dependency_ids_json TEXT NOT NULL DEFAULT '[]',
                input_json TEXT NOT NULL DEFAULT '{}',
                output_contract TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                error_code TEXT,
                error_detail TEXT,
                lease_token TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(production_id, idempotency_key),
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_council_tasks_ready
                ON council_tasks(production_id, state, created_at);

            CREATE TABLE IF NOT EXISTS council_deliverables (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                contract TEXT NOT NULL,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                artifact_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'valid',
                supersedes_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(production_id, contract, version),
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE,
                FOREIGN KEY(task_id) REFERENCES council_tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS council_reviews (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                deliverable_id TEXT NOT NULL,
                reviewer_seat_id TEXT NOT NULL,
                gate_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                findings_json TEXT NOT NULL DEFAULT '[]',
                independent INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS council_interventions (
                id TEXT PRIMARY KEY,
                production_id TEXT NOT NULL,
                content TEXT NOT NULL,
                target_seat_ids_json TEXT NOT NULL DEFAULT '[]',
                state TEXT NOT NULL,
                affected_task_ids_json TEXT NOT NULL DEFAULT '[]',
                queued_reason TEXT,
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                acknowledged_at TEXT,
                applied_at TEXT,
                resume_policy TEXT,
                action_results_json TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_council_interventions_state
                ON council_interventions(production_id, state, created_at);

            CREATE TABLE IF NOT EXISTS council_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                production_id TEXT NOT NULL,
                worker_type TEXT NOT NULL,
                worker_id TEXT,
                role_id TEXT,
                task_id TEXT,
                state TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_council_activity_production
                ON council_activity(production_id, id);
            """
        )
        columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(council_tasks)").fetchall()}
        if "worker_type" not in columns:
            db.execute("ALTER TABLE council_tasks ADD COLUMN worker_type TEXT NOT NULL DEFAULT 'agent'")
        intervention_columns = {
            str(row["name"])
            for row in db.execute("PRAGMA table_info(council_interventions)").fetchall()
        }
        if "resume_policy" not in intervention_columns:
            db.execute("ALTER TABLE council_interventions ADD COLUMN resume_policy TEXT")
        if "action_results_json" not in intervention_columns:
            db.execute(
                "ALTER TABLE council_interventions ADD COLUMN action_results_json TEXT NOT NULL DEFAULT '[]'"
            )


def save_config(production_id: str, config: CouncilConfig, validation: CouncilValidation) -> int:
    timestamp = now_iso()
    with connect() as db:
        row = db.execute(
            "SELECT COALESCE(MAX(revision),0) AS revision FROM council_config_revisions WHERE production_id=?",
            (production_id,),
        ).fetchone()
        revision = int(row["revision"]) + 1
        db.execute(
            """INSERT INTO council_config_revisions
               (id,production_id,revision,mode,self_review_policy,revision_budget,config_json,validation_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, production_id, revision, config.mode, config.self_review_policy,
             config.revision_budget, config.model_dump_json(), validation.model_dump_json(), timestamp),
        )
        for verified in validation.seats:
            seat = verified.seat
            db.execute(
                """INSERT INTO council_seats
                   (id,production_id,config_revision,label,runtime,model,effort,role_ids_json,
                    user_capabilities_json,effective_capabilities_json,capability_evidence_json,
                    priority,active,custom_instructions,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (seat.id, production_id, revision, seat.label, seat.runtime, seat.model, seat.effort,
                 _json(seat.role_ids), _json(seat.user_enabled_capabilities),
                 _json(verified.effective_capabilities),
                 _json([item.model_dump() for item in verified.evidence]), seat.priority,
                 int(seat.active), seat.custom_instructions, timestamp),
            )
            db.execute(
                """INSERT OR IGNORE INTO council_agent_sessions
                   (production_id,seat_id,status,updated_at) VALUES(?,?,'new',?)""",
                (production_id, seat.id, timestamp),
            )
    return revision


def latest_config(production_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM council_config_revisions WHERE production_id=? ORDER BY revision DESC LIMIT 1",
            (production_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["config"] = _loads(item.pop("config_json"), {})
    item["validation"] = _loads(item.pop("validation_json"), {})
    return item


def list_seats(production_id: str, revision: int | None = None) -> list[dict[str, Any]]:
    config = latest_config(production_id)
    if not config:
        return []
    selected_revision = revision or int(config["revision"])
    with connect() as db:
        rows = db.execute(
            """SELECT * FROM council_seats WHERE production_id=? AND config_revision=?
               ORDER BY priority,id""",
            (production_id, selected_revision),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for source, target in (
            ("role_ids_json", "role_ids"), ("user_capabilities_json", "user_enabled_capabilities"),
            ("effective_capabilities_json", "effective_capabilities"),
            ("capability_evidence_json", "capability_evidence"),
        ):
            item[target] = _loads(item.pop(source), [])
        item["active"] = bool(item["active"])
        result.append(item)
    return result


def create_task(
    production_id: str, *, config_revision: int, stage: str, task_type: str,
    role_id: str, output_contract: str, idempotency_key: str,
    dependencies: list[str] | None = None, inputs: dict[str, Any] | None = None,
    max_attempts: int = 2, worker_type: str = "agent",
) -> dict[str, Any]:
    if worker_type not in {"agent", "controller", "comfyui", "ffmpeg"}:
        raise ValueError("Unsupported Council task worker type")
    timestamp = now_iso()
    task_id = uuid.uuid4().hex
    with connect() as db:
        db.execute(
            """INSERT OR IGNORE INTO council_tasks
               (id,production_id,config_revision,stage,task_type,role_id,worker_type,state,max_attempts,
                dependency_ids_json,input_json,output_contract,idempotency_key,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?)""",
            (task_id, production_id, config_revision, stage, task_type, role_id, worker_type, max_attempts,
             _json(dependencies or []), _json(inputs or {}), output_contract,
             idempotency_key, timestamp, timestamp),
        )
        row = db.execute(
            "SELECT * FROM council_tasks WHERE production_id=? AND idempotency_key=?",
            (production_id, idempotency_key),
        ).fetchone()
    return _task_dict(row)


def _task_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["dependency_ids"] = _loads(item.pop("dependency_ids_json"), [])
    item["input"] = _loads(item.pop("input_json"), {})
    return item


def list_tasks(production_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM council_tasks WHERE production_id=? ORDER BY created_at,id", (production_id,),
        ).fetchall()
    return [_task_dict(row) for row in rows]


def retarget_unstarted_tasks(production_id: str, config_revision: int) -> int:
    """Apply a new Council revision to work that can still be rerun.

    Council settings are intentionally live-editable. A task that is already
    running or completed must keep its actual provider/model record, but
    queued and user-waiting tasks have not started their next provider turn
    yet and should use the newest model/effort configuration.
    """
    with connect() as db:
        result = db.execute(
            """UPDATE council_tasks SET config_revision=?,updated_at=?
               WHERE production_id=? AND state IN ('queued','waiting')""",
            (config_revision, now_iso(), production_id),
        )
    return int(result.rowcount or 0)


def get_task(task_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM council_tasks WHERE id=?", (task_id,)).fetchone()
    return _task_dict(row) if row else None


def update_task(task_id: str, **values: Any) -> None:
    allowed = {
        "assigned_seat_id", "state", "attempt", "error_code", "error_detail",
        "lease_token", "started_at", "finished_at", "input_json",
    }
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Unsupported council task fields: {sorted(unknown)}")
    if "state" in values and values["state"] not in TASK_STATES:
        raise ValueError("Unsupported council task state")
    if not values:
        return
    values["updated_at"] = now_iso()
    columns = ",".join(f"{key}=?" for key in values)
    with connect() as db:
        db.execute(f"UPDATE council_tasks SET {columns} WHERE id=?", (*values.values(), task_id))


def update_task_input(task_id: str, inputs: dict[str, Any]) -> None:
    update_task(task_id, input_json=_json(inputs))


def update_task_dependencies(task_id: str, dependencies: list[str]) -> None:
    """Update dependencies for queued work when the execution graph evolves."""
    with connect() as db:
        db.execute(
            "UPDATE council_tasks SET dependency_ids_json=?,updated_at=? WHERE id=?",
            (_json(dependencies), now_iso(), task_id),
        )


def next_ready_task(production_id: str) -> dict[str, Any] | None:
    ready = ready_tasks(production_id)
    return ready[0] if ready else None


def ready_tasks(production_id: str) -> list[dict[str, Any]]:
    """Return every dependency-ready queued task in deterministic order.

    Resource ownership is intentionally decided by the controller. Keeping the
    database query resource-agnostic lets the scheduler run independent seats
    concurrently without ever bypassing persisted task dependencies.
    """
    tasks = list_tasks(production_id)
    completed = {task["id"] for task in tasks if task["state"] == "completed"}
    return [
        task for task in tasks
        if task["state"] == "queued" and set(task["dependency_ids"]).issubset(completed)
    ]


def save_deliverable(
    production_id: str, task_id: str, role_id: str, contract: str,
    payload: Any, artifact_ids: list[str] | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    with connect() as db:
        row = db.execute(
            "SELECT COALESCE(MAX(version),0) AS version FROM council_deliverables WHERE production_id=? AND contract=?",
            (production_id, contract),
        ).fetchone()
        version = int(row["version"]) + 1
        deliverable_id = uuid.uuid4().hex
        db.execute(
            """INSERT INTO council_deliverables
               (id,production_id,task_id,role_id,contract,version,payload_json,artifact_ids_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (deliverable_id, production_id, task_id, role_id, contract, version,
             _json(payload), _json(artifact_ids or []), timestamp),
        )
        result = db.execute("SELECT * FROM council_deliverables WHERE id=?", (deliverable_id,)).fetchone()
    return _deliverable_dict(result)


def _deliverable_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["payload"] = _loads(item.pop("payload_json"), {})
    item["artifact_ids"] = _loads(item.pop("artifact_ids_json"), [])
    return item


def list_deliverables(production_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM council_deliverables WHERE production_id=? ORDER BY created_at,id", (production_id,),
        ).fetchall()
    return [_deliverable_dict(row) for row in rows]


def council_shot_prompt_projection(
    production_id: str, shots: list[dict[str, Any]] | None, *,
    deliverables: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Attach the prompts produced by Council to its public shot plan.

    ``production_shots.prompt`` is the durable Legacy-compatible fallback. In
    Council, the actual scene-frame and video prompts are generated later as
    deliverables, so the database row can legitimately contain only the shot
    title. Keep this projection separate from ``list_shots`` so the Legacy
    pipeline retains its existing response shape and behavior.
    """
    if not shots:
        return []

    deliverables = deliverables if deliverables is not None else list_deliverables(production_id)
    task_index = {
        str(task["id"]): task
        for task in (tasks if tasks is not None else list_tasks(production_id))
    }
    by_shot: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for deliverable in deliverables:
        payload = deliverable.get("payload")
        if not isinstance(payload, dict):
            continue
        shot_id = payload.get("shot_id")
        contract = str(deliverable.get("contract") or "")
        if not shot_id or contract not in {"scene_frame_plan.v1", "generation_prompt.v1"}:
            continue
        grouped = by_shot.setdefault(str(shot_id), {"scene": [], "video": []})
        grouped["scene" if contract == "scene_frame_plan.v1" else "video"].append(deliverable)

    def sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
        try:
            version = int(item.get("version") or 0)
        except (TypeError, ValueError):
            version = 0
        return version, str(item.get("created_at") or ""), str(item.get("id") or "")

    def text_value(payload: Any, *keys: str) -> str | None:
        if not isinstance(payload, dict):
            return None
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    projected: list[dict[str, Any]] = []
    for source in shots:
        shot = dict(source)
        grouped = by_shot.get(str(shot.get("id")), {"scene": [], "video": []})
        scene_deliverables = sorted(grouped["scene"], key=sort_key)
        video_deliverables = sorted(grouped["video"], key=sort_key)
        latest_scene = scene_deliverables[-1] if scene_deliverables else None
        latest_video = video_deliverables[-1] if video_deliverables else None
        scene_prompt = text_value(
            latest_scene.get("payload") if latest_scene else None,
            "opening_frame_prompt", "scene_frame_prompt", "prompt",
        )
        video_prompt = text_value(
            latest_video.get("payload") if latest_video else None,
            "prompt", "video_prompt", "generation_prompt",
        )

        # ``prompt`` remains populated for existing consumers, while the
        # explicit fields make the two different generation stages clear.
        if video_prompt:
            shot["prompt"] = video_prompt
            shot["video_prompt"] = video_prompt
        elif isinstance(shot.get("prompt"), str) and shot["prompt"].strip():
            shot["video_prompt"] = shot["prompt"].strip()
        if scene_prompt:
            shot["scene_frame_prompt"] = scene_prompt

        history: list[dict[str, Any]] = []
        for delivery in video_deliverables:
            payload = delivery.get("payload")
            prompt = text_value(payload, "prompt", "video_prompt", "generation_prompt")
            if not prompt:
                continue
            # A scene-frame plan is normally emitted immediately before the
            # matching generation prompt. Prefer the same revision, otherwise
            # use the newest plan that existed before the video prompt.
            candidate_plans = [
                item for item in scene_deliverables
                if sort_key(item) <= sort_key(delivery)
            ] or scene_deliverables
            scene_for_revision = candidate_plans[-1] if candidate_plans else None
            task = task_index.get(str(delivery.get("task_id"))) or {}
            history_item: dict[str, Any] = {
                "version": delivery.get("version"),
                "task_id": delivery.get("task_id"),
                "task_attempt": task.get("attempt"),
                "status": delivery.get("status"),
                "created_at": delivery.get("created_at"),
                "video_prompt": prompt,
            }
            revision_scene_prompt = text_value(
                scene_for_revision.get("payload") if scene_for_revision else None,
                "opening_frame_prompt", "scene_frame_prompt", "prompt",
            )
            if revision_scene_prompt:
                history_item["scene_frame_prompt"] = revision_scene_prompt
            history.append(history_item)
        if history:
            shot["prompt_history"] = history
        projected.append(shot)
    return projected


def latest_deliverable(production_id: str, contract: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """SELECT * FROM council_deliverables WHERE production_id=? AND contract=?
               AND status='valid' ORDER BY version DESC LIMIT 1""",
            (production_id, contract),
        ).fetchone()
    return _deliverable_dict(row) if row else None


def deliverable_for_task(task_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM council_deliverables WHERE task_id=? AND status='valid' ORDER BY version DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    return _deliverable_dict(row) if row else None


def save_review(
    production_id: str, task_id: str, deliverable_id: str, reviewer_seat_id: str,
    gate_id: str, decision: str, findings: list[dict[str, Any]], *, independent: bool = True,
) -> dict[str, Any]:
    review_id = uuid.uuid4().hex
    with connect() as db:
        db.execute(
            """INSERT INTO council_reviews
               (id,production_id,task_id,deliverable_id,reviewer_seat_id,gate_id,decision,
                findings_json,independent,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (review_id, production_id, task_id, deliverable_id, reviewer_seat_id, gate_id,
             decision, _json(findings), int(independent), now_iso()),
        )
        row = db.execute("SELECT * FROM council_reviews WHERE id=?", (review_id,)).fetchone()
    item = dict(row)
    item["findings"] = _loads(item.pop("findings_json"), [])
    return item


def list_reviews(production_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM council_reviews WHERE production_id=? ORDER BY created_at,id",
            (production_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["findings"] = _loads(item.pop("findings_json"), [])
        result.append(item)
    return result


def latest_review_for_task(task_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM council_reviews WHERE task_id=? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["findings"] = _loads(item.pop("findings_json"), [])
    return item


def get_session(production_id: str, seat_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM council_agent_sessions WHERE production_id=? AND seat_id=?",
            (production_id, seat_id),
        ).fetchone()
    return dict(row) if row else None


def update_session(production_id: str, seat_id: str, **values: Any) -> None:
    allowed = {"provider_session_id", "status", "last_task_id", "handoff_summary"}
    if set(values) - allowed:
        raise ValueError("Unsupported council session field")
    values["updated_at"] = now_iso()
    columns = ",".join(f"{key}=?" for key in values)
    with connect() as db:
        db.execute(
            f"UPDATE council_agent_sessions SET {columns} WHERE production_id=? AND seat_id=?",
            (*values.values(), production_id, seat_id),
        )


def add_intervention(
    production_id: str, content: str, target_seat_ids: list[str], *, queued_reason: str | None = None,
) -> dict[str, Any]:
    intervention_id = uuid.uuid4().hex
    timestamp = now_iso()
    with connect() as db:
        db.execute(
            """INSERT INTO council_interventions
               (id,production_id,content,target_seat_ids_json,state,queued_reason,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (intervention_id, production_id, content, _json(target_seat_ids), "queued", queued_reason, timestamp),
        )
    return get_intervention(intervention_id) or {}


def get_intervention(intervention_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM council_interventions WHERE id=?", (intervention_id,)).fetchone()
    return _intervention_dict(row) if row else None


def _intervention_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["target_seat_ids"] = _loads(item.pop("target_seat_ids_json"), [])
    item["affected_task_ids"] = _loads(item.pop("affected_task_ids_json"), [])
    item["action_results"] = _loads(item.pop("action_results_json", None), [])
    return item


def list_interventions(production_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM council_interventions WHERE production_id=? ORDER BY created_at,id", (production_id,),
        ).fetchall()
    return [_intervention_dict(row) for row in rows]


def update_intervention(intervention_id: str, state: str, **values: Any) -> None:
    if state not in INTERVENTION_STATES:
        raise ValueError("Unsupported intervention state")
    allowed = {
        "affected_task_ids", "queued_reason", "delivered_at", "acknowledged_at", "applied_at",
        "resume_policy", "action_results", "error",
    }
    if set(values) - allowed:
        raise ValueError("Unsupported intervention field")
    encoded = {
        (
            "affected_task_ids_json" if key == "affected_task_ids"
            else "action_results_json" if key == "action_results"
            else key
        ): (_json(value) if key in {"affected_task_ids", "action_results"} else value)
        for key, value in values.items()
    }
    encoded["state"] = state
    columns = ",".join(f"{key}=?" for key in encoded)
    with connect() as db:
        db.execute(f"UPDATE council_interventions SET {columns} WHERE id=?", (*encoded.values(), intervention_id))


def add_activity(
    production_id: str, worker_type: str, state: str, message: str, *, worker_id: str | None = None,
    role_id: str | None = None, task_id: str | None = None, metadata: dict[str, Any] | None = None,
) -> int:
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO council_activity
               (production_id,worker_type,worker_id,role_id,task_id,state,message,metadata_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (production_id, worker_type, worker_id, role_id, task_id, state, message,
             _json(metadata or {}), now_iso()),
        )
        return int(cursor.lastrowid)


def latest_activity(production_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM council_activity WHERE production_id=? ORDER BY id DESC LIMIT 1", (production_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["metadata"] = _loads(item.pop("metadata_json"), {})
    return item


def council_snapshot(production_id: str) -> dict[str, Any] | None:
    config = latest_config(production_id)
    if not config:
        return None
    return {
        "config": config,
        "seats": list_seats(production_id, int(config["revision"])),
        "tasks": list_tasks(production_id),
        "deliverables": list_deliverables(production_id),
        "reviews": list_reviews(production_id),
        "interventions": list_interventions(production_id),
        "activity": latest_activity(production_id),
    }
