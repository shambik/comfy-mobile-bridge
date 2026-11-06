# Performance test workflows (RTX 3080 10 GB)

These are the exact ComfyUI graphs behind the speed tests in `docs/H3_PERFORMANCE_TESTS_RTX3080.md`. There is one file
for each mode and attention setting shown in the explainer video. Each graph was read from the `prompt` metadata that
ComfyUI's SaveVideo wrote into the shot's MP4, so nothing here was rebuilt by hand. Only the input file names and the
output prefix were changed to neutral placeholders.

**How to open one:** drag the `.json` file into ComfyUI. They are API-format graphs, so the nodes load without a
layout; use "Arrange" in the canvas menu to lay them out.

1. Put your own pictures or audio in ComfyUI's `input` folder.
2. Pick them in the `LoadImage` (and `LoadAudio`) nodes; the placeholders are `input_image_1.png`, `input_image_2.png`
   and so on.
3. Rewrite the prompt for your scene. The seed in `RandomNoise` is the one the test used.

## The files

Times are full job times for one 5 s shot on the RTX 3080 10 GB, ComfyUI 0.44, measured by the app (queue start to a
verified MP4).

| File | What it is | Size | Time per 5 s shot |
| --- | --- | --- | --- |
| `turbo_v4_standard_opening_frame.json` | MiniMax H3 + Turbo v4 LoRA, standard attention, fp16 video VAE | 928×1632 | 712-789 s |
| `turbo_v4_standard_first_last_frame.json` | same, first + last frame | 928×1632 | 712-789 s |
| `turbo_v4_int8_opening_frame.json` | Turbo v4, **int8 attention + int8 video VAE** | 928×1632 | **346-383 s** |
| `turbo_v4_int8_first_last_frame.json` | same, first + last frame | 928×1632 | **346-383 s** |
| `pika_flow_sage_opening_frame.json` | MiniMax H3 + Pika H3 Flex LoRA, Pika's 6-knot schedule, Sage attention | 928×1632 | 409-419 s |
| `pika_flow_sage_first_last_frame.json` | same, first + last frame | 928×1632 | 450-454 s |
| `ref2v_realism_standard.json` | Singularity Ref2V v1.3 + people realism LoRA + Turbo v4, T8 sampler, 8 steps, 3 reference pictures, standard attention | 928×1632 | 880-884 s |
| `ref2v_realism_sage.json` | same seed, Sage attention | 928×1632 | 534-539 s |
| `ref2v_realism_int8.json` | same seed, **int8 attention** | 928×1632 | **448-453 s** |
| `ltx25_2mp_standard_opening_frame.json` | LTX 2.5 distilled, 8 steps, sharp decode, standard attention | 1056×1888 | 296-308 s |
| `ltx25_2mp_standard_first_last_frame.json` | same, first + last frame | 1056×1888 | 296-308 s |
| `ltx25_2mp_int8_opening_frame.json` | same seed, **int8 attention** | 1056×1888 | **219-229 s** |
| `ltx25_2mp_int8_first_last_frame.json` | same seed, **int8 attention**, first + last frame | 1056×1888 | **219-229 s** |

**Int8 attention** is ComfyUI's built-in `ModelAttentionBackend` node set to "comfy kitchen attention", placed after
the model and LoRA loaders. It needs no install and no launch flag. To try it on a graph of your own, add that node
after the last LoRA loader.

**Not included:** "Int8 + skip 6 blocks" from the video. Block skipping was a lab-only runtime patch. It saved about
10% more time but softened fine detail in motion. The report's sections 5 and 6 describe it, with the code.

## What you need

**ComfyUI 0.44 or newer.** It includes the MiniMax H3 nodes, `ModelAttentionBackend`, `ResolutionSelector` and
`ComfyMathExpression`.

**Custom nodes:**

| Pack | Used by |
| --- | --- |
| [ComfyUI-MiniMax-H3-Turbo](https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo) | `turbo_*` and `ref2v_*` (Turbo LoRA loader and sampler) |
| [comfyui-minimax-h3-audio-T8](https://github.com/T8mars/comfyui-minimax-h3-audio-T8) | `ref2v_*` (Dual-Clock T8 sampler) |
| [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) | the Sage files (`PathchSageAttentionKJ`), plus the SageAttention package installed |
| [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) | `ltx25_*` (tiled VAE decode) |

**Models, by file name:**

| Model | Used by | Source |
| --- | --- | --- |
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `turbo_*`, `pika_*` | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` (text encoder) | all H3 files | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) |
| `minimax_h3_video_vae_fp16.safetensors`, `minimax_h3_audio_vae_fp32.safetensors` | all H3 files | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) |
| `minimax_h3_video_vae_int8_convrot.safetensors` | `turbo_v4_int8_*`, `pika_*`, `ref2v_*` | INT8 video VAE released with the int8 H3 models |
| `minimax_h3_turbo_v4_step600_ema.safetensors` (Turbo v4 LoRA) | `turbo_*`, `ref2v_*` | [larryvrh/MiniMax-H3-Turbo-Lora](https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora) |
| `pika_h3_flex_fl2va_comfy_bf16.safetensors` | `pika_*` | Pika-Labs/Pika-H3-Flex (`comfy/loras`) |
| `Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors`, `h3-realism-people-t2v-i2v-r2v.safetensors` | `ref2v_*` | Singularity Ref2V v1.3 and its people realism LoRA |
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors`, `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors`, `ltx-2.5-video-vae-bf16.safetensors`, `ltx-2.5-audio-vae-bf16.safetensors` | `ltx25_*` | LTX 2.5 ComfyUI release |

**On a 10 GB card** the tests used ComfyUI with `--reserve-vram 0.9 --enable-dynamic-vram --async-offload 2`, and
nothing else on the GPU. A game launcher or browser using the GPU pushes H3 past about 9.7 GB, and then it spills to
shared memory and runs 2-4× slower.

## Repeat the tests on your machine

Give `docs/H3_PERFORMANCE_TESTS_RTX3080.md` to your coding agent. It describes how the tests were run, every result,
and a checklist for repeating them on another GPU. It is written so an agent can follow it.
