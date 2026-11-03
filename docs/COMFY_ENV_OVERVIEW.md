# Our ComfyUI setup, and how it runs on a home PC

A short tour of how we run local AI video generation (MiniMax H3 and
Lightricks LTX 2.5) on one consumer GPU, and how we use it from a phone.
Everything runs on our own machine. There are no cloud GPUs and no paid API
nodes.

## The hardware

| Part | What we use |
| --- | --- |
| GPU | NVIDIA RTX 3080, **10 GB VRAM** |
| System RAM | 64 GB |
| OS | Windows 10 (Windows 11 also works) |
| Disk | About 100 GB free for models and the runtime |

This is the only machine we have tested. The minimum we would suggest is an
NVIDIA card with 8 GB of VRAM, 32 GB of RAM and 100 GB of free disk, but
that is untested. Some modes (LTX 2.3 reference) need about 43 GB of free
RAM, so 32 GB machines will struggle with those.

## How the pieces fit

```text
Phone (browser)
   │  private HTTPS, only inside our own Tailscale network
   ▼
Tailscale Serve ──► Bridge app  127.0.0.1:8787   (web UI + job queue + SQLite)
                         │
                         ▼
                    ComfyUI     127.0.0.1:8190   (one instance, does all GPU work)
                         │
                         ▼
                    RTX 3080 (one job at a time)
```

- **ComfyUI** is the engine. It loads the models and runs the node graphs
  ("workflows") that turn a prompt, images or audio into a video.
- **The bridge** is our own app: a Python backend and a React web UI. It
  builds the ComfyUI workflow for each job, queues jobs, tracks progress,
  stores results and serves a phone-friendly page.
- **Tailscale** lets the phone reach the bridge privately. Both servers bind
  only to `127.0.0.1`. Tailscale Serve exposes the bridge to devices in our
  own tailnet, and Funnel (public internet) is never turned on.

## The models

All weights are quantized (INT8, FP8 or 4-bit) so they fit in 10 GB. Full
BF16 versions do not fit.

| Model | Role | Format |
| --- | --- | --- |
| MiniMax H3 FL2VA / Ref2VA | Video + audio diffusion model (text, first/last frame, reference) | INT8, about 21 GB each on disk |
| Qwen3-VL 32B | H3 text encoder (the biggest single model) | NVFP4 (4-bit), about 16 GB |
| ClipProj 4B | Lighter, optional H3 text encoder | FP8 |
| H3 video and audio VAEs | Decode latents into frames and sound | INT8 / BF16 |
| H3 Turbo LoRAs (v1, v4, Ref2VA) | Cut sampling from 20+ steps down to 4–8 | BF16 |
| LTX 2.5 22B distilled | Second video engine, makes video and sound in 8 steps | INT8 |
| Gemma 12B | LTX text encoder | INT8 |

The H3 set alone is about 72 GB on disk. The LTX files add more.

A trick that matters: ComfyUI does not need the whole model in VRAM at once.
It keeps weights in system RAM and streams them to the GPU as needed. That is
why 64 GB of RAM matters almost as much as the GPU.

## How it fits in 10 GB

These are the settings that make it work. Each one was measured on the 3080.

1. **ComfyUI launch flags**:
   `--reserve-vram 0.9 --enable-dynamic-vram --async-offload 2`.
   This leaves 0.9 GB for Windows and the desktop, and lets ComfyUI move
   weights between RAM and VRAM in the background.
2. **One GPU job at a time.** The bridge has a single job queue, and image
   jobs are refused while a video is rendering.
3. **One ComfyUI only.** Two ComfyUI processes fight over the same VRAM and
   both slow down or crash, so we never run a second one next to the app.
4. **Frame size cap of 2.0 megapixels** (for example 896×1600 vertical or
   1600×896 landscape). Bigger frames ran out of memory.
5. **Text encoders are offloaded** between uses, so the VRAM is free for
   sampling.
6. **Tiled VAE decode.** The final decode from latents to pixels is split into
   tiles and chunks, because decoding a whole clip at once does not fit.
7. **Models unload after 5 idle minutes**, which gives the memory back to the
   rest of the PC.
8. **Optional faster attention**: SageAttention and sparse attention (SLA).
   Together they make H3 jobs 2–4 times faster.

Measured peaks: H3 Turbo at 0.7 MP uses about 7.4 GB. LTX 2.5 at 1600×896
peaks at 9.4–9.9 GB, which is close to the limit.

## Rough render times on the 3080

For 5-second clips unless noted:

| Job | Time |
| --- | --- |
| H3 Turbo, text to video, Sage + sparse attention | about 4 min |
| H3 Turbo, image to video, sparse attention | about 5 min |
| H3 Turbo, same jobs without the speed-ups | 12–17 min |
| LTX 2.5, image to video, 896×1600 | about 3 min |
| LTX 2.5, lip-sync to an audio track | 3–4 min |
| LTX 2.5, 9-second clip, 1600×896 | 9–14 min |

## What you can make

- **Text to video**: a prompt only.
- **Opening frame, closing frame, or both**: animate one still, or move from
  one image to another.
- **Reference**: keep a character, outfit or place consistent from reference
  images.
- **Lip-sync**: a character sings or talks to an uploaded audio track.
- **Connected sequences**: several clips where each starts on the last frame
  of the one before.
- **Still images** through the same ComfyUI.

LTX also generates matching sound (ambience and foley) with the video.

## Software stack (what we actually run)

The app runs on an existing ComfyUI install with its own Python virtual
environment. Every time and VRAM number in this file came from this stack:

| Component | Version |
| --- | --- |
| GPU driver | NVIDIA 610.88 |
| Python | 3.10.6 (in a dedicated venv; nothing in the system Python) |
| PyTorch | 2.11.0 + CUDA 13.0 (torchvision 0.26, torchaudio 2.11) |
| SageAttention | 1.0.6, with triton-windows 3.6 |
| Nunchaku | 1.2.1 (4-bit image models in the Image Lab) |
| ComfyUI | v0.33.0 plus 24 commits (August 2026) |

Key custom nodes: MiniMax H3 Turbo, H3 Native AudioLock (keeps uploaded audio
exact for lip-sync), LTXVideo, KJNodes, VideoHelperSuite, the sparse-attention
nodes, Nunchaku and MagCache. The install also has general-purpose node
packs (Impact Pack, rgthree, Easy Use and others) that the app does not need.

The bridge app itself is Python (FastAPI) and a React UI built with
Node.js 22+. It also needs Git, FFmpeg/ffprobe and Tailscale.

## Setting it up

A bootstrap script does the whole install into a self-contained `.runtime`
folder: ComfyUI, the custom nodes, the Python environment and the models. It
downloads every model with resume support and checks its exact size and
SHA-256 before using it.

**A fresh install is not the same as our stack.** Bootstrap builds a new
environment from the repo's pinned list (`manifests/python-lock.txt`), which
is Python 3.12 with PyTorch 2.9.1 and CUDA 12.6, and it does not include
SageAttention. That combination has not been tested with a real render, so
expect to verify it, and install SageAttention yourself if you want the Sage
speed-ups. Matching our stack exactly means Python 3.10, PyTorch 2.11 with
CUDA 13.0, and a recent NVIDIA driver.

```powershell
git clone https://github.com/shambik/comfy-mobile-bridge.git
cd comfy-mobile-bridge
.\scripts\preflight.ps1 -Json        # checks GPU, RAM, disk and tools
.\scripts\bootstrap.ps1 -Profile Full -AcceptLicenses
.\scripts\start.ps1                  # starts ComfyUI and the bridge
.\scripts\doctor.ps1 -Deep           # health check
```

Read `THIRD_PARTY_NOTICES.md` before running bootstrap, because the models
and nodes have their own licenses. Each person needs their own Tailscale
login. Do not reuse someone else's tailnet.

## Running it on different hardware

- **Bigger card (16–24 GB or more):** it will run as is, just more
  conservatively than it needs to. You can drop the dynamic-VRAM and offload
  flags, use fewer decode tiles, raise the 2 MP cap, and try BF16 models for
  better quality. Change one thing at a time and compare against the same
  job with the same seed.
- **8 GB card:** use smaller frames and the ClipProj encoder, keep clips
  short, and skip LTX 2.3 reference. This is untested.
- **Less than 64 GB of RAM:** expect slower model swaps, and skip LTX 2.3
  reference mode.
- **Not NVIDIA, or not Windows:** not supported by our scripts. ComfyUI itself
  runs on Linux, and the same ideas apply, but you would have to set it up by
  hand.

## Tips from our experience

- Close games and GPU-heavy apps while rendering. Fortnite in particular made
  jobs look stuck, so the app now shows a warning when it is running.
- If a job is suddenly much slower, check for a second ComfyUI or another app
  using VRAM before blaming the settings.
- Short clips (5–8 seconds) at about 1 MP are the reliable range on 10 GB.
  Longer or bigger clips start spilling into shared GPU memory and slow to a
  crawl.
- To compare settings, keep the prompt, seed, size, length and steps the same.
  Otherwise you are measuring noise.
