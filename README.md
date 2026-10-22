# H3 Mobile Bridge

Portable private bridge for local MiniMax H3 video generation on Windows 10/11
x64 with an NVIDIA GPU. The bridge stays on `127.0.0.1`; Tailscale Serve gives
private HTTPS access only to devices allowed in the current user's tailnet.

## Start here

| You want to… | Read |
| --- | --- |
| Install or repair it | Quick start below, then `.agents/skills/h3-environment-bootstrap/SKILL.md` |
| Understand the hardware limits, or run it on a bigger GPU | [`docs/HARDWARE_AND_VRAM.md`](docs/HARDWARE_AND_VRAM.md) |
| Use LTX (lip-sync, reference sheets, the optional fixes) | [`docs/ltx-2.5-ia2v-workflow.md`](docs/ltx-2.5-ia2v-workflow.md) |
| Reach it from a phone | [`docs/TAILSCALE.md`](docs/TAILSCALE.md) |
| Change the code (people and agents) | [`AGENTS.md`](AGENTS.md), then `.agents/skills/h3-mobile-bridge-codebase/SKILL.md` |
| Commit or release | `.agents/skills/git-standards/SKILL.md`, `.agents/skills/release-process/SKILL.md` |

## Built for a 10 GB GPU

The app is tuned for an **NVIDIA RTX 3080 with 10 GB of VRAM** (and 64 GB of
RAM): quantized INT8/FP8/4-bit models, a 2.0 MP frame cap, memory-saving
ComfyUI flags, tiled decoding and one GPU job at a time. It runs safely there
but leaves speed and quality on the table on bigger cards. See
[`docs/HARDWARE_AND_VRAM.md`](docs/HARDWARE_AND_VRAM.md) for where each setting
lives and the checklist for tuning it to other hardware.

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

## GPU conflict warning

The app checks for `FortniteClient-Win64-Shipping.exe` and displays a warning
when Fortnite is running, because it can compete with ComfyUI for GPU memory
and make a generation appear stuck. The warning does not close Fortnite.

The app's ComfyUI stop control stops only the ComfyUI process tree; it keeps
the mobile bridge running so the UI and logs remain available.

Image Lab runs on the app's own ComfyUI (port 8190), so the app never runs a
second ComfyUI. Its recipes need the image add-ons (for example Nunchaku and
MagCache) and their Python packages in that ComfyUI; the Image Lab page shows,
per recipe, any node or model that is still missing. Image Lab runs and video
jobs share the GPU one at a time: a new image run is refused while a video job
is running.

For Ref2VA Turbo, bootstrap also downloads and verifies the dedicated
`minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` LoRA. If an
existing ComfyUI installation is configured in `config.local.json`, bootstrap
preserves its root, Python, models, and media-directory paths instead of
switching them to the portable layout.

## Requirements

- Windows 10/11 x64.
- NVIDIA GPU with at least 8 GiB VRAM, 32 GiB RAM, and 100 GB free disk.
  Only an RTX 3080 10 GB with 64 GB of RAM has been tested; LTX 2.3 reference
  mode needs about 43 GB of free RAM.
- Git, Python 3.12, Node.js 22 or newer, FFmpeg/ffprobe, and Tailscale.
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

## Image workflow lab

The separate **Image lab** page can load API-format image workflows from an
external bot without executing its Python code or copying its credentials.
Set `bot_image_workflows_dir` in the ignored `config.local.json` to that bot's
`workflows` directory. The page discovers text-to-image, editing, multi-image,
ControlNet, outpainting, and upscaling graphs, then exposes the bot's prompt,
seed, steps, CFG, resolution, denoise, ControlNet, and outpainting controls.
Enumerated fields such as sampler and scheduler use choices reported by the
active ComfyUI server. Optional LoRAs use a recipe-specific multi-select menu
(for example, Goofballs); LoRAs already enabled by a recipe are listed
separately. Free text is kept only for inputs that ComfyUI defines as open-ended.
Grain and simple-upscale modes are separate workflows in the selector;
Telegram-only delivery flags are not generation parameters. Missing custom
nodes or model dropdown entries are shown per workflow before submission. The
current ComfyUI environment is never installed or changed by this page.

## Engines and modes

The Studio page makes videos in six modes: text only, opening frame, closing
frame, opening + closing frame (I2V), reference, and lip-sync to an uploaded
audio track. Engines:

