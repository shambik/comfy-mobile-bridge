import asyncio
import json
import time
import uuid
from pathlib import Path

from .comfy import ComfyClient, find_video, gpu_sample, media_probe
from .config import (AUDIOLOCK_NODE_DIR, CLIPPROJ_NODE_DIR, CLIPPROJ_PROJECTION,
                     CLIPPROJ_TEXT_ENCODER, INPUT, MODELS, REF2VA_MODEL,
                     REF2VA_TURBO_LORA,
                     SEQUENCES)
from .db import (connect, get_job, get_sequence, historical_generation_seconds,
                 now_iso, update_job, update_sequence)
from .media import assemble_clips, extract_last_frame
from .library import finalize_completed_asset
from .workflows import (native_audio_lock_workflow, reference_workflow, spectrum_workflow,
                        standard_workflow, turbo_workflow)


SAMPLER_NODE_ID = "14"
ACTIVE_STATUSES = ("starting", "running", "verifying")


class QueueWorker:
    def __init__(self):
        self.comfy = ComfyClient()
        self.task: asyncio.Task | None = None
        self.wake = asyncio.Event()
        self.stopping = False
        self.current_job: str | None = None
        self.current_sequence: str | None = None
        self.cancelled: set[str] = set()

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
            await self.comfy.cancel(job.get("prompt_id"))
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
            await self.comfy.cancel(current.get("prompt_id") if current else None)
        return True

    async def reconcile(self):
        with connect() as db:
            rows = db.execute(
                "SELECT id,prompt_id FROM jobs WHERE status IN ('starting','running','verifying')"
            ).fetchall()
        for row in rows:
            history = None
            try:
                history = await self.comfy.history(row["prompt_id"]) if row["prompt_id"] and await self.comfy.ready() else None
            except Exception:
                pass
            if history and history.get("status", {}).get("completed"):
                error = "Recovered after app restart; previous result will not be duplicated automatically"
            else:
                error = "Requeued after app restart"
            update_job(
                row["id"], status="queued", phase="queued", prompt_id=None,
                progress=0, step=0, total_steps=0, eta_seconds=None, error=error,
            )

        with connect() as db:
            now = now_iso()
            db.execute(
                """UPDATE sequences SET status='queued',phase='queued',eta_seconds=NULL,
                   updated_at=? WHERE status IN ('starting','running','verifying')""",
                (now,),
            )

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
                    update_sequence(
                        record["id"], status="failed", phase="failed",
                        eta_seconds=None, error=str(exc)[:8000], finished_at=now_iso(),
                    )
                finally:
                    self.current_sequence = None
                continue

            job = record
            self.current_job = job["id"]
            self.current_sequence = job.get("sequence_id")
            try:
                await self.run_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                status = "canceled" if job["id"] in self.cancelled else "failed"
                error = str(exc)[:8000]
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
                """SELECT j.output_path FROM jobs j
                   WHERE j.sequence_id=? AND j.sequence_index=? AND j.status='completed'""",
                (job["sequence_id"], job["sequence_index"] - 1),
            ).fetchone()
        if not previous or not previous["output_path"]:
            raise RuntimeError("The previous sequence shot has no validated output")

        frame_name = f"sequence_{job['sequence_id']}_shot{job['sequence_index'] - 1:02d}_last.png"
        frame_path = INPUT / frame_name
        await asyncio.to_thread(
            extract_last_frame, Path(previous["output_path"]), frame_path,
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

    async def run_job(self, job: dict):
        await self._ensure_continuity_frame(job)
        estimated_total = historical_generation_seconds(
            job["mode"], job["duration"], job["engine"], job["steps"],
            job["width"], job["height"], job.get("encoder") or "native",
            job.get("turbo_profile") or "v1",
        )
        if estimated_total:
            update_job(job["id"], phase="starting", eta_seconds=round(estimated_total, 1))
            self._update_parent_progress(job, "starting", 0, estimated_total)
        await self.comfy.ensure_started()
        runtime = await self.comfy.runtime_metadata()
        runtime["job"] = {
            "mode": job["mode"], "engine": job["engine"],
            "turbo_profile": job.get("turbo_profile") or "v1",
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

        if job["mode"] == "lip_sync":
            required |= {"KSamplerSelect", "LoadAudio", "MiniMaxH3NativeAudioLock"}
            if job["engine"] == "turbo":
                required |= {"MiniMaxH3TurboLoRA", "MiniMaxH3TurboSampler", "MiniMaxH3SigmaShift"}
            elif job["engine"] != "standard":
                raise RuntimeError("Lip-sync supports only the Standard or Turbo engine")
            if (job.get("encoder") or "native") != "native":
                raise RuntimeError("Lip-sync requires the native 32B encoder")
            if not (AUDIOLOCK_NODE_DIR / "__init__.py").exists():
                raise RuntimeError("Native AudioLock node is not installed")
            if not job.get("reference_audio_name"):
                raise RuntimeError("Lip-sync job has no uploaded audio")
        elif job["mode"] == "reference":
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
        elif job["engine"] == "turbo":
            required |= {"MiniMaxH3TurboLoRA", "MiniMaxH3TurboSampler", "MiniMaxH3SigmaShift"}
        elif job["engine"] == "spectrum":
            required |= {"KSamplerSelect", "MiniMaxH3SigmaShift", "SpectrumApplyMiniMaxH3"}
        else:
            required.add("KSamplerSelect")
        missing = sorted(required - set(info))
        if missing:
            raise RuntimeError("ComfyUI is missing node classes: " + ", ".join(missing))

        seed = int(job["seed"])
        prefix = f"h3_bridge_{job['id']}"
        image_name = job.get("input_name")
        workflow_builder = "unknown"
        if job["mode"] == "lip_sync":
            workflow_builder = "native_audio_lock_workflow"
            workflow = native_audio_lock_workflow(
                job["prompt"], job["duration"], seed, prefix,
                audio_name=job["reference_audio_name"],
                first_frame_name=job.get("first_frame_name"),
                steps=job["steps"], width=job["width"], height=job["height"],
                megapixels=job.get("megapixels"), aspect_ratio=job.get("aspect_ratio"),
                encoder=encoder,
                turbo=job["engine"] == "turbo", turbo_profile=job.get("turbo_profile") or "v1",
            )
        elif job["mode"] == "reference":
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

        runtime["workflow"] = {
            "builder": workflow_builder,
            "node_count": len(workflow),
            "node_classes": sorted({str(node.get("class_type")) for node in workflow.values()}),
        }
        update_job(job["id"], runtime=runtime)

        client_id = str(uuid.uuid4())
        prompt_id: str | None = None
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
            while True:
                if job["id"] in self.cancelled:
                    raise RuntimeError("Generation canceled")
                history = await self.comfy.history(prompt_id)
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
            video = find_video(prefix)
            if not video:
                raise RuntimeError("ComfyUI completed but no MP4 was found")
            probe = await asyncio.to_thread(
                media_probe, video, require_audio=not bool(job.get("no_audio"))
            )

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
                SELECT i.item_index,COALESCE(i.clip_path,j.output_path) AS clip_path
                FROM sequence_items i
                LEFT JOIN jobs j ON j.id=i.job_id
                WHERE i.sequence_id=? ORDER BY i.item_index
                """,
                (sequence_id,),
            ).fetchall()
        clips = [Path(row["clip_path"]) for row in rows if row["clip_path"]]
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
