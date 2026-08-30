---
name: realistic-rap-turbo-poc
description: "Regression POC for realistic rap music videos with AGY and Turbo: enforce integer five-second renders, 1:1/1 MP output, explicit overlap, vocal ownership, approved-artifact locking, and freeze-free assembly. Use when testing a new clip against the lessons from a previous production session."
---

# Realistic Rap Turbo POC Regression

Codex and AGY operate as a joint production agency. Codex is the producing/directing agent and final workflow operator; AGY is the audio-analysis, visual-development, continuity, and QC partner. The user may be an active creative decision-maker or delegate production decisions.

## Skill collision guard

This skill is the single top-level controller for the regression POC. Do not activate another monolithic music-video controller at the same time (`e2e-music-video`, `e2e-music-video-poc`, `lipsync-skill`, `agy-turbo-lipsync-pipeline`, or `realistic-rap-turbo-music-video`). Their overlapping defaults can reintroduce the exact duration, overlap, performer, and assembly mistakes this skill is designed to prevent.

Use narrow role skills only when needed for a defined subtask: audio analysis, visual direction, storyboard editing, scene-frame design, prompt writing, technical direction, A/V sync review, technical QC, continuity review, or post-production. The POC contract in this file remains authoritative for execution settings and approval state.

## Production contract

- Keep a persistent production folder containing the song, lyrics, style brief, analysis, storyboard, references, prompts, every shot attempt, QC reports, assembly files, and final review.
- Never silently replace an approved asset. Use numbered attempts and checkpoint state.
- Keep generated clips silent. Add the original song only after approved silent shots are assembled.
- Use T2V for intentional fresh resets and I2V for continuity. Keep R2V out unless the user explicitly enables it.
- Apply a normal human-viewer threshold to text: reject clearly visible gibberish or materially wrong text on cars, signs, billboards, screens, or labels; ignore tiny ambiguous marks that are not readable during normal playback.
- Do not allow a technical AGY/CLI error to terminate production. Retry the consultation, record the failure, or escalate to Codex’s own visual review while preserving the clip and checkpoint.

## POC regression contract — mandatory for the next test

This section is the regression harness distilled from the previous rap-video session. It is not optional guidance. Apply it before starting a new clip so the pipeline cannot silently repeat the known failures.

### Hard execution settings

- Treat the current song, current lyrics, current approved character references, and the current production folder as the only inputs. If the user says “start fresh,” do not reuse an older treatment, timeline, AGY conversation, prompt, render, or approval unless the user explicitly re-approves it.
- Capture the requested execution profile before generation: `5` seconds per raw Turbo clip, integer duration only, square `1:1`, `1 MP` target. Record the legal dimensions and actual pixel area sent to ComfyUI; never let a helper substitute `6`, `4.36`, `5.7`, or another hidden duration.
- Keep all execution-facing duration fields as integers: `editorial_duration`, `audio_duration`, `generation_duration`, `overlap_seconds`, `trim_in_seconds`, and `trim_out_seconds`. Source analysis may retain precise audio timestamps as evidence, but decimals must not leak into the Comfy request or the shot manifest used by the runner.
- A five-second raw clip plus a discarded overlap cannot also provide five full post-trim seconds. The manifest must expose that tradeoff. With the user’s five-second hard cap, either use the overlap as deliberate transition coverage or reduce the post-overlap editorial coverage; never hide the missing second with a frozen frame and never silently generate six seconds.

### Per-shot contract

Every shot record must contain all of these fields before it can be queued:

```text
id
section
editorial_start
editorial_end
editorial_duration
model_audio_start
model_audio_end
model_audio_duration
generation_duration
overlap_seconds
trim_in_seconds
trim_out_seconds
model: turbo_lipsync | turbo_regular
performance_owner: main_mc | phantom | instrumental_only | both_nonvocal
opening_frame_path
previous_shot_id
next_shot_id
transition_in
transition_out
```

