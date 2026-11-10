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
| Engine models (Fused SLA, Singularity, Pika, FastH3 Omni, LTX-2.5 and 2.3, character swap, RIFE, FILM, Real-ESRGAN) | Each repository and revision in `manifests/models.json`, listed in `docs/MODELS_AND_NODES.md` | Each model card; LTX-2.5 is gated behind Lightricks' terms; Real-ESRGAN is BSD-3-Clause |
| Engine node packs | MAINodes, PlagueKind sparse nodes, ComfyUI-LTXVideo, h3-relay (GPL-3.0), Viggle Remake nodes (Apache-2.0), pinned in `manifests/dependencies.json` | Each upstream repository |
| Fused SLA workflows | `MATLOWAI/minimax-h3-fused-turbo-int8-convrot`, `workflows/` | The model card |
| PyTorch and CUDA wheels | PyTorch package index, versions in `manifests/python-lock.txt` and `manifests/python-lock-engines.txt` | [PyTorch terms](https://github.com/pytorch/pytorch/blob/main/LICENSE) and NVIDIA CUDA terms |
| React, Vite, TypeScript, and dependencies | `package-lock.json` | Each package license is recorded by npm metadata |

The bridge does not enable paid API nodes or Funnel. SageAttention is installed for the per-job Sage and sparse
options and is never on by default. Model
licenses may have extra usage limits; a successful SHA-256 check does not mean
that a user has accepted those terms.

The Native AudioLock node under `custom_nodes/` is bridge code covered by the
MIT license above. It is not copied from the optional upstream experiment.

Character swap (issue #46) uses pieces the user installs into ComfyUI; none are stored in this repository:
Viggle Remake (`Viggle/Viggle-Remake`: swap weights under Viggle's own terms, ComfyUI nodes under Apache-2.0),
H3 Relay (`akatz-ai/h3-relay`, GPL-3.0: akatz's character-swap graph is read from its installed folder, not copied),
the akatz character-swap LoRA (`akatz-ai/MiniMax-H3-Character-Swap-LoRA`), the lightx2v FL2V Turbo 8-step LoRA
(`lightx2v/Minimax-h3-Turbo`) and SAM 3.1 (`Comfy-Org/sam3.1`). The Viggle swap graph is written in this
repository's own code. Review each license and model card before installing.
