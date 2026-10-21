import asyncio
import json
import re
import time
import uuid
from pathlib import Path

import httpx

from .comfy import (ComfyBusyError, ComfyCancellationError, ComfyClient,
                    find_video, gpu_sample, media_probe)
from .config import (AUDIOLOCK_NODE_DIR, AUDIO_VAE, CLIPPROJ_NODE_DIR, CLIPPROJ_PROJECTION,
                     CLIPPROJ_TEXT_ENCODER, FUSED_MAINODES_DIR, FUSED_MOTION_ADAPTER,
                     FUSED_SLA_MODEL, FUSED_SLA_NODE_DIR, FUSED_VIDEO_VAE,
                     FUSED_WORKFLOW_FILES, INPUT, LTX_MODEL_FILES, LTX_REFERENCE_FILES,
                     MODELS, REF2VA_MODEL, REF2VA_TURBO_LORA, SEQUENCES)
from .db import (connect, get_job, get_sequence, historical_generation_seconds,
                 now_iso, update_job, update_sequence)
from .media import assemble_clips, extract_last_frame
from .reference_check import sheet_frames
from .library import finalize_completed_asset, resolve_asset_path
from .workflows import (apply_attention_mode, attention_node_classes,
                        fused_sla_audio_lock_workflow, ltx_lipsync_workflow,
                        ltx_node_classes, ltx_reference_workflow, ltx_video_workflow,
                        native_audio_lock_workflow,
                        official_fused_workflow,
                        reference_workflow,
                        spectrum_workflow, standard_workflow, turbo_workflow)


SAMPLER_NODE_ID = "14"
ACTIVE_STATUSES = ("starting", "running", "verifying")
# LTX reference clips are checked for frames that show the reference sheet
# itself; a clip that does is set aside and re-rendered with a new seed.
LTX_REFERENCE_ATTEMPTS = 3
LTX_REFERENCE_SEED_STEP = 7919


class ReferenceSheetShown(RuntimeError):
    """An LTX reference render showed the reference sheet instead of the scene."""

    def __init__(self, video: Path, check: dict):
        frames = check["sheet_frames"]
        super().__init__(f"The clip showed the reference sheet in frames {frames[0]}-{frames[-1]}")
        self.video = video
        self.check = check


