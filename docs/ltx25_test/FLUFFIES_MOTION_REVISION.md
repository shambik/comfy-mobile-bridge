# Fluffies — motion and intro revision

**Stopped / superseded:** the user stopped this production after E07 (E08 canceled) and selected their uploaded `1002475080.mp4` opener. Do not resume this manifest. The active fresh story is [FLUFFIES_WOBBLY_SURPRISE_PLAN.md](FLUFFIES_WOBBLY_SURPRISE_PLAN.md).

## Latest user feedback

The 22-second preview opens each story shot with a visible frozen reference pose. Remove that lead-in so the cut begins during motion. The previous logo intro loses a letter. Combine characters into the intro and visibly include the new blue, pink, purple, white and grey/black characters.

## Immediate correction

`fluffies_motion_fix_preview.py` removes the first 60 frames (2.5 seconds) from E01 and E02. It produces a nine-second story-only demonstration with original native sounds and music. The superseded logo intro is omitted. Vault item: `9d5b9fe37de340989e16bf93e51968ef`. Full decode, 216 frames at 24 fps, nine seconds and HTTPS playback were verified.

The old story producer finished E04 and then stopped normally before E05. No GPU job was canceled or interrupted. Preserve `state/fluffies_ep01_shortcut/` as the source comparison; do not restart that manifest.

## Eight-character intro v4

- Source/manifest: `state/fluffies_cast_intro_app_v4/`.
- Main-app job: `2630d65f261044d98a21cf0e1c3c5181`.
- Upper cast: blue Bobo, pink Lulu, purple Zuzu, pearl-white Numi.
- Lower cast: coral Pip, yellow Momo, mint Tiki, charcoal/silver Pebble.
- The plate is a clean abstract pastel brand composition, with bouncing/waving characters and native nonverbal reactions. No garden or story scene.
- Render ten seconds through LTX opening-image mode; trim frames 48–239 for the eight-second ident.
- Composite the exact selected transparent furry `Fluffies` wordmark as one animated foreground layer. The video model never generates letters. Keep all eight glyphs visible within safe margins throughout.
- Preserve native reactions/effects and mix the original eight-second musical signature underneath.
- Finish/publish: `python docs/ltx25_test/fluffies_cast_intro_finish.py --wait`.
- Output: `state/fluffies_cast_intro_app_v4/Fluffies_All_Cast_Intro_v4_8s.mp4`.
- Completed/published: vault item `18ffd1c7ec3d471a84c72b7220b78988`, SHA-256 `0df504c8857e5e59323e98962ec19be2e25464388d42da8553e04345c43478c8`. Exactly 192 frames at 24 fps, eight seconds, H.264/AAC, full decode and private HTTPS playback passed. App source generation took 519.5 seconds, peak VRAM 9755 MiB.

The latest white/charcoal reference is `state/fluffies_cast_expansion/white-charcoal-lineup-v2.png`; it preserves the pearl-white character and adds deep charcoal/soft-black fur to Pebble while retaining a silver face. Both the earlier grey version and all source files are preserved. Exact prompts are in the cast expansion JSON records.

## Episode motion v2

- Plan builder: `docs/ltx25_test/fluffies_motion_episode_plan.py`.
- Active episode folder: `state/fluffies_ep01_shortcut_motion_v2/`.
- Retain all 14 story beats and their cast/location/prop references. Regenerate video sources with explicit immediate continuing motion and ten-second source windows.
- Each story cut uses eight seconds after a two-second source lead-in: 14 × 192 frames = 2688 story frames. Intro 192 + story 2688 = 2880 frames / 120 seconds.
- Exact trims live per shot in `trim_start_frame` and `edit_frames`; native audio receives the identical start offset and duration. If the user identifies another slow start, adjust that shot's actual cut rather than hiding it with an establishing pause.
- Main app only, one ComfyUI, existing Balanced landscape, eight steps, sharp decode enabled, calm sampler disabled, native audio enabled. No runtime/environment/model/workflow edits.
- User is the visual/listening reviewer. No AGY, subagents or strict inspection gates.

Resume commands:

```powershell
python docs/ltx25_test/tumble_puffs_ep01/episode_runner.py render --out state/fluffies_ep01_shortcut_motion_v2
python docs/ltx25_test/fluffies_shortcut_finish.py --out state/fluffies_ep01_shortcut_motion_v2 --wait --publish
```

The first command journals each app job before polling/downloading and stops on uncertain or failed submissions. The second waits for verified sources, uses exact picture/audio trims, hard cuts, the protected eight-character ident and original instrumental music, then validates and publishes the master. It never submits or cancels GPU jobs.

Do not launch a second copy of an already-running producer/editor. Reconcile journal IDs before retrying any uncertain POST. The old berry run remains stopped after S15. No commits, app package installs or runtime changes are required.

## Verification

The delivered v4 intro and nine-second motion correction passed ffprobe, full FFmpeg audio/video decode, exact frame counts and private HTTPS range playback. `npm run build` and preflight passed. The repository suite ran 302 tests: 301 passed; the existing `test_required_agent_instruction_layout_exists` failure expects at most 20 AGENTS.md lines while the user's file has 38. The user's instructions were preserved. Logs are under `state/fluffies_cast_intro_app_v4/`.
