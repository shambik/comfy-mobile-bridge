# Hardware and VRAM tuning

This app was built and tuned on **one machine: an NVIDIA RTX 3080 with 10 GB
of VRAM, 64 GB of system RAM, Windows 10**. Every default below was chosen so
that video jobs fit in 10 GB without crashing, and most were measured on that
card. They are safe, not optimal: a card with more VRAM can run faster, larger,
or at higher quality by relaxing them. Nothing here was tested on other GPUs.

If you are a person, read "What the 10 GB tuning means for you". If you are an
agent asked to adapt the app to different hardware, follow "Moving to a bigger
card" and "How to verify a change" exactly.

## What the 10 GB tuning means for you

- **One job at a time.** The worker runs one video job at a time. Image Lab
  runs and H3 stills use the same ComfyUI on port 8190 and are refused while a
  video job is running, so the GPU never runs two jobs at once.
- **One ComfyUI only.** Two ComfyUI processes cannot take GPU memory from each
  other, so a second instance (a lab copy, an old image server) slows or breaks
  the app's jobs. Stop extra instances before generating.
- **Size limit of 2.0 MP per frame** for every engine.
- **Quantized models.** H3 and LTX run INT8, FP8 or 4-bit weights so they fit;
  this costs a little quality compared with BF16 weights.
- **Other GPU programs hurt.** Games (the app warns when Fortnite is running),
  browsers with video, or another ComfyUI can make a job slow or look stuck.
- **System RAM matters too.** LTX 2.3 reference mode stages about 43 GB of RAM;
  on a 32 GB machine it is likely to fail.

## Where each low-VRAM choice lives

