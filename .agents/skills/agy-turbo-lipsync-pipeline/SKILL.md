---
name: agy-turbo-lipsync-pipeline
description: "Plan music videos around Turbo lip-sync and regular Turbo by analyzing the actual song with fresh AGY sessions, validating phrase-level timing, designing overlap-aware shots, and gating all Opening Frame/video generation on user approval. Use for audio-first music-video planning and reusable AGY-driven production pipelines."
---

# Agy Turbo Lipsync Pipeline

Use this skill when a music-video workflow needs accurate lyric timing, natural shot boundaries, Turbo lip-sync versus regular Turbo decisions, deliberate overlap, and Opening Frame continuity. This is an audio-first planning skill. It does not authorize image or video generation by itself.

## Non-negotiable scope and gates

- Treat the current song file and the current lyric text as the only creative inputs for a fresh planning pass unless the user explicitly adds references or prior decisions.
- Do not reuse a previous production's analysis, treatment, shot list, references, settings, transcript, AGY conversation, or generated media when the user asks to start fresh.
- Inspect the actual audio file. Lyric text is an alignment aid, never timing truth.
- Start with the first approximately 30 seconds. Extend the plan past 30 seconds when stopping at 30 would cut an active phrase; a phrase-safe 35-second plan is better than an illegal 30-second cut.
- Do not generate video, images, Opening Frames, or other creative media before the user approves the refined audio/shot plan.
- Keep the stages explicit: `Analyze -> propose -> inspect problems -> refine -> user approves plan -> Opening Frames/references -> user approves assets/manifest -> generate -> QC -> assemble`.
- Preserve every pass as a versioned artifact. Never overwrite an earlier analysis or silently change an approved plan.

## Explicit integer/5-second execution profile

When the user explicitly requests the integer/5-second profile, apply these
constraints to the editorial and generation plan:

- Use 5-second editorial shots as the default cadence, with integer start,
  end, and duration values only. Do not emit decimal editorial or generation
  durations.
- Keep the no-illegal-phrase-cut rule active. If an exact 5-second boundary
  splits an active phrase or trims a phrase tail, use the smallest integer
  exception needed to preserve the phrase, label the exception, and require
  user approval. Never hide the conflict by silently rounding.
- A 5-second editorial shot with a 1-second lip-sync lead-in has a 6-second
  model window and integer generation duration; a 6-second phrase-safe shot
  with the same lead-in has a 7-second model window. Editorial duration and
  generation duration remain separate clocks.
- Set the requested visual target to 1:1 and 1 MP. Before generation, resolve
  legal workflow dimensions, record the actual pixel area, and do not claim
  the rounded dimensions are exactly 1 MP when they are not.
- Preserve fractional source-accurate evidence timings in the audio timeline
  for validation, but keep the execution-facing shot manifest integer-only.

If the user instead requires every generated clip itself to be exactly five
seconds, do not add hidden overlap to that clip. Either choose a phrase-safe
window with no lead-in or obtain approval for reduced visible editorial
content and the resulting continuity risk.

## Fresh AGY analysis protocol

Run AGY in a new conversation for each material analysis or critique pass. Use the actual source path and a lossless excerpt when a short-window audit is needed. Do not attach old production folders merely for convenience.

Every structured AGY call must:

1. Create or refresh a dedicated response schema for that call.
2. State the exact files AGY may inspect and explicitly forbid prior artifacts and saved conversations.
3. Require AGY to open/inspect the media, not infer timing from lyrics or metadata.
4. Require proof such as `decoded_audio: true`, the exact `inspected_path`, duration, sample rate, channels, and inspection method.
5. Require a real response envelope containing `summary`, `decision`, `content`, `issues`, `next_action`, `confidence`, and `requires_user`.
6. Reject schema echoes, empty placeholder output, missing media proof, or timing content that is not an object/array of real data.

For high-accuracy analysis, use focused passes rather than trusting one long answer:

- Full-source sanity pass: verify the container duration and the song's broad structure.
- Lossless first-30/35-second pass: map every vocal and instrumental event in the planning range.
- Precision pass: tighten vocal onsets, offsets, breaths, phrase tails, scratch samples, and safe windows.
- Adjudication pass: give AGY source-derived hypotheses as untrusted candidates and ask it to accept, reject, or correct them against the audio.
- Plan critique pass: send the proposed shot windows and model modes back to AGY for phrase integrity, adjacent-context, overlap, and vocal-bleed review.

