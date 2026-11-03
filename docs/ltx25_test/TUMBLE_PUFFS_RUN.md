# Tumble Puffs — cast and first animation sample

Authorized by the user's “Go” after the new-series proposal. No AGY or
delegated agents. Night Train remains stopped.

## Deliverables

1. Cast lineup: Pip, Momo and Tiki, generated directly with built-in ImageGen.
2. Opening shot: Pip beside the red cushion in Bounce Patch, derived from
   the ImageGen cast with built-in ImageGen, preserving the coral character.
3. One six-second animated gag: Pip presses the cushion, its spring-back
   gently bops the chin, and surprise becomes a delighted grin and giggle.
   LTX High, 1888×1056, 8 steps, sharp decode, opening-image mode, generated
   sound. The camera holds on the action.

The user supplies visual feedback. Basic media verification records dimensions,
24 fps, audio, decoded frame count and a full FFmpeg decode. There is no
automatic creative rejection loop or multi-method pilot batch.

## Files and execution

- Media and exact submission journal: `state/tumble_puffs/`.
- Runner: `docs/ltx25_test/tumble_puffs_execute.py`.
- Built-in ImageGen does not expose a seed through this tool. Exact image
  prompts are saved in `state/tumble_puffs/imagegen-prompts.json`.
- Gag seed: 1023603.
- Video rendering is submitted through `http://127.0.0.1:8787`; stills use
  built-in ImageGen directly, following the user's correction.
- No application source, saved workflow, package or runtime setting is changed.
- POST requests are not automatically retried.

The first short remains outlined in `TUMBLE_PUFFS_DIRECTION.md`. This run
creates the cast and one concrete animation sample so the user can respond
to actual output before the short expands.

## State

Built-in ImageGen cast and opening images are complete:
`state/tumble_puffs/cast-imagegen-v1.png` and
`state/tumble_puffs/opening-imagegen-v1.png`.
The earlier app-generated cast and opening are retained as unused attempts.
The runner now refuses app image submissions. The six-second animation uses
the direct ImageGen opening image and is complete:
`state/tumble_puffs/gag_01.mp4`, app job
`a857ca583bce433a9389470ae6736820`, seed 1023603.

Basic media proof passed: 1888×1056, 24 fps, 145 decoded frames,
6.041667 seconds, AAC audio, full FFmpeg decode. The proof is
`state/tumble_puffs/gag_01_proof.json`; a 2 fps contact sheet is
`state/tumble_puffs/gag_01_contact.png`. No subjective visual or listening
acceptance is claimed; feedback belongs to the user.

The final image provider is **built-in ImageGen**. Exact cast and opening
prompts are in `state/tumble_puffs/imagegen-prompts.json`; the video prompt
and settings are in `state/tumble_puffs/execution.json`.