| Setting | Value on the 3080 | File | Why |
| --- | --- | --- | --- |
| ComfyUI memory flags | `--reserve-vram 0.9 --enable-dynamic-vram --async-offload 2` | `backend/comfy.py` (launch arguments) | Keeps 0.9 GB free for Windows and the desktop; lets ComfyUI stream weights between RAM and VRAM. These are the flags that behaved well in direct runs on this card (`docs/H3_RUNTIME_NOTES.md`) |
| Steady Memory node on Pika Sage jobs | async offload off and GPU waits in attention, for that job's sampling only | `backend/workflows.py` (`apply_steady_memory`), `custom_nodes/ComfyUI-H3-SteadyMemory` | Keeps Pika Sage near 9.2 GB instead of 9.7; above about 9.7 GB the card spills and runs 2-4x slower (see "H3 stall, other GPU apps") |
| Frame size cap | 2,000,000 pixels | `backend/generation.py` (`MAX_PIXELS`), the `jobs` table CHECK in `backend/db.py`, and the UI | Larger frames ran out of memory or became very slow |
| H3 video models | INT8 "convrot" FL2VA / Ref2VA / Fused SLA, INT8 video VAE | `backend/config.py` | The BF16 versions do not fit in 10 GB |
| H3 text encoder | Qwen3-VL 32B in NVFP4 (4-bit); optional ClipProj 4B FP8 | `backend/config.py`; ClipProj is a per-job choice | The 32B encoder is the largest model; ClipProj trades accuracy for memory |
| Encoder loading | `dynamic` (offloaded between uses); `resident` only where the reference node requires it | `backend/workflows.py` (`_clip_loader`) | Frees VRAM for sampling |
| Turbo LoRA | `low_vram: True` | `backend/workflows.py` | Applies the LoRA without a full extra copy of the weights |
| Fused SLA graphs | MiniMax's official `*_lowvram.api.json` graphs | `backend/config.py` (`FUSED_WORKFLOW_FILES`) | The official low-VRAM variants |
| Attention speed-ups | Sage and/or sparse (SLA) attention, per job | `backend/generation.py` (`ATTENTION_MODES`) | Faster and lighter attention on this card |
| Int8 attention (opt-in) | ComfyUI's built-in Comfy Kitchen INT8 attention (`ModelAttentionBackend`), per job; on Turbo also the INT8 decode VAE | `backend/generation.py` (`INT8_ATTENTION_TESTED`), `backend/workflows.py` | Fastest tested attention on this card (Ampere has INT8 tensor cores); same GPU peak as standard. Check `comfy_kitchen.int8_attention_is_available()` on another GPU |
| LTX models | LTX 2.5 transformer and Gemma encoder in INT8 | `backend/config.py` | BF16 does not fit |
| LTX sizes | Balanced 896×1600, High 1056×1888 (trimmed to fit 2.0 MP; the lab ran 1088×1920) | `backend/generation.py` (`LTX_SIZES`) | One full-resolution pass within the cap |
| LTX default decode | `VAEDecodeTiled` 512 px tiles, 64-frame chunks | `backend/workflows.py` | Fits in memory, but the chunk joins soften frames every 2 s |
| LTX "sharp decode" | `LTXVTiledVAEDecode`, 4×2 tiles up to 121 frames at ≤1600×896, else 6×4 | `backend/workflows.py` (`_ltx_seam_free_decode`) | Seam-free. Peaks measured on the 3080: 7.9 GB (4×2, 1600×896, 5 s) and 6.6 GB (6×4, 1536×896, 10 s) |
| LTX reference size | Fixed 768×448 grid, upscaled ×2 to 1536×896, landscape, up to 5 s | `backend/generation.py` (`LTX_REFERENCE_*`) | **Not a VRAM limit**: the Ingredients LoRA was trained only at 768×448; other sizes failed in tests |
| Upscale / motion smoothing jobs | RIFE and Real-ESRGAN sources up to 1920×1080, FILM up to 1632×928; 150 frames (Lanczos 300); targets up to 2560×1440; whole clip in one pass | `backend/post_process.py` (`MAX_SOURCE`), the `jobs` table CHECK for engine `post` in `backend/db.py` | FILM peaked at 9.77 GB on 1080p and spilled past 10 GB at 2560×1456; longer clips need frame windows that were only tested in the lab |
| LTX 2.3 reference | Unload all models before the job | `backend/worker.py` | The 2.3 checkpoint stages about 43 GB of RAM |
| Idle unload | Unload models after 5 minutes without jobs | `backend/worker.py` (`free_models` on idle) | Gives the memory back to the rest of the PC |
| Engine-switch unload | Unload all models when the next job's engine family (LTX, H3, Fused SLA) differs from the last one, then wait 2 s before submitting | `backend/worker.py` (`_unload_other_engine_family`) | ComfyUI keeps every loaded model in RAM: after LTX and H3 jobs it held 88.9 GB committed on a 64 GB PC, and one H3 first step took 6:37 instead of about 2:15 (2026-10-27). The wait is needed because ComfyUI applies `/free` between prompts. Costs one model reload per switch |
| Load warning in the UI | Relative to 736×416, 5 s, 4 steps on Turbo | `src/main.tsx` (`relativeLoad`) | Calibrated on the 3080; asks for confirmation on heavy jobs |

`comfy.memory_mode` in local configuration defaults to `dynamic`, preserving
the launch flags above. The optional `legacy` recovery mode selects
`--disable-dynamic-vram --disable-async-offload --disable-pinned-memory` while
retaining the 0.9 GB reserve. This bypasses dynamic prefetch and CUDA host
registration when stack diagnostics show those calls blocking. It needs a
ComfyUI restart and may be slower. Disabling those paths does not reduce video
activation memory: an eight-second H3 Fused SLA 1.5 MP shot still spilled about
4 GB into shared GPU memory and advanced too slowly in the October 23 lab.
The five-second production recovery is tracked in
`docs/ltx25_test/TUMBLE_PUFFS_MINIMAX.md`; do not treat the legacy option as proof
that long, high-resolution clips fit this GPU.

Measured on the 3080 (5 s clips unless noted): H3 Turbo v4 at 0.7 MP, 6 steps
used about 7.35 GB. LTX 2.5 at 1600×896 peaked at 9.4–9.6 GB; LTX at 10 s peaked
at 9.2–9.8 GB. The worker records each job's peak in its metrics (see below).

## Moving to a bigger card (checklist for agents)

Do these in order, one change at a time, and verify each with the procedure in
the next section. Never change the app's ComfyUI or its Python environment
directly: test in a separate copy first, as the project rules require.

