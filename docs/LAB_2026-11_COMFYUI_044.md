# Lab test and upgrade: ComfyUI 0.44 on PyTorch 2.11 (November 2026)

**Decision: adopted on 2026-11-04.** The app moved from ComfyUI 0.33 (`8b2d2917`)
to ComfyUI 0.44 (`56f179f6`). PyTorch stays at 2.11 cu130, because Nunchaku
has no build for anything newer, and the Image Lab needs Nunchaku.

The October lab (`LAB_2026-10_COMFYUI_AND_TURBO_LORAS.md`) rejected 0.35.2
and 0.42.1. This test found 0.44 faster or equal on every app flow, with
output the user judged the same.

## How it was tested

The lab was a separate copy (`D:\h3-comfy044`) with its own ComfyUI on port
8197, its own venv and its own bridge on 8798. It read the app's models
through `extra_model_paths.yaml`. The app was not touched.

For each flow, the lab took one finished app job and replayed it with the
same inputs, settings and seed. The comparison covered generation seconds
from the job metrics, the video and audio stream hashes, PSNR on grey
480-pixel frames, and a full FFmpeg decode. Side-by-side clips went to the
lab's Video Vault for the user to review.

| | App before | Lab |
| --- | --- | --- |
| ComfyUI | 0.33.0 `8b2d2917` | 0.44.0 `56f179f6` |
| Python | 3.10.6 | 3.12.11 |
| PyTorch | 2.11.0 cu130 | 2.14.1 cu130 (first run), 2.11.0 cu130 (second run) |
| SageAttention, Triton | 1.0.6, 3.6 | 1.0.6, 3.6 (on 2.11) |
| Nunchaku | 1.2.1 cu13.0 torch2.11 | the same wheel (on 2.11 only) |
| T8 node pack | `e576eba` | `3a23f33` (latest; 780 node classes load) |

## Video flows

PyTorch 2.14 ran all 42 flows. All 42 completed and none took longer than on
0.33. The user reviewed the side-by-sides and called them "all look identical,
very good".

PyTorch 2.11 ran 28 of the same 42 flows, all completed and all decoded
cleanly. The other 14 were cancelled once the evidence was enough. Their
times were within a few seconds of the 2.14 run. The one exception was
Fused SLA Ref2VA multi-reference, at 450 s against 266 s, which is still
faster than 727 s on 0.33.

Generation seconds:

| Flow | 0.33 app | 0.44 + 2.14 | 0.44 + 2.11 |
| --- | ---: | ---: | ---: |
| Fused SLA opening | 660 | 245 | 244 |
| Fused SLA Ref2VA | 402 | 178 | 179 |
| Fused SLA lip-sync | 285 | 214 | 209 |
| LTX 2.5 reference | 1178 | 253 | 253 |
| LTX frames (sharp + calm) | 417 | 367 | 368 |
| LTX text | 215 | 194 | 189 |
| Pika opening | 468 | 423 | 417 |
| Pika Turbo 4-step lip-sync | 316 | 301 | 300 |
| Singularity lip-sync (App) | 717 | 694 | 694 |
| Turbo v4 lip-sync, Sage+SLA | 482 | 290 | not run |
| Turbo v1 opening | 412 | 290 | not run |
| Turbo v4 text | 1051 | 640 | not run |
| Standard lip-sync | 377 | 368 | not run |

Some of the large gains overstate the upgrade. Their 0.33 baselines (Fused SLA
opening, LTX 2.5 reference, Turbo lip-sync Sage and SLA) were rendered between
October 23 and 28, while the app ran the legacy memory mode, which was about
35% slower. Baselines from October 31 onward, all in dynamic mode, give the
fair comparison: 0.44 is 0 to 15% faster there (LTX, Pika, Singularity, Turbo
v4 opening and frames).

Most outputs are not bit-identical to 0.33, so PSNR ranges from 13 to
45 dB. At the same seed, the newer kernels change the noise path. Audio is
identical wherever the flow keeps the uploaded audio (lip-sync with
AudioLock).

## Image Lab and H3 still (0.44 + PyTorch 2.11)

All 33 Image Lab workflows report ready. Eleven of them were rendered on
both versions with seed 424242 and the same inputs. All 11 were faster on
0.44, and 4 came out pixel-identical.