class QueueWorker:
    def __init__(self):
        self.comfy = ComfyClient()
        self.task: asyncio.Task | None = None
        self.wake = asyncio.Event()
        self.stopping = False
        self.current_job: str | None = None
        self.current_sequence: str | None = None
        self.cancelled: set[str] = set()
        # A prompt can survive /interrupt while a model forward is running.
        # Keep the worker blocked until Comfy has been restarted, so a new
        # queued job can never run behind the canceled prompt.
        self.comfy_restart_required = False
        self.comfy_manual_stop = False
        # ComfyUI prompts survive a bridge restart.  Recovery uses this map to
        # resume those prompts instead of submitting duplicate generations.
        self.recovered_prompts: dict[str, dict[str, str | None]] = {}

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        """Keep failure cards useful even when an exception has no message."""
        detail = str(exc).strip()
        return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__

    async def _read_comfy_history(self, prompt_id: str):
        """Read history without turning a transient bridge poll failure into a job failure."""
        try:
            return await self.comfy.history(prompt_id), None
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError) as exc:
            return None, exc

    async def _observe_comfy_prompt(self, prompt_id: str) -> dict[str, object]:
        """Observe prompt liveness without treating a blocked HTTP endpoint as death.

        H3's first high-resolution forward can occupy ComfyUI's event loop
        long enough for both /history and /system_stats to time out.  The
        queue endpoint, a configured process, or the listening port can still
        prove that the prompt is alive.  This observation is persisted with
        the job so a later recovery has enough evidence to reconcile it.
        """
        queue_available = False
        queue_state: str | None = None
        queue_error: str | None = None
        try:
            payload = await self.comfy.queue()
            queue_available = True
            queue_state = ComfyClient.prompt_queue_state(payload, prompt_id)
        except Exception as exc:
            queue_error = self._error_text(exc)

        server_ready = queue_available or await self.comfy.ready()
        process_pid = await asyncio.to_thread(self.comfy.discovered_pid)
        return {
            "queue_available": queue_available,
            "queue_state": queue_state,
            "queue_error": queue_error,
            "server_ready": server_ready,
            "process_alive": process_pid is not None,
            "process_pid": process_pid,
        }

    def start(self):
        self.task = asyncio.create_task(self.loop())

    async def stop(self):
        self.stopping = True
        self.wake.set()
        if self.task:
            await self.task
        # The bridge lifecycle is independent from ComfyUI. Restarting or
        # reloading the app must not kill a manually running ComfyUI process;
        # only the explicit /api/comfy/stop action calls shutdown().

    def notify(self):
        self.wake.set()

    async def _cancel_comfy_prompt(self, prompt_id: str | None):
        if not prompt_id:
            # ComfyUI's /interrupt endpoint is global. A queued/starting
            # bridge job has not submitted a prompt yet, so interrupting here
            # could terminate an unrelated manual ComfyUI generation.
            return
        try:
            await self.comfy.cancel(prompt_id)
        except ComfyCancellationError:
            # The queue could not prove that a global interrupt was safe. Keep
            # the process alive and hold the worker at the recovery gate; a
            # manual ComfyUI render must never be sacrificed for a UI cancel.
            self.comfy_restart_required = True
        except Exception:
            # If Comfy did not acknowledge the cancellation, kill only the
            # configured ComfyUI process tree.  The loop will restart it
            # before taking another queued job.
            self.comfy_restart_required = True
            try:
                await self.comfy.shutdown()
            except Exception:
                pass

    async def start_comfy(self):
        self.comfy_manual_stop = False
        await self.comfy.ensure_started()

    async def stop_comfy(self):
        self.comfy_manual_stop = True
        if self.current_job:
            self.cancelled.add(self.current_job)
            current = get_job(self.current_job, public=False)
            await self._cancel_comfy_prompt(current.get("prompt_id") if current else None)
        await self.comfy.shutdown()
        self.comfy_restart_required = False

    async def cancel(self, job_id: str):
        job = get_job(job_id, public=False)
        if not job:
            return False
        if job["status"] == "queued":
            update_job(
                job_id, status="canceled", phase="canceled",
                finished_at=now_iso(), error=None, eta_seconds=None,
            )
            if job.get("sequence_id"):
                self._fail_connected_sequence(job, "canceled", "Sequence canceled")
            return True
        if job_id == self.current_job and job["status"] in ACTIVE_STATUSES:
            self.cancelled.add(job_id)
            if job.get("prompt_id"):
                await self._cancel_comfy_prompt(job["prompt_id"])
            self.wake.set()
            return True
        return False

    async def cancel_sequence(self, sequence_id: str):
        sequence = get_sequence(sequence_id, public=False)
        if not sequence or sequence["status"] not in ("queued", *ACTIVE_STATUSES):
            return False
        if sequence_id == self.current_sequence and sequence.get("phase") == "assembling":
            # FFmpeg assembly is intentionally atomic for both connected and
            # history sequences. The completed result can be deleted after it
            # finishes, but interrupting the encoder risks a corrupt MP4.
            return False

        now = now_iso()
        with connect() as db:
            db.execute(
                """UPDATE sequences SET status='canceled',phase='canceled',error=NULL,
                   eta_seconds=NULL,finished_at=?,updated_at=? WHERE id=?""",
                (now, now, sequence_id),
            )
            db.execute(
                """UPDATE jobs SET status='canceled',phase='canceled',error=NULL,
                   eta_seconds=NULL,finished_at=?,updated_at=?
                   WHERE sequence_id=? AND status='queued'""",
                (now, now, sequence_id),
            )
            db.execute(
                "UPDATE sequence_items SET status='canceled' WHERE sequence_id=? AND status='queued'",
                (sequence_id,),
            )

        if sequence_id == self.current_sequence and self.current_job:
            self.cancelled.add(self.current_job)
            current = get_job(self.current_job, public=False)
            prompt_id = current.get("prompt_id") if current else None
            if prompt_id:
                await self._cancel_comfy_prompt(prompt_id)
            self.wake.set()
        return True

    @staticmethod
    def _queue_records(payload: dict) -> list[dict]:
        """Normalize ComfyUI's tuple-shaped and dict-shaped queue entries."""
        records: list[dict] = []
        for queue_name in ("queue_running", "queue_pending"):
            for item in payload.get(queue_name) or []:
                if isinstance(item, (list, tuple)):
                    if len(item) < 2:
                        continue
                    priority = item[0]
                    prompt_id = item[1]
                    workflow = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}
                    extra = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
                elif isinstance(item, dict):
                    priority = item.get("priority")
                    prompt_id = item.get("prompt_id")
                    workflow = item.get("prompt") or item.get("workflow") or {}
                    extra = item.get("extra_data") or item.get("extra") or {}
                else:
                    continue
                if prompt_id:
                    records.append({
                        "queue": queue_name,
                        "priority": priority,
                        "prompt_id": str(prompt_id),
                        "workflow": workflow,
                        "client_id": extra.get("client_id") if isinstance(extra, dict) else None,
                    })
        return records

    @staticmethod
    def _job_id_from_workflow(workflow: dict) -> str | None:
        """Extract the bridge job ID from a SaveVideo filename prefix."""
        if not isinstance(workflow, dict):
            return None
        for node in workflow.values():
            if not isinstance(node, dict) or node.get("class_type") != "SaveVideo":
                continue
            prefix = str((node.get("inputs") or {}).get("filename_prefix") or "")
            match = re.search(r"h3_bridge_([0-9a-f]{32})(?:$|[/\\_])", prefix, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @classmethod
    def _prompts_for_job(cls, payload: dict, job_id: str) -> list[dict]:
        return [
            record for record in cls._queue_records(payload)
            if cls._job_id_from_workflow(record["workflow"]) == job_id
        ]

    async def _claim_existing_prompt(
        self, job_id: str, preferred_prompt_id: str | None = None,
    ) -> dict | None:
        """Claim one prompt and remove only duplicate pending copies.

        This is deliberately separate from ``ComfyClient.cancel``.  Calling
        ``/interrupt`` during recovery would stop the valid prompt currently
        using the GPU just because another copy is waiting in the queue.
        """
        try:
            payload = await self.comfy.queue()
        except Exception:
            return None
        matches = self._prompts_for_job(payload, job_id)
        if not matches:
            return None

        running = [record for record in matches if record["queue"] == "queue_running"]
        preferred = next(
            (record for record in matches if record["prompt_id"] == preferred_prompt_id),
            None,
        )
        # The GPU-active prompt always wins over a pending prompt.  This is
        # the key guard against a restart attaching the card to a duplicate.
        selected = running[0] if running else preferred or min(
            matches,
            key=lambda record: (record["priority"] is None, record["priority"] or 0),
        )
        duplicate_pending = [
            record["prompt_id"] for record in matches
            if record["prompt_id"] != selected["prompt_id"]
            and record["queue"] == "queue_pending"
        ]
        if duplicate_pending:
            try:
                await self.comfy.delete_queued(duplicate_pending)
            except Exception:
                # Cleanup is best effort.  A transient queue API failure must
                # not turn the valid generation into a failed job.
                pass
        return selected

    async def _recover_prompt_for_job(self, job: dict) -> dict | None:
        runtime = {}
        try:
            runtime = json.loads(job.get("runtime_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            pass
        runtime_prompt_id = ((runtime.get("comfy") or {}).get("prompt_id"))
        return await self._claim_existing_prompt(
            job["id"], job.get("prompt_id") or runtime_prompt_id,
        )

    async def reconcile(self):
        self.recovered_prompts.clear()
        with connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE status IN ('starting','running','verifying')"
            ).fetchall()
        recovered_sequences: set[str] = set()
        for row in rows:
            job = dict(row)
            prompt = await self._recover_prompt_for_job(job)
            if prompt:
                self.recovered_prompts[job["id"]] = {
                    "prompt_id": prompt["prompt_id"],
                    "client_id": prompt.get("client_id"),
                }
                if job.get("sequence_id"):
                    recovered_sequences.add(job["sequence_id"])
                update_job(
                    job["id"], status="running", phase="starting",
                    prompt_id=prompt["prompt_id"], progress=0, step=0,
                    total_steps=0, eta_seconds=None, error=None,
                )
                continue

            history = None
            prompt_id = job.get("prompt_id")
            try:
                runtime = json.loads(job.get("runtime_json") or "{}")
                prompt_id = prompt_id or ((runtime.get("comfy") or {}).get("prompt_id"))
                history = await self.comfy.history(prompt_id) if prompt_id and await self.comfy.ready() else None
            except Exception:
                pass
            if history and history.get("status", {}).get("completed") and prompt_id:
                # Reuse the completed prompt so run_job performs its normal
                # output validation without generating a second video.
                self.recovered_prompts[job["id"]] = {
                    "prompt_id": prompt_id, "client_id": None,
                }
                if job.get("sequence_id"):
                    recovered_sequences.add(job["sequence_id"])
                update_job(
                    job["id"], status="running", phase="starting",
                    prompt_id=prompt_id, progress=0, step=0,
                    total_steps=0, eta_seconds=None, error=None,
                )
                continue

            update_job(
                job["id"], status="queued", phase="queued", prompt_id=None,
                progress=0, step=0, total_steps=0, eta_seconds=None,
                error="Requeued after app restart",
            )

        with connect() as db:
            now = now_iso()
            active_sequences = db.execute(
                "SELECT id FROM sequences WHERE status IN ('starting','running','verifying')"
            ).fetchall()
            for sequence in active_sequences:
                sequence_id = sequence["id"]
                if sequence_id in recovered_sequences:
                    db.execute(
                        """UPDATE sequences SET status='running',phase='starting',
                           eta_seconds=NULL,updated_at=? WHERE id=?""",
                        (now, sequence_id),
                    )
                else:
                    db.execute(
                        """UPDATE sequences SET status='queued',phase='queued',
                           eta_seconds=NULL,updated_at=? WHERE id=?""",
                        (now, sequence_id),
                    )

    async def _execute_job(self, job: dict, recovered_prompt: dict | None = None):
        self.current_job = job["id"]
        self.current_sequence = job.get("sequence_id")
        try:
            reference_retries: list[dict] = []
            while True:
                try:
                    await self.run_job(job, recovered_prompt=recovered_prompt,
                                       reference_retries=reference_retries)
                    break
                except ReferenceSheetShown as exc:
                    # Keep the rejected render beside the outputs under a name
                    # find_video cannot match, then re-render with a new seed.
                    rejected = exc.video.with_name(f"rejected{len(reference_retries) + 1}_{exc.video.name}")
                    exc.video.replace(rejected)
                    reference_retries.append({
                        "seed": job.get("seed"), "sheet_frames": exc.check["sheet_frames"],
                        "rejected_output": str(rejected),
                    })
                    if len(reference_retries) >= LTX_REFERENCE_ATTEMPTS or job["id"] in self.cancelled:
                        raise RuntimeError(
                            f"LTX reference kept showing the reference sheet after {len(reference_retries)} "
                            "renders with different seeds; try a clearer sheet description in the prompt"
                        ) from exc
                    next_seed = str((int(job["seed"]) + LTX_REFERENCE_SEED_STEP) % (2 ** 53))
                    update_job(job["id"], seed=next_seed, status="starting", phase="starting",
                               progress=0, step=0, total_steps=0, prompt_id=None)
                    job = get_job(job["id"], public=False) or {**job, "seed": next_seed}
                    recovered_prompt = None
        except asyncio.CancelledError:
            raise
        except ComfyBusyError as exc:
            # A live manual/ComfyUI process whose health endpoint is busy is a
            # transient resource condition, not a generation failure. Keep
            # the job queued and let the next worker pass retry after a short
            # backoff. Do not call /interrupt or kill the existing process.
            if job["id"] in self.cancelled:
                error = "Generation canceled while waiting for ComfyUI"
                update_job(
                    job["id"], status="canceled", phase="canceled", eta_seconds=None,
                    error=None, finished_at=now_iso(),
                )
                if job.get("sequence_id"):
                    self._fail_connected_sequence(job, "canceled", error)
            else:
                error = self._error_text(exc)[:8000]
                update_job(
                    job["id"], status="queued", phase="queued", progress=0,
                    step=0, total_steps=0, eta_seconds=None, error=error,
                )
                if job.get("sequence_id"):
                    update_sequence(
                        job["sequence_id"], status="queued", phase="queued",
                        eta_seconds=None, error=error,
                    )
                await asyncio.sleep(5)
        except Exception as exc:
            status = "canceled" if job["id"] in self.cancelled else "failed"
            error = self._error_text(exc)[:8000]
            update_job(
                job["id"], status=status, phase=status, eta_seconds=None,
                error=error, finished_at=now_iso(),
            )
            if job.get("sequence_id"):
                self._fail_connected_sequence(job, status, error)
        finally:
            self.cancelled.discard(job["id"])
            self.current_job = None
            self.current_sequence = None

    def _take_recovered(self):
        if not self.recovered_prompts:
            return None
        job_id, prompt = next(iter(self.recovered_prompts.items()))
        del self.recovered_prompts[job_id]
        job = get_job(job_id, public=False)
        return (job, prompt) if job else None

    def _assembly_candidate(self, db):
        return db.execute(
            """
            SELECT s.* FROM sequences s
            WHERE s.status='queued' AND (
                s.kind='history' OR (
                    s.kind='connected'
                    AND NOT EXISTS (
                        SELECT 1 FROM jobs j
                        WHERE j.sequence_id=s.id AND j.status <> 'completed'
                    )
                )
            )
            ORDER BY s.position,s.created_at LIMIT 1
            """
        ).fetchone()

    def take_next(self):
        while True:
            with connect() as db:
                job_row = db.execute(
                    """SELECT * FROM jobs WHERE status='queued'
                       ORDER BY position,COALESCE(sequence_index,0),created_at LIMIT 1"""
                ).fetchone()
                sequence_row = self._assembly_candidate(db)

                if not job_row and not sequence_row:
                    return None

                choose_sequence = bool(sequence_row) and (
                    not job_row
                    or (sequence_row["position"], sequence_row["created_at"])
                    < (job_row["position"], job_row["created_at"])
                )
                now = now_iso()
                if choose_sequence:
                    db.execute(
                        """UPDATE sequences SET status='starting',phase='assembling',
                           started_at=COALESCE(started_at,?),updated_at=?,error=NULL
                           WHERE id=?""",
                        (now, now, sequence_row["id"]),
                    )
                    return "sequence", dict(sequence_row)

                job = dict(job_row)
                if job.get("sequence_id"):
                    sequence = db.execute(
                        "SELECT * FROM sequences WHERE id=?", (job["sequence_id"],)
                    ).fetchone()
                    if not sequence or sequence["status"] in ("failed", "canceled", "completed"):
                        db.execute(
                            """UPDATE jobs SET status='canceled',phase='canceled',
                               finished_at=?,updated_at=? WHERE id=?""",
                            (now, now, job["id"]),
                        )
                        continue
                    db.execute(
                        """UPDATE sequences SET status='running',phase='starting',
                           current_item=?,started_at=COALESCE(started_at,?),updated_at=?,error=NULL
                           WHERE id=?""",
                        (job["sequence_index"], now, now, job["sequence_id"]),
                    )

                db.execute(
                    """
                    UPDATE jobs SET status='starting',started_at=COALESCE(started_at,?),
                        updated_at=?,error=NULL,phase='starting',progress=0,step=0,
                        total_steps=0,eta_seconds=NULL WHERE id=?
                    """,
                    (now, now, job["id"]),
                )
                return "job", job

    async def loop(self):
        await self.reconcile()
        while not self.stopping:
            if self.comfy_restart_required and not self.comfy_manual_stop:
                try:
                    await self.comfy.ensure_started()
                except Exception:
                    # Do not dequeue work while the recovery start is still
                    # failing.  The next pass retries without losing jobs.
                    await asyncio.sleep(2)
                    continue
                self.comfy_restart_required = False

            recovered = self._take_recovered()
            if recovered:
                job, prompt = recovered
                if job and job["status"] in ACTIVE_STATUSES:
                    await self._execute_job(job, recovered_prompt=prompt)
                continue

            task = self.take_next()
            if not task:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=300)
                except asyncio.TimeoutError:
                    await self.comfy.free_models()
                continue

            task_type, record = task
            if task_type == "sequence":
                self.current_sequence = record["id"]
                try:
                    await self.assemble_sequence(record["id"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    error = self._error_text(exc)
                    update_sequence(
                        record["id"], status="failed", phase="failed",
                        eta_seconds=None, error=error[:8000], finished_at=now_iso(),
                    )
                finally:
                    self.current_sequence = None
                continue

            await self._execute_job(record)

    def _fail_connected_sequence(self, job: dict, status: str, error: str):
        sequence_id = job.get("sequence_id")
        if not sequence_id:
            return
        sequence_status = "canceled" if status == "canceled" else "failed"
        now = now_iso()
        with connect() as db:
            db.execute(
                """UPDATE sequences SET status=?,phase=?,error=?,eta_seconds=NULL,
                   finished_at=?,updated_at=? WHERE id=?""",
                (sequence_status, sequence_status, error, now, now, sequence_id),
            )
            db.execute(
                """UPDATE jobs SET status='canceled',phase='canceled',
                   error='Canceled because another shot in the sequence failed',
                   eta_seconds=NULL,finished_at=?,updated_at=?
                   WHERE sequence_id=? AND status='queued'""",
                (now, now, sequence_id),
            )
            db.execute(
                """UPDATE sequence_items SET status=CASE
                     WHEN job_id=? THEN ? WHEN status='queued' THEN 'canceled' ELSE status END
                   WHERE sequence_id=?""",
                (job["id"], sequence_status, sequence_id),
            )

    async def _ensure_continuity_frame(self, job: dict):
        if not job.get("sequence_id") or int(job.get("sequence_index") or 1) <= 1:
            return
        if job.get("first_frame_name") and Path(job.get("first_frame_path") or "").exists():
            return

        with connect() as db:
            previous = db.execute(
                """SELECT j.id,j.output_path FROM jobs j
                   WHERE j.sequence_id=? AND j.sequence_index=? AND j.status='completed'""",
                (job["sequence_id"], job["sequence_index"] - 1),
            ).fetchone()
        previous_path = resolve_asset_path("job", previous["id"]) if previous else None
        if not previous_path:
            raise RuntimeError("The previous sequence shot has no validated output")

        frame_name = f"sequence_{job['sequence_id']}_shot{job['sequence_index'] - 1:02d}_last.png"
        frame_path = INPUT / frame_name
        await asyncio.to_thread(
            extract_last_frame, previous_path, frame_path,
            int(job["width"]), int(job["height"]),
        )
        update_job(job["id"], first_frame_path=str(frame_path), first_frame_name=frame_name)
        with connect() as db:
            db.execute(
                """UPDATE sequence_items SET continuity_frame_path=?
                   WHERE sequence_id=? AND item_index=?""",
                (str(frame_path), job["sequence_id"], job["sequence_index"] - 1),
            )
        job["first_frame_path"] = str(frame_path)
        job["first_frame_name"] = frame_name

    def _update_parent_progress(self, job: dict, phase: str, fraction: float, eta: float | None):
        if not job.get("sequence_id"):
            return
        index = int(job["sequence_index"])
        total = int(job["sequence_total"])
        overall = min(0.98, max(0.0, ((index - 1) + fraction) / total))
        update_sequence(
            job["sequence_id"], status="running", phase=phase,
            current_item=index, progress=overall,
            eta_seconds=round(max(0.0, eta), 1) if eta is not None else None,
        )

    async def run_job(self, job: dict, recovered_prompt: dict | None = None,
                      reference_retries: list | None = None):
        await self._ensure_continuity_frame(job)
        estimated_total = historical_generation_seconds(
            job["mode"], job["duration"], job["engine"], job["steps"],
            job["width"], job["height"], job.get("encoder") or "native",
            job.get("turbo_profile") or "v1",
            job.get("attention_mode") or "standard",
        )
        if estimated_total:
            update_job(job["id"], phase="starting", eta_seconds=round(estimated_total, 1))
            self._update_parent_progress(job, "starting", 0, estimated_total)
        await self.comfy.ensure_started()
        runtime = await self.comfy.runtime_metadata()
        runtime["job"] = {
            "mode": job["mode"], "engine": job["engine"],
            "turbo_profile": job.get("turbo_profile") or "v1",
            "attention_mode": job.get("attention_mode") or "standard",
            "encoder": job.get("encoder") or "native", "duration": job["duration"],
            "steps": job["steps"], "width": job["width"], "height": job["height"],
            "megapixels": job.get("megapixels"), "aspect_ratio": job.get("aspect_ratio"),
            "seed": job.get("seed"), "no_audio": bool(job.get("no_audio")),
        }
        update_job(job["id"], runtime=runtime)
        info = await self.comfy.object_info()
        required = {
            "UNETLoader", "VAELoader", "MiniMaxH3ImageToVideo", "CreateVideo", "SaveVideo",
            "ResolutionSelector", "ComfyMathExpression",
        }
        encoder = job.get("encoder") or "native"
        if encoder == "clipproj":
            required.add("ClipProjLoader")
            required_files = [
                MODELS / "text_encoders" / CLIPPROJ_TEXT_ENCODER,
                MODELS / "clip_projections" / CLIPPROJ_PROJECTION,
                CLIPPROJ_NODE_DIR / "clipproj_nodes.py",
            ]
            missing_files = [str(path) for path in required_files if not path.exists()]
            if missing_files:
                raise RuntimeError("ClipProj is not fully installed: " + ", ".join(missing_files))
        else:
            required.add("CLIPLoader")

        ltx_workflow = None
        if job["engine"] == "ltx":
            # LTX runs its own graph; none of the H3 node classes are involved.
            reference_model = (job.get("ltx_reference_model") or "2.5") if job["mode"] == "reference" else None
            model_files = LTX_REFERENCE_FILES[reference_model] if reference_model else LTX_MODEL_FILES
            missing_files = [
                str(MODELS / folder / name) for folder, name in model_files
                if not (MODELS / folder / name).exists()
            ]
            if missing_files:
                label = f"LTX {reference_model} reference mode" if reference_model else "LTX 2.5"
                raise RuntimeError(f"{label} is not fully installed: " + ", ".join(missing_files))
            if reference_model:
                sheets = json.loads(job.get("reference_images_json") or "[]") or [job.get("input_name")]
                if reference_model == "2.3" and not recovered_prompt:
                    # The 2.3 checkpoint stages about 43 GB of RAM; unload
                    # whatever the previous job left resident first.
                    await self.comfy.free_models()
                ltx_workflow = ltx_reference_workflow(
                    reference_model, job["prompt"], job["duration"], int(job["seed"]),
                    f"h3_bridge_{job['id']}", sheets[0],
                    include_audio=not bool(job.get("no_audio")),
                )
                required = {node["class_type"] for node in ltx_workflow.values()}
            elif job["mode"] == "lip_sync":
                if not job.get("reference_audio_name"):
                    raise RuntimeError("Lip-sync job has no uploaded audio")
                if not job.get("first_frame_name"):
                    raise RuntimeError("LTX 2.5 lip-sync job has no opening image")
                required = ltx_node_classes()
            else:
                first_frame_name = job.get("first_frame_name")
                last_frame_name = job.get("last_frame_name")
                if job["mode"] == "opening":
                    first_frame_name = first_frame_name or job.get("input_name")
                elif job["mode"] == "closing":
                    last_frame_name = last_frame_name or job.get("input_name")
                ltx_workflow = ltx_video_workflow(
                    job["mode"], job["prompt"], job["duration"], int(job["seed"]),
                    f"h3_bridge_{job['id']}", job["width"], job["height"],
                    first_frame_name=first_frame_name, last_frame_name=last_frame_name,
                    include_audio=not bool(job.get("no_audio")),
                    sharp_decode=bool(job.get("ltx_sharp_decode")),
                    calm_sampler=bool(job.get("ltx_calm_sampler")),
                )
                required = {node["class_type"] for node in ltx_workflow.values()}
        elif job["mode"] == "lip_sync":
            required |= {"KSamplerSelect", "LoadAudio", "MiniMaxH3NativeAudioLock"}
            if job["engine"] == "turbo":
                required |= {"MiniMaxH3TurboLoRA", "MiniMaxH3TurboSampler", "MiniMaxH3SigmaShift"}
            elif job["engine"] == "fused_sla":
                required |= {
                    "MiniMaxH3SigmaShift", "MiniMaxChunkFeedForward", "H3SLAAttention",
                    "VAEDecode", "SamplerCustomAdvanced", "BasicGuider",
                    "BasicScheduler", "RandomNoise",
                }
                required_files = [
                    MODELS / "diffusion_models" / FUSED_SLA_MODEL,
                    MODELS / "vae" / FUSED_VIDEO_VAE,
                    MODELS / "vae" / AUDIO_VAE,
                    FUSED_SLA_NODE_DIR / "__init__.py",
                    AUDIOLOCK_NODE_DIR / "__init__.py",
                ]
            elif job["engine"] != "standard":
                raise RuntimeError("Lip-sync supports the Standard, Turbo or Fused SLA engine")
            if (job.get("encoder") or "native") != "native":
                raise RuntimeError("Lip-sync requires the native 32B encoder")
            if not (AUDIOLOCK_NODE_DIR / "__init__.py").exists():
                raise RuntimeError("Native AudioLock node is not installed")
            if job["engine"] == "fused_sla":
                missing_files = [str(path) for path in required_files if not path.exists()]
                if missing_files:
                    raise RuntimeError("Fused H3 lip-sync is not fully installed: " + ", ".join(missing_files))
            if not job.get("reference_audio_name"):
                raise RuntimeError("Lip-sync job has no uploaded audio")
        elif job["mode"] == "reference" and job["engine"] != "fused_sla":
            required.add("MiniMaxH3ReferenceToVideo")
            if job["engine"] == "turbo":
                required |= {"MiniMaxH3TurboLoRA", "MiniMaxH3TurboSampler", "MiniMaxH3SigmaShift"}
                if not (MODELS / "loras" / REF2VA_TURBO_LORA).exists():
                    raise RuntimeError(f"Ref2VA Turbo LoRA is not installed: {REF2VA_TURBO_LORA}")
            elif job["engine"] == "spectrum":
                required |= {"KSamplerSelect", "MiniMaxH3SigmaShift", "SpectrumApplyMiniMaxH3"}
            else:
                required.add("KSamplerSelect")
            if job.get("reference_audio_name"):
                required.add("LoadAudio")
            reference_videos = json.loads(job.get("reference_videos_json") or "[]")
            if reference_videos:
                required |= {"LoadVideo", "GetVideoComponents"}
            ref_path = MODELS / "diffusion_models" / REF2VA_MODEL
            if not ref_path.exists():
                raise RuntimeError(f"Reference model is not installed: {REF2VA_MODEL}")
        elif job["engine"] == "fused_sla":
            variant = job.get("workflow_variant") or ("ref2va" if job["mode"] == "reference" else "direct")
            required |= {
                "KSamplerSelect", "MiniMaxH3SigmaShift", "MiniMaxChunkFeedForward",
                "H3SLAAttention", "VAEDecode", "VAEDecodeAudio",
                "SamplerCustomAdvanced", "BasicGuider", "BasicScheduler", "RandomNoise",
            }
            required_files = [
                MODELS / "diffusion_models" / FUSED_SLA_MODEL,
                MODELS / "vae" / FUSED_VIDEO_VAE,
                FUSED_SLA_NODE_DIR / "__init__.py",
            ]
            workflow_path = FUSED_WORKFLOW_FILES.get(variant)
            if workflow_path is None or not workflow_path.exists():
                required_files.append(workflow_path or MODELS / "missing-official-workflow.json")
            if variant in {"derope", "dyrope"}:
                required |= {
                    "H3JerkOracle", "H3TimeSmear", "H3V2VInit", "H3InjectSchedule",
                    "H3ExactRecover", "H3JerkHeatmap", "H3AudioSmear", "H3AudioRecover",
                    "H3ClockRemap", "H3SaveHoldMap", "VAEEncode", "VAEEncodeAudio",
                }
                required_files.append(FUSED_MAINODES_DIR / "__init__.py")
            if variant in {"ref2va", "ref2va_multiref"}:
                required.add("MiniMaxH3ReferenceToVideo")
            if variant == "ref2va_multiref":
                reference_videos = json.loads(job.get("reference_videos_json") or "[]")
                if reference_videos:
                    required |= {"LoadVideo", "GetVideoComponents"}
                if job.get("reference_audio_name"):
                    required.add("LoadAudio")
            if variant == "dyrope":
                required |= {"H3DyRoPE", "LoraLoaderModelOnly"}
                required_files.append(MODELS / "loras" / FUSED_MOTION_ADAPTER)
            missing_files = [str(path) for path in required_files if not path.exists()]
            if missing_files:
                raise RuntimeError("H3 Fused SLA is not fully installed: " + ", ".join(missing_files))
        elif job["engine"] == "turbo":
            required |= {"MiniMaxH3TurboLoRA", "MiniMaxH3TurboSampler", "MiniMaxH3SigmaShift"}
        elif job["engine"] == "spectrum":
            required |= {"KSamplerSelect", "MiniMaxH3SigmaShift", "SpectrumApplyMiniMaxH3"}
        else:
            required.add("KSamplerSelect")
        attention_mode = job.get("attention_mode") or "standard"
        required |= attention_node_classes(attention_mode)
        missing = sorted(required - set(info))
        if missing:
            raise RuntimeError("ComfyUI is missing node classes: " + ", ".join(missing))

        seed = int(job["seed"])
        prefix = f"h3_bridge_{job['id']}"
        image_name = job.get("input_name")
        workflow_builder = "unknown"
        if ltx_workflow is not None:
            workflow_builder = "ltx_reference_workflow" if job["mode"] == "reference" else "ltx_video_workflow"
            workflow = ltx_workflow
        elif job["engine"] == "ltx":
            workflow_builder = "ltx_lipsync_workflow"
            workflow = ltx_lipsync_workflow(
                job["prompt"], job["duration"], seed, prefix,
                audio_name=job["reference_audio_name"],
                first_frame_name=job["first_frame_name"],
                width=job["width"], height=job["height"],
            )
        elif job["mode"] == "lip_sync":
            if job["engine"] == "fused_sla":
                workflow_builder = "fused_sla_audio_lock_workflow"
                workflow = fused_sla_audio_lock_workflow(
                    job["prompt"], job["duration"], seed, prefix,
                    audio_name=job["reference_audio_name"],
                    first_frame_name=job.get("first_frame_name"),
                    last_frame_name=job.get("last_frame_name"),
                    steps=job["steps"], width=job["width"], height=job["height"],
                    megapixels=job.get("megapixels"), aspect_ratio=job.get("aspect_ratio"),
                )
            else:
                workflow_builder = "native_audio_lock_workflow"
                workflow = native_audio_lock_workflow(
                    job["prompt"], job["duration"], seed, prefix,
                    audio_name=job["reference_audio_name"],
                    first_frame_name=job.get("first_frame_name"),
                    last_frame_name=job.get("last_frame_name"),
                    steps=job["steps"], width=job["width"], height=job["height"],
                    megapixels=job.get("megapixels"), aspect_ratio=job.get("aspect_ratio"),
                    encoder=encoder,
                    turbo=job["engine"] == "turbo", turbo_profile=job.get("turbo_profile") or "v1",
                )
        elif job["mode"] == "reference" and job["engine"] != "fused_sla":
            workflow_builder = "reference_workflow"
            reference_images = json.loads(job.get("reference_images_json") or "[]")
            if not reference_images and image_name:
                reference_images = [image_name]
            workflow = reference_workflow(
                job["prompt"], job["duration"], seed, prefix, reference_images[0] if reference_images else None,
                audio_name=job.get("reference_audio_name"),
                steps=job["steps"], width=job["width"], height=job["height"],
                megapixels=job.get("megapixels"), aspect_ratio=job.get("aspect_ratio"),
                spectrum=job["engine"] == "spectrum", turbo=job["engine"] == "turbo", encoder=encoder,
                image_names=reference_images, video_names=json.loads(job.get("reference_videos_json") or "[]"),
                include_audio=not bool(job.get("no_audio")),
            )
        elif job["engine"] == "fused_sla":
            variant = job.get("workflow_variant") or ("ref2va" if job["mode"] == "reference" else "direct")
            first_frame_name = job.get("first_frame_name")
            last_frame_name = job.get("last_frame_name")
            if job["mode"] == "opening":
                first_frame_name = first_frame_name or image_name
            elif job["mode"] == "closing":
                last_frame_name = last_frame_name or image_name
            reference_images = json.loads(job.get("reference_images_json") or "[]")
            if not reference_images and job["mode"] == "reference" and image_name:
                reference_images = [image_name]
            reference_videos = json.loads(job.get("reference_videos_json") or "[]")
            workflow_builder = f"official_{variant}_workflow"
            workflow = official_fused_workflow(
                variant, job["prompt"], job["duration"], seed, prefix,
                first_frame_name=first_frame_name,
                last_frame_name=last_frame_name,
                reference_image_name=reference_images[0] if reference_images else None,
                reference_image_names=reference_images if variant == "ref2va_multiref" else None,
                reference_video_names=reference_videos if variant == "ref2va_multiref" else None,
                reference_audio_name=job.get("reference_audio_name") if variant == "ref2va_multiref" else None,
                steps=job["steps"], width=job["width"], height=job["height"],
                megapixels=job.get("megapixels"), aspect_ratio=job.get("aspect_ratio"),
                include_audio=not bool(job.get("no_audio")),
            )
        else:
            first_frame_name = job.get("first_frame_name")
            last_frame_name = job.get("last_frame_name")
            if job["mode"] == "opening":
                first_frame_name = first_frame_name or image_name
            elif job["mode"] == "closing":
                last_frame_name = last_frame_name or image_name
            workflow_builder = {
                "turbo": turbo_workflow,
                "spectrum": spectrum_workflow,
                "standard": standard_workflow,
            }[job["engine"]]
            workflow_builder_name = f"{workflow_builder.__name__}"
            workflow_options = {
                "first_frame_name": first_frame_name,
                "last_frame_name": last_frame_name,
                "steps": job["steps"], "width": job["width"], "height": job["height"],
                "megapixels": job.get("megapixels"), "aspect_ratio": job.get("aspect_ratio"),
                "encoder": encoder,
                "include_audio": not bool(job.get("no_audio")),
            }
            if job["engine"] == "turbo":
                workflow_options["turbo_profile"] = job.get("turbo_profile") or "v1"
            workflow = workflow_builder(
                job["prompt"], job["duration"], seed, prefix, **workflow_options,
            )
            workflow_builder = workflow_builder_name

        workflow = apply_attention_mode(workflow, attention_mode)
        runtime["workflow"] = {
            "builder": workflow_builder,
            "attention_mode": attention_mode,
            "node_count": len(workflow),
            "node_classes": sorted({str(node.get("class_type")) for node in workflow.values()}),
        }
        update_job(job["id"], runtime=runtime)

        recovered_prompt = recovered_prompt or {}
        client_id = recovered_prompt.get("client_id") or str(uuid.uuid4())
        prompt_id: str | None = recovered_prompt.get("prompt_id")
        if not prompt_id:
            # A previous bridge process may have submitted this job and died
            # before persisting its prompt ID.  Claim that prompt rather than
            # enqueueing a duplicate.
            existing = await self._claim_existing_prompt(job["id"])
            if existing:
                prompt_id = existing["prompt_id"]
                client_id = existing.get("client_id") or client_id
        started = time.monotonic()
        sampling_started: float | None = None
        ws_ready = asyncio.Event()
        ws_stop = asyncio.Event()

        async def on_comfy_message(message: dict):
            nonlocal sampling_started
            data = message.get("data") or {}
            event_prompt_id = data.get("prompt_id")
            if not prompt_id or event_prompt_id != prompt_id:
                return

            event_type = message.get("type")
            elapsed = max(0.0, time.monotonic() - started)
            historical_eta = max(0.0, estimated_total - elapsed) if estimated_total else None

            if event_type == "execution_start":
                update_job(job["id"], status="running", phase="starting", eta_seconds=historical_eta)
                self._update_parent_progress(job, "starting", 0, historical_eta)
                return

            if event_type == "executing":
                node_id = str(data.get("node")) if data.get("node") is not None else None
                if node_id == SAMPLER_NODE_ID:
                    if sampling_started is None:
                        sampling_started = time.monotonic()
                    update_job(job["id"], status="running", phase="sampling")
                    self._update_parent_progress(job, "sampling", 0, historical_eta)
                elif sampling_started is not None and node_id is not None:
                    update_job(job["id"], status="running", phase="processing", progress=1, eta_seconds=historical_eta)
                    self._update_parent_progress(job, "processing", 1, historical_eta)
                return

            if event_type == "progress":
                try:
                    value = float(data.get("value", 0))
                    total = int(float(data.get("max", 0)))
                except (TypeError, ValueError):
                    return
                if total <= 0:
                    return
                if sampling_started is None:
                    sampling_started = time.monotonic()
                fraction = min(1.0, max(0.0, value / total))
                step = min(total, max(0, int(round(value))))
                sample_elapsed = max(0.0, time.monotonic() - sampling_started)
                step_eta = ((total - value) * sample_elapsed / value) if value > 0 else None
                candidates = [eta for eta in (step_eta, historical_eta) if eta is not None]
                eta = max(candidates) if candidates else None
                update_job(
                    job["id"], status="running", phase="sampling", progress=fraction,
                    step=step, total_steps=total,
                    eta_seconds=round(max(0.0, eta), 1) if eta is not None else None,
                )
                self._update_parent_progress(job, "sampling", fraction, eta)
                return

            if event_type == "executed" and str(data.get("node")) == SAMPLER_NODE_ID:
                update_job(job["id"], status="running", phase="processing", progress=1, eta_seconds=historical_eta)
                self._update_parent_progress(job, "processing", 1, historical_eta)

        monitor_task = asyncio.create_task(
            self.comfy.monitor_progress(client_id, on_comfy_message, ws_ready, ws_stop)
        )
        try:
            try:
                await asyncio.wait_for(ws_ready.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

            if not prompt_id:
                prompt_id = await self.comfy.submit(workflow, client_id)
            update_job(
                job["id"], status="running", phase="starting", prompt_id=prompt_id,
                progress=0, step=0, total_steps=0,
                eta_seconds=round(estimated_total, 1) if estimated_total else None,
            )
            runtime.setdefault("comfy", {})["prompt_id"] = prompt_id
            update_job(job["id"], runtime=runtime)
            peak = {}
            samples = []
            consecutive_history_failures = 0
            consecutive_comfy_down_failures = 0
            total_history_failures = 0
            # Keep polling until Comfy reports completion, the prompt becomes
            # unreachable, or the user cancels the job. Generation time is
            # deliberately unbounded because H3 runtime varies sharply with
            # duration, resolution, VRAM, and model offload behavior.
            while True:
                if job["id"] in self.cancelled:
                    raise RuntimeError("Generation canceled")
                history, history_error = await self._read_comfy_history(prompt_id)
                if history_error is not None:
                    consecutive_history_failures += 1
                    total_history_failures += 1
                    poll_error = self._error_text(history_error)
                    observation = await self._observe_comfy_prompt(prompt_id)
                    queue_state = observation["queue_state"]
                    queue_available = bool(observation["queue_available"])
                    server_ready = bool(observation["server_ready"])
                    process_alive = bool(observation["process_alive"])
                    process_pid = observation["process_pid"]
                    # A prompt visible in either Comfy queue is definitive
                    # evidence that the generation is still owned by Comfy.
                    # A responsive queue, live process, or listening port is
                    # also enough to classify this as transport noise rather
                    # than a terminal generation failure.
                    if queue_state or queue_available or server_ready or process_alive:
                        consecutive_comfy_down_failures = 0
                    else:
                        consecutive_comfy_down_failures += 1
                    runtime.setdefault("comfy", {})["history_poll"] = {
                        "status": "retrying",
                        "consecutive_failures": consecutive_history_failures,
                        "server_ready": server_ready,
                        "queue_available": queue_available,
                        "queue_state": queue_state,
                        "queue_error": observation["queue_error"],
                        "process_alive": process_alive,
                        "process_pid": process_pid,
                        "consecutive_comfy_down_failures": consecutive_comfy_down_failures,
                        "total_failures": total_history_failures,
                        "last_error": poll_error,
                        "last_attempt_at": now_iso(),
                    }
                    # Do not fail solely because /history and /system_stats
                    # timed out.  Only terminalize after the queue endpoint is
                    # also unavailable and neither the configured process nor
                    # its listening port can be found.
                    if not queue_available and not server_ready and not process_alive and consecutive_comfy_down_failures >= 3:
                        update_job(job["id"], runtime=runtime)
                        raise RuntimeError(
                            "ComfyUI process and prompt became unreachable while this generation was running"
                        )
                    if consecutive_history_failures == 1 or consecutive_history_failures % 5 == 0:
                        update_job(
                            job["id"],
                            status="running",
                            phase="processing" if sampling_started is not None else "starting",
                            runtime=runtime,
                            error=None,
                        )
                    await asyncio.sleep(5)
                    continue

                if consecutive_history_failures:
                    runtime.setdefault("comfy", {})["history_poll"] = {
                        "status": "recovered",
                        "consecutive_failures": consecutive_history_failures,
                        "server_ready": True,
                        "consecutive_comfy_down_failures": 0,
                        "total_failures": total_history_failures,
                        "recovered_at": now_iso(),
                    }
                    update_job(job["id"], runtime=runtime, error=None)
                    consecutive_history_failures = 0
                    consecutive_comfy_down_failures = 0

                sample = gpu_sample()
                if sample:
                    samples.append({"at_seconds": round(time.monotonic() - started, 1), **sample})
                    if sample.get("vram_used_mib", 0) > peak.get("vram_used_mib", 0):
                        peak = sample
                if history:
                    status = history.get("status", {})
                    if status.get("status_str") == "error" or not status.get("completed", False):
                        messages = status.get("messages", [])
                        errors = [m for m in messages if m and m[0] == "execution_error"]
                        if errors:
                            raise RuntimeError("ComfyUI execution error: " + json.dumps(errors[-1][1], ensure_ascii=False)[:7500])
                    if status.get("completed"):
                        break
                await asyncio.sleep(5)

            elapsed = time.monotonic() - started
            eta = max(0.0, estimated_total - elapsed) if estimated_total else None
            update_job(
                job["id"], status="verifying", phase="verifying", progress=1,
                eta_seconds=round(eta, 1) if eta is not None else None,
            )
            self._update_parent_progress(job, "verifying", 1, eta)
            video = None
            # SaveVideo can finish just after the completed history response;
            # give the filesystem a short grace period before declaring the
            # output missing.
            for _ in range(12):
                video = find_video(
                    prefix,
                    exact_prefix=job["engine"] == "fused_sla" and (job.get("workflow_variant") or "direct") in {"derope", "dyrope"},
                )
                if video:
                    break
                await asyncio.sleep(5)
            if not video:
                raise RuntimeError("ComfyUI completed but no MP4 was found")
            probe = await asyncio.to_thread(
                media_probe, video, require_audio=not bool(job.get("no_audio"))
            )
            reference_check = None
            if job["engine"] == "ltx" and job["mode"] == "reference":
                sheets = json.loads(job.get("reference_images_json") or "[]") or [job.get("input_name")]
                reference_check = await asyncio.to_thread(sheet_frames, video, INPUT / sheets[0])
                if reference_check["shows_sheet"]:
                    raise ReferenceSheetShown(video, reference_check)

            if job.get("sequence_id") and job["sequence_index"] < job["sequence_total"]:
                frame_name = f"sequence_{job['sequence_id']}_shot{job['sequence_index']:02d}_last.png"
                frame_path = INPUT / frame_name
                await asyncio.to_thread(
                    extract_last_frame, video, frame_path,
                    int(job["width"]), int(job["height"]),
                )
                with connect() as db:
                    next_job = db.execute(
                        "SELECT id FROM jobs WHERE sequence_id=? AND sequence_index=?",
                        (job["sequence_id"], job["sequence_index"] + 1),
                    ).fetchone()
                    if not next_job:
                        raise RuntimeError("The next sequence shot is missing")
                    now = now_iso()
                    db.execute(
                        """UPDATE jobs SET first_frame_path=?,first_frame_name=?,updated_at=?
                           WHERE id=?""",
                        (str(frame_path), frame_name, now, next_job["id"]),
                    )
                    db.execute(
                        """UPDATE sequence_items SET continuity_frame_path=?
                           WHERE sequence_id=? AND item_index=?""",
                        (str(frame_path), job["sequence_id"], job["sequence_index"]),
                    )

            elapsed = round(time.monotonic() - started, 1)
            metrics = {
                "generation_seconds": elapsed, "peak_gpu": peak,
                "samples": samples[-120:], "ffprobe": probe,
            }
            if reference_check is not None:
                metrics["reference_check"] = reference_check
                metrics["reference_retries"] = reference_retries or []
            update_job(
                job["id"], status="completed", phase="completed", progress=1,
                eta_seconds=0, output_path=str(video), metrics=metrics,
                finished_at=now_iso(), error=None,
            )
            organized = await asyncio.to_thread(finalize_completed_asset, "job", job["id"])
            if organized:
                video = organized

            if job.get("sequence_id"):
                with connect() as db:
                    db.execute(
                        """UPDATE sequence_items SET status='completed',clip_path=?
                           WHERE sequence_id=? AND item_index=?""",
                        (str(video), job["sequence_id"], job["sequence_index"]),
                    )
                index = int(job["sequence_index"])
                total = int(job["sequence_total"])
                update_sequence(
                    job["sequence_id"], status="running", phase="between_shots",
                    current_item=index, progress=min(0.98, index / total), eta_seconds=None,
                )
                if index == total:
                    try:
                        await self.assemble_sequence(job["sequence_id"])
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        # The final child MP4 has already passed validation.
                        # Keep it completed even if only final assembly fails.
                        update_sequence(
                            job["sequence_id"], status="failed", phase="failed",
                            eta_seconds=None, error=str(exc)[:8000], finished_at=now_iso(),
                        )
        finally:
            ws_stop.set()
            try:
                await asyncio.wait_for(monitor_task, timeout=3)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                monitor_task.cancel()
                await asyncio.gather(monitor_task, return_exceptions=True)

    async def assemble_sequence(self, sequence_id: str):
        sequence = get_sequence(sequence_id, public=False)
        if not sequence:
            raise RuntimeError("Sequence not found")
        with connect() as db:
            rows = db.execute(
                """
                SELECT i.item_index,i.clip_path,i.job_id,i.source_job_id,i.source_sequence_id,
                       j.output_path AS job_output_path
                FROM sequence_items i
                LEFT JOIN jobs j ON j.id=i.job_id
                WHERE i.sequence_id=? ORDER BY i.item_index
                """,
                (sequence_id,),
            ).fetchall()
        clips: list[Path] = []
        path_updates: list[tuple[str, int, str]] = []
        for row in rows:
            current: Path | None = None
            if row["job_id"]:
                current = resolve_asset_path("job", row["job_id"])
            if not current and row["source_job_id"]:
                current = resolve_asset_path("job", row["source_job_id"])
            if not current and row["source_sequence_id"]:
                current = resolve_asset_path("sequence", row["source_sequence_id"])
            if not current and row["clip_path"]:
                candidate = Path(row["clip_path"])
                current = candidate if candidate.is_file() else None
            if current:
                clips.append(current)
                if str(current) != str(row["clip_path"] or ""):
                    path_updates.append((str(current), row["item_index"], sequence_id))
        if path_updates:
            with connect() as db:
                db.executemany(
                    "UPDATE sequence_items SET clip_path=? WHERE item_index=? AND sequence_id=?",
                    path_updates,
                )
        if len(clips) != int(sequence["total_items"]):
            raise RuntimeError("Not every selected clip is available for assembly")
        if any(not path.exists() for path in clips):
            raise RuntimeError("One or more source clips are missing from disk")

        update_sequence(
            sequence_id, status="verifying", phase="assembling", progress=0.99,
            current_item=sequence["total_items"], eta_seconds=None,
        )
        output_dir = SEQUENCES / sequence_id
        output_name = "connected-final.mp4" if sequence["kind"] == "connected" else "history-joined.mp4"
        output = output_dir / output_name
        started = time.monotonic()
        result = await asyncio.to_thread(assemble_clips, clips, output)
        metrics = {
            "assembly_seconds": round(time.monotonic() - started, 1),
            "source_count": result["source_count"],
            "source_durations": result["source_durations"],
            "ffprobe": result["ffprobe"],
        }
        update_sequence(
            sequence_id, status="completed", phase="completed", progress=1,
            eta_seconds=0, output_path=str(output), metrics=metrics,
            error=None, finished_at=now_iso(),
        )
        await asyncio.to_thread(finalize_completed_asset, "sequence", sequence_id)
