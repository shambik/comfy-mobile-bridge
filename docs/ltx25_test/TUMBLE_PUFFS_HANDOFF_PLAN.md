# Tumble Puffs: execution and handoff plan

Updated: 2026-10-23. Workspace: `D:\repository`.

## New user-requested retest

After stopping the library-visibility investigation, the user explicitly asked
to run the MiniMax test again. A fresh job was submitted **to the main bridge
on 8787**, not the lab. Current retest key: `gag_02_pinwheel_retest_01`; job:
`93c2578c1bdb4a0e9b0da3738b01a516`. Seed is **1023611**; all other production
settings match the completed five-second test below (1.5 MP, Fused SLA Direct,
six steps, native audio, sparse attention). It is a new render, not the old
download. No AGY or sub-agents are involved.

The existing finish runner writes `state/tumble_puffs-retest-01.log` and will
download, decode-check, compose/mix music and decode-check the final file.
Do not submit another job or start a competing finish runner. Inspect the
main API and journal before resuming. After completion, publish the verified
music mix with `tumble_puffs_publish.py` so it is also available in Video Vault;
the native generated job belongs to main Studio history already. The stopped
blank-page/library investigation is not part of this retest.

Expected final file:
`state/tumble_puffs/gag_02_pinwheel_retest_01_with_music.mp4`.
Publish record: `state/tumble_puffs/gag_02_pinwheel_retest_01_published.json`.

**Retest completed:** main bridge job `93c2578c1bdb4a0e9b0da3738b01a516`
finished in 660.3 s. Native and music-mixed files passed full decode; actual
output is 1664×928, 24 fps, 124 frames and 5.166667 s. The native generation
appears in main Studio history. The music mix is available in **Video Vault**
as `Tumble Puffs - MiniMax sparse 1.5 MP - Test 2 with music.mp4`, item
`23c6c1d8e7594816af0390a495461a5f`. Its playback route is
`/api/video-vault/23c6c1d8e7594816af0390a495461a5f/video`. No rerender is pending.
Actual sparse execution again logged 300 calls, 83.5% effective sparsity with
the protected prefix, and zero dense fall-throughs. Peak GPU use: 9845 MiB;
system RAM: 64801 MiB. Build/preflight passed; 301/302 tests passed, with the
same pre-existing AGENTS.md line-count failure. The user remains the artistic
reviewer. Frozen result metadata: `state/tumble_puffs/retest-01-job.json`.

**Latest outcome:** MiniMax render and music mix completed. Native and mixed
MP4s passed full FFmpeg decode. The original app and ComfyUI are restored and
idle with the tested fallback saved. Only the user's artistic review remains.

## User instructions

- Work directly. No AGY, and do not introduce delegated production reviews.
- If sub-agents are used with user authorization, use **GPT-6.1 Sol**
  (`gpt-6.1-sol`), **medium** reasoning effort, matching the user's chosen model.
  Set those overrides explicitly; do not silently inherit another model/effort.
  No sub-agents were used in this recovery. The model preference alone is not
  an instruction to spawn agents.
- Generate stills with built-in ImageGen, not Image Lab. Use the supplied local
  cast and scene images as references rather than making new identities.
- Make videos through the bridge app. The user is the visual reviewer; skip
  council/AGY/strict visual-inspection gates. Still verify media integrity.
- Latest authorization: stop the stuck job, restart ComfyUI, and retry.
- Keep MiniMax, sparse attention and **1.5 MP** for this sample. Add audible music
  and make the scene more interesting than the first cushion sample.
- Never interrupt an unrelated job. One ComfyUI instance at a time. Read
  `AGENTS.md` and applicable skills before changes. Preserve all existing user
  edits and media; do not install into the app environments.

## Creative direction

Original, wordless, bright 3D preschool slapstick inspired by the broad comic
appeal of Sunny Bunnies, with distinct original characters:

- Pip: small coral pear-shaped fluff creature, curved top tuft.
- Momo: broad lemon-yellow cushion-shaped fluff creature.
- Tiki: tall mint jellybean-shaped fluff creature.

Current sample: Pip at left and Momo at right beside a planted multicolor
pinwheel. Momo blows; the spinner turns and the breeze sweeps Pip's tuft;
surprise resolves into a shared amused reaction. The garden has a leaf arch,
stepping stones, flowers and a butterfly. A restrained camera push keeps the
faces and prop readable. Native foley/nonverbal sounds plus an original score;
no speech, singing, narration, labels or logos.

## Selected assets and durable records

Everything below is relative to the workspace unless stated otherwise.

