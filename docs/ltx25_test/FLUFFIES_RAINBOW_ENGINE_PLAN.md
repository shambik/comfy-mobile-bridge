# Fluffies — The Rainbow Garden Rescue (active revision)

The active plan is `state/fluffies_ep05_rainbow_engine/review_v3/`.
The user clarified that the story itself must last **120 seconds**, excluding
the selected ten-second intro and ten-second outro. The full target is
**140 seconds / 3360 frames** at 24 fps: story from 00:10 to 02:10, outro
through 02:20. Eighteen six/seven-second shots add calling for help,
preparing a strong leaf, and checking the restored water. Nine/ten-second
source requests retain three seconds of handles. No slowed clips or still
padding. The Python score was regenerated against all eighteen revised cues,
with silence during both bookends to preserve their existing music.

The wheel is removed entirely. A seedpod blocks a stationary basin outlet;
Rolo holds the leaf sling as a counterweight while Nori frees the pod.
Old wheel-bearing clips cannot be reused. New shot art and video validation
remain incomplete; no final upload has occurred. The user explicitly approved
the revised nine-second S04 test after the earlier launch was blocked by
automatic approval review. Job `4f25ac3274a9452887806a7babdaf449` was submitted
once; full motion review and the full revised batch remain pending.

The root manifest, renderer, editor and old score below are preserved draft
artifacts. Do not run those commands for this revision. Active renderer/editor
integration uses the corrected 3360-frame target. The revised `finish.py`
imports successfully and prepared both selected bookends; final assembly has
not yet been exercised against a complete set of revised story sources.

## Superseded original draft

Episode 05 is a connected two-minute story in a new floating cloud garden.
Bobo and Lulu meet orange striped Rolo, long-eared teal Nori, and indigo
comet-tailed Lumi. A runaway golden seedpod jams the irrigation engine;
failed individual attempts lead to a leaf sling, a gentle crank turn, a soft
tail cushion, and a successful shared repair. Returning water restores the
rainbow flowers. Reactions follow the emotion; laughter is reserved for relief
and celebration.

The selected `1002475080.mp4` intro and `1002475708.mp4` outro each retain
their complete ten seconds. Fifteen six/seven-second story cuts total 100
seconds. Master: exactly 2880 frames / 120 seconds, 1080p24, H.264/AAC.
Sources are the tested main-app LTX Balanced recipe with sharp decode,
calm sampler and native sound. Built-in ImageGen creates the stills. No
runtime, environment, model or saved workflow changes are needed.

The source windows include three extra seconds, initially trimmed from a
two-second in-point. Inspect body motion around every actual cut; keep each
authored action window and its payoff. Picture and native audio use the same
offset. No source-speed changes or held-frame padding. Original Python/numpy
music follows each scene, ducks under native sounds, and leaves intro/outro
themes alone. Keep all sources and previous episodes.

Production files, prompts, storyboard, score, journal and evidence are under
`state/fluffies_ep05_rainbow_engine/`. `BRIEF.md` there records the lessons
from episodes 1–4. `production-handoff.json` and `producer.pid` identify the
current producer; reconcile them before starting another copy. Renderer:
`python state/fluffies_ep05_rainbow_engine/render.py`. Review each completed
source with `qc.py Sxx --start 48` and record its actual in-point in
`motion_inpoints.json`. Finish only when every source is verified and every
in-point is reviewed:
`python state/fluffies_ep05_rainbow_engine/finish.py --publish`.

The editor validates every source and segment, exact total frames, native
sound and final full decode before publication. The complete episode is the
deliverable; a prefix must never be presented as the finished episode.
The user remains the final creative/listening reviewer. No delegated agents.
