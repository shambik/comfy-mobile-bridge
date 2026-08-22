---
name: h3-environment-bootstrap
description: Windows setup and runtime separation rules for the H3 bridge, ComfyUI, models, state, and Tailscale.
---

# H3 environment bootstrap

## Trigger

Use this skill when a user clones the bridge, asks to install it, changes the
local runtime, repairs dependencies, or asks why bootstrap or doctor failed.

## Goal

Build one self-contained Windows runtime under .runtime and keep the bridge,
ComfyUI, models, state, and Tailscale identity separate from every other
machine.

## Required order

1. Run .\scripts\preflight.ps1 -Json.
2. Read THIRD_PARTY_NOTICES.md and get user approval for applicable licenses.
3. Run .\scripts\bootstrap.ps1 -Profile Full -AcceptLicenses.
4. Run .\scripts\start.ps1.
5. Run .\scripts\doctor.ps1 -Deep, then check http://127.0.0.1:8787/api/health.

Use .\scripts\bootstrap.ps1 -DryRun in CI or before a real install. Never
download a model by hand into Git. The installer writes a .part file,
supports resume, checks exact bytes and SHA-256, and moves it only after a
successful check.

## Layout and rules

- ComfyUI code: .runtime/comfyui.
- Python: .runtime/python.
- Models: .runtime/models.
- App state and logs: state/.
- Local settings: ignored config.local.json.
- Bridge and ComfyUI bind only to 127.0.0.1.
- Tailscale Serve is allowed; Funnel is forbidden.

## Failure handling

Exit 2 means the computer or tool requirements failed. Exit 3 means the user
must log in to Tailscale or approve terms. Exit 4 means a pin, download, size,
hash, or dependency failed. Exit 5 means startup or health failed. Preserve
.part files and logs. Do not delete a wrong final model; stop and report it.

## Verification

Do not report success until preflight, manifest validation, doctor, API health,
and the requested tests pass. A model hash, API check, GPU render, FFmpeg
decode, and private second-device access are separate proofs.
