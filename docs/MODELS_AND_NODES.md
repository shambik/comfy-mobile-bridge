# Models, nodes and packages

Everything the app downloads or clones besides its own code, where it comes from and which engine needs it.
The tables are generated from `manifests/models.json` and `manifests/dependencies.json`; every file is pinned to a
public revision with its exact size and SHA-256, taken from the files the app ran on the reference machine
(RTX 3080 10 GB, ComfyUI 0.44, 2026-11-10) and matched against the public copy. Image Lab is not covered.

## Installing

```powershell
.\scripts\bootstrap.ps1 -Profile Full -AcceptLicenses              # every default group
.\scripts\bootstrap.ps1 -Profile Full -AcceptLicenses -Groups pika,swap_viggle   # h3 plus the named groups
.\scripts\bootstrap.ps1 -DryRun -Groups ltx25                                  # sizes only, changes nothing
```

- `h3` is always installed; a group also brings the groups it needs.
- Each file is downloaded to a `.part` file, resumed if interrupted, checked for size and SHA-256 and only then
  moved into place. A file already present with the wrong hash stops the install; nothing is overwritten.
- **Gated:** the LTX-2.5 repositories ask you to accept Lightricks' terms on Hugging Face first. Accept them on
  the model pages, then set `HF_TOKEN` (a read token) for the bootstrap run. The token goes to curl in a header
  file that is deleted right after; it is never written to the repository.
- `.\scripts\doctor.ps1 [-Deep] [-Groups ...]` checks the same groups (`-Deep` re-hashes every file).

## Groups

| Group | Engines | Size | Needs | Default |
|---|---|---|---|---|
| `h3` | MiniMax H3 base: H3 standard and Turbo (opening frame, first + last frame, reference, lip-sync), H3 stills, Native AudioLock | 62.4 GB | - | yes |
| `h3_int8_vae` | H3 int8 video decoder: Singularity, Pika, FastH3 Omni, int8 VAE option | 3.0 GB | `h3` | yes |
| `fused_sla` | H3 Fused SLA: Fused SLA direct, I2V/FL2V, Ref2VA, DeRoPE, DyRoPE | 19.6 GB | `h3` | yes |
| `singularity` | Singularity realistic skin: Singularity reference | 21.5 GB | `h3`, `h3_int8_vae` | yes |
| `pika` | Pika H3 Flex: Pika, Pika Turbo 4-step | 7.3 GB | `h3`, `h3_int8_vae` | yes |
| `omni` | FastH3 OmniRef: FastH3 Omni | 20.7 GB | `h3`, `h3_int8_vae` | yes |
| `ltx25` | LTX-2.5 (gated): LTX lip-sync, LTX opening frame and first + last frame (official templates) | 37.0 GB | - | yes |
| `ltx25_reference` | LTX-2.5 reference (gated): LTX reference 2.5 | 1.2 GB | `ltx25` | yes |
| `ltx23_reference` | LTX-2.3 reference: LTX reference 2.3 | 40.6 GB | - | yes |
| `swap_viggle` | Character swap: Viggle Remake: Character swap (Viggle Remake) | 19.5 GB | `h3` | yes |
| `swap_akatz` | Character swap: akatz: Character swap (akatz V1.5) | 3.6 GB | `h3` | yes |
| `post_process` | Upscale and smoothing: RIFE and FILM smoothing, Real-ESRGAN upscale | 151 MB | - | yes |
| `h3_detail` | RTX VSR + H3 detail: the upscale sheet's H3 detail pass (a node pack; it uses the `h3` and `pika` models) | 0 B | `h3`, `h3_int8_vae`, `pika` | yes |
| `h3_edit` | H3 video edit LoRAs: H3 edit (text edit, outfit from photos, style, head swap) | 2.4 GB | `h3`, `h3_int8_vae` | yes |
| `h3_motion` | H3 motion transfer: motion transfer in the edit sheet (pose ControlNet, SDPose, RT-DETR) | 4.0 GB | `h3`, `h3_int8_vae`, `h3_edit` | yes |
| `clipproj_spectrum` | ClipProj and Spectrum (not ready on ComfyUI 0.44; off by default): Spectrum speed-up, ClipProj text encoder | 5.0 GB | `h3` | no |

