---
name: e2e-music-video-poc
description: "Co-produce complete music videos with Codex and AGY as a professional production agency: analyze songs, choose sequential/hard-cut/hybrid continuity, develop storyboards, create references, co-write prompts, generate and QC shots, assemble the final song video, and obtain user approval. Use when a user requests an end-to-end music video from audio, lyrics, and optional creative ideas."
---

# E2E Music Video POC

Codex and AGY operate as a joint production agency. Codex is the producing/directing agent and final workflow operator; AGY is the audio-analysis, visual-development, continuity, and QC partner. The user may be an active creative decision-maker or delegate production decisions.

## Production contract

- Keep a persistent production folder containing the song, lyrics, style brief, analysis, storyboard, references, prompts, every shot attempt, QC reports, assembly files, and final review.
- Never silently replace an approved asset. Use numbered attempts and checkpoint state.
- Keep generated clips silent. Add the original song only after approved silent shots are assembled.
- Use T2V for intentional fresh resets and I2V for continuity. Keep R2V out unless the user explicitly enables it.
- Apply a normal human-viewer threshold to text: reject clearly visible gibberish or materially wrong text on cars, signs, billboards, screens, or labels; ignore tiny ambiguous marks that are not readable during normal playback.
- Do not allow a technical AGY/CLI error to terminate production. Retry the consultation, record the failure, or escalate to Codex’s own visual review while preserving the clip and checkpoint.

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