1. **Measure before changing anything.** Run the same jobs (same prompt, image,
   seed, duration, size, steps) on the new card with the current settings and
   record time and peak VRAM. These are your baselines.
2. **ComfyUI memory flags** (`backend/comfy.py`). With 16 GB or more, try
   removing `--enable-dynamic-vram` and `--async-offload 2`, then try
   `--highvram`. Lower `--reserve-vram` only if the desktop stays responsive.
   Keep whichever is fastest without errors.
3. **Decode tiling** (`backend/workflows.py`). Fewer tiles are faster: try
   2×1 or 1×1 tiles in `_ltx_seam_free_decode` and larger `VAEDecodeTiled`
   tiles or chunks. On a big enough card, "sharp decode" could become the
   default (it removes the 2-second blur).
4. **Frame size cap.** Raising `MAX_PIXELS` needs three coordinated changes:
   `backend/generation.py`, the `width * height <= 2000000` CHECK in
   `backend/db.py` (SQLite cannot alter a CHECK; the existing table-rebuild
   path in `init_db` must be triggered, and the database backed up first), and
   the UI limits in `src/main.tsx`. Then the LTX `High` sizes can return to the
   tested 1088×1920 or go higher.
5. **Model precision.** With 24 GB or more, BF16 versions of the LTX
   transformer, the Gemma encoder or the H3 VAE may fit and improve quality.
   This means new entries in the manifests (with sizes and SHA-256) and new
   names in `backend/config.py`; compare quality side by side before switching.
6. **Encoder loading and ClipProj.** With spare VRAM, `resident` text encoders
   avoid reloading between jobs; ClipProj (the memory saver) matters less.
7. **Official non-low-VRAM graphs.** The Fused SLA engine uses the
   `*_lowvram` official graphs; check whether higher-memory official variants
   exist and test them.
8. **Clip length.** LTX accepts 1–10 s and H3 up to 60 s via sequences. Longer
   single LTX clips are a memory question first; reference mode stays at 5 s
   regardless (a model limit, see above).
9. **UI load warning.** Re-calibrate `relativeLoad` thresholds in
   `src/main.tsx` so "heavy" still means heavy on the new card.
10. **Attention modes.** On newer GPUs, check which SageAttention build and
    kernels apply before trusting the Sage speed-ups measured on the 3080.

For a smaller card (8 GB): expect to lower sizes, prefer ClipProj, keep
"sharp decode" off for long clips, and avoid LTX 2.3 reference. Untested.

## How to verify a change

1. Use identical inputs and seeds before and after the change.
2. Read the job's metrics: `generation_seconds` and `peak_gpu.vram_used_mib`,
   stored in the job's `metrics_json` column (`state/jobs.sqlite3`).
3. Check the file: `ffprobe` (resolution, frame count, audio stream) and a full
   FFmpeg decode.
4. Compare the videos by eye, and for decode or sampler changes check for soft
   frames at 1-second marks and frame-to-frame flicker.
5. Run the test suite and `npm run build`. A unit test never proves a GPU
   result.
6. Record the new numbers in this file with the card name.

## Job diagnostics

Every generation job stores its evidence in `metrics_json` (`state/jobs.sqlite3`).
It is saved when the job is submitted, every 30 seconds while it runs, and at the
end, so stuck and failed jobs keep it too. The public job API never returns
`diagnostics` or `samples`.

| Field | Contents |
| --- | --- |
| `runtime_json.comfy.memory_mode` | `dynamic`, `legacy` or `default`, read from ComfyUI's launch arguments |
| `diagnostics.graph` | The exact graph sent to ComfyUI: every node with its input values; links are `[node id, output index]` |
| `diagnostics.host_at_start` | GPU name, driver, PCIe link and power limit; RAM, commit charge and page file; Windows power plan; the ten processes holding the most RAM |
| `diagnostics.timeline.nodes` | Each node as it starts executing, in seconds since the job started; `cached_nodes` lists nodes ComfyUI reused |
| `diagnostics.timeline.step_seconds` | Duration of each progress step per node; the sampler (node `14` in H3 graphs) shows slow first steps directly |
| `diagnostics.comfy_log` | ComfyUI log lines for this job about model loading, offload or staging, memory warnings and errors |
| `samples` | One sample every 5 seconds: VRAM, GPU load, power, SM clock, memory-bus load, PCIe generation, free RAM, commit charge, CPU load, and the ComfyUI process's working set, private memory, CPU time and page faults. The first 10 minutes and the last 50 are kept |

