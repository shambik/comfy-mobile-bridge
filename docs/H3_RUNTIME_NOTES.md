# H3 runtime notes

The bridge is configured to use the faster ComfyUI environment:

`D:\Repos\ComfyUI_venv\ComfyUI\venv_h3_torch211_cu130\Scripts\python.exe`

Observed environment on 2026-08-15:

- Python 3.10.6
- PyTorch 2.11.0+cu130
- CUDA runtime 13.0
- CUDA available: yes
- GPU: RTX 3080 10 GB

The direct ComfyUI run that behaved well used these launch flags:

```text
--listen 127.0.0.1 --port 8188 --disable-auto-launch
--reserve-vram 0.9 --enable-dynamic-vram --async-offload 2
```

The bridge launcher now uses the same VRAM/offload settings. This is an observation from this machine, not a universal benchmark. During testing, a Turbo v4 run at 0.7 MP, 5 seconds, and 6 steps progressed normally with roughly 7.35 GB of GPU memory in use and full GPU utilization. The observed practical range was also that 5–8 second clips at 1 MP can run acceptably in this environment.

## Ref2VA Turbo LoRA

Ref2VA Turbo uses a dedicated LoRA; the regular FL2VA Turbo v1/v4 files are not substitutes:

```text
minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors
```

The setup manifest downloads it into `ComfyUI\models\loras` and verifies 1,956,193,000 bytes plus SHA-256 `5b9ab5ade15d0775676d01a907268a69a1468dc6033b3b0d3ded5502f3ebb84c`. Bootstrap now explicitly checks this entry and preserves explicit existing-ComfyUI paths in `config.local.json`; a fresh machine still uses the portable layout by default.

For reproducible comparisons, keep the model, ComfyUI revision, venv, resolution, duration, steps, and launch flags identical. A different workflow, stale process, model load, or memory pressure can dominate the timing.
