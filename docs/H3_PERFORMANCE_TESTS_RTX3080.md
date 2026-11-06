# MiniMax H3 speed tests on a 10 GB RTX 3080 (ComfyUI 0.44)

A write-up of lab tests run on 2026-11-05, meant for another agent to repeat on its own machine. It builds on an earlier
guide from an RTX 4060 8 GB (`H3-OPTIMIZATION-GUIDE.md`: int8 attention, block pruning, profiling one step) and checks
which of those ideas pay off on a different card and setup. Every result here is training-free and touches no model
file.

## Setup

| | |
|---|---|
| GPU | RTX 3080 10 GB (Ampere, sm_86), driver 610.88 |
| System | Windows 10, 64 GB RAM, NVMe |
| ComfyUI | 0.44.0 with dynamic VRAM: `--reserve-vram 0.9 --enable-dynamic-vram --async-offload 2` |
| Python stack | Python 3.12, PyTorch 2.11.0+cu130 (cuDNN 9.19), Triton 3.6, SageAttention, comfy_kitchen (int8 attention available) |
| H3 models | `minimax_h3_fl2va_pruned_int8_convrot` (frame and lip-sync modes), `minimax_h3_ref2va_pruned_int8_convrot` (reference) |
| Turbo LoRAs | `minimax_h3_turbo_4step_ema_ckpt850` (v1), `minimax_h3_turbo_v4_step600_ema` (v4), `minimax_h3_ref2v_turbo_*` (Ref2V) |
| Pika | `pika_h3_flex_fl2va_comfy_bf16` / `pika_h3_flex_ref2va_comfy_bf16` (Pika's 6-knot sampler) |
| VAEs | `minimax_h3_video_vae_fp16` vs `minimax_h3_video_vae_int8_convrot`, `minimax_h3_audio_vae_fp32` |

**Test clip unless noted:** 5 s (124 frames at 24 fps), 6 steps, Turbo v4 lip-sync or Turbo v1 opening frame,
**1.5 MP** (928×1632 at 9:16, 1632×928 at 16:9), the same seed and inputs for every variant of a case. Times are the
bridge's full job time (queue start to verified MP4), including text and image encoding, decode and save.

## How the tests were run

- **Separate lab copy.** The tests ran on their own ComfyUI copy, venv and port, never on the production ComfyUI.
  Production was stopped first, so only one ComfyUI was ever on the GPU.
- **Original model files were never written.** Every speed-up is a runtime patch (a node or model patch).
- **Visible jobs.** Jobs went through the app's normal queue, so each one recorded its time, VRAM peak and system RAM
  peak. Variants were applied per job by a lab-only override, keyed by seed and taken in queue order.
- **Other GPU programs were closed first:** game launchers and the like. On a 10 GB card they push H3 over about 9.7 GB,
  and it then spills to shared memory and runs 2-4× slower.
- **Every output was checked** with `ffprobe` and a full FFmpeg decode, compared frame by frame (PSNR/SSIM, close-up
  crops, motion metrics; see "Measuring quality" below), and judged by eye by the user.

## Results

### 1. Where a job's time goes

A lab-only ComfyUI node logs every node's wall time (code below). Turbo reference, 1 MP, 4 steps, standard attention:

| Stage | Time |
|---|---|
| Sampler (4 steps) | 238 s, of which roughly 60-70 s happen before the first model call (see 7) |
| Video decode (fp16 VAE) | 40 s |
| Text + reference encode | 19 s |
| Save | 5 s |

At 1.5 MP, 6 steps, the sampler is about 88% of a standard-attention job, and the video decode takes about 63 s.

### 2. One-step profile: attention is the bottleneck

`torch.profiler` on exactly one model call (code below), sorted by self CUDA time:

| Case | Step | Attention (cuDNN flash SDPA) | int8 linears |
|---|---|---|---|
| Turbo reference 1 MP, standard | 59 s | 46.9 s (80%) | ~14 s, as `comfy_kitchen::int8_linear` |
| Turbo v1 opening 1.5 MP, standard | 103 s | 88.2 s (85%) | ~20 s |
| Same with Sage + sparse (SLA) | 31 s | 15.3 s | ~20 s, unchanged |

**Difference from the 8 GB guide:** there, a runtime LoRA forced every linear layer into bf16 matmuls (56% of a step).
Here the linears already run as int8. This setup merges the LoRA patches into the int8 weights at load, with 208
patches on the Ref2V LoRA. So the "LoRA forces bf16" problem doesn't exist on this path, and attention is what's left.

### 3. Attention: the big lever

Turbo, 1.5 MP, 6 steps, same seed per row:

| Attention | Opening frame (v1) | Lip-sync (v4) | Look vs standard |
|---|---|---|---|
| Standard (PyTorch SDPA) | 716 s | 722 s | reference |
| **comfy_kitchen int8** (the 8 GB guide's kernel) | - | **382 s** | same character and performance; motion diverges a little (PSNR 21.8) |
| SageAttention only | 448 s | 453 s | opening close (PSNR 34), lip-sync motion diverges (PSNR 21) |
| Sage + sparse attention (SLA 0.9) | 280 s | 286 s | clean, but motion changes more (lip-sync PSNR 17) |

- **comfy_kitchen int8 attention** needs no install. In ComfyUI 0.44 it's the built-in node `ModelAttentionBackend` →
  "comfy kitchen attention". Python equivalent: `m.set_model_optimized_attention(attention_comfy_kitchen_int8)`.
- On this card it was **faster than SageAttention** (382 s vs 453 s on the same lip-sync job).
- **Memory:** neither int8 kernel saved memory. Peak VRAM stayed at 9.52 GB and system RAM at about 50 GB for the
  whole PC.
- **Low PSNR here means different motion, not damage.** Changing the attention changes the trajectory on the same seed.
  Identity, wardrobe and performance beats stayed the same; check by eye.

### 4. VAE decode

- **Tiled decode does nothing for the H3 video VAE.** The VAE sets `handles_tiling = True` and always decodes in its own
  256 px, 17-frame chunks. `VAEDecode` and `VAEDecodeTiled` (512/64/64/16, 512/tall, 1024/tall) gave
  **pixel-identical** output (PSNR inf) in 60-63 s each. This matches the 8 GB guide.
- **The int8 convrot video VAE is the real gain.** Same latent decoded both ways:

| VAE | Decode at 1.5 MP | vs fp16 |
|---|---|---|
| `minimax_h3_video_vae_fp16` | 63 s | - |
| `minimax_h3_video_vae_int8_convrot` | **27 s** | PSNR 42-47 dB, SSIM 0.985-0.99, close-ups indistinguishable |

  That saves about 36 s per 1.5 MP job. Swap only the VAE used for decoding; the frame encode can stay fp16.

### 5. Block probe, measured separately per modality

The 8 GB guide's probe, re-run on this flow (Turbo v4 lip-sync, 1.5 MP, int8 attention). It measures each of the 50
blocks' influence as `1 - cos(input, output)`, separately on the audio, video and text rows, at all 6 steps:

- **Audio-critical blocks** (look idle for video, essential for sound): **5** (0.97), **2** (0.37), **3** (0.35),
  **4** (0.07), **17**, **18**. Same set as the 8 GB guide.
- **Text-critical:** **13** (0.49 on text rows, idle on audio and video). Keep it.
- **Quietest in all modalities:** 6-12 and 14-16 (under 0.7%), then 20 and 19.
- **Always heavy:** 0, 1 and 36-49.

### 6. Block skipping (runtime, no file changes)

Same lip-sync job, int8 attention plus the int8 VAE:

| Version | Skipped blocks | Time | Fine-detail change in the face, frame to frame (regular = 10.5) | User verdict |
|---|---|---|---|---|
| K1 int8 attention | none | 382 s | 10.6 | looks like regular |
| **K3 int8 attention + int8 VAE** | none | **351 s** | **10.6** | looks like regular: **the quality-safe setting** |
| K4 | 6-11 (6 blocks) | 310 s | 9.3 | slightly softer |
| K2 | 6-12, 14-16, 19, 20 (12 blocks) | 280 s | 8.1 | "a little blurry, less sharp when it moves" |

- **Skipping blocks softens motion even when no single frame looks blurry.** Sharpness per frame stayed the same or
  rose, but fine textures (beard, hair, beads) updated about 25% less from frame to frame with 12 blocks skipped, and the
  character moved less (overall motion 8.0 vs 10.3). Measure this over time, not on single frames.
- **No memory saving:** runtime skipping still loads every block. A pruned copy of the file would save system RAM (about
  4.5 GB on the 8 GB guide's machine) but not GPU memory. The GPU peak comes from the working data of one block on the
  whole clip, which no amount of pruning changes.

### 7. Things that did not help

- **`LoraLoaderBypassModelOnly`** (the LoRA as a side branch next to the int8 weights) on Turbo reference: the sampler
  took **634 s vs 248 s** patched, and the output changed (PSNR 13.5). Rejected on this stack.
- **The ~60-70 s before the first step of Turbo reference** happens before the first model call. It's most likely the
  208-patch LoRA merge at load, and it's paid on every job. The first model call itself profiles like a normal step.
  Unresolved; a pre-merged copy would be the next test, but the 8 GB guide shows baking a small LoRA into int8 rounds it
  away, so that needs care.
- **Profiling the very first model call** with `torch.profiler` collides with the dynamic-VRAM loader's CUDA hooks
  (`External init callback must run in same thread as registerClient`). Profile model call 2 instead.
- **`py-spy`** without `--idle` doesn't see time spent waiting on the GPU.

### 8. Other engines at 1.5 MP 9:16 (5 s, ComfyUI 0.44)

| Setup | Opening frame | First + last frame | Reference |
|---|---|---|---|
| Pika flow (H3 FL2VA + Pika FL2VA LoRA, 6 knots) + Sage | 409-419 s | 450-454 s | - |
| Singularity Ref2V, God tier (People realism LoRA + Turbo v4), T8, 8 steps, Sage | - | - | ~620 s (earlier lab run) |

- Pika with Sage moved noticeably less than Turbo with standard attention on the same dialogue shots: motion 5.3 vs 15.2
  on the most active shot.
- **A first + last frame shot can reach its last frame early and then hold still.** It ended almost frozen for ~2 s.
  Use a mid-motion last frame and keep action going to the last second.
- **Pika attention A/B** (one dialogue shot, same seed, only the attention changed):

| Pika flow attention | Time | Motion | Look |
|---|---|---|---|
| Standard | 666 s | 7.86 | reference |
| Sage | 413 s | 7.72 | same performance beat for beat (PSNR 23 vs standard) |
| **comfy_kitchen int8** | **348 s** | 7.69 | same performance (PSNR 23 vs standard) |

  The int8 kernel beat Sage again (−16%) at the same GPU peak (~9.5 GB). Attention was not the cause of Pika's calm
  motion; the prompts and an early last frame were. With second-by-second beats and a mid-motion last frame, motion rose
  25-95% per shot, and the frozen last 2 s of the first + last frame shot went from 1.1-1.6 to 9-10.

- **Singularity Ref2V, God tier** (People realism LoRA + Turbo v4, T8 sampler, 8 steps, three reference pictures,
  1.5 MP 9:16). Three dialogue shots, same seeds, only the attention changed:

| Attention | 15 s scene (3 shots) | Per shot | Look |
|---|---|---|---|
| Standard | 2,648 s | 880-884 s | reference |
| Sage | 1,612 s | 534-539 s | same faces and performance |
| **comfy_kitchen int8** | **1,348 s** | **448-453 s** | same faces and performance (PSNR 21.6-26.2 vs Sage) |

  int8 was 16% faster than Sage and 49% faster than standard. Motion was the same in all three (9.6-12.0), and so was
  the GPU peak (9.4-9.8 GB).

### 8b. Full 15 s dialogue scenes (two characters, three 5 s shots incl. a hard cut, Turbo v4, 1.5 MP 9:16)

| Version | Render time for 15 s | Per shot |
|---|---|---|
| Regular (standard attention, fp16 VAE) | 2,208-2,215 s (~37 min) | 712-789 s |
| int8 attention + int8 VAE | 1,081-1,086 s (~18 min) | 346-383 s |
| + skip blocks 6-11 | 977-978 s (~16 min) | 315-346 s |

Very steady across two different scenes: the speed-up is a property of the setup, not of one prompt. GPU peaks were
9.4-9.8 GB in all versions. For comparison, Singularity Ref2V God (People realism, T8 8 steps, Sage) took 534-641 s per
shot.

### 8c. LTX 2.5: the int8 attention also works there

LTX 2.5 lip-sync, 1600×896, 6 s, 8 steps, same frame, song window and seed:

| LTX attention | Time | Motion | vs standard |
|---|---|---|---|
| Standard | 259 s | 6.99 | reference |
| **comfy_kitchen int8** | **153 s** (−41%) | 6.52 | PSNR 28.4: frames nearly identical |

- **One-step profile (standard):** attention is 60% of an LTX step (10.2 of ~17 s, cuDNN flash SDPA). The linears
  already run as int8 (`comfy_kitchen::int8_linear`). So the same lever applies.
- LTX's transformer calls ComfyUI's shared attention function, so the `ModelAttentionBackend` node (after the UNET
  loader) switches it without anything LTX-specific.
- **What does not transfer from H3:** the int8 VAE (H3-only file) and "tiles don't matter". The LTX VAE really tiles,
  and its tile settings change speed, memory and quality.
- **Observation, not a conclusion:** the same LTX job took 214 s on ComfyUI 0.33 a week earlier and 259 s here on 0.44.
  One run each.

**LTX 2.5 at 2 MP** (High, 1056×1888, 9:16, sharp decode, 8 steps). A 15 s two-character dialogue scene in three
shots (opening frame, first + last frame, opening frame), same seed per pair:

| LTX attention | 15 s scene | Per shot | Sampling per shot | Decode per shot |
|---|---|---|---|---|
| Standard | 910 s | 296-308 s | 187-201 s | 86 s |
| **comfy_kitchen int8** | **667 s** (−27%) | 219-229 s | 126-133 s (−34%) | 85 s |

- Frames stayed close (PSNR 26.4-29.0) and motion was identical (9.6/5.5/11.1 vs 9.7/5.5/11.2).
- GPU peak was the same (~9.5 GB). System RAM peaked ~3-4 GB lower with int8.
- The same standard scene rendered through the production app took 917 s, matching the lab within 1%.
- **Sharp decode becomes the bottleneck at 2 MP:** 86 s per shot, the same with either attention, which is about 40%
  of an int8 job. On LTX, tile settings do matter, so the decode tiling is the next lever there.

### 9. Prompting notes that affected the results

- **If a face first appears after a cut or a turn, give the shot a last frame showing that face.** With only an opening
  frame, H3 invents the face.
- **Second-by-second beats and an explicit real-time speed line** ("SPEED IS CRITICAL … NO slow motion") help the calmer
  samplers move naturally, with "0-1 s: …, 1-2 s: …" for each line and gesture.

## Measuring quality

- `ffprobe` + `ffmpeg -v error -xerror -i out.mp4 -f null -` on every output.
- PSNR/SSIM against the baseline: `ffmpeg -i a.mp4 -i b.mp4 -lavfi "[0:v][1:v]psnr" -f null -`. Low values with the
  same seed often mean different motion, not damage: always look at frames and close-up crops.
- Detail per frame: variance of the Laplacian on grayscale frames.
- **Motion:** mean |frame - previous frame| on a downscaled grayscale copy. Reports 0.5 s windows and runs of near-still
  frames (catches "frozen" endings).
- **Fine-detail change over time** (catches "blurry when it moves"): high-pass each frame (frame minus a 9×9 box blur),
  then measure |f[i] - (f[i-1] + f[i+1]) / 2| over the face.

## Lab tools (ComfyUI custom nodes, lab copy only)

**Per-node timer:** wraps `execution.get_output_data` and appends one JSON line per executed node:

```python
import json, time, execution
_original = execution.get_output_data

async def _timed(prompt_id, unique_id, obj, input_data_all, *args, **kwargs):
    start = time.time()
    try:
        return await _original(prompt_id, unique_id, obj, input_data_all, *args, **kwargs)
    finally:
        with open("node_timing.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"prompt_id": prompt_id, "node": str(unique_id), "class": type(obj).__name__,
                                "start": start, "seconds": round(time.time() - start, 3)}) + "\n")

execution.get_output_data = _timed
NODE_CLASS_MAPPINGS = {}
```

**One-step profiler:** wraps `comfy.samplers.calc_cond_batch`. When a flag file exists, it profiles model call N
(use 2), writes `prof.key_averages().table(sort_by="self_cuda_time_total", row_limit=45)`, and deletes the flag.

**Block probe and block skip:** H3's block loop honours `transformer_options["patches_replace"]["dit"][("double_block", i)]`:

```python
def probe(args, extra):                       # per block i
    before = args["img"].clone()              # the block writes into its input in place
    out = extra["original_block"](args)["img"]
    for start, end, kind in args["layout"].segments:     # kinds include text, audio, video
        ...                                   # 1 - cos(before[..., start:end, :], out[..., start:end, :]), chunked in fp32
    return {"img": out}

def skip(args, extra):
    return {"img": args["img"]}

m = model.clone()
m.set_model_patch_replace(probe_or_skip, "dit", "double_block", i)
```

Keep the probe's comparisons chunked (4096 rows at a time in fp32). At 1.5 MP the sequence is about 57k tokens, and a
second full fp32 copy would not fit. The probe adds about 50 s to a job, so its time is not a valid speed measurement.

## Checklist for another machine

1. **Read the ComfyUI log and profile one step** (model call 2). Find the attention backend and check whether the linear
   layers run as int8 (`comfy_kitchen::int8_linear`) or as bf16 GEMMs (a runtime LoRA forcing dequantisation).
2. **Try comfy_kitchen int8 attention** (`ModelAttentionBackend` → "comfy kitchen attention") against standard and Sage
   on the same seed. Here it gave the biggest safe win: about −47% on a 1.5 MP lip-sync job.
3. **Decode with the int8 convrot video VAE.** Don't bother with tile settings; the H3 VAE ignores them.
4. **Probe blocks per modality before skipping any.** Then judge in motion, not on stills: measure frame-to-frame fine
   detail, and have a person watch the lips and faces. Here even 6 skipped blocks softened motion.
5. **Close other GPU programs and watch the VRAM peak.** On 10 GB, H3 at 1.5 MP sits at 9.5-9.8 GB, right at the edge.
6. **One seed per case is a limit of these tests.** Repeat on a second seed before trusting a small difference.

## Bottom line on this machine

| Setting for a 5 s, 1.5 MP Turbo lip-sync | Time | Quality |
|---|---|---|
| Regular (standard attention, fp16 VAE) | 722 s | baseline |
| **int8 attention (comfy_kitchen) + int8 VAE** | **351 s** | **looked like regular (best trade)** |
| + skip 6 blocks | 310 s | slightly softer motion |
| + skip 12 blocks | 280 s | visibly softer in motion |
| Sage + sparse | 286 s | clean, more motion change |

The comfy_kitchen int8 attention was the best single change on every engine tried: H3 Turbo (−47%), the Pika flow
(−48% vs standard, −16% vs Sage), Singularity Ref2V God (−49% vs standard, −16% vs Sage) and LTX 2.5 (−41% at
1600×896, −27% at 2 MP where the decode dominates). It saved no memory and kept the same performance on the same seed.
