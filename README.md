# H3 Mobile Bridge

Portable private bridge for local MiniMax H3 video generation on Windows 10/11
x64 with an NVIDIA GPU. The bridge stays on `127.0.0.1`; Tailscale Serve gives
private HTTPS access only to devices allowed in the current user's tailnet.

## Quick start

```powershell
git clone https://github.com/shambik/comfy-mobile-bridge.git comfy-mobile-bridge
Set-Location .\comfy-mobile-bridge
.\scripts\preflight.ps1 -Json
Get-Content .\THIRD_PARTY_NOTICES.md
.\scripts\bootstrap.ps1 -Profile Full -AcceptLicenses
.\scripts\start.ps1
.\scripts\doctor.ps1 -Deep
```

The bootstrap downloads pinned ComfyUI, custom nodes, Python packages, FFmpeg
checks, Tailscale checks, and external model files. It never stores models,
runtime files, state, logs, or local configuration in Git.

For Ref2VA Turbo, bootstrap also downloads and verifies the dedicated
`minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` LoRA. If an
existing ComfyUI installation is configured in `config.local.json`, bootstrap
preserves its root, Python, models, and media-directory paths instead of
switching them to the portable layout.

## Requirements

- Windows 10/11 x64.
- NVIDIA GPU with at least 8 GiB VRAM, 32 GiB RAM, and 100 GB free disk.
- Git, Python 3.12, Node.js 22, FFmpeg/ffprobe, and Tailscale.
- A Tailscale login for the user who owns this computer. Do not use another
  person's tailnet or hostname.
- License review for downloaded model and node files before bootstrap.

## What bootstrap creates

```text
.runtime/
├── comfyui/
├── models/
├── python/
└── downloads/
state/
├── input/
├── output/
└── logs/
config.local.json
```

The local configuration is generated from `config.example.json`. It contains
the current machine's paths and detected Tailscale hostname and is ignored.

## Ports and private access

- Bridge: `127.0.0.1:8787`.
- ComfyUI: `127.0.0.1:8190`.
- Tailscale Serve: HTTPS to the bridge inside the current tailnet.
- Funnel is never enabled.

Use `.\scripts\doctor.ps1 -Deep` to check listeners, Serve, nodes, files,
hashes, and API health. Use `.\scripts\stop.ps1` to stop only processes
started by this bridge.

For complete Windows setup and phone-access instructions, see
[`docs/TAILSCALE.md`](docs/TAILSCALE.md).

## Development

```powershell
npm ci
npm run build
python -m unittest discover -s tests -p "test_*.py"
```

The bridge supports text-to-video, first/last-frame video, reference video,
native stereo audio, Turbo, Standard, Spectrum, and the optional ClipProj
encoder. Turbo remains the default profile. No paid API nodes and no
SageAttention are part of this release.

Read `.agents/skills/h3-environment-bootstrap/SKILL.md` before setup and
`.agents/skills/h3-mobile-bridge-codebase/SKILL.md` before code changes.
Read `.agents/skills/git-standards/SKILL.md` before Git work and
`.agents/skills/release-process/SKILL.md` before releases.

## Proof boundaries

CI proves source build and tests. A hash report proves a downloaded file. API
health proves the bridge is responding. `ffprobe` and a full FFmpeg decode
prove media validity. GPU generation and second-device Tailscale access are
separate clean-machine acceptance proofs.

See `THIRD_PARTY_NOTICES.md` for upstream code, node, model, and license links.
