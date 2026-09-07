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
