# Night Train execution — 2026-10-23

**Stopped by the user on 2026-10-23. Do not resume this production.**
The user rejected the results and requested a new series approach informed
by Sunny Bunnies. The submission driver was stopped and the active
P2_smooth job was canceled through the bridge; cancellation was confirmed.
No Night Train production clips were started. Completed assets are retained.

Source: `NIGHT_TRAIN_PLAN.md`. All nine keyframes and the character sheet
were completed, followed by six completed pilot clips. The smooth-motion
pilot was canceled. The sound-bed and music pilots were not submitted.

User steering: no AGY or delegated agents, and no strict visual inspection
gates. Generate the documented deliverables and execute; the user will be
the visual reviewer. Retain basic file-integrity checks and measured pilot
comparisons. Listening and visual judgements must not be presented as verified.

All render submissions use the bridge at `127.0.0.1:8787`. No application
code, saved workflows, models, packages or runtime settings have been changed.
Generated media and exact submission records are in `state/night_train/`;
the durable journal is `state/night_train/execution.json`. A submission is
never automatically retried.

## Keyframe preparation

- Selected creation recipe: Flux Krea, `krea_t2i_simplified_workflow.json`.
- Selected editing recipe: Qwen Image Edit 2509, `qwen2509_i2i_1input.json`.
- Both recipes passed the live Image Lab compatibility check.
- The first corridor master rendered in 67.8 seconds, seed 102300, at
  1600×896. Review found an early duckling and windows on the left wall.
  Its original is retained as `K0_master_raw.png`; the targeted correction
  completed. `K0_exact` then rendered at native 1600×896 in 165.2 seconds,
  using the recipe's exposed empty-latent size selector.
- Dining-car master: 71.2 seconds. Luggage-van master: 63.6 seconds.
  Character sheet: 50.9 seconds. All six derived keyframes completed.
- All K0–K8 files are natively 1600×896. The contact sheet is
  `state/night_train/keyframes_contact.png`; a nine-frame strip is
  `state/night_train/keyframes_strip.png`.
- One edit payload was rejected before queueing because the app treats the
  image-scale `megapixels` override as an integer. Removed that optional
  override; the requested output resolution remains 1600×896. This is a
  recorded payload correction, not a GPU retry or application change.

## Verification

- Frontend `npm run build`: passed.
- Tests: 300 of 301 passed using the configured bridge Python. The existing
  portability assertion requiring AGENTS.md to have at most 20 lines failed
  (the supplied file has 38 lines). The default system Python lacks FastAPI;
  that first invocation was replaced with the configured-Python run.
- Preflight: exit 3, Tailscale login/hostname unavailable.
- Doctor: exit 5, reports the existing all-interface app binding, runtime pin
  differences, missing optional ClipProj files and Tailscale configuration.
- Live bridge health: ready; LTX and the selected image recipes are ready.
- ComfyUI: one launcher/child process tree on 8190; queue was empty at start.

Pilot decisions will be published in `PILOT_RESULTS.md` after actual renders,
measurements and review. No pilot result or final episode is claimed yet.