- `generation_duration` must equal `5` for this POC. `model_audio_duration` must match the actual file sent to the model, and the overlap must be explicit on every lip-sync shot, including the first shot if it has an intentional lead-in.
- No lip-sync shot may have a blank or inferred overlap value. The editor must know exactly which source portion is used as transition coverage and exactly which portion is the shot’s main editorial content.
- Do not use a generic fallback such as `S29_raw.mp4`, `latest.mp4`, or “the last successful file.” Resolve the raw artifact through an approval ledger containing the exact path, generation job id, attempt number, QC status, and user approval. A later retry must never replace a user-approved take.
- For each shot, record the action phase at the opening frame: `scratch_before_vocal`, `vocal_already_in_progress`, `instrumental_performance`, or another explicit state. The first frame must make the intended state possible; do not start a clip with the character already singing when the action is supposed to begin with scratching.

### Vocal-owner gate

- Assign one vocal owner per performance shot. The mouth owner is not inferred from who happens to be closest to camera.
- On every chorus marked as the Phantom’s low, deep, metallic vocal, set `performance_owner: phantom`. The main MC may be visible, scratching, gesturing, or reacting, but his mouth must remain closed/neutral unless the timeline explicitly gives him a separate line.
- On every main-MC verse or scratch-then-verse shot, set `performance_owner: main_mc`; the Phantom must not lip-sync. If the shot contains a handoff, specify the exact onset and action state in the manifest and QC it against the source audio.
- Prompts must identify the non-singing character as “mouth closed, no lip-sync, reacting only.” Never rely on a vague “both rappers perform” instruction.

### Real music-video visual gate

- The target is a finished-looking rap music video, not a character turnaround, generic portrait, or literal storyboard illustration. Opening frames must be performance-driven, cinematic, and immediately usable as a shot start.
- Preserve the approved MC identity and cool rapper wardrobe. Preserve the approved Phantom identity as the larger muscular half-droid/science-fiction performer. Do not redesign either character during shot generation.
- One shot has one stable camera position. Allow only micro handheld, breathing, rack-focus, or small push/pull movement that does not relocate the camera or introduce a hidden angle change. Make all major angle changes in the next opening frame.
- If a brief is “scratch, then sing,” show the physical scratch action first and delay mouth performance until the vocal onset. If a brief is “close and moving,” put the close framing and restrained camera motion in the opening-frame brief; do not ask the model to discover a new angle halfway through the shot.

### Freeze-free assembly gate

- Never cover an editorial gap with a duplicated last frame, `tpad=clone`, a still-image hold, or a repeated final frame. Such a hold is a production failure, not a transition.
- If five-second hard-capped generations create an overlap gap, use the incoming shot’s actual generated lead-in only when it is an intentional, documented overlap and the A/V review confirms that the visual action and vocal timing are acceptable. Otherwise stop assembly and revise the timing or generate explicit coverage.
- Run a freeze detector over the silent assembly and final master. Any unintended freeze event is a rejection. Also inspect a frame-difference/contact-sheet sample around every cut; a clean `ffprobe` report alone is not enough.
- The final master uses the original song exactly once, aligned at `00:00`. Per-shot audio may exist temporarily to drive Turbo lip-sync, but it must be labeled as internal/model audio and must not be accidentally omitted from the review copy or duplicated in the master.

### Recovery and approval integrity

- Distinguish a transport timeout, ComfyUI unavailability, and a failed generation. A timeout after submission is not permission to create a duplicate job. Recover the existing job id, update the checkpoint, and review the returned artifact.
- Run one controller per production. On restart, resume the saved state and the exact pending shot; do not launch a second controller or create a new creative attempt merely because the UI stopped responding.
- Keep rejected attempts, failed outputs, and old manifests. Mark them `rejected` or `superseded`; never delete them and never let a reconciliation script choose them as a fallback.
- Maintain these separate states: `generated`, `technically_qc_passed`, `agy_reviewed`, `user_approved`, `rejected`, and `superseded`. Only `user_approved` artifacts may enter the final assembly.

## POC acceptance gates

The next clip cannot advance through a gate until the listed evidence exists:

1. **Analysis gate:** fresh AGY analysis of the actual audio file, with lyric onsets, breaths, instrumental passages, energy/transition notes, and uncertainty labels. Whisper or another local transcription may triangulate the result, but it cannot replace an AGY audio review when AGY is requested.
2. **Plan gate:** approved treatment and shot manifest; every shot is five seconds raw, integer-only, square/1 MP class, has a performance owner, and has explicit overlap fields where lip-sync is used.
3. **Reference gate:** approved MC/Phantom/style references and an approved shot-specific opening frame for every shot. No video generation before this gate.
4. **Shot gate:** full generated clip reviewed against the exact audio window; correct singer, correct action onset, stable camera, no freeze, no unintended extra character, and no obvious anatomy/rendering defect.
5. **Assembly gate:** exact approved-artifact map, no rejected/generic fallback paths, no duplicated-frame gap fillers, original song present once, freeze detector clean, and full-master A/V review complete.

Read `references/session-lessons.md` for the failure-to-prevention record and use `scripts/validate_poc_manifest.py` as a deterministic preflight when a JSON manifest is available.

## AGY structured-output guardrail

- The bridge writes a fresh `agent-context/response.schema.json` before every AGY call; never reuse an older checkpoint schema.
- The AGY prompt and schema must agree: `summary`, `decision`, and `next_action` are plain strings; `content` is the actual object/array/string/null task payload; `issues` is an array or null. Do not describe `content` or `issues` as JSON-encoded strings in the AGY prompt.
- A response containing schema descriptors such as `{"type":"string"}` is not an analysis. Preserve the raw response, retry once without the saved conversation, and escalate if the fresh result repeats the same signature. Never save it as an approval or QC report.

## Stage 1 — intake and user intent

Collect the song file, lyrics, style/genre, output location, ComfyUI endpoint, available models, and optional clip idea. If anything required is missing, ask for it before generation.

Confirm these choices explicitly:

1. Continuity: fully sequential with the previous last frame, hard-cut independent shots, segmented sequential, or hybrid.
2. User involvement: active approvals at treatment/references/shots/final, or delegated creative production with final review only.
3. Visual constraints: characters, locations, violence, wardrobe, text/signage, aspect ratio, duration/megapixel policy, and audio policy.

If the user is active, ask for ideas at each decision gate. If delegated, Codex and AGY still record their reasoning and only interrupt for missing information or a material creative conflict.

## Stage 2 — AGY song analysis

Send the actual song file and lyrics to AGY. Request:

- duration, sample rate, channels, BPM/tempo confidence, meter, energy curve, sections, beat/bar grid, lyric timing, vocal entrances, instrumental breaks, transitions, and visual opportunities;
- genre and production style;
- a timestamped lyric map suitable for shot durations;
- risks such as dense lyric passages, beat drops, or timing ambiguity.

Save the raw AGY response and Codex’s normalized timeline. Do not invent exact lyric timestamps when AGY reports uncertainty; mark them as estimates.

## Stage 3 — joint treatment and storyboard

Codex proposes the treatment, character/location bible, visual language, continuity map, shot list, shot durations, generation mode, references, camera movement, and transition intent. Ask AGY to critique it.

Then Codex responds to AGY point by point, revises the treatment, and asks AGY for approval. Repeat until the two producers agree. Show the useful exchange to the user at the agreed decision gate and obtain approval before references or generation.

Every shot record must include: id, lyric/section, time range, duration, mode, continuity source, prompt intent, camera movement, action, negative constraints, megapixel/resolution policy, and acceptance criteria. It must also record an `opening_frame_strategy`: `reference_composed`, `reference_composed_with_previous_last_frame`, `previous_last_frame`, `corrected_previous_last_frame`, `approved_anchor`, or `none`.

## Stage 4 — reference development

For each main character, recurring prop, vehicle, location, and continuity anchor:

1. Codex proposes a reference brief.
2. AGY critiques identity, wardrobe, composition, text risk, and future shot usability; AGY may suggest alternate reference concepts.
3. Codex accepts, revises, or rejects the suggestion and records the decision.
4. Generate the reference image, inspect it, and send it back to AGY.
5. Mark it approved or create a numbered replacement.