A slow first step with low GPU power, low free RAM and fast-rising
`comfy_page_faults` means offloaded weights are being read back from the page
file. Compare `memory_mode` before blaming the model: on the 3080, `legacy`
took about 35% longer than `dynamic` for the same 1.5 MP H3 Turbo shots.

## Singularity, Pika and the T8 node pack

Singularity's T8 tiers use `comfyui-minimax-h3-audio-T8`. On ComfyUI 0.44 it runs at `3a23f33`, where all 780 node classes load. On 0.33 it had to stay at `e576eba`, because newer versions need nodes that 0.33 lacks.
The notes below were measured on 0.33.
ComfyUI logs "IMPORT FAILED" for it (`io.Hidden.execution_list`), yet its 549 node classes load, including the Dual-Clock
sampler. Proof it does not change existing flows (2026-11-01, `h3-skinlab/tests/ab_t8.py`): four production jobs re-rendered
with the same inputs and seeds came out with identical full-size video and audio hashes, with equal times once warm and no
core sampler or scheduler definition changed. Peak VRAM varies by 300-400 MB with what else is open on the PC, with or
without T8. Pika 6-step and the Singularity App flow tier use no T8 node; Pika Turbo 4-step uses the T8 Dual-Clock sampler
(same size and Steady Memory setting as Pika Sage, peaks 9.19-9.59 GB in the lab). Both engines tile the decode at 512/64/64/16.
Singularity and Pika count as their own model families, so ComfyUI unloads when switching to or from them.

**H3 stall, other GPU apps, and the Steady Memory node.** An H3 job on this card can stay at 100% GPU util but 130-260 W
(healthy is about 320-335 W) and 0-4% memory util, with 6-18 GB/s over PCIe, while the output stays identical. Steps take
2-4x longer. It tracks VRAM level: clean runs stayed under about 9.6 GB, stalls started from about 9.7-9.75 GB (the
Windows budget for the card is about 8.7 GB, so above it the driver pages buffers to shared memory). The same weight copy
then took 0.25 s or 7-8 s depending only on its address.

The main trigger is other programs on the GPU. On 2026-11-03 the unchanged production app stalled on a Turbo first + last
job that took 807 s on 2026-10-28 (about 422 s per step, 9.70 GB); with Epic Games Launcher, Chrome, Telegram and other
unneeded programs closed, the same job and seed ran 810 s at 336 W, peaking at 9.50 GB, with bit-identical output. Before a
long batch, close games, launchers and browsers; check `nvidia-smi` shows well under 1 GB used with ComfyUI stopped.

Pika with Sage peaks right at the edge even on a clean PC (9.64-9.72 GB without help), so it gets `ComfyUI-H3-SteadyMemory`
(local node, `scripts/install-steady-memory.ps1`): for that job's sampling it turns off async weight offload and waits for
the GPU around H3's attention kernel, after each modulation step, and after each attention and MLP block. Without waits,
PyTorch cannot reuse a temporary buffer until the GPU is done with it, so its pool grows. The worker adds it after the
Sage node on Pika Sage jobs only (`steady_memory_needed` in `backend/workflows.py`). Measured 2026-11-03 on a clean PC,
same seeds: with the node Pika Sage first + last 516 s and opening 468 s at 9.17-9.29 GB; without it 525 s and 491-501 s
at 9.64-9.72 GB. Singularity God peaks at only 9.19 GB and is faster without the node (572 s against 633 s), with the same
decoded video and audio either way, so Singularity does not get it. LTX and Turbo do not get it either.

Tried without effect on the stall: unloading before sampling, the fp16 VAE, `--reserve-vram 1.5` and `3`,
`--disable-nvml-pressure`, `empty_cache` on slowdown, a preallocated pool, a 0.2 GB VBAR cap, async offload off alone, and
waits only after each block. Sparse attention stays refused for Pika opening and first + last: it was not retested.

