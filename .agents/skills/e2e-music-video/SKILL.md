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
- Apply a human-viewer QC threshold: reject only defects that are clearly visible at normal playback or materially affect identity, action, lyric alignment, continuity, or story comprehension. Do not reject a shot for an ambiguous single-frame texture, tiny distant mark, or microscopic logo variation that a normal viewer would not notice.
- Conduct AGY consultation as a visible multi-round producer dialogue: show AGY's useful response to the user, state Codex's counterproposal, then ask AGY to review the revision. Never hide the exchange in a terminal and present only a summary.
- Save AGY prompts, responses, Codex decisions, and the final agreement in a production transcript.
- Treat a completed ComfyUI job as technically successful only; AGY must approve the visual result before dependent shots continue.
- Treat generated lettering as unreliable. Avoid signs, captions, logos, labels, and screens unless intentionally required; add required readable text during post-production whenever possible.
- Preserve checkpoints so a run can resume without regenerating approved shots.
- Keep generated clips silent unless explicitly requested. Add the original song only after video assembly.
- Do not create reference images or start generation before the user approves the treatment, continuity strategy, and shot manifest. Draft references must remain clearly labeled.

## AGY structured-output guardrail

- Refresh the AGY response schema for every invocation, including resumed productions; old checkpoint copies must not be trusted.
- Keep one canonical contract: textual `summary`/`decision`/`next_action`, real structured `content`, and `issues` as an array or null. The prompt must never contradict the schema by requesting JSON-encoded strings for those fields.
- Treat type-descriptor output (`{"type":"string"}`, property definitions, or the complete schema) as a provider handoff failure. Preserve it for diagnostics, retry once in a fresh AGY conversation, and stop/escalate on a repeated signature instead of accepting it or regenerating creative shots.

## Workflow

1. Validate environment and inputs. Use `scripts/analyze_media.py` for media metadata and frame extraction. Ask the user for anything missing.
2. Ask AGY to analyze the song, lyrics, BPM, beat grid, sections, lyric timing, energy changes, and visual opportunities. Show the useful response to the user.
3. Have Codex propose the treatment, character/location bible, continuity map, and shot manifest. Send it to AGY for critique, show that critique, then send a Codex revision back to AGY for approval. Repeat until approved or the user changes direction.
4. Show the final agreed treatment and manifest to the user and wait for explicit approval. Do not create references or start ComfyUI generation before approval.
5. After approval, have AGY review the reference plan. Generate references one at a time, show each to the user, record approval/rejection, and use numbered attempts for replacements.
6. Select T2V for fresh visual resets and I2V for continuity, unless the approved manifest explicitly restricts the project to I2V. For each I2V shot, AGY chooses the prior last frame, a corrected extracted frame, or a fixed anchor.
7. Generate shots with `scripts/e2e_runner.py --agy --max-attempts 0`. The runner submits jobs, extracts a dense timeline frame set plus the complete video, records state, and retries rejected shots until AGY approves them.
8. After every completed shot, have AGY inspect the complete video and dense frame set for identity, action, lyric alignment, composition, motion, artifacts, continuity, and text legibility. Do not continue dependent shots until approved.
9. For dependent I2V shots, never use the previous last frame blindly. If the prior shot ends on a rear view, cropped face, obscured face, profile that does not establish identity, malformed face, or an otherwise rejected transition, AGY must choose a face-visible corrected extracted frame or a fixed approved character anchor. Record that choice in the transcript and use the selected frame as the next input.
10. Reject and regenerate failed shots with numbered attempts; never overwrite approved artifacts. A rejection must not terminate the E2E run: retry the same shot with AGY's correction until it passes, while preserving every attempt and checkpoint.
11. Concatenate approved silent clips with `scripts/assemble_video.py`, then add the original song and trim the final output to the song duration. Validate streams and duration.
12. Deliver the final video, silent master, shot clips, prompts, references, AGY transcript/reports, manifest, and technical report.

## Default generation policy

- T2V/I2V selection is per shot.
- Turbo v4, 6 steps, 16:9, no generated audio unless overridden.
- The skill/agent selects the megapixel value and passes it to the job API as `megapixels`; the ComfyUI `ResolutionSelector` node is the sole authority for final width and height.
- Do not convert the selected MP value into a resolution in the app or runner.
- Recommended MP policy for this machine: 5 seconds = 1.5 MP; 6–8 seconds = 1.0 MP; 9–10 seconds = 0.7 MP; 11 seconds = 0.6 MP; 12–15 seconds = 0.5 MP.
- Always pass the shot's `aspect_ratio` separately (normally `16:9`).

## Text legibility policy

- Prefer clean surfaces and text-free backgrounds in generation prompts.
- If the story requires readable text, specify the exact wording, language, placement, size, color, and duration in the shot manifest.
- Do not trust the model to render exact spelling. Have AGY inspect text-bearing frames and reject clearly visible gibberish, duplicated letters, warped characters, or accidental logos; ignore imperceptible or ambiguous marks that are not readable at normal viewing size.
- For subtitles, lyrics, title cards, signs, phone screens, or credits, prefer FFmpeg or a dedicated post-production overlay after video generation.
- Include text checks in the acceptance criteria and final technical report.

## Portable execution

The scripts use HTTP, JSON, FFmpeg, and command-line AGY integration. Agents may call them from Codex, Claude Code, AGY, OpenClaw, or another shell-capable agent. Agent-specific behavior is limited to user questions, progress display, and file presentation.

## Safety and control

Do not stop unrelated ComfyUI jobs. Before canceling a job, confirm that the user requested cancellation. Never overwrite approved artifacts; use numbered attempts. Do not add audio to individual clips when the project requires final-song assembly.