| Engine | What it is |
| --- | --- |
| Turbo (default) | MiniMax H3 with a 4–12 step Turbo LoRA (v1 or v4) |
| Standard / Spectrum | MiniMax H3 with full sampling (Spectrum adds its own acceleration node) |
| H3 Fused SLA | MiniMax's official fused INT8 graphs with sparse attention (direct, I2V/FL2V, Ref2VA, de-rope variants) |
| LTX 2.5 | Lightricks LTX 2.5, 8 distilled steps, video with generated audio; reference mode offers LTX 2.5 or 2.3 recipes |

Per-job options include Sage and sparse (SLA) attention speed-ups where the
engine supports them, the ClipProj 4B text encoder as a memory saver, and for
LTX the opt-in "sharp decode" and "calm sampler" fixes. No paid API nodes are
used: ComfyUI runs with `--disable-api-nodes`.

## Studio asset library

Generated videos can be assigned to a Studio project and optional subfolder,
either before generation or afterward from the result card. These UI actions
create, move, rename, and delete the corresponding files on disk under the
canonical `state/projects/<project>/<folder>/` structure. Existing unassigned
videos remain in the configured ComfyUI output directory until organized.

See [`docs/ASSET_LIBRARY.md`](docs/ASSET_LIBRARY.md) for the filesystem rules,
safety checks, and configuration.

## Agent Production Studio POC

The **Production** page adds a responsive production council made up of the
user, Codex, and AGY. It supports persistent projects, autonomous or
interactive planning, model and reasoning selection, selectable production
skills, user messages and decisions, and pause/stop/resume checkpoints. Codex
and AGY run through the locally authenticated CLIs; their credentials never
enter the browser.

The POC carries a project through song analysis, joint treatment/storyboard
consultation, reference planning, executable shot prompts, silent ComfyUI
generation, per-attempt Codex + AGY review, bounded regeneration, hard-cut
assembly, original-song attachment, final joint review, and explicit user
approval. Production jobs use the existing ComfyUI queue and the workflow's
own duration and resolution calculator nodes; existing Studio behavior is
unchanged. Restart recovery preserves shot attempts and can reattach to an
already queued job or resume review of a completed clip.

Reference development produces an executable reference package. Codex then
uses its authenticated built-in ImageGen tool to create project-bound stills;
AGY inspects each actual image and Codex reviews AGY's findings before the
still is registered for I2V/R2V. Users can also upload their own images,
videos, and audio, assign them per shot, edit a shot, and retry only that shot
plus any dependent sequential shots. Sequential I2V shots use the previous
accepted last frame; independent I2V shots use an assigned opening image.

The Reference Media panel also supports manual still generation. Auto mode
tries Codex ImageGen and falls back to AGY ImageGen; either provider can be
selected directly. Multiple productions can advance concurrently (three by
default through `agents.production_concurrency`), while the global ComfyUI
queue intentionally keeps GPU video generation serialized.

The producer seat can run through either Codex CLI or AGY CLI. Its model list
comes from the selected authenticated runtime rather than a hardcoded UI list.
The media producer stays on AGY because audio/video inspection is required.
Productions can be reconfigured while inactive, duplicated with their shot
plan and remapped references, archived, exported, or deleted. Completed jobs
from the regular generation page can be imported into a production.

See [`docs/architecture/agent-production-studio.md`](docs/architecture/agent-production-studio.md)
and [`todo/agent-production-studio-plan.md`](todo/agent-production-studio-plan.md).

Read `.agents/skills/h3-environment-bootstrap/SKILL.md` before setup and
`.agents/skills/h3-mobile-bridge-codebase/SKILL.md` before code changes.
Read `.agents/skills/git-standards/SKILL.md` before Git work and
`.agents/skills/release-process/SKILL.md` before releases.

Bootstrap also installs the versioned production skills for Codex and AGY into
`.agents/skills`. The Production UI still decides which production skills are
enabled, and Council seats decide which specialist role is active; installed
skill bodies are read natively by the agents rather than pasted into every
request. To refresh only that project installation after editing a skill, run
`scripts\install-project-skills.ps1`.

## Proof boundaries

CI proves source build and tests. A hash report proves a downloaded file. API
health proves the bridge is responding. `ffprobe` and a full FFmpeg decode
prove media validity. GPU generation and second-device Tailscale access are
separate clean-machine acceptance proofs.

See `THIRD_PARTY_NOTICES.md` for upstream code, node, model, and license links.