| Workflow | 0.33 | 0.44 |
| --- | ---: | ---: |
| Qwen 2509 edit | 177.6 s | 162.8 s |
| Nunchaku Qwen edit | 62.9 s | 52.6 s |
| Qwen 3-input ControlNet | 183.0 s | 146.8 s |
| Krea text-to-image | 57.5 s | 49.2 s |
| Kontext edit | 118.2 s | 110.2 s |
| Simple upscaler | 10.1 s | 6.7 s |

The H3 still (seed 5150) took 64.7 s on 0.44 against 72.9 s on 0.33, at
PSNR 47.1.

## What the upgrade needed

- **protobuf 7.36.2.** Nunchaku fails to import with protobuf 5.29.6, which
  mediapipe pulls in. The package list therefore has a declared conflict
  (`google-ai-generativelanguage` wants protobuf below 6), so it is installed
  with `--no-deps` from the tested freeze.
- **MagCache import guard.** ComfyUI 0.44 removed
  `comfy.ldm.lightricks.model.precompute_freqs_cis`. MagCache imports it but
  does not use it, so the import is wrapped in try/except
  (`magcache-comfy044.patch` in the lab folder).
- **Two Image Lab packs pinned back** to versions that work with 0.44:
  comfyui-vrgamedevgirl `10225d5` and ComfyUI_UltimateSDUpscale `c48d60d`.
- **A separate ComfyUI user folder** (`state\user044`). ComfyUI 0.44 migrates
  its `comfyui.db`, and 0.33 keeps its own untouched copy for a rollback.
- **Only the node packs the app uses (23).** The packs the app never loads
  were left out: Impact Pack, AnimateDiff, WanVideoWrapper, TTS and others.

## The production install

The 0.44 install is a new folder beside the old one:

- ComfyUI code and node packs: `D:\Repos\ComfyUI044`, copied from the lab
  copy that passed. Its `install_comfy044.sh` records how it was built.
- Python: `D:\Repos\ComfyUI044\venv`, built from the lab's exact freeze
  (`requirements-lock.txt`). `uv pip freeze` matches the lab line for line.
- Models: unchanged, in `D:\Repos\ComfyUI_venv\ComfyUI\models`.
- `config.local.json`: `comfy.root`, `comfy.python` and `comfy.user` point to
  the new install. `start-project.bat` uses the same paths.

**Rollback.** Stop the app and point those three settings back to the 0.33
values (kept in `D:\repo-backups\production-2026-11-04\meta\config.local.json`).
Then start the app again. The full snapshot from right before the upgrade is
`D:\repo-backups\production-2026-11-04` (`restore.ps1`).

## Production check after the switch (2026-11-04)

The upgraded app replayed six app jobs through its own queue, with the same
inputs and seeds. These are the flows the lab's PyTorch 2.11 run did not
reach. All six completed, passed ffprobe with the expected streams and
duration, and passed a full FFmpeg decode.

| Flow | 0.33 | 0.44 | PSNR vs 0.33 |
| --- | ---: | ---: | ---: |
| Turbo v1 text | 107 s | 66 s | 24.8 |
| Turbo v1 opening (silent) | 412 s | 290 s | 35.1 |
| Turbo v1 reference | 472 s | 453 s | 30.1 |
| Turbo v4 lip-sync, Sage+SLA | 482 s | 275 s | 18.9 |
| Standard lip-sync | 377 s | 369 s | 25.0 |
| Singularity God opening, Sage | 586 s | 524 s | 21.5 |

- The H3 still (seed 5150) took 64.7 s and is pixel-identical to the lab's
  0.44 render.
- The Nunchaku Qwen edit (seed 424242) took 56.5 s, against 62.9 s on 0.33.
- Doctor passes the new pins (ComfyUI, H3 Turbo, T8). The checks it fails
  failed the same way before the upgrade: the local config binds the app to
  0.0.0.0, and Spectrum, ClipProj and their models are not installed.

## Not covered

- Spectrum and ClipProj are not installed in production, so they were not
  tested. Health reports them as not ready, as it did on 0.33.
- Fresh `.runtime` bootstrap: its pins (`manifests/`) now name the tested
  ComfyUI, H3 Turbo and T8 commits and the cu130 index, but a fresh install
  was only dry-run.
- Connected-sequence assembly fails the same way on 0.33 and 0.44: "Not every
  selected clip is available for assembly". This is an app bug and has
  nothing to do with the upgrade.
