import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

import backend.db as db_module
from backend.db import connect, now_iso
from backend.comfy import ComfyClient
from backend.worker import QueueWorker


class WorkerSequenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h3-worker-test-")
        self.path = Path(self.temp.name) / "jobs.sqlite3"
        self.original_path = db_module.DB_PATH
        db_module.DB_PATH = self.path
        db_module.init_db()

    async def asyncTearDown(self):
        db_module.DB_PATH = self.original_path
        self.temp.cleanup()

    async def test_final_mp4_assembly_cannot_be_canceled_mid_write(self):
        sequence_id = "assembling-sequence"
        now = now_iso()
        with connect() as db:
            db.execute(
                """INSERT INTO sequences
                   (id,kind,title,status,position,progress,phase,current_item,
                    total_items,created_at,updated_at,started_at)
                   VALUES(?,'connected','test','verifying',1,0.99,'assembling',2,2,?,?,?)""",
                (sequence_id, now, now, now),
            )

        worker = QueueWorker()
        worker.current_sequence = sequence_id
        self.assertFalse(await worker.cancel_sequence(sequence_id))

        with connect() as db:
            row = db.execute(
                "SELECT status,phase FROM sequences WHERE id=?", (sequence_id,)
            ).fetchone()
        self.assertEqual(tuple(row), ("verifying", "assembling"))

    async def test_transient_comfy_history_timeout_is_retryable(self):
        worker = QueueWorker()
        worker.comfy.history = AsyncMock(
            side_effect=[httpx.ReadTimeout("history endpoint timed out"), {
                "status": {"status_str": "success", "completed": True},
            }]
        )

        history, error = await worker._read_comfy_history("prompt-1")

        self.assertIsNone(history)
        self.assertIsInstance(error, httpx.ReadTimeout)
        history, error = await worker._read_comfy_history("prompt-1")
        self.assertEqual(history["status"]["completed"], True)
        self.assertIsNone(error)

    async def test_cancel_waits_until_comfy_prompt_leaves_queue(self):
        client = ComfyClient()
        client.queue = AsyncMock(side_effect=[
            {"queue_running": [[1, "prompt-1"]], "queue_pending": []},
            {"queue_running": [], "queue_pending": []},
        ])

        self.assertTrue(await client.wait_for_prompt_clear("prompt-1", timeout=2))

    async def test_cancel_failure_sets_restart_gate_before_next_job(self):
        worker = QueueWorker()
        worker.comfy.cancel = AsyncMock(side_effect=RuntimeError("prompt still running"))
        worker.comfy.shutdown = AsyncMock()

        await worker._cancel_comfy_prompt("prompt-1")

        self.assertTrue(worker.comfy_restart_required)
        worker.comfy.shutdown.assert_awaited_once()

    def test_empty_exception_messages_still_have_a_type(self):
        worker = QueueWorker()
        self.assertEqual(worker._error_text(httpx.ReadTimeout("")), "ReadTimeout")


if __name__ == "__main__":
    unittest.main()
