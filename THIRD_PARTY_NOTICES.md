# Third-party notices

The MIT license in `LICENSE` covers the bridge code in this repository only.
The following files are downloaded or cloned into `.runtime`; they are not
stored in this Git repository. Each user must review the current license and
terms before downloading them.

| Component | Pinned source | License or terms |
|---|---|---|
| ComfyUI | `Comfy-Org/ComfyUI`, pinned in `manifests/dependencies.json` | [ComfyUI license](https://github.com/comfyanonymous/ComfyUI/blob/master/LICENSE) |
| MiniMax H3 weights | `Comfy-Org/MiniMax-H3` | [Hugging Face model card and terms](https://huggingface.co/Comfy-Org/MiniMax-H3) |
| MiniMax H3 Turbo LoRA | `larryvrh/MiniMax-H3-Turbo-Lora` | [Upstream model card](https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora) |
| Spectrum node | `xmarre/ComfyUI-Spectrum-MiniMax-H3` | [Upstream repository](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3) |
| ClipProj node and weights | `nicolab28/ComfyUI-ClipProj` and linked model sources | [Upstream repository](https://github.com/nicolab28/ComfyUI-ClipProj) |
| Official workflows | `Comfy-Org/workflow_templates` | [ComfyUI repository terms](https://github.com/comfyanonymous/ComfyUI/blob/master/LICENSE) |
| PyTorch and CUDA wheels | PyTorch package index, versions in `manifests/python-lock.txt` | [PyTorch terms](https://github.com/pytorch/pytorch/blob/main/LICENSE) and NVIDIA CUDA terms |
| React, Vite, TypeScript, and dependencies | `package-lock.json` | Each package license is recorded by npm metadata |

The bridge does not enable paid API nodes, SageAttention, or Funnel. Model
licenses may have extra usage limits; a successful SHA-256 check does not mean
that a user has accepted those terms.
