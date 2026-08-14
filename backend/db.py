import json
import sqlite3
import statistics
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def _create_jobs_table(db):
    db.executescript("""
    CREATE TABLE jobs (
        id TEXT PRIMARY KEY,
        prompt TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('text','opening','closing','frames','reference')),
        duration REAL NOT NULL CHECK(duration BETWEEN 0.5 AND 60),
        engine TEXT NOT NULL CHECK(engine IN ('turbo','standard','spectrum')),
        turbo_profile TEXT NOT NULL CHECK(turbo_profile IN ('v1','v4')),
        encoder TEXT NOT NULL CHECK(encoder IN ('native','clipproj')),
        steps INTEGER NOT NULL,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL,
        seed TEXT NOT NULL,
        sequence_id TEXT,
        sequence_index INTEGER,
        sequence_total INTEGER,
        status TEXT NOT NULL,
        position INTEGER NOT NULL,
        input_path TEXT,
        input_name TEXT,
        reference_audio_path TEXT,
        reference_audio_name TEXT,
        first_frame_path TEXT,
        first_frame_name TEXT,
        last_frame_path TEXT,
        last_frame_name TEXT,
        output_path TEXT,
        prompt_id TEXT,
        progress REAL NOT NULL DEFAULT 0,
        phase TEXT NOT NULL DEFAULT 'queued',
        step INTEGER NOT NULL DEFAULT 0,
        total_steps INTEGER NOT NULL DEFAULT 0,
        eta_seconds REAL,
        error TEXT,
        metrics_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        CHECK((engine='turbo' AND steps BETWEEN 4 AND 12) OR
              (engine IN ('standard','spectrum') AND steps BETWEEN 8 AND 30)),
        CHECK(width BETWEEN 256 AND 2048 AND height BETWEEN 256 AND 2048 AND
              width % 32 = 0 AND height % 32 = 0 AND width * height <= 2000000),
        CHECK(mode <> 'reference' OR engine IN ('standard','spectrum')),
        CHECK((sequence_id IS NULL AND sequence_index IS NULL AND sequence_total IS NULL) OR
              (sequence_id IS NOT NULL AND sequence_index BETWEEN 1 AND sequence_total AND sequence_total BETWEEN 2 AND 20))
    );
    CREATE INDEX idx_jobs_queue ON jobs(status, position);
    CREATE INDEX idx_jobs_sequence ON jobs(sequence_id, sequence_index);
    """)


