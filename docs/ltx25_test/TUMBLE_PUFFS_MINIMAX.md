# Tumble Puffs — MiniMax pinwheel sample

The user liked the first visual sample and requested audible music, more scene
interest, and the next sample through MiniMax with sparse attention at 1.5 MP.
Stills continue to use built-in ImageGen. No AGY or delegated agents are used.
The user supplies visual feedback; basic file-integrity checks remain.

## Creative change

Eight-second garden comedy: Momo blows the planted pinwheel, the breeze sweeps
Pip's coral fur and curled tuft sideways, and their surprised expressions turn
into a shared chuckle. Two distinct characters and the pinwheel create a clear
cause and reaction. The garden includes a leaf arch, a winding stepping-stone
path, layered flowers and a distant butterfly. A small slow camera push keeps
the faces and the spinner readable.

The opening image is
`state/tumble_puffs/opening-02-pinwheel-imagegen-v1.png`, generated directly
with built-in ImageGen from the selected cast and garden references. Its exact
prompt is `state/tumble_puffs/opening-02-imagegen-prompt.json`.

## Exact video request

- Mode: opening image / I2VA.
- Engine: MiniMax H3 Turbo, profile v1.
- Attention: sparse only, `attention_mode=sla`.
- Requested size: `megapixels=1.5`, aspect ratio 16:9; the workflow resolution
  selector owns final dimensions.
- Steps: 6; duration: 8 seconds; seed: 1023610; native encoder.
- Generated audio: enabled, for wind, pinwheel, garden and nonverbal reactions.
- Job: `f15d8778ef0c41f698eda0f8ed9a4db4`.
- No application source, saved workflow or runtime setting was changed.

The live ComfyUI node catalog contained H3SLAAttention. Execution logs confirmed
SLA was installed with the app's tested 0.90 sparsity and 64×64 blocks, with
audio protection enabled. The API accepted 1.5 MP and `sla` for this job.