All default groups together: 242.9 GB of models.

`clipproj_spectrum` is off by default: ClipProj and Spectrum do not load on ComfyUI 0.44, the app shows
both as not ready, and nothing in the tested setup uses them. They stay listed for an older ComfyUI.

## Model files

### `h3`: MiniMax H3 base

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `models/diffusion_models` | 19.5 GB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) `014cd40f7e` |
| `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | `models/diffusion_models` | 19.5 GB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) `014cd40f7e` |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders` | 14.6 GB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) `014cd40f7e` |
| `minimax_h3_video_vae_fp16.safetensors` | `models/vae` | 4.9 GB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) `014cd40f7e` |
| `minimax_h3_audio_vae_fp32.safetensors` | `models/vae` | 577 MB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) `014cd40f7e` |
| `minimax_h3_turbo_4step_ema_ckpt850.safetensors` | `models/loras` | 744 MB | [larryvrh/MiniMax-H3-Turbo-Lora](https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora) `43a74557ac` |
| `minimax_h3_turbo_v4_step600_ema.safetensors` | `models/loras` | 744 MB | [larryvrh/MiniMax-H3-Turbo-Lora](https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora) `43a74557ac` |
| `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | `models/loras` | 1.8 GB | [lightx2v/Minimax-h3-Turbo](https://huggingface.co/lightx2v/Minimax-h3-Turbo) `5d1d4829fe` |
| `h3_silu_temb_grid.safetensors` | `ComfyUI/custom_nodes/ComfyUI-MiniMax-H3-Turbo` | 5 MB | [Larryvrh/ComfyUI-MiniMax-H3-Turbo](https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo) `55fee864dd` |

### `h3_int8_vae`: H3 int8 video decoder

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `minimax_h3_video_vae_int8_convrot.safetensors` | `models/vae` | 3.0 GB | [Kijai/MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental) `c2e7b89b18` |

### `fused_sla`: H3 Fused SLA

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `minimax_h3_fused_refdelta_r1024_turbo8_mystic07_int8_convrot.safetensors` | `models/diffusion_models` | 19.5 GB | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` |
| `minimax_h3_temporal_expansion_step375_r16.safetensors` | `models/loras/minimax_h3` | 60 MB | [MATLOWAI/MiniMax-H3-Motion-Adapter](https://huggingface.co/MATLOWAI/MiniMax-H3-Motion-Adapter) `42cbd13e6e` |

### `singularity`: Singularity realistic skin

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors` | `models/diffusion_models` | 19.5 GB | [WarmBloodAban/Minimax-h3_Singularity](https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity) `1259cf16cd` |
| `h3-realism-people-t2v-i2v-r2v.safetensors` | `models/loras` | 125 MB | [fal/MiniMax-H3-Realism-People-LoRA](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA) `039cc8579d` |
| `minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors` | `models/loras` | 1.8 GB | [lightx2v/Minimax-h3-Turbo](https://huggingface.co/lightx2v/Minimax-h3-Turbo) `30f485ed87` |

### `pika`: Pika H3 Flex

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `pika_h3_flex_ref2va_comfy_bf16.safetensors` | `models/loras` | 1.8 GB | [Pika-Labs/Pika-H3-Flex](https://huggingface.co/Pika-Labs/Pika-H3-Flex) `ca45d99f9b` |
| `pika_h3_flex_fl2va_comfy_bf16.safetensors` | `models/loras` | 1.8 GB | [Pika-Labs/Pika-H3-Flex](https://huggingface.co/Pika-Labs/Pika-H3-Flex) `ca45d99f9b` |
| `pika_h3_flex_turbo_4step_fl2va.safetensors` | `models/loras` | 3.6 GB | [Pika-Labs/Pika-H3-Flex-Turbo-LoRA](https://huggingface.co/Pika-Labs/Pika-H3-Flex-Turbo-LoRA) `dcacd93a50` |

### `omni`: FastH3 OmniRef

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `fasth3_omniref_8step_pruned_int8_convrot.safetensors` | `models/diffusion_models` | 20.7 GB | [FastVideo/FastH3-Omni-Comfy](https://huggingface.co/FastVideo/FastH3-Omni-Comfy) `82eff2a6ee` |

### `ltx25`: LTX-2.5

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `models/diffusion_models` | 20.0 GB | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) `e8dc69fd26` |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `models/text_encoders` | 14.3 GB | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) `7597fb305b` |
| `ltx-2.5-video-vae-bf16.safetensors` | `models/vae` | 1.4 GB | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) `e8dc69fd26` |
| `ltx-2.5-audio-vae-bf16.safetensors` | `models/vae` | 348 MB | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) `e8dc69fd26` |
| `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | `models/latent_upscale_models` | 950 MB | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) `e8dc69fd26` |

