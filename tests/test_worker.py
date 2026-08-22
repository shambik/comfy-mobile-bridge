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

    async def test_recovery_prefers_running_prompt_and_deletes_pending_duplicates(self):
        job_id = "a" * 32
        workflow = {
            "92": {
                "class_type": "SaveVideo",
                "inputs": {"filename_prefix": f"h3_bridge_{job_id}"},
            }
        }
        worker = QueueWorker()
        worker.comfy.queue = AsyncMock(return_value={
            "queue_running": [[1, "running-prompt", workflow, {"client_id": "running-client"}, ["92"]]],
            "queue_pending": [
                [2, "pending-prompt-1", workflow, {"client_id": "pending-client-1"}, ["92"]],
                [3, "pending-prompt-2", workflow, {"client_id": "pending-client-2"}, ["92"]],
            ],
        })
        worker.comfy.delete_queued = AsyncMock()

        selected = await worker._claim_existing_prompt(job_id, "pending-prompt-2")

        self.assertEqual(selected["prompt_id"], "running-prompt")
        self.assertEqual(selected["client_id"], "running-client")
        worker.comfy.delete_queued.assert_awaited_once_with([
            "pending-prompt-1", "pending-prompt-2",
        ])

    def test_queue_records_support_comfy_savevideo_job_prefix(self):
        job_id = "b" * 32
        payload = {
            "queue_pending": [{
                "priority": 4,
                "prompt_id": "dict-prompt",
                "prompt": {
                    "92": {
                        "class_type": "SaveVideo",
                        "inputs": {"filename_prefix": f"video/h3_bridge_{job_id}_retry"},
                    }
                },
                "extra_data": {"client_id": "dict-client"},
            }]
        }

        records = QueueWorker._prompts_for_job(payload, job_id)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["prompt_id"], "dict-prompt")
        self.assertEqual(records[0]["client_id"], "dict-client")

    def test_empty_exception_messages_still_have_a_type(self):
        worker = QueueWorker()
        self.assertEqual(worker._error_text(httpx.ReadTimeout("")), "ReadTimeout")


if __name__ == "__main__":
    unittest.main()