If AGY reports disagree by more than the stated timestamp resolution, stop treating the timeline as approved. Triangulate with an independent source-only check (for example, `ffprobe`, waveform/onset analysis, or local ASR), then send the disputed candidates back to a focused AGY pass. Never average contradictory timestamps and never hide the conflict. Record the conflict and resolution in the analysis artifact.

If AGY can inspect the container or metadata but cannot directly hear the
audio track, record `direct_audio_inspection: false` and treat all lyric and
phrase timings as provisional. Independent waveform/onset/ASR analysis may
support a draft and a focused AGY critique, but it does not count as AGY
source listening and cannot unlock Opening Frame or video generation without
the user's approval.

The song's source metadata must be independently checked. A multimodal model can misreport duration or shift timestamps even when it claims successful inspection. Use the source file's decoded duration/sample rate/channels as the container authority, and use AGY for what it can hear and interpret.

## Required audio timeline

Normalize the accepted audio evidence into a versioned timeline. At minimum include:

- source path, decoded duration, sample rate, channels, and independent validation method;
- tempo/BPM estimate, meter, tempo changes, confidence, and beat/energy events;
- a second-by-second or finer event timeline covering the planning range;
- every lyric line, spoken word, ad-lib, vocal sample, onset, offset, breath/pause before and after, phrase-complete flag, and confidence;
- vocal, mixed, and true instrumental windows;
- `hard_no_cut_ranges`, `preferred_cut_points`, `acceptable_cut_ranges`, and reasons;
- transition events such as sub drops, beat entrances, scratches, fills, risers, energy ramps, and atmosphere changes;
- uncertainties and validation tasks that remain before generation.

Do not label a scratched or chopped vocal sample as a clean visible performance. Mark its voice type as `sample`/`scratch` and decide separately whether a visible mouth is appropriate.

## Shot and overlap contract

Five seconds is a starting point, not a grid. Choose cut points around completed phrases, breath gaps, beat changes, and visual action. Do not cut in a word, an active bar, a breath that belongs to the phrase, or a musical transition that needs to resolve.

For every shot keep these clocks separate:

```text
editorial_start/end       = the time the shot is visible in the edit
model_audio_start/end     = the exact source-audio window sent to Turbo
overlap_before            = editorial_start - model_audio_start
trim_in                   = the hidden lead-in removed from the generated clip
trim_out                  = the hidden tail removed from the generated clip
generation_duration       = the integer duration requested by the model/API, if required
```

The source-audio window is authoritative. If an API requires integer generation duration, record that separately and block silent rounding. A technical pass may ceil the request or add an explicitly documented pad, but it must not change the song timing without recalculating the shot.

Use an intentional lead-in so a new Opening Frame does not make the performer appear to start from rest at the cut. A practical starting point is about 0.5 seconds, then adjust to the actual preceding action, vocal onset, and breath. It is not always one second and it is not always appropriate.

For each shot verify:

- `editorial_duration = editorial_end - editorial_start`;
- `model_audio_duration = model_audio_end - model_audio_start`;
- `trim_in` equals the hidden lead-in when the shot has a previous shot;
- `trim_out = model_audio_duration - trim_in - editorial_duration` and is non-negative;
- the model window does not unintentionally expose the next lyric in the visible segment;
- the overlap does not swallow the previous phrase's tail or make the new model lip-sync the wrong word;
- the next shot has its own Opening Frame and a matching action state at the edit boundary.

If a cut at exactly 30.0 seconds would split a phrase, extend the plan until the phrase ends and show the continuation explicitly.

## Turbo mode selection

Decide mode using the shot, the shot before it, and the shot after it - not the isolated text label.

- `turbo_lipsync`: a visible performer is speaking, rapping, or singing and the mouth must track the supplied audio. Include enough lead-in for the performance to be underway before the visible edit point.
- `turbo_regular`: true instrumental material, environmental/b-roll action, prop or texture shots, and scratched vocal samples when no visible character is expected to articulate the sample. If a character remains on screen, specify a closed/neutral mouth.
- `mixed`: only when the editorial shot intentionally changes between a visible lip-sync performance and a non-lip-sync section; prefer separate shots when a clean cut is musically available.