### `ltx25_reference`: LTX-2.5 reference

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `ltx-2.5-22b-ic-lora-ingredients-0.9.safetensors` | `models/loras` | 1.2 GB | [Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients) `12040e4091` |

### `ltx23_reference`: LTX-2.3 reference

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `ltx-2.3-22b-dev-fp8.safetensors` | `models/checkpoints` | 27.1 GB | [Lightricks/LTX-2.3-fp8](https://huggingface.co/Lightricks/LTX-2.3-fp8) `91eda216f8` |
| `ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors` | `models/loras` | 2.6 GB | [Comfy-Org/ltx-2.3](https://huggingface.co/Comfy-Org/ltx-2.3) `f20f3a5437` |
| `ltx-2.3-22b-ic-lora-ingredients-0.9.safetensors` | `models/loras` | 1.2 GB | [Comfy-Org/ltx-2.3](https://huggingface.co/Comfy-Org/ltx-2.3) `f20f3a5437` |
| `gemma_3_12B_it_fp4_mixed.safetensors` | `models/text_encoders` | 8.8 GB | [Comfy-Org/ltx-2](https://huggingface.co/Comfy-Org/ltx-2) `ccde4ba417` |
| `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | `models/latent_upscale_models` | 950 MB | [Lightricks/LTX-2.3](https://huggingface.co/Lightricks/LTX-2.3) `c1521179de` |

### `swap_viggle`: Character swap: Viggle Remake

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `viggle_remake_swap_pruned_int8_convrot.safetensors` | `models/diffusion_models` | 19.5 GB | [Viggle/Viggle-Remake](https://huggingface.co/Viggle/Viggle-Remake) `7e5be14370` |

### `swap_akatz`: Character swap: akatz

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors` | `models/loras/character_swap` | 1.8 GB | [lightx2v/Minimax-h3-Turbo](https://huggingface.co/lightx2v/Minimax-h3-Turbo) `30f485ed87` |
| `h3_character_swap_v1.5.safetensors` | `models/loras/character_swap` | 148 MB | [akatz-ai/MiniMax-H3-Character-Swap-LoRA](https://huggingface.co/akatz-ai/MiniMax-H3-Character-Swap-LoRA) `96ea3407b2` |
| `sam3.1_multiplex_fp16.safetensors` | `models/checkpoints` | 1.6 GB | [Comfy-Org/sam3.1](https://huggingface.co/Comfy-Org/sam3.1) `7bb8374780` |

### `swap_openjutsu`: Character swap: Openjutsu

Needs `swap_akatz` for SAM 3.1 and `h3_edit` for the DMAD 4-step LoRA; the H3 model, text encoder and VAEs are the `h3` ones.

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `qwen3vl_8b_int8_convrot.safetensors` | `models/text_encoders` | 8.7 GB | [Comfy-Org/Qwen3-VL](https://huggingface.co/Comfy-Org/Qwen3-VL) `02f0d3eefb` |

### `h3_edit`: H3 video edit LoRAs

Runs on the `h3` Ref2VA int8 model, text encoder and VAEs; these four LoRAs are the only new files.

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `minimax_h3_vfx_edit_v1.0_r128.safetensors` | `models/loras/h3_edit` | 1.2 GB | [Alissonerdx/Minimax-H3-ComfyUI](https://huggingface.co/Alissonerdx/Minimax-H3-ComfyUI) `db85bdf94e` |
| `minimax_h3_style_transfer_v1.0_r64.safetensors` | `models/loras/h3_edit` | 592 MB | [Alissonerdx/Minimax-H3-ComfyUI](https://huggingface.co/Alissonerdx/Minimax-H3-ComfyUI) `db85bdf94e` |
| `minimax_h3_head_swap_v1.0_r32.safetensors` | `models/loras/h3_edit` | 296 MB | [Alissonerdx/Minimax-H3-ComfyUI](https://huggingface.co/Alissonerdx/Minimax-H3-ComfyUI) `db85bdf94e` |
| `minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors` | `models/loras/h3_edit` | 350 MB | [Kijai/MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental) `c2e7b89b18` |

### `h3_motion`: H3 motion transfer

Uses the `h3` Ref2VA model and the `h3_edit` DMAD 4-step LoRA (at 0.7); the pose nodes are core ComfyUI 0.44.

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors` | `models/model_patches` | 2.1 GB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) `54472221d2` |
| `sdpose_wholebody_fp16.safetensors` | `models/checkpoints` | 1.8 GB | [Comfy-Org/SDPose](https://huggingface.co/Comfy-Org/SDPose) `acb43fbe81` |
| `rt_detr_v4-x-hgnet_fp16.safetensors` | `models/diffusion_models` | 118 MB | [Comfy-Org/SDPose](https://huggingface.co/Comfy-Org/SDPose) `acb43fbe81` |

### `post_process`: Upscale and smoothing

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `rife_v4.26.safetensors` | `models/frame_interpolation` | 22 MB | [Comfy-Org/Frame-Interpolation](https://huggingface.co/Comfy-Org/Frame-Interpolation) `aa7009be4d` |
| `film_net_fp16.safetensors` | `models/frame_interpolation` | 66 MB | [Comfy-Org/Frame-Interpolation](https://huggingface.co/Comfy-Org/Frame-Interpolation) `aa7009be4d` |
| `RealESRGAN_x2plus.pth` | `models/upscale_models` | 64 MB | [xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.1) release v0.2.1 |

### `clipproj_spectrum`: ClipProj and Spectrum (not ready on ComfyUI 0.44; off by default)

| File | Folder | Size | Source (revision) |
|---|---|---|---|
| `qwen3vl_4b_fp8_scaled.safetensors` | `models/text_encoders` | 4.9 GB | [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2) `952f49d496` |
| `h3_qwen3vl_4b_tap24.safetensors` | `models/clip_projections` | 50 MB | [NicoLab28/ClipProj-MiniMax-H3](https://huggingface.co/NicoLab28/ClipProj-MiniMax-H3) `ef89d0fc87` |
| `h3_control_identity.safetensors` | `models/clip_projections` | 50 MB | [NicoLab28/ClipProj-MiniMax-H3](https://huggingface.co/NicoLab28/ClipProj-MiniMax-H3) `ef89d0fc87` |
| `h3_control_zero.safetensors` | `models/clip_projections` | 50 MB | [NicoLab28/ClipProj-MiniMax-H3](https://huggingface.co/NicoLab28/ClipProj-MiniMax-H3) `ef89d0fc87` |

## Node packs and ComfyUI

| Repository | Group | Commit | Installed at |
|---|---|---|---|
| [ComfyUI](https://github.com/Comfy-Org/ComfyUI) | `h3` | `56f179f6c5` | `.runtime/comfyui` |
| [MiniMax H3 Turbo node](https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo) | `h3` | `4274783a23` | `.runtime/comfyui/custom_nodes/ComfyUI-MiniMax-H3-Turbo` |
| [Spectrum v0.2.5](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3) | `clipproj_spectrum` | `4b9a7d1163` | `.runtime/comfyui/custom_nodes/ComfyUI-Spectrum-MiniMax-H3` |
| [ClipProj](https://github.com/nicolab28/ComfyUI-ClipProj) | `clipproj_spectrum` | `ca9b325e83` | `.runtime/comfyui/custom_nodes/ComfyUI-ClipProj` |
| [Official workflow templates](https://github.com/Comfy-Org/workflow_templates) | `h3` | `2b7f823136` | `.runtime/workflow_templates` |
| [MiniMax H3 audio T8 nodes](https://github.com/T8mars/comfyui-minimax-h3-audio-T8) | `h3` | `3a23f33353` | `.runtime/comfyui/custom_nodes/comfyui-minimax-h3-audio-T8` |
| [MAINodes](https://github.com/matlowai/ComfyUI-MAINodes) | `fused_sla` | `f4868b4a08` | `.runtime/comfyui/custom_nodes/ComfyUI-MAINodes` |
| [PlagueKind sparse attention nodes](https://github.com/ethanfel/ComfyUI-PlagueKind-Nodes-only-sparse) | `fused_sla` | `fd26ffb89d` | `.runtime/comfyui/custom_nodes/ComfyUI-PlagueKind-Nodes-only-sparse` |
| [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) | `ltx25_reference`, `ltx23_reference` | `220e1d45aa` | `.runtime/comfyui/custom_nodes/ComfyUI-LTXVideo` |
| [h3-relay (GPL-3.0, akatz character swap)](https://github.com/akatz-ai/h3-relay) | `swap_akatz` | `e2a7665b6e` | `.runtime/comfyui/custom_nodes/h3-relay` |
| [MMH3 Ultimate Upscale (MIT; its tiled-diffusion file GPL-3.0)](https://github.com/bbaudio-2025/Comfyui-MMH3-UltimateUpscale) | `h3_detail` | `0a8d5ee391` | `.runtime/comfyui/custom_nodes/Comfyui-MMH3-UltimateUpscale` |
| [comfyui-h3-oneclick-swap (MIT)](https://github.com/D3voz/comfyui-h3-oneclick-swap) | `swap_openjutsu` | `e44a56e929` | `.runtime/comfyui/custom_nodes/comfyui-h3-oneclick-swap` |
| [ComfyUI-MiniMaxH3-Context-Loop (GPL-3.0)](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Context-Loop) | `swap_openjutsu` | `43afeffcc5` | `.runtime/comfyui/custom_nodes/ComfyUI-MiniMaxH3-Context-Loop` |
| [ComfyUI-Fantastic-MiniMaxH3-PromptBuilder (MIT, bridge patch)](https://github.com/Adudeguyman/ComfyUI-Fantastic-MiniMaxH3-PromptBuilder) | `swap_openjutsu` | `22e719fe89` | `.runtime/comfyui/custom_nodes/ComfyUI-Fantastic-MiniMaxH3-PromptBuilder` |

Copied from this repository by bootstrap: `custom_nodes/ComfyUI-H3-NativeAudioLock`,
`custom_nodes/ComfyUI-H3-SteadyMemory` and, with `swap_openjutsu`, `custom_nodes/ComfyUI-H3-OpenjutsuHelpers` (MIT,
bridge code). With `swap_openjutsu` bootstrap also applies `patches/fantastic-promptbuilder-empty-mask.patch`.

h3-relay is GPL-3.0. It is cloned into ComfyUI at install time and the app reads akatz's graph from that folder;
no GPL file is stored in this MIT repository.

MMH3 Ultimate Upscale is MIT except `nodes/tiled_diffusion.py` (GPL-3.0, from ComfyUI-TiledDiffusion). It is
cloned at install time; the H3 detail pass does not use its tiled-diffusion node, and no file of it is stored here.

## Single files

Small files fetched from a model repository at the pinned revision:

| File | Group | Installed at | Source (revision) |
|---|---|---|---|
| `__init__.py` | `swap_viggle` | `ComfyUI/custom_nodes/ComfyUI-Viggle-Remake` | [Viggle/Viggle-Remake](https://huggingface.co/Viggle/Viggle-Remake) `7e5be14370` `comfyui/ComfyUI-Viggle-Remake/__init__.py` |
| `nodes.py` | `swap_viggle` | `ComfyUI/custom_nodes/ComfyUI-Viggle-Remake` | [Viggle/Viggle-Remake](https://huggingface.co/Viggle/Viggle-Remake) `7e5be14370` `comfyui/ComfyUI-Viggle-Remake/nodes.py` |
| `01_reference_4step_sla_lowvram.api.json` | `fused_sla` | `state/h3-new-flow/official` | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` `workflows/lowvram/01_reference_4step_sla_lowvram.api.json` |
| `02_derope_4plus4_sla.api.json` | `fused_sla` | `state/h3-new-flow/official` | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` `workflows/02_derope_4plus4_sla.api.json` |
| `02_derope_4plus4_sla_lowvram.api.json` | `fused_sla` | `state/h3-new-flow/official` | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` `workflows/lowvram/02_derope_4plus4_sla_lowvram.api.json` |
| `03_derope_dyrope_pb3049_warm375.api.json` | `fused_sla` | `state/h3-new-flow/official` | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` `workflows/03_derope_dyrope_pb3049_warm375.api.json` |
| `03_derope_dyrope_pb3049_warm375_lowvram.api.json` | `fused_sla` | `state/h3-new-flow/official` | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` `workflows/lowvram/03_derope_dyrope_pb3049_warm375_lowvram.api.json` |
| `04_i2v_fl2v_4step_sla.api.json` | `fused_sla` | `state/h3-new-flow/official` | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` `workflows/04_i2v_fl2v_4step_sla.api.json` |
| `04_i2v_fl2v_4step_sla_lowvram.api.json` | `fused_sla` | `state/h3-new-flow/official` | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` `workflows/lowvram/04_i2v_fl2v_4step_sla_lowvram.api.json` |
| `05_ref2va_4step_sla.api.json` | `fused_sla` | `state/h3-new-flow/official` | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` `workflows/05_ref2va_4step_sla.api.json` |
| `05_ref2va_4step_sla_lowvram.api.json` | `fused_sla` | `state/h3-new-flow/official` | [MATLOWAI/minimax-h3-fused-turbo-int8-convrot](https://huggingface.co/MATLOWAI/minimax-h3-fused-turbo-int8-convrot) `8a8dffaa0c` `workflows/lowvram/05_ref2va_4step_sla_lowvram.api.json` |

The Fused SLA graphs are MATLOWAI's official low-VRAM and standard API workflows, used as published; the app
sets each job's inputs (prompt, images, size, seed) on them.

## Python packages

| Lock file | What it covers |
|---|---|
| `manifests/python-lock.txt` | ComfyUI 0.44, PyTorch 2.11 (cu130) and the bridge |
| `manifests/python-lock-engines.txt` | Sage and sparse attention (`sageattention`, `triton-windows`) and ComfyUI-LTXVideo's packages |

Both are exact pins from the tested environment (Python 3.12). Packages that only Image Lab or unused nodes
pull in are left out.

## Not installed by bootstrap

| Piece | Why | How |
|---|---|---|
| Visual Enhancer (RTX VSR, FSR 3) | Windows binaries outside Hugging Face and GitHub source pins | Download from [Merserk/dlss5-visual-enhancer](https://github.com/Merserk/dlss5-visual-enhancer) and set `visual_enhancer_cli` in `config.local.json` (see `docs/WORKFLOW_GUIDE.md`) |
| An image generator for painted frames (character swap) | Your choice: Codex, a local model or by hand | `docs/CHARACTER_SWAP_GUIDE.md` |
| FFmpeg, Git, Node, Python 3.12, Tailscale | System tools | `scripts/preflight.ps1` names what is missing |

## Licences

Each model repository has its own licence or terms (most are custom "other" licences on the model card).
A matching SHA-256 does not mean you accepted them: read each source page before installing. See
`THIRD_PARTY_NOTICES.md`.
