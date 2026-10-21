import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

import backend.db as db_module
from backend.db import connect, now_iso
from backend.comfy import ComfyBusyError, ComfyCancellationError, ComfyClient
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

    async def test_pending_prompt_is_deleted_without_global_interrupt(self):
        client = ComfyClient()
        client.queue = AsyncMock(return_value={
            "queue_running": [[1, "manual-prompt"]],
            "queue_pending": [[2, "prompt-1"]],
        })
        client.delete_queued = AsyncMock()
        client.wait_for_prompt_clear = AsyncMock(return_value=True)

        with patch("backend.comfy.httpx.AsyncClient") as http_client:
            await client.cancel("prompt-1")

        client.delete_queued.assert_awaited_once_with(["prompt-1"])
        client.wait_for_prompt_clear.assert_awaited_once_with("prompt-1")
        http_client.assert_not_called()

    async def test_cancel_refuses_global_interrupt_when_queue_cannot_prove_ownership(self):
        client = ComfyClient()
        client.queue = AsyncMock(side_effect=httpx.ReadTimeout("queue unavailable"))

        with self.assertRaises(ComfyCancellationError), \
             patch("backend.comfy.httpx.AsyncClient") as http_client:
            await client.cancel("prompt-1")

        http_client.assert_not_called()

    async def test_running_prompt_proves_liveness_when_health_probe_times_out(self):
        worker = QueueWorker()
        worker.comfy.queue = AsyncMock(return_value={
            "queue_running": [[1, "prompt-1"]], "queue_pending": [],
        })
        worker.comfy.ready = AsyncMock(return_value=False)
        worker.comfy.discovered_pid = lambda: None

        observation = await worker._observe_comfy_prompt("prompt-1")

        self.assertEqual(observation["queue_state"], "queue_running")
        self.assertTrue(observation["queue_available"])
        self.assertTrue(observation["server_ready"])
        self.assertFalse(observation["process_alive"])

    async def test_live_process_proves_liveness_when_queue_and_health_probes_time_out(self):
        worker = QueueWorker()
        worker.comfy.queue = AsyncMock(side_effect=httpx.ReadTimeout("queue endpoint timed out"))
        worker.comfy.ready = AsyncMock(return_value=False)
        worker.comfy.discovered_pid = lambda: 6972

        observation = await worker._observe_comfy_prompt("prompt-1")

        self.assertFalse(observation["queue_available"])
        self.assertEqual(observation["queue_error"], "ReadTimeout: queue endpoint timed out")
        self.assertTrue(observation["process_alive"])
        self.assertEqual(observation["process_pid"], 6972)

    def test_prompt_queue_state_distinguishes_running_and_pending(self):
        running = {"queue_running": [[1, "prompt-1"]], "queue_pending": []}
        pending = {"queue_running": [], "queue_pending": [{"prompt_id": "prompt-1"}]}

        self.assertEqual(ComfyClient.prompt_queue_state(running, "prompt-1"), "queue_running")
        self.assertEqual(ComfyClient.prompt_queue_state(pending, "prompt-1"), "queue_pending")
        self.assertIsNone(ComfyClient.prompt_queue_state({}, "prompt-1"))

    def test_discovered_pid_falls_back_to_port_owner(self):
        client = ComfyClient()
        client._windows_process_ids = lambda: []
        client._listening_pid = lambda: 8190

        self.assertEqual(client.discovered_pid(), 8190)

    async def test_shutdown_falls_back_to_comfy_listener_after_bridge_restart(self):
        client = ComfyClient()
        client._windows_process_ids = lambda: []
        client._listening_pid = lambda: 8190

        with patch("backend.comfy.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=0)
            await client.shutdown()

        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0],
            ["taskkill", "/PID", "8190", "/T", "/F"],
        )

    def test_windows_stop_retries_exact_pid_with_elevation(self):
        with patch("backend.comfy.subprocess.run", side_effect=[
            SimpleNamespace(returncode=5),
            SimpleNamespace(returncode=0),
        ]) as run:
            self.assertTrue(ComfyClient._kill_windows_process_tree(8190))

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0][0], "powershell.exe")
        self.assertIn("'/PID','8190'", run.call_args.args[0][-1])

    async def test_cancel_failure_sets_restart_gate_before_next_job(self):
        worker = QueueWorker()
        worker.comfy.cancel = AsyncMock(side_effect=RuntimeError("prompt still running"))
        worker.comfy.shutdown = AsyncMock()

        await worker._cancel_comfy_prompt("prompt-1")

        self.assertTrue(worker.comfy_restart_required)
        worker.comfy.shutdown.assert_awaited_once()

    async def test_unsafe_cancel_keeps_comfy_alive_for_manual_work(self):
        worker = QueueWorker()
        worker.comfy.cancel = AsyncMock(side_effect=ComfyCancellationError("ownership unknown"))
        worker.comfy.shutdown = AsyncMock()

        await worker._cancel_comfy_prompt("prompt-1")

        self.assertTrue(worker.comfy_restart_required)
        worker.comfy.shutdown.assert_not_awaited()

    async def test_busy_existing_comfy_process_is_not_replaced(self):
        client = ComfyClient()
        client.ready = AsyncMock(return_value=False)
        client._present_process_ids = lambda: [6972]
        client.shutdown = AsyncMock()

        # A stand-in installation, so the check reaches the busy-process guard
        # on machines without a real ComfyUI checkout (CI).
        with tempfile.TemporaryDirectory(prefix="h3-fake-comfy-") as temp:
            code = Path(temp) / "ComfyUI"
            code.mkdir()
            (code / "main.py").write_text("", encoding="utf-8")
            python = Path(temp) / "python.exe"
            python.write_bytes(b"")
            with patch("backend.comfy.COMFY_CODE", code), patch("backend.comfy.COMFY_PYTHON", python), \
                 self.assertRaises(ComfyBusyError):
                await client.ensure_started()

        client.shutdown.assert_not_awaited()

    async def test_busy_comfy_requeues_job_instead_of_failing_it(self):
        worker = QueueWorker()
        worker.run_job = AsyncMock(side_effect=ComfyBusyError("existing process is busy"))
        job = {"id": "job-waiting-for-comfy", "status": "starting"}

        with patch("backend.worker.update_job") as update, \
             patch("backend.worker.asyncio.sleep", new=AsyncMock()):
            await worker._execute_job(job)

        update.assert_called_once()
        self.assertEqual(update.call_args.args[0], job["id"])
        self.assertEqual(update.call_args.kwargs["status"], "queued")
        self.assertEqual(update.call_args.kwargs["phase"], "queued")
        self.assertIn("existing process is busy", update.call_args.kwargs["error"])

    async def test_canceling_unsubmitted_job_does_not_interrupt_manual_comfy_work(self):
        worker = QueueWorker()
        worker.current_job = "job-without-prompt"
        worker.comfy.cancel = AsyncMock()

        with patch("backend.worker.get_job", return_value={
            "id": worker.current_job, "status": "starting", "prompt_id": None,
        }):
            self.assertTrue(await worker.cancel(worker.current_job))

        worker.comfy.cancel.assert_not_awaited()

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