Never use regular Turbo for a visible singer during an active lyric merely because a neighboring shot is instrumental. Never use lip-sync for a turntable scratch or chopped sample unless the treatment explicitly makes a visible performer articulate it and AGY confirms the interpretation.

## Opening Frame design gate

Do not create an Opening Frame until the user approves the audio/shot plan. After approval, create one Opening Frame brief per shot using the approved identity, wardrobe, environment, lighting, prop, and art-direction references.

Each brief must state:

- shot ID and the exact editorial/model timing it represents;
- character identity, wardrobe, pose, action state, mouth state, and any visible prop;
- camera angle, fixed camera position, focal/framing intent, and crop-safe placement;
- lighting direction, palette, atmosphere, and continuity anchors;
- the action already in progress during the hidden overlap lead-in;
- what is inherited from the previous shot and what deliberately changes at the cut;
- what the following shot must receive at its boundary;
- negative constraints such as no camera relocation, no accidental text/logos, no new character, no mouth movement in regular-Turbo shots, and no identity/wardrobe drift.

The camera may change angle between shots through a new Opening Frame. During a shot, keep the camera position stable: allow only micro movement, subtle handheld vibration, breathing motion, or a small physically motivated adjustment. Do not turn a micro move into a hidden angle change.

Use references to stabilize identity, wardrobe, location, lighting, props, and art direction. Do not blindly use the previous shot's last frame as the next Opening Frame; that is only valid for an explicitly approved sequential-continuity workflow. A hard cut receives a newly composed angle with the same approved visual bible.

## Review and QC requirements

Before generation, the user must be able to review a plan containing, for every shot:

- editorial start/end;
- exact model-audio start/end and overlap/trim math;
- model mode and why adjacent context supports it;
- lyric/vocal/instrumental content;
- action, Opening Frame requirement, angle, framing, lighting, character motion, camera motion;
- previous-shot context, next-shot context, and the transition method;
- confidence, unresolved issues, and the AGY review decision.

After generation, inspect each shot against the actual song audio and its neighbors. Check vocal onset, mouth state, wrong-word bleed, overlap continuity, camera relocation, identity/wardrobe/prop drift, frozen or sliding motion, and unintended text. Regular-Turbo shots with a visible character must remain closed-mouth during non-vocal windows. Assemble the original song once at the end and re-check synchronization after export.

## Recommended artifacts

Use a versioned namespace under the current production or project:

```text
source_manifest.json
agy_raw/<pass>.json
audio_timeline.json
audio_validation.md
shot_plan.json
shot_plan_review.md
treatment.md
reference_bible.json
opening_frames/<shot_id>_brief.md
generation_manifest.json
shot_qc/<shot_id>.json
assembly_manifest.json
final_review.md
```

The planning checkpoint must contain no generated image/video outputs. Keep the raw AGY response, the normalized timeline, the human-readable plan, and the final approval decision linked by version and source hash/path.

## Model policy

Use AGY's strongest available analysis model and high effort for source inspection and critique when timing accuracy matters (the current tested configuration is `gemini-3.1-pro-high` with high effort). Turbo lip-sync versus regular Turbo is a shot-level decision. Turbo profile, steps, resolution, aspect ratio, and integer duration are technical configuration, not creative guesses; resolve them only after plan approval from the active workflow configuration and validate them before submitting any job.

## Failure lessons encoded by this skill

- A prior fixed five-second workflow can create lip-sync, trim, and assembly bugs. Editorial windows and model windows must be separate fields.
- A model can claim successful media inspection while reporting the wrong duration. Independent source probing is mandatory.
- Multiple AGY passes can disagree by seconds. Use focused excerpts and adjudication; do not average or silently pick a convenient result.
- Scratch vocals and instrumental beds can look like "vocal chunks" in text. Mode selection must distinguish a clean visible lyric from a sampled texture.
- A new Opening Frame resets motion. Deliberate overlap plus a pre-action frame is part of the shot design, not an emergency repair.
- A 30-second deliverable boundary is not a valid cut point if a lyric is active. Plan through the completed phrase and label the continuation.
- No user approval means no Opening Frame and no video generation.
- Photorealism alone does not guarantee a convincing music-video frame. Literal prop actions, over-explained blocking, and visible malformed hands can make a shot read like a storyboard. Prefer artist-first performance coverage, keep props secondary, simplify or crop hand gestures when they are not editorially essential, and run anatomy QC before user approval.