The H3 prompt follows the [official base guide](https://raw.githubusercontent.com/MiniMax-AI/MiniMax-H3/main/skills/h3-prompt-writing/references/base-en.txt),
with an opening-frame anchor and the three exact fields. The full original
prompt is saved at `state/tumble_puffs/gag_02_h3_prompt.txt`.

## Music

An original locally composed four-bar instrumental cue uses synthesized
celesta-like mallet tones, plucked chord stabs and a bouncing bass. The score
is saved as its own stereo WAV, with notes/timing recorded in JSON. It is mixed
over the generated foley and normalized toward −16 LUFS. H3 is prompted with
`non_diegetic_music: N/A` so it generates the action sounds for this mix.

The first cushion clip has also received this theme:
`state/tumble_puffs/gag_01_with_music.mp4`. Its video stream was copied, with
no picture re-encode; the file remains 1888×1056, 24 fps, 145 frames and
6.041667 seconds. Audio is AAC and a full decode passed.

## Execution and outputs

- Video submission/polling: `tumble_puffs_minimax.py`.
- Original score and music mix: `tumble_puffs_music.py`.
- Journal: `state/tumble_puffs/execution.json`.
- Native MiniMax clip: `state/tumble_puffs/gag_02_pinwheel.mp4`.
- Delivery clip with music: `state/tumble_puffs/gag_02_pinwheel_with_music.mp4`.
- Score: `state/tumble_puffs/gag_02_pinwheel_music.wav`.
- Basic proof: `*_proof.json`; mixing details: `*_mix.json`.

The MiniMax render remains on its first sampling step after more than ten
minutes. No execution error is logged, and GPU use is reported as 100%.
Windows reports about 9.4 GB dedicated and 26.8 GB shared GPU memory assigned
to the ComfyUI process; about 15 GB of system RAM remains free. Those readings
do not establish whether computation is merely slow or stalled.

The user explicitly requested stopping the stuck job. It was canceled through
the bridge and confirmed as `canceled`. ComfyUI's running and pending queues
are empty. GPU use fell to 3%, with 1318 MiB used, confirming the generation
released the GPU. The submission runner has stopped and a stop marker is saved
at `state/tumble_puffs/STOPPED.json`.

The draft five-second payload at
`state/tumble_puffs/gag_02_retry_5s_DRAFT.json` was **not submitted**. No retry
or replacement job was started. This MiniMax attempt produced no video.

## Repair authorized after cancellation

The user subsequently requested repair and rerun. The canceled Turbo attempt
and its stop marker are preserved as `STOPPED-canceled-turbo.json`. The new
runner is `tumble_puffs_recover.py`; it submits once through the bridge and
does not retry automatically.

Evidence: the old job entered its first model forward and completed no sampling
step in 28:58. Its logs contain 208 live Turbo LoRA weight patches; Windows
reported heavy shared GPU memory use. There was no logged CUDA exception.
This identifies the stall location and suggests memory pressure; it does not
prove a particular kernel or patch is defective.

Recovery job `88e3c38d6fe24a3b80b7345cf739d2ef` uses the app's existing
**MiniMax Fused SLA Direct low-VRAM** graph. It retains the exact opening image,
prompt, seed 1023610, 8-second request, 1.5 MP, 16:9 and six steps. This path
uses a fused INT8 model, INT8 VAE and four feed-forward chunks, with zero live
Turbo LoRA patches. Sparse attention is already in the graph at 0.90/64 with
audio protection; the API field is `attention_mode=standard` because adding
another sparse patch would duplicate it. No Sage patch is added.

This is an operational comparison using supported app controls. No source,
saved workflow, package, environment or service launch flag was changed.
The new job must finish and pass file checks before recovery is called proven.
Its outputs use the prefix `gag_02_pinwheel_fused`, with the same original music
cue added afterward. The user remains the visual reviewer.

### Prefetch stall isolated

The fused comparison also remains at step zero. Two nonblocking `py-spy`
samples, saved in `repair-stack-1.txt` and `repair-stack-2.txt` under the output
folder, show the prompt worker blocked at the same call:

```text
MiniMaxH3._forward -> model_prefetch.prefetch_queue_pop
 -> ensure_pin_registerable -> free_registrations
 -> unregister_inactive_pins -> cudaHostUnregister
```

This places the observed block in dynamic-VRAM host-memory registration
eviction during prefetch, rather than establishing a sparse-kernel defect.
Switching the model alone did not avoid it. The exact CUDA/stream deadlock
mechanism still needs the controlled render comparison.

`prepare_h3_stall_lab.py` prepares a separate ComfyUI copy, bridge copy, venv,
state and config under `.runtime/h3-stall-lab`. Existing dependencies are reused
read-only, and models are shared without modification. In the lab copy only,
`--disable-async-offload` replaces `--async-offload 2`; dynamic VRAM and pinned
memory remain unchanged to isolate one compute setting. It is prepared, not
started. No second ComfyUI may start while the original remains running.

The explicit approval request is pending because AGENTS.md requires asking
before stopping a busy ComfyUI. The recovery job is still running; it has not
been canceled without that approval.

Verification so far: UI build passed; 300/301 tests passed, with the existing
AGENTS.md line-count assertion failing (38 lines, maximum 20). Preflight reports
unavailable Tailscale status; doctor reports existing bind/runtime findings.
No completed MiniMax video or GPU repair proof existed at that checkpoint.

## Authorized restart and controlled retries

The user explicitly authorized stopping the stuck recovery, restarting ComfyUI,
and retrying. Only one ComfyUI was running throughout; all experiments used the
separate lab bridge on 8788 and ComfyUI on 8190. No packages were installed into
the app's environments. The lab's Triton CUDA toolchain path was set explicitly
to the existing bundled toolkit so its sparse kernels can compile.

The retry with async offload disabled (`1067706caee94621aae41b281f9cd4c5`)
also blocked inside dynamic host-buffer transfer. Disabling dynamic VRAM alone
then blocked in CUDA host registration during model loading
(`62620d61fc26418984cf96d8984005e3`). Disabling pinned memory too allowed model
loading and slow forward progress (`5c5e59a73d3747e5985138b26d62b357`), but the
eight-second 1.5 MP sample packed 90,055 tokens and spilled about 4 GB of GPU
allocations into shared memory. Stack snapshots showed block 2 advancing to 3,
so this was severe slowdown rather than proof of an infinite loop. These jobs
were canceled as part of the authorized repair, with a clean ComfyUI restart
before each comparison.

The current recovery `212e3b3be95748cf92f4294fec7b09d9` reduces only the request
duration to **five seconds**, with the matching duration word changed in its
prompt. It retains the same opening, seed, six steps, Fused SLA Direct, native
audio, sparse 0.90/64 attention, 1.5 MP and 16:9. Its runtime uses
`--disable-dynamic-vram --disable-async-offload --disable-pinned-memory`.
Outputs use the prefix `gag_02_pinwheel_5s`. The original music cue will be mixed
after the native video finishes and passes FFprobe/full decode.

The bridge now has an optional `comfy.memory_mode=legacy` setting for that
three-flag fallback; the default remains `dynamic`. Startup tests verify the
two modes cannot select conflicting flags. This setting does not claim that
long high-resolution H3 sequences fit a 10 GB card.

## Completed MiniMax recovery

Job `212e3b3be95748cf92f4294fec7b09d9` completed in **597.9 s**. Its video is
1664×928 at 24 fps, 124 frames and 5.167 s. Peak GPU use was 9851 MiB and
system RAM use reached 64174 MiB. This is a tight memory fit, not a speed
improvement claim. The runtime fallback and shorter duration together produced
the completed file; these comparisons do not isolate a single universal cause
for every stall.

The completion log confirms **300 sparse attention calls**, 59,669 tokens,
154/933 blocks retained (83.5% effective sparsity including 61 protected prefix
blocks), and **zero dense fall-throughs**. Requested sparsity was 0.90, blocks
64×64 and audio protection enabled.

Both `gag_02_pinwheel_5s.mp4` and `gag_02_pinwheel_5s_with_music.mp4` passed
FFprobe and full audio/video FFmpeg decode. The mixed file preserves the video
stream and adds the original five-second mallet/plucked-string cue. The final
mixed duration is 5.166667 s. Native foley mean level was −27.7 dB; its gain was
+4.7 dB, music gain −8.6 dB, with normalization targeting −16 LUFS. The user
remains the visual/listening reviewer.

The full portable execution/handoff plan, including the user's GPT-6.1 Sol /
medium sub-agent preference, is `TUMBLE_PUFFS_HANDOFF_PLAN.md`.

The lab services are stopped. The original bridge and ComfyUI are restored with
local `comfy.memory_mode=legacy`; both job queues are empty and the GPU is idle.
Original config backup: `state/tumble_puffs/config-before-recovery.json`.
Restoration proof: `state/tumble_puffs/restored-runtime.json`. No retry remains
running. Build passed and 301/302 tests passed; the remaining failure is the
pre-existing AGENTS.md line-count assertion. Preflight/doctor still report
existing Tailscale/bind/runtime configuration findings.

## Main-bridge repeat test

The user explicitly requested another MiniMax test after stopping the
library-visibility investigation. Job `93c2578c1bdb4a0e9b0da3738b01a516` ran
through the normal bridge on 8787, using the same five-second 1.5 MP Fused SLA
Direct preset and opening image, with a new seed 1023611. It completed in
660.3 s, outputting 1664×928 at 24 fps with 124 frames. Actual sparse attention
again logged 300 calls and no dense fall-throughs. Peak GPU/system RAM use was
9845/64801 MiB respectively. The queues are empty.

Native file: `state/tumble_puffs/gag_02_pinwheel_retest_01.mp4`. The original
music mix is `gag_02_pinwheel_retest_01_with_music.mp4`; both passed full FFmpeg
decode. The mix was uploaded via the existing Video Vault API, verified by
SHA-256, as item `23c6c1d8e7594816af0390a495461a5f`. Its title is
`Tumble Puffs - MiniMax sparse 1.5 MP - Test 2 with music.mp4`. Native job
history and final mixed playback are now both on the main bridge.
