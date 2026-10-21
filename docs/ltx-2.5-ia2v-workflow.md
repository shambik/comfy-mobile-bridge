# LTX-2.5 IA2V workflow

The repository keeps both representations of the supplied LTX-2.5 image-and-audio-to-video graph:

- `workflows/video_ltx2_5_ia2v_core_FIXED_api.json` is the executable ComfyUI API prompt.
- `workflows/video_ltx2_5_ia2v_core_FIXED_gui.json` is the editable regular ComfyUI workflow.

Regenerate both files while ComfyUI is running on port 8190:

```powershell
python scripts/export_ltx25_ia2v_gui_workflow.py `
  --source D:\video_ltx2_5_ia2v_core_FIXED.json
```

The exporter validates all required node classes and exact model bindings. It only reads `/object_info`; it does not queue a generation.

## Required models

Place the model files under the configured ComfyUI model root:

| Purpose | Filename | ComfyUI folder |
| --- | --- | --- |
| Transformer | `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `models/diffusion_models/` or `models/unet/` |
| Text encoder | `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `models/text_encoders/` or `models/clip/` |
| Video VAE | `ltx-2.5-video-vae-bf16.safetensors` | `models/vae/` |
| Audio VAE | `ltx-2.5-audio-vae-bf16.safetensors` | `models/vae/` |
| 2x latent upscaler | `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | `models/latent_upscale_models/` |

Restart ComfyUI after installing the files so the loader dropdowns refresh.

## LTX 2.5 lip-sync in the app

Studio's lip-sync mode offers **LTX 2.5** as an engine. It runs
`workflows/ltx25_ia2v_single_pass_api.json` on the same ComfyUI as H3: one
distilled 8-step pass at full resolution, no latent upscaler, with the
uploaded (already trimmed) audio held fixed while sampling and muxed into the
output.

| Quality | 9:16 | 16:9 | 1:1 | 4:3 | 3:4 |
| --- | --- | --- | --- | --- | --- |
| Balanced | 896×1600 | 1600×896 | 1216×1216 | 1376×1024 | 1024×1376 |
| High | 1056×1888 | 1888×1056 | 1408×1408 | 1632×1216 | 1216×1632 |

Rules enforced by the bridge: lip-sync mode only, an opening image is
required, no closing image, 1–10 seconds, fixed 8 steps. High stays inside
the app's 2.0 MP limit (the speed-lab run used 1088×1920).

Why one pass: in the speed-lab tests the two-stage graph (half-size pass,
2× latent upscale, 3-step refine) rendered sharper frames but loosened lip
timing, while one full-size pass kept the mouth in sync. Lip-sync is best when
the opening image is a close-up with the face filling most of the frame and
the prompt describes that same framing with a static camera.

The original two-stage graph above is kept for reference; the app does not
run it.

## LTX reference mode in the app

Reference mode with the LTX engine takes exactly one reference sheet (one
image laying out the characters, props and location) and offers two recipes,
each built exactly as it passed the speed-lab tests. Nothing else is
configurable: both are landscape only, render 1536×896, and accept 1–5
seconds. Longer clips, other sizes and vertical sheets failed or jumped to a
new shot mid-clip in the lab.

Both recipes run Lightricks' Ingredients IC-LoRA on the 768×448 grid it was
trained on (the sheet is letterboxed, never cropped), then upscale the latent
×2, refine it in three steps without the IC-LoRA, and decode seam-free.

| Recipe | Lab runs | Models | Sampler |
| --- | --- | --- | --- |
| LTX 2.5 (default) | R20–R22 | the LTX 2.5 files above, `ltx-2.5-22b-ic-lora-ingredients-0.9.safetensors` (`models/loras/`), the 2.5 latent upscaler | euler_ancestral |
| LTX 2.3 | R9–R14 | `ltx-2.3-22b-dev-fp8.safetensors` (`models/checkpoints/`), `ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors` at 0.5 and `ltx-2.3-22b-ic-lora-ingredients-0.9.safetensors` (`models/loras/`), `gemma_3_12B_it_fp4_mixed.safetensors` (`models/text_encoders/`), `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` (`models/latent_upscale_models/`) | euler |

The 2.5 recipe adds one line to the prompt ("The video opens directly inside
the scene…") and matching negative terms; without them LTX 2.5 opened on the
sheet itself. The line goes right after `### Target Description` or
`Generated video:` when the prompt has one. The 2.3 checkpoint stages about
43 GB of RAM, so the worker unloads resident models before a 2.3 job.

Both models sometimes open a clip on the reference sheet itself (or a zoomed
piece of it) before cutting to the scene; which seeds do it depends on the
model, not on the prompt for 2.3. Every finished reference clip is therefore
scanned by `backend/reference_check.py`. A frame is flagged when several grid
cells are nearly identical to the same cells of the letterboxed sheet (whole
sheet or a collage of its panels), or when it carries full-length black panel
gutters away from the frame edges (a zoomed piece of the sheet); cinema bars
along the top and bottom edges are ignored, since the model also renders real
scenes with them. A flagged render is renamed `rejected<N>_<name>.mp4` beside
the outputs and the job is re-rendered with a new seed, up to three renders in
total; if all three show the sheet the job fails with that reason instead of
delivering it. The seeds and flagged frames of rejected renders are kept in the
job's metrics. On 34 labelled lab and app clips (9 broken, 25 clean, two
sheets) the check flagged every broken clip and no clean one.
For 2.5, prompts in the `### Reference Sheet Description` / `### Target
Description` format needed fewer retries than `Reference sheet:` /
`Generated video:` in the lab.

## Optional decode and sampler fixes

Text, opening, closing and first+last LTX jobs offer two opt-in fixes, off by
default (lip-sync and reference mode do not use them):

- **Sharp decode** replaces the temporal-tiled `VAEDecodeTiled`, whose chunk
  joins soften a few frames every two seconds, with LTX's spatial-only
  `LTXVTiledVAEDecode` (4×2 tiles up to 5 s at 1600×896, 6×4 otherwise).
- **Calm sampler** uses `euler` instead of `euler_ancestral`, which adds fresh
  noise every step; in the lab it cut detail flicker by about 14%.

Both were proven on opening-frame clips (lab V4 vs V6–V8); the other modes
use the same graph but were not tested separately.
