---
name: lipsync-skill
description: Plan and produce song-timed Turbo music-video shots in full lip-sync, full non-lip-sync, or hybrid modes, with AGY audio analysis, content-driven cuts, correct audio windows and overlap, opening-frame continuity, per-shot QC, and final user approval.
---

# Lip-Sync Music Video Skill

Use this skill when the user wants a music video built around an uploaded song and a recurring singer or character. It supports three explicit production modes:

- **Full lip-sync:** every shot containing the singer uses Turbo lip-sync with the source audio window that belongs to that shot.
- **Full non-lip-sync:** all shots use regular Turbo/I2V; prompts explicitly prohibit singing, talking, and mouth performance. The original song is added only during final assembly.
- **Hybrid:** choose lip-sync or regular Turbo independently per shot. The manifest must explain the choice and check the transition to neighboring shots.

Confirm the mode before planning. Do not silently turn a hybrid request into all lip-sync or all non-lip-sync. R2V is not part of this skill's default pipeline; leave it available for future work but use opening-frame I2V unless the user explicitly enables R2V.

## Non-negotiable production rules

- Work outside the Production page and its autonomous orchestrator unless the user explicitly requests that page.
- Do not generate anything before the user approves the treatment, continuity strategy, and shot manifest.
- Begin with a detailed analysis and plan for approximately the first 30 seconds. If the approach is approved, extend it to the rest of the song.
- Use the actual uploaded audio file for AGY analysis and for lip-sync windows. Lyrics and style text support planning; they are not a substitute for the audio.
- For Turbo native-audio-lock lip-sync, do **not** put the lyrics or transcript into the generation prompt by default. The audio drives mouth timing. Use lyrics in the timeline, prompt review, and QC only. Add lyric text to a model prompt only if the selected workflow explicitly requires it.
- Use the original song once as the final soundtrack. Individual generated shots should remain silent unless the selected lip-sync workflow needs an audio segment internally to drive synchronization.
- Use the supplied singer image and approved references as identity anchors. Preserve face, hair, cybernetic anatomy, wardrobe, accessories, palette, lighting direction, and art direction. Record deliberate changes; do not allow accidental drift.
- Any user-provided references are optional by category. The user may provide only a character, location, prop, or other subset; AGY and Codex fill missing categories from the approved creative direction and record what was invented.
- Use small, physically plausible camera movement inside a shot. Change angle or camera position between shots through the next opening frame, not through a large mid-shot move.
- Use a normal-human-viewer QC threshold. Reject clear defects affecting identity, action, lip-sync, continuity, story comprehension, or visibly readable text. Do not reject a shot for microscopic texture or an ambiguous tiny mark that a viewer cannot read.

## Resolution and duration policy

These are the default local Turbo recommendations and may be overridden only when the user explicitly chooses another setting. Always record both the requested target and the legal dimensions actually sent to ComfyUI.

| Generated duration | Target | Square legal default | Actual area |
|---|---:|---:|---:|
| 5 seconds or less | 0.41 MP | 640×640 | 0.4096 MP |
| More than 5 through 10 seconds | 0.7 MP | 832×832 | 0.692224 MP |
| More than 10 seconds | 0.5 MP | 704×704 | 0.495616 MP |

- Keep the requested aspect ratio, normally 1:1 for this skill, unless the user approves another ratio.
- Dimensions sent to ComfyUI must satisfy the selected workflow's constraints, including multiples of 32 where required. Never claim the requested megapixel value is the actual area when rounding to legal dimensions changes it.
- The Comfy job's generated `duration` must be a whole integer number of seconds. Do not send decimal durations such as `4.36`, `5.7`, or `8.5`; this local environment became substantially slower and less predictable with those values.
- Editorial cut points and audio timestamps may remain fractional because music timing is continuous. Only the generation-duration field is required to be an integer.
- Five seconds is a starting point, not a mechanical editing rule. A shot may be shorter or longer when phrase, breath, bar, action, or transition boundaries require it.

### The audio-window contract

Every shot must distinguish these values in its manifest:

1. `editorial_start` and `editorial_end`: the exact time the shot appears in the final edit.
2. `audio_start`: the time at which the supplied audio segment begins.
3. `audio_end` or `audio_duration`: the exact audio window sent to the model.
4. `generation_duration`: the whole-integer video duration requested from ComfyUI.
5. `overlap`: how much of the generated lead-in is discarded at the edit.
6. `trim_from_start`: the actual amount removed before concatenation.

If a shot uses a one-second lead-in, a five-second editorial shot cannot be generated as a five-second model clip. It needs a six-second integer generation window, for example:

```text
editorial:       00:05 → 00:10
model audio:     00:04 → 00:10
overlap:         1 second
generation:      6 seconds
edit:            trim the first 1 second, keep 00:05 → 00:10
```

Never generate a fixed five-second clip and then discard one or two seconds from its beginning while still expecting the complete five-second editorial content. That was the observed cause of lost opening audio and lip-sync offset during the 10 Again run.

If the user insists that every generation itself must be exactly five seconds, choose cuts with no required lead-in or reduce the editorial span accordingly, and warn that the model may begin lip-sync late. Do not silently use overlap that the five-second clip cannot contain.

For each lip-sync shot, AGY must identify the first audible vocal onset inside the model window. If a long silent lead-in precedes an important first word, do not assume overlap is helpful: Turbo can settle into a closed-mouth state and articulate the first word late. Either start the audio window at the vocal onset, or use a longer integer generation window only when AGY confirms that the lead-in improves the transition. Verify the first audible phrase after generation.

## Phase 1 — intake and deep audio analysis

1. Preserve the song, singer reference, lyrics if supplied, style brief, user references, and all later artifacts in a dedicated production directory.
2. Ask for information that blocks a reliable plan: the song, written lyrics when available, visual concept if not delegated, desired mode, and whether the user wants active decisions or delegated creative decisions. Do not ask again for information already supplied.
3. Send the actual audio file to AGY. When available, use Gemini 3.1 Pro High through AGY for the first analysis. Ask AGY to report:
   - duration, sample rate, channels, BPM/tempo and confidence, meter, beat/bar grid, sections, energy curve, vocal entrances, breaths, instrumental-only passages, transitions, and risks;
   - timestamped lyric/transcription timing, clearly marking estimates and uncertain words;
   - phrase boundaries and cut points that do not interrupt a word, sentence, breath, or important action;
   - the first audible onset for each lip-sync window;
   - visual opportunities and which sections are lip-sync, non-lip-sync, or transitional.
4. Codex independently checks the report against audio metadata and treats uncertain AGY timestamps as estimates until verified.
5. Save AGY's raw response, Codex's normalized timeline, and the producer discussion. Codex and AGY must genuinely consult: AGY is not a hidden single-pass oracle and Codex must not claim agreement without a recorded response.

## Phase 2 — first-30-second structure and approval loop

Build a complete draft timeline for approximately `00:00–00:30` before creating any visual asset. Do not cut mechanically every five seconds. Choose boundaries from lyrics, breaths, musical phrases, bars, energy changes, instrumental transitions, and visual actions.

Run this loop:

`Analyze → propose structure → AGY critique → Codex correction → user review → approve plan`

Repeat when the user or either producer identifies a timing, mode, continuity, or story problem. Do not create references or start ComfyUI generation before explicit user approval of the plan.

Each shot record must include:

- editorial start/end and editorial duration;
- exact model-audio start/end and first vocal onset;
- integer generation duration;
- overlap duration and the portion removed in the edit;
- `Turbo lip-sync` or regular `Turbo`, with a reason based on vocals and neighboring shots;
- the lyric/section and what the singer or other characters do;
- opening-frame reference requirements, framing, angle, lighting, and invariant details;
- permitted motion, screen direction, and action continuity;
- what precedes and follows it and the intended cut behavior;
- resolution target, legal dimensions, actual megapixels, steps, seed policy, and acceptance criteria.

The decision between lip-sync and regular Turbo must consider the shot before and after it. An instrumental shot can still use lip-sync when the singer continues an established performance, but regular Turbo is preferable when the singer is absent or the visual action should not imply vocal performance.

## Phase 3 — opening-frame and reference development

After plan approval, create a character, wardrobe, location, prop, lighting, and art-direction bible from the supplied references and AGY's recommendations. For each shot:

- propose the opening frame and have AGY critique it before video generation;
- keep the pose, gaze, screen direction, and action phase compatible with the previous shot;
- use a clear face-visible anchor when a previous last frame is rear-facing, cropped, obscured, malformed, or otherwise insufficient to establish identity;
- use the previous accepted last frame only when it is actually a good continuity anchor;
- generate numbered opening-frame attempts and preserve rejected attempts;
- check intentional text at normal viewing size. If exact readable text matters, add it in post rather than trusting generation.

## Phase 4 — prompt co-writing, generation, and per-shot QC

For every approved opening frame:

1. Codex drafts a prompt describing one stable camera setup, one clear action, the visual behavior, and continuity constraints. For lip-sync, refer to the uploaded audio timing but do not paste the lyrics into the generation prompt by default.
2. AGY critiques the prompt for phrase fit, mouth/action timing, physics, identity drift, camera movement, color, and visible-text risk. Codex resolves disagreements and records the decision.
3. Generate with the manifest's integer duration, audio window, overlap, resolution, steps, and seed. Do not let a helper silently replace these values with defaults.
4. Send AGY the complete generated video, representative/dense frames, prompt, audio timing, opening frame, and previous accepted last frame when continuity matters.
5. Codex independently reviews AGY's QC. Check first-word timing, mouth/jaw articulation, face/body consistency, glitches, camera stability, action-to-lyric fit, readable text, and whether the clip is actually silent or carries only the intended internal audio.
6. If rejected, preserve the attempt, record the concrete correction, and regenerate the same shot with a numbered attempt. Do not silently overwrite an approved asset or switch to another shot.

For full non-lip-sync shots, explicitly prompt for a closed/resting mouth and no singing or talking. For hybrid projects, make the transition between lip-sync and non-lip-sync intentional; do not allow the character to appear to be singing in a shot whose audio is not supplied to the model.

## Phase 5 — assembly and final review

- Preserve every attempt and the accepted-shot decision.
- Trim model lead-ins using the approved overlap table; never trim by a guessed number of frames.
- Concatenate approved silent clips with hard cuts for sequential continuity. Do not add crossfades unless the user requests them.
- Validate the silent assembly's editorial duration, dimensions, frame rate, and absence of unintended audio.
- Add the original song once, aligned to `00:00`, and preserve both the silent master and final audio master.
- Send the final clip and representative frames to AGY for producer-level review of shot joins, lip-sync, identity, action, glitches, text, and audio presence.
- Present the final file and AGY's material findings to the user. The user decides whether a final QC finding warrants another targeted rerun.

## Operational reliability and recovery

- Use one generation controller for a production. Before starting or resuming it, query the saved state and live job queue. Never launch a second controller for the same project.
- A completed ComfyUI job is technically successful, not automatically visually accepted. If a controller stops after submission, recover the existing job by ID and review/download it; do not submit a duplicate.
- Keep the ComfyUI process and bridge alive unless the user explicitly asks for a restart or a confirmed runtime failure requires it. Do not kill broad `python.exe` processes; target only the exact controller or job.
- If a duplicate controller is discovered, stop only the duplicate controllers, preserve jobs already running, and reconcile the state before continuing.
- Record runtime metadata for every job: ComfyUI version/commit, Python, PyTorch, CUDA, root path, command line, workflow builder, model/LoRA, dimensions, actual megapixels, duration, audio start, overlap, steps, and seed.

## Required artifacts

Keep a resumable production folder containing:

- song, audio metadata, lyrics/transcription, style brief, and user references;
- AGY raw analysis, Codex normalized analysis, producer transcript, treatment, and timeline;
- mode decision: full lip-sync, full non-lip-sync, or hybrid;
- opening-frame/reference attempts and the approved reference map;
- shot manifest with editorial windows, model audio windows, first vocal onset, integer generation duration, overlap, trim, model choice, prompt, dimensions, megapixels, steps, and seed;
- generated attempts, accepted clips, AGY/Codex QC reports, and correction decisions;
- silent assembly, final audio master, technical report, runtime metadata, and `state.json`.

Never overwrite an approved asset. Use numbered attempts and record every decision that changes continuity, timing, mode, resolution, or audio alignment.