If AGY suggests an external image, use it only as a description/composition reference and independently create a clean original asset; do not remove watermarks from third-party files.

## Stage 5 — co-writing and shot generation

For each approved shot:

1. Codex drafts the video prompt from the storyboard and continuity requirements.
2. AGY critiques the prompt for action clarity, camera physics, character identity, lyric fit, text risk, and transition compatibility.
3. Codex revises the prompt and asks AGY to confirm it.
4. Before generation, Codex and AGY explicitly decide the opening-frame inputs for this shot and record the decision in the shot manifest.
5. Generate the silent shot with the approved I2V/T2V mode and parameters.

Opening-frame rules for the current I2V-only production path:

- Assigned images are planning/creative references, never the actual I2V opening frame. A shot-specific opening frame must be newly composed from the assigned character, location, prop, wardrobe, and lighting references plus the shot prompt. Never pass a selected library/reference image directly as the scene frame.
- If a shot has assigned scene references and is sequential, generate a new opening frame from those references and provide the previous accepted last frame as continuity context. Use the last frame to preserve identity, unfinished action, screen geography, and camera direction; it must not override the new shot’s location, action, or composition.
- If a shot has assigned scene references and is a hard cut/independent shot, compose the new opening frame from those references without the previous last frame.
- If a shot is sequential but has no assigned scene references, use the previous accepted last frame directly only when AGY and Codex agree it is a valid opening image. If the face, action, framing, or geometry is unsuitable, create a corrected frame before I2V.
- If the previous frame is rear-facing, cropped, obscured, malformed, or otherwise a poor identity anchor, choose `corrected_previous_last_frame` or `reference_composed_with_previous_last_frame`; do not blindly reuse it.
- R2V remains disabled for production. The generated shot-specific frame is the only image sent to the I2V workflow.

Check camera direction and screen geography so cuts do not reverse motion or jump locations without intent. Save the chosen inputs and the generated opening frame path in the shot checkpoint so the UI can distinguish planning references from the actual scene frame.

## Stage 6 — per-shot video and frame QC

After every generation, send AGY:

- the complete MP4;
- a dense timeline frame set covering the whole clip, plus first/middle/last frames;
- the previous shot’s final frame and the current opening frame when continuity matters;
- the opening-frame strategy and the exact input list used to create the current opening frame;
- the shot prompt, lyric timing, and acceptance criteria.

AGY reports identity, action, lyric fit, camera movement, continuity, visual glitches, and clearly visible text. Codex then independently reviews AGY’s report and the artifacts, agrees or disagrees with reasons, and sends a concrete next-step proposal back to AGY. Only after Codex and AGY agree is the shot approved.

If rejected, preserve the attempt, append the agreed correction to the prompt, and regenerate automatically. Do not stop after an arbitrary attempt count; continue until approval or a genuine external blocker. A transient AGY timeout, empty response, or CLI failure must be retried and recorded rather than ending the run.

## Stage 7 — assembly

After all shots are approved:

1. Validate every clip’s duration, dimensions, codec, frame rate, and audio absence.
2. Concatenate without crossfades for sequential continuity unless the user explicitly requests a different transition.
3. Add the original song once, trim/pad to the analyzed duration, and encode the final master.
4. Preserve both the silent master and the final audio version.

## Stage 8 — final AGY and user review

Send the complete final clip and representative/dense frames to AGY. Ask for a producer-level final report covering lyric synchronization, pacing, continuity, visible glitches, text legibility, transitions, audio alignment, and technical validity.

Codex discusses AGY’s report, records any required fixes, and sends the final clip to the user. The user decides whether to accept it or request targeted revisions. Never declare the production complete before this final user review.

## Required artifacts

- `production_transcript.md`: user decisions, Codex/AGY exchanges, approvals, disagreements, and corrections;
- `song_analysis.json`, `lyrics_timeline.json`, `treatment.md`, `storyboard.json`;
- `references/` with approval status and numbered attempts;
- `shots/` with every silent attempt, extracted frames, prompts, and AGY/Codex QC reports;
- `assembly/` with concat list, silent master, final master, and validation output;
- `final_review.md` and a resumable `state.json`.