| Purpose | File |
| --- | --- |
| Full production journal, request bodies, IDs and results | `state/tumble_puffs/execution.json` |
| Selected cast | `state/tumble_puffs/cast-imagegen-v1.png` |
| Current opening image | `state/tumble_puffs/opening-02-pinwheel-imagegen-v1.png` |
| Opening image prompt and references | `state/tumble_puffs/opening-02-imagegen-prompt.json` |
| Original eight-second H3 prompt | `state/tumble_puffs/gag_02_h3_prompt.txt` |
| First successful cushion sample with music | `state/tumble_puffs/gag_01_with_music.mp4` |
| Native MiniMax target | `state/tumble_puffs/gag_02_pinwheel_5s.mp4` |
| Final MiniMax target with music | `state/tumble_puffs/gag_02_pinwheel_5s_with_music.mp4` |
| Score and mix records | `state/tumble_puffs/gag_02_pinwheel_5s_{music.wav,score.json,mix.json}` |
| Current runner log | `state/tumble_puffs-5s.log` |
| Detailed repair history | `docs/ltx25_test/TUMBLE_PUFFS_MINIMAX.md` |

The exact five-second prompt is stored in the current journal item’s payload.
It changes the original prompt's duration wording to five seconds.

Night Train is abandoned and stopped. Do not resume it. Old Image Lab stills
are superseded. The old eight-second draft retry JSON is not the current job.

## Current render: inspect before doing anything

Current journal key: **`gag_02_pinwheel_5s`**.

Current lab bridge job: **`212e3b3be95748cf92f4294fec7b09d9`**.

The job **completed all six sampling steps**, and the finish runner completed
the native download, full decode checks, original score and final mix. Do not
submit or rerun it. The final file is 1664×928, 24 fps, 124 frames, 5.166667 s,
with AAC audio. Generation took 597.9 s; peak GPU use was 9851 MiB and peak
system RAM use was 64174 MiB. Actual sparse execution was confirmed: 300 calls,
59,669 tokens, 83.5% effective sparsity after protecting 61 prefix blocks, and
zero dense fall-throughs. The node's requested sparsity remained 90%.

Settings: H3 Fused SLA Direct, native encoder/audio, six steps, five-second
request, 1.5 MP, 16:9, seed 1023610. Sparse attention is built into this graph
at 0.90 sparsity, 64 blocks, audio protection. Its API attention field is
`standard` because the graph already contains SLA; do not add a duplicate
patch or substitute dense attention.

The eight-second request packed 90,055 tokens, spilled into shared GPU memory
and advanced too slowly on the 3080 10 GB. Keep this recovery at five seconds.
Do not upscale a smaller render and claim it was generated at 1.5 MP.

### Runtime locations

- Original bridge is healthy at `http://127.0.0.1:8787`, with no active job.
- The separate lab bridge formerly at `http://127.0.0.1:8788` is stopped.
- Exactly one ComfyUI serves `http://127.0.0.1:8190`, now from the original
  configured root/interpreter; its running and pending queues are empty.
- Lab configuration: `.runtime/h3-stall-lab/config.local.json`.
- Lab job database: `.runtime/h3-stall-lab/state/jobs.sqlite3`.
- Lab ComfyUI log: `.runtime/h3-stall-lab/state/logs/comfy-8190.log`.
- Models and installed dependencies are reused read-only from existing
  configured paths. No app packages were installed or changed.
- Current flags: `--reserve-vram 0.9 --disable-dynamic-vram
  --disable-async-offload --disable-pinned-memory`.
- Original app job database: `state/jobs.sqlite3`. The new lab job will not
  appear there; do not mistake that for a missing submission.

The completed job is frozen at `state/tumble_puffs/recovered-job.json`. Read
that and `execution.json` when the lab bridge is stopped. The historical poll
command below applies only while that lab bridge is already running:

```powershell
python docs/ltx25_test/tumble_puffs_recover.py poll --base http://127.0.0.1:8788 --key gag_02_pinwheel_5s --duration 5
```

If the original finish runner is no longer running, resume the existing job
with the `finish` action and the same base/key/duration. Set
`TUMBLE_PUFFS_MEDIA_PYTHON` to the bundled workspace Python that has NumPy
(discover through the app dependency tool). Do not replace `finish` with
`submit`: submission is deliberately guarded against duplicate POSTs.

## Recovery procedure and completion checklist

Steps 1–4 below are complete. Steps 5–8 are finalized in the restoration
checkpoint below. They remain documented so another agent can reproduce the
process after inspecting the current state; they are not orders to regenerate.

1. Let the existing render and finish runner complete. Monitor approximately
   every 30–60 seconds, and keep the user informed of meaningful progress.
