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