def _create_sequence_tables(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS sequences (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK(kind IN ('connected','history')),
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        position INTEGER NOT NULL,
        engine TEXT CHECK(engine IS NULL OR engine IN ('turbo','standard','spectrum')),
        encoder TEXT CHECK(encoder IS NULL OR encoder IN ('native','clipproj')),
        steps INTEGER,
        width INTEGER,
        height INTEGER,
        duration INTEGER,
        progress REAL NOT NULL DEFAULT 0,
        phase TEXT NOT NULL DEFAULT 'queued',
        current_item INTEGER NOT NULL DEFAULT 0,
        total_items INTEGER NOT NULL CHECK(total_items BETWEEN 2 AND 20),
        eta_seconds REAL,
        output_path TEXT,
        error TEXT,
        metrics_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_sequences_queue ON sequences(status, position);

    CREATE TABLE IF NOT EXISTS sequence_items (
        sequence_id TEXT NOT NULL,
        item_index INTEGER NOT NULL,
        prompt TEXT,
        job_id TEXT,
        source_job_id TEXT,
        source_sequence_id TEXT,
        clip_path TEXT,
        continuity_frame_path TEXT,
        status TEXT NOT NULL DEFAULT 'queued',
        PRIMARY KEY(sequence_id, item_index),
        FOREIGN KEY(sequence_id) REFERENCES sequences(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_sequence_items_job ON sequence_items(job_id);
    """)


def _table_columns(db):
    return {row[1] for row in db.execute("PRAGMA table_info(jobs)").fetchall()}


def _rebuild_jobs_table(db):
    old_columns = _table_columns(db)
    db.execute("DROP INDEX IF EXISTS idx_jobs_queue")
    db.execute("DROP INDEX IF EXISTS idx_jobs_sequence")
    db.execute("ALTER TABLE jobs RENAME TO jobs_legacy")
    _create_jobs_table(db)

    columns = [
        "id", "prompt", "mode", "duration", "engine", "turbo_profile", "encoder", "steps", "width", "height",
        "seed", "sequence_id", "sequence_index", "sequence_total", "status", "position",
        "input_path", "input_name", "reference_audio_path", "reference_audio_name",
        "first_frame_path", "first_frame_name",
        "last_frame_path", "last_frame_name", "output_path", "prompt_id",
        "progress", "phase", "step", "total_steps", "eta_seconds", "error",
        "metrics_json", "created_at", "updated_at",
        "started_at", "finished_at",
    ]
    defaults = {
        "engine": "CASE WHEN mode='reference' THEN 'standard' ELSE 'turbo' END",
        "turbo_profile": "'v1'",
        "encoder": "'native'",
        "steps": "CASE WHEN mode='reference' THEN 20 ELSE 4 END",
        "width": "736",
        "height": "416",
        "progress": "0",
        "phase": "'queued'",
        "step": "0",
        "total_steps": "0",
        "eta_seconds": "NULL",
    }
    select_values = ",".join(
        column if column in old_columns else defaults.get(column, "NULL")
        for column in columns
    )
    db.execute(
        f"INSERT INTO jobs ({','.join(columns)}) SELECT {select_values} FROM jobs_legacy"
    )
    db.execute("DROP TABLE jobs_legacy")


def init_db():
    with connect() as db:
        table = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
        if table:
            table_sql = table[0] or ""
            required_columns = {
                "first_frame_path", "first_frame_name", "last_frame_path", "last_frame_name",
                "phase", "step", "total_steps", "eta_seconds",
                "engine", "turbo_profile", "encoder", "steps", "width", "height",
                "sequence_id", "sequence_index", "sequence_total",
                "reference_audio_path", "reference_audio_name",
            }
            if "frames" not in table_sql or "spectrum" not in table_sql or "clipproj" not in table_sql or "turbo_profile" not in table_sql or "2000000" not in table_sql or "duration REAL" not in table_sql or not required_columns.issubset(_table_columns(db)):
                # SQLite cannot alter a CHECK constraint in place. Rebuild the
                # table while preserving every existing job and its output path.
                _rebuild_jobs_table(db)
            else:
                db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, position)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_sequence ON jobs(sequence_id, sequence_index)")
        elif not table:
            _create_jobs_table(db)
        _create_sequence_tables(db)
        db.execute(
            """
            UPDATE jobs
            SET phase = CASE status
                WHEN 'completed' THEN 'completed'
                WHEN 'failed' THEN 'failed'
                WHEN 'canceled' THEN 'canceled'
                WHEN 'verifying' THEN 'verifying'
                WHEN 'running' THEN 'starting'
                WHEN 'starting' THEN 'starting'
                ELSE phase
            END
            WHERE phase='queued' AND status <> 'queued'
            """
        )


def row_dict(row):
    if not row:
        return None
    item = dict(row)
    raw_metrics = json.loads(item.pop("metrics_json") or "{}")
    item["metrics"] = {key: raw_metrics[key] for key in ("generation_seconds", "peak_gpu", "ffprobe") if key in raw_metrics}
    output_path = item.pop("output_path", None)
    for private_key in (
        "seed", "input_path", "input_name", "reference_audio_path", "reference_audio_name",
        "first_frame_path", "first_frame_name",
        "last_frame_path", "last_frame_name", "prompt_id",
    ):
        item.pop(private_key, None)
    if output_path:
        item["video_url"] = f"/api/jobs/{item['id']}/video"
    return item


def list_jobs(include_sequence_children: bool = False):
    child_filter = "" if include_sequence_children else "WHERE sequence_id IS NULL"
    with connect() as db:
        rows = db.execute(f"""
          SELECT * FROM jobs
          {child_filter}
          ORDER BY
            CASE status WHEN 'running' THEN 0 WHEN 'starting' THEN 0 WHEN 'verifying' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
            CASE WHEN status = 'queued' THEN position END ASC,
            CASE WHEN status NOT IN ('queued','starting','running','verifying')
                 THEN COALESCE(finished_at, created_at) END DESC,
            created_at DESC
        """).fetchall()
    return [row_dict(r) for r in rows]


def get_job(job_id: str, public=True):
    with connect() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return row_dict(row) if public else (dict(row) if row else None)


def next_position(db) -> int:
    return int(db.execute("""
        SELECT COALESCE(MAX(position), 0) + 1 FROM (
            SELECT position FROM jobs
            UNION ALL
            SELECT position FROM sequences
        )
    """).fetchone()[0])


def update_job(job_id: str, **values):
    if not values:
        return
    values["updated_at"] = now_iso()
    if "metrics" in values:
        values["metrics_json"] = json.dumps(values.pop("metrics"), ensure_ascii=False)
    assignments = ",".join(f"{key}=?" for key in values)
    with connect() as db:
        db.execute(f"UPDATE jobs SET {assignments} WHERE id=?", (*values.values(), job_id))


def _sequence_items(db, sequence_id: str) -> list[dict]:
    rows = db.execute(
        """
        SELECT i.*, COALESCE(j.status, i.status) AS resolved_status
        FROM sequence_items i
        LEFT JOIN jobs j ON j.id=i.job_id
        WHERE i.sequence_id=?
        ORDER BY i.item_index
        """,
        (sequence_id,),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        items.append({
            "item_index": item["item_index"],
            "prompt": item.get("prompt"),
            "job_id": item.get("job_id"),
            "source_job_id": item.get("source_job_id"),
            "source_sequence_id": item.get("source_sequence_id"),
            "status": item.get("resolved_status") or item.get("status"),
        })
    return items


def _sequence_row_dict(db, row):
    if not row:
        return None
    item = dict(row)
    raw_metrics = json.loads(item.pop("metrics_json") or "{}")
    item["metrics"] = {
        key: raw_metrics[key]
        for key in ("assembly_seconds", "source_count", "source_durations", "ffprobe")
        if key in raw_metrics
    }
    output_path = item.pop("output_path", None)
    if output_path:
        item["video_url"] = f"/api/sequences/{item['id']}/video"
    item["items"] = _sequence_items(db, item["id"])
    return item


def list_sequences():
    with connect() as db:
        rows = db.execute("""
          SELECT * FROM sequences
          ORDER BY
            CASE status WHEN 'running' THEN 0 WHEN 'starting' THEN 0 WHEN 'verifying' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
            CASE WHEN status = 'queued' THEN position END ASC,
            CASE WHEN status NOT IN ('queued','starting','running','verifying')
                 THEN COALESCE(finished_at, created_at) END DESC,
            created_at DESC
        """).fetchall()
        return [_sequence_row_dict(db, row) for row in rows]


def get_sequence(sequence_id: str, public: bool = True):
    with connect() as db:
        row = db.execute("SELECT * FROM sequences WHERE id=?", (sequence_id,)).fetchone()
        return _sequence_row_dict(db, row) if public else (dict(row) if row else None)


def update_sequence(sequence_id: str, **values):
    if not values:
        return
    values["updated_at"] = now_iso()
    if "metrics" in values:
        values["metrics_json"] = json.dumps(values.pop("metrics"), ensure_ascii=False)
    assignments = ",".join(f"{key}=?" for key in values)
    with connect() as db:
        db.execute(
            f"UPDATE sequences SET {assignments} WHERE id=?",
            (*values.values(), sequence_id),
        )


def historical_generation_seconds(
    mode: str,
    duration: int,
    engine: str,
    steps: int,
    width: int,
    height: int,
    encoder: str = "native",
    turbo_profile: str = "v1",
) -> float | None:
    """Return a same-machine baseline for an honest ETA estimate."""
    with connect() as db:
        rows = db.execute(
            """
            SELECT metrics_json FROM jobs
            WHERE status='completed' AND mode=? AND duration=? AND engine=? AND encoder=?
              AND turbo_profile=?
              AND steps=? AND width=? AND height=? AND metrics_json IS NOT NULL
            ORDER BY finished_at DESC LIMIT 12
            """,
            (mode, duration, engine, encoder, turbo_profile, steps, width, height),
        ).fetchall()

    values = []
    for row in rows:
        try:
            seconds = float(json.loads(row[0]).get("generation_seconds", 0))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if seconds > 0:
            values.append(seconds)
    return float(statistics.median(values)) if values else None
