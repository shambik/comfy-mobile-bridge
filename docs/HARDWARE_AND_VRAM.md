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
| Frame size cap | 2,000,000 pixels | `backend/generation.py` (`MAX_PIXELS`), the `jobs` table CHECK in `backend/db.py`, and the UI | Larger frames ran out of memory or became very slow |
| H3 video models | INT8 "convrot" FL2VA / Ref2VA / Fused SLA, INT8 video VAE | `backend/config.py` | The BF16 versions do not fit in 10 GB |
| H3 text encoder | Qwen3-VL 32B in NVFP4 (4-bit); optional ClipProj 4B FP8 | `backend/config.py`; ClipProj is a per-job choice | The 32B encoder is the largest model; ClipProj trades accuracy for memory |
| Encoder loading | `dynamic` (offloaded between uses); `resident` only where the reference node requires it | `backend/workflows.py` (`_clip_loader`) | Frees VRAM for sampling |
| Turbo LoRA | `low_vram: True` | `backend/workflows.py` | Applies the LoRA without a full extra copy of the weights |
| Fused SLA graphs | MiniMax's official `*_lowvram.api.json` graphs | `backend/config.py` (`FUSED_WORKFLOW_FILES`) | The official low-VRAM variants |
| Attention speed-ups | Sage and/or sparse (SLA) attention, per job | `backend/generation.py` (`ATTENTION_MODES`) | Faster and lighter attention on this card |
| LTX models | LTX 2.5 transformer and Gemma encoder in INT8 | `backend/config.py` | BF16 does not fit |
| LTX sizes | Balanced 896×1600, High 1056×1888 (trimmed to fit 2.0 MP; the lab ran 1088×1920) | `backend/generation.py` (`LTX_SIZES`) | One full-resolution pass within the cap |
| LTX default decode | `VAEDecodeTiled` 512 px tiles, 64-frame chunks | `backend/workflows.py` | Fits in memory, but the chunk joins soften frames every 2 s |
| LTX "sharp decode" | `LTXVTiledVAEDecode`, 4×2 tiles up to 121 frames at ≤1600×896, else 6×4 | `backend/workflows.py` (`_ltx_seam_free_decode`) | Seam-free. Peaks measured on the 3080: 7.9 GB (4×2, 1600×896, 5 s) and 6.6 GB (6×4, 1536×896, 10 s) |
| LTX reference size | Fixed 768×448 grid, upscaled ×2 to 1536×896, landscape, up to 5 s | `backend/generation.py` (`LTX_REFERENCE_*`) | **Not a VRAM limit**: the Ingredients LoRA was trained only at 768×448; other sizes failed in tests |
| LTX 2.3 reference | Unload all models before the job | `backend/worker.py` | The 2.3 checkpoint stages about 43 GB of RAM |
| Idle unload | Unload models after 5 minutes without jobs | `backend/worker.py` (`free_models` on idle) | Gives the memory back to the rest of the PC |
| Load warning in the UI | Relative to 736×416, 5 s, 4 steps on Turbo | `src/main.tsx` (`relativeLoad`) | Calibrated on the 3080; asks for confirmation on heavy jobs |

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
