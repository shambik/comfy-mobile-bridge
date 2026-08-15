---
name: e2e-music-video
description: Plan, generate, review, and assemble music videos from songs and lyrics using AGY plus ComfyUI T2V/I2V workflows. Use for lyric-timed music videos, storyboarded clips, sequential or independent shots, continuity review, automated regeneration, and adding the original song to the final video.
---

# E2E Music Video

Use this skill as a portable production pipeline. Keep creative decisions explicit, save every artifact, and do not start generation until the user's intent and the shot manifest are confirmed.

## Operating rules

- Ask for missing required inputs: song, lyrics, style, references, ComfyUI endpoint, models, or output location.
- Confirm the production mode: fully sequential, segmented sequential, independent shots, hybrid, or one continuous clip.
- Support T2V and I2V per shot. Keep R2V out of the default pipeline until explicitly enabled.
- Use AGY for audio/lyric analysis, reference planning, frame selection, video QC, and continuity decisions.
- Treat a completed ComfyUI job as technically successful only; AGY must approve the visual result before dependent shots continue.
- Treat generated lettering as unreliable. Avoid signs, captions, logos, labels, and screens unless intentionally required; add required readable text during post-production whenever possible.
- Preserve checkpoints so a run can resume without regenerating approved shots.
- Keep generated clips silent unless explicitly requested. Add the original song only after video assembly.

## Workflow

1. Validate environment and inputs. Use `scripts/analyze_media.py` for media metadata and frame extraction. Ask the user for anything missing.
2. Ask AGY to analyze the song, lyrics, BPM, beat grid, sections, lyric timing, energy changes, and visual opportunities.
3. Build and confirm a creative treatment, character/location bible, continuity map, and shot manifest.
4. Have AGY review references and create face-visible anchors, location frames, props, wardrobe, and lighting references.
5. Select T2V for fresh visual resets and I2V for continuity. For each I2V shot, AGY chooses between a prior last frame, a corrected extracted frame, or a fixed anchor.
6. Generate shots with `scripts/e2e_runner.py`. The runner submits jobs, extracts frames, records state, and can be wrapped by an AGY QC adapter.
7. Reject and regenerate shots that fail identity, action, lyric, composition, motion, artifact, continuity, or text-legibility review. Inspect every visible sign, caption, logo, label, and screen for gibberish or unwanted lettering.
8. Concatenate approved silent clips with `scripts/assemble_video.py`, then add the original song and trim the final output to the song duration. Validate streams and duration.
9. Deliver the final video, silent master, shot clips, prompts, references, AGY reports, manifest, and technical report.

## Default generation policy

- T2V/I2V selection is per shot.
- Turbo v4, 6 steps, 16:9, no generated audio unless overridden.
- 5 seconds: approximately 1.5 MP.
- 7–8 seconds: approximately 1 MP.
- 10 seconds: approximately 0.7 MP.
- 15 seconds: approximately 0.5 MP.

## Text legibility policy

- Prefer clean surfaces and text-free backgrounds in generation prompts.
- If the story requires readable text, specify the exact wording, language, placement, size, color, and duration in the shot manifest.
- Do not trust the model to render exact spelling. Have AGY inspect text-bearing frames and reject gibberish, duplicated letters, warped characters, or accidental logos.
- For subtitles, lyrics, title cards, signs, phone screens, or credits, prefer FFmpeg or a dedicated post-production overlay after video generation.
- Include text checks in the acceptance criteria and final technical report.

## Portable execution

The scripts use HTTP, JSON, FFmpeg, and command-line AGY integration. Agents may call them from Codex, Claude Code, AGY, OpenClaw, or another shell-capable agent. Agent-specific behavior is limited to user questions, progress display, and file presentation.

## Safety and control

Do not stop unrelated ComfyUI jobs. Before canceling a job, confirm that the user requested cancellation. Never overwrite approved artifacts; use numbered attempts. Do not add audio to individual clips when the project requires final-song assembly.
