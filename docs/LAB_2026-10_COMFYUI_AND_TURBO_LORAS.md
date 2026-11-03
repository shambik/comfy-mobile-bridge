# Lab test: newer ComfyUI and the lightx2v Turbo LoRAs (October 2026)

**Decision: rejected. The app stays on its current environment.**

This test was done in October 2026 on an RTX 3080 10 GB with 64 GB of RAM.
It checked two things in a separate lab copy, with its own ComfyUI, venv and
bridge, so the app was never touched:

1. Whether a newer ComfyUI runs the app's existing flows at least as well as
   the current one.
2. Whether the new lightx2v MiniMax H3 Turbo LoRAs beat the app's current
   Turbo LoRAs (v0.1 for reference, v1 and v4 for the other modes).

The new LoRAs are faster, but in every flow the output quality was worse than
the current setup. On 0.35.2 the old flows were mostly slower, and on 0.42.1
two of them stalled. Nothing justified the change.

## What was tested

| | Current app | Lab |
| --- | --- | --- |
| ComfyUI | v0.33.0-24 | v0.42.1, then v0.35.2 |
| comfy-aimdo | 0.4.13 | 0.5.6 / 0.5.3 |
| comfy-kitchen | 0.2.31 | 0.2.39 / 0.2.33 |
| Frontend | 1.47.12 | 1.55.18 / 1.51.10 |
| Torch, SageAttention, Triton | 2.11.0+cu130, 1.0.6, 3.6.0.post26 | the same (copy of the app venv) |
| Custom nodes | 21 packs | the same 21 packs |
| Memory mode | legacy | legacy |

Version 0.35.2 was chosen because it is the oldest release that has
everything the researched items need:

- Motion Context needs 0.34 or later.
- Native FunControl (`MiniMaxH3FunControlNetApply`) needs 0.35 or later.
- The Turbo LoRAs need no ComfyUI change.

Version 0.42.1 was tried first only because it was the latest release, and
that was a mistake.

The new LoRAs, all 768p bf16 ComfyUI builds:

| Profile | File | Distilled for |
| --- | --- | --- |
| FL2V 4-step v1.3 | `minimax_h3_fl2v_turbo_4step_v1.3_768p_comfyui_bf16.safetensors` | 4 steps, video shift 6 |
| FL2V 8-step v1.1 | `minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors` | 8 steps, video shift 6 |
| REF2V 4-step v1.0 | `minimax_h3_ref2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` | 4 steps |
| REF2V 8-step v1.1 | `minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors` | 8 steps |

Every LoRA was loaded through `MiniMaxH3TurboLoRA` at strength 1.0. The FL2V
LoRAs used video flow shift 6, as lightx2v recommend. The REF2V LoRAs kept
shift 12 and the beta scheduler.

## Method

- Each test reran a known-good app job with the same inputs, prompt and seed,
  and changed only the item under test.
- The jobs were submitted through the lab bridge, so they ran on the app's
  real workflows.
- Every finished output passed `ffprobe` and a full FFmpeg decode, with 124
  frames.
- Times are generation seconds from the jobs database.
- Quality was judged by eye, side by side.

## Results: the old flows on the new ComfyUI

The timings are generation seconds. The 0.33 column is the original app job,
and many of those ran in August and September, so the comparison is not a
controlled A/B. A dash means the job never ran there, because that run was
stopped first.

| Flow | Size, steps | 0.33 (app) | 0.42.1 | 0.35.2 |
| --- | --- | ---: | ---: | ---: |
| Fused SLA, frames | 864×1152, 4 | 158 | 306 | 214 |
| Fused SLA, lip-sync | 736×1344, 6 | 285 | 426 | 316 |
| Fused SLA, opening | 1632×928, 6 | 660 | 702 | 356 |
| Fused SLA, Ref2VA | 1056×1408, 4 | 402 | 361 | 264 |
| Fused SLA, Ref2VA multiref | 1056×1408, 4 | 727 | stalled | 1218 |
| Fused SLA, text | 512×928, 6 | 72 | — | 137 |
| LTX closing | 1600×896, 8 | 251 | — | 281 |
| LTX frames | 1600×896, 8 | 362 | 412 | 355 |
| LTX lip-sync | 1600×896, 8 | 179 | 183 | 173 |
| LTX opening | 1600×896, 8 | 295 | 295 | 290 |
| LTX reference 2.3 | 1536×896, 8 | 281 | 497 | 308 |
| LTX reference 2.5 | 1536×896, 8 | 176 | stalled | 666 |
| LTX text | 1600×896, 8 | 215 | — | 249 |
| Turbo v4, frames | 1632×928, 6 | 735 | 980 | 1078 |
| Turbo v4, lip-sync | 1632×928, 6 | 756 | 980 | 1049 |
| Turbo v1, opening | 1120×640, 6 | 412 | — | 772 |
| Turbo v4, opening | 1632×928, 6 | 731 | — | 1048 |
| Turbo v1, reference | 1344×736, 8 | 472 | — | 538 |
| Turbo v1, text | 736×416, 4 | 107 | — | 142 |
| Turbo v4, text, sage+SLA | 544×928, 6 | 117 | — | 193 |
| Turbo v4, text, standard | 1632×928, 6 | 1051 | — | 898 |

