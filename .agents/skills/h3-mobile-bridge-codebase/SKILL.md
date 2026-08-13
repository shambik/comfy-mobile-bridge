# H3 mobile bridge codebase

## Trigger

Use this skill before changing backend, UI, workflows, worker behavior, API
contracts, media validation, startup, or tests.

## Code map

- backend/main.py: FastAPI routes, upload validation, health, and static UI.
- backend/config.py: safe defaults and ignored local configuration.
- backend/worker.py: one owned generation queue and ComfyUI lifecycle.
- backend/comfy.py: localhost HTTP/WebSocket client and media proof.
- backend/workflows.py: H3 workflow builders and model names.
- backend/db.py: SQLite job and sequence state.
- src/: React mobile UI.
- tests/: Python API, database, worker, media, and workflow tests.

## Required patterns

Use paths from backend.config. Never calculate a path from a parent folder,
read a personal username, or hardcode a Tailscale address. Keep app and
ComfyUI hosts local. Add new settings to config.example.json, document them,
and keep config.local.json ignored.

Keep route behavior backward compatible unless the task explicitly changes the
API. Preserve SQLite and output files. Validate user media before queueing it.
Use the existing worker rather than starting an unowned process from a route.

## Change and verify

    python -m unittest discover -s tests -p "test_*.py"
    npm run build
    .\scripts\preflight.ps1 -Json
    .\scripts\doctor.ps1

For generation changes, also verify the exact node classes in /object_info,
the API health version, a valid MP4 with audio, ffprobe, and full FFmpeg
decode. Never claim a GPU or tailnet proof from a unit test.