2. Confirm both native and mixed MP4s exist and their `*_proof.json` files say
   full decode passed, with video and audio streams. The runner calls FFprobe
   and full FFmpeg decode; the user handles artistic review.
3. Confirm the final mix contains the original score WAV. The helper
   `tumble_puffs_music.py` writes the note ledger, mix gains and loudness target,
   preserving the video stream without re-encoding it.
4. Record final duration, dimensions, frame count, actual sparse invocation
   summary, generation time and peak memory from the lab job. A sparse node
   being installed does not by itself prove sparse kernels ran; inspect its
   completion summary for calls and fallback warnings.
5. Once the lab is idle, stop its ComfyUI through its bridge endpoint and stop
   the lab bridge. Verify port 8190 is free before restoring the original app.
6. Apply the tested fallback to the original app via local
   `comfy.memory_mode=legacy`, backing up local config first. Restart the
   original bridge if needed to read the new setting, then start its ComfyUI.
   The existing original bridge was started as `python -u run.py`; derive its
   interpreter and runtime paths from config/process evidence. Keep the user's
   host/port and other settings. Do not change dependencies or models.
7. Confirm the original app on 8787 is healthy, its ComfyUI on 8190 matches the
   configured original root/interpreter, queues are empty, and only one ComfyUI
   remains. Do not leave the original app pointing at the lab.
8. Update this plan, `TUMBLE_PUFFS_MINIMAX.md`, `WORKFLOW_GUIDE.md` and the journal
   with the actual outcome. Present the final local MP4 link and open it for
   the user's review. Never describe a pending/failed render as complete.

## Repair code and verification

Changes made for persistence and applied to the restarted original bridge:

- `backend/config.py`: validates optional `comfy.memory_mode`, dynamic/legacy.
- `backend/comfy.py`: legacy selects the three disable flags above; dynamic
  retains the original flags. No default behavior changed.
- `config.example.json`: documents default `memory_mode=dynamic`.
- `tests/test_worker.py`: tests actual launch command selection for both modes.
- `tests/test_portability.py`: recognizes the added example configuration field.
- `docs/HARDWARE_AND_VRAM.md`: documents the fallback and its limits.

Preserve unrelated pre-existing edits in AGENTS.md, README.md,
backend/workflows.py, tests/test_ltx_lipsync.py and other working-tree files.
Do not run broad reset/restore or commit runtime, state, media, config or models.

Latest checks: UI build passed. **301/302 tests passed**; the existing
portability test rejects AGENTS.md's 38 lines (maximum 20). Do not shorten the
user's instructions to make that assertion pass. Preflight could not read
Tailscale login/hostname; doctor also reports pre-existing bind/runtime findings.
Keep those limitations distinct from local render/media proof. Logs are under
`state/tumble_puffs/repair-*`.

## After the user reviews this sample

Use their feedback before expanding the series. Keep the selected character
shapes and colors, readable cause/reaction comedy, richer but uncluttered garden
staging, and actual music. Generate any new opening still directly with built-in
ImageGen. Use short MiniMax sparse-attention shots at the proven size/duration,
or the already successful LTX path if the user chooses it. Document exact
inputs, prompts, seeds, settings, job IDs and final media for every shot.

No new series episode, additional job, AGY review or delegated agent is required
to finish the current recovery.

## Final restoration checkpoint

All eight recovery steps are complete. Original local config was backed up to
`state/tumble_puffs/config-before-recovery.json`, then `comfy.memory_mode` was
set to `legacy`. The original bridge was restarted using its configured app
Python and `run.py`; its ComfyUI was started through `/api/comfy/start`.

Live `/system_stats` confirmed the original configured ComfyUI root, the
three disable flags and 0.9 GB reserve. The lab bridge is stopped, both ComfyUI
queues are empty, and GPU use is idle (3%, 1116 MiB at the checkpoint). Runtime
proof is `state/tumble_puffs/restored-runtime.json`. No second render or retry
is running. The MP4 and this plan can now be handed to any other agent without
requiring access to this conversation.

### Tailscale enabled after recovery

The user subsequently requested enabling Tailscale. Its Windows service was
disabled; it is now Automatic/Running, and the existing tailnet connection is
Running. The original `accept-dns=false` preference and existing Serve routes
were preserved. Private HTTPS forwards to the bridge on 127.0.0.1:8787; Funnel
is disabled. An HTTPS `/api/health` request through the Tailscale address
returned `ok=true`. Preflight now passes; the earlier Tailscale login/hostname
failures are resolved. Phone access has not been independently tested. Existing
unrelated doctor bind/runtime findings remain. Latest check files:
`state/tumble_puffs/tailscale-enabled-{preflight,doctor}.json`.