What these runs showed:

- **0.42.1 stalled twice mid-queue,** on multiref and on LTX reference 2.5.
  Both times the GPU showed 100% busy at about 140 W, against about 320 W
  when healthy, with 0% memory-controller load and about 1 GB spilled into
  shared GPU memory. One step of LTX reference 2.5 took 47 minutes.
- **0.35.2 never stalled,** with only 90 to 140 MB shared. Peak VRAM stayed
  within the same range as the app.
- **Most flows were slower on 0.35.2,** Turbo in particular: 30 to 90% slower
  than the app's original jobs. Only a few Fused SLA flows were faster.
- **The lab ComfyUI hit 68.8 GB at its peak working set,** more than the
  64 GB of physical RAM, so the page file was in use. That may account for
  part of the slowdown.

## Results: the new Turbo LoRAs, on 0.35.2

All of these ran on the lab's ComfyUI 0.35.2.

### Text (544×928), attention grid at 6 steps

Same input, prompt and seed in every run.

| LoRA | Standard | Sage | SLA | Sage+SLA |
| --- | ---: | ---: | ---: | ---: |
| Current v4 | 249 s | 218 s | 193 s | 193 s |
| FL2V 4-step v1.3 | 168 s | 142 s | 123 s | 122 s |
| FL2V 8-step v1.1 | 174 s | 137 s | 117 s | 117 s |

At the distilled step counts with sage+SLA, FL2V v1.3 at 4 steps took 176 s
and FL2V v1.1 at 8 steps took 143 s. The v1.3 4-step result was the worst
looking of the whole test.

The text runs peaked at 8.1 to 8.4 GB of VRAM.

### First frame to video, standard attention

| LoRA | 768p (1344×768) | 1.5 MP (1632×928) |
| --- | --- | --- |
| Current v4, 6 steps | 670 s | 1078 s (regression run) |
| FL2V 4-step v1.3, 4 steps | 330 s | — |
| FL2V 4-step v1.3, 6 steps | 482 s | 863 s |
| FL2V 8-step v1.1, 6 steps | 456 s | stopped |
| FL2V 8-step v1.1, 8 steps | 570 s | — |

All of these peaked at 9.2 to 9.3 GB of VRAM. The source job has audio
turned off.

### Reference (1344×736), 6 steps

| LoRA | Time |
| --- | ---: |
| Current v0.1 | 432 s |
| REF2V 4-step v1.0 | 417 s |
| REF2V 8-step v1.1 | 416 s |

The REF2V LoRAs gave almost no speed gain over the current reference LoRA,
and the quality was worse.

### Not run

Lip-sync with both FL2V LoRAs, and FL2V v1.1 at 1.5 MP, were stopped once
the decision was made.

## Why the change was rejected

- **Quality:** worse than the current LoRAs in every flow tested. This
  matches reports in lightx2v's Hugging Face discussion #57:
  - FL2V v1.3 breaks with sparse attention and with extra LoRAs.
  - REF2V 4-step is blurry.
  - REF2V 8-step v1.1 has incoherent speech.
- **Speed:** the FL2V LoRAs save time, but not enough to make up for the
  quality loss.
- **Stability and speed of the old flows:** 0.42.1 stalls. 0.35.2 is stable
  but slower than the app's 0.33 on most flows.

## Not tested

These items were researched but never run. Each would need its own test if
it becomes worth trying:

- Motion Context.
- Native FunControl.
- LanPaint.
- The latent upscalers.
- VAE_TRT.
- FL2V 4-step v1.2, which is reported to work with sparse attention.
- LoRA strength 2.0.

A fair same-day 0.33 baseline was not run either.

## When to revisit

Revisit this if lightx2v publish a LoRA version with better reported quality,
or if the app needs a feature that only a newer ComfyUI has, such as Motion
Context or native FunControl. In that case, start from this test set and
compare against the same source jobs. The lab copy was deleted after the
test.
