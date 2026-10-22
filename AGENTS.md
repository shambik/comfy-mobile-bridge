# H3 Mobile Bridge

Portable local MiniMax H3 and LTX video bridge for Windows and NVIDIA GPUs,
used from a phone over Tailscale. Tuned for an RTX 3080 with 10 GB of VRAM.

## Start here

1. `README.md`: what the app does, engines and modes, setup.
2. `docs/HARDWARE_AND_VRAM.md`: why every memory setting is what it is, and the
   checklist for adapting the app to a different GPU. Read it before touching
   sizes, models, tiling, ComfyUI flags or the job queue.
3. `.agents/skills/h3-environment-bootstrap/SKILL.md` for setup or repair.
4. `.agents/skills/h3-mobile-bridge-codebase/SKILL.md` before code changes.
5. `.agents/skills/git-standards/SKILL.md` before any Git operation.
6. `docs/ltx-2.5-ia2v-workflow.md` before changing anything LTX.

## Working rules

- One ComfyUI at a time. The app uses a single ComfyUI on port 8190 for
  videos, Image Lab and H3 stills. Never leave a second instance running; ask
  the user before stopping one that is busy.
- Do experiments in a separate copy (for example a lab folder with its own
  ComfyUI and venv), never in the app's ComfyUI, its Python environment or its
  workflows. Ask the user before changing the app's environment.
- Install packages only into a project or lab venv, never globally.
- Never cancel or interrupt a running job unless the user asks.
- Diagnose from evidence: logs, the jobs database, live API data, and an A/B
  against a known-good job with the same inputs and seed.
- Keep only what was tested: when a feature works only within limits (sizes,
  durations, modes), the code enforces those limits and the docs say why.
- Never commit `.runtime`, `state`, models, logs, or local config.
- Run the tests, `npm run build` and preflight before reporting success; a GPU
  result needs a real render, `ffprobe` and a full FFmpeg decode.
- GitHub: the repository is `shambik/comfy-mobile-bridge` (`origin`); pass
  `-R shambik/comfy-mobile-bridge` to `gh`, which otherwise defaults to the
  upstream fork.
