---
name: h3-prompt-writing-master
description: "Write, audit, and refine MiniMax H3 prompts for T2VA, I2VA, FL2VA, L2VA, and Ref2VA, including reference alignment, realistic shot direction, audiovisual sound fields, and local ComfyUI native-audio workflows. Use when authoring or QA-ing H3 prompts; do not submit jobs or change runtime settings."
---

# H3 Prompt Writing Master

Use this skill as the prompt-authoring and prompt-QA layer for MiniMax H3. It is deliberately separate from editorial planning, scene-frame design, ComfyUI execution, and post-production. It may describe the approved shot and its audio relationship, but it must not submit jobs, change a live service, choose hardware settings, or silently redesign an approved storyboard.

The official H3 guides are the format authority. Their field names, section order, label syntax, timing notation, and speaker conventions are contractual. The local rules in this skill are additive safeguards for realistic music-video work and the repository's native-audio workflows. The source links are listed in `references/official-sources.md`.

## Required workflow

1. Identify the exact H3 mode before writing: T2VA, I2VA, FL2VA, L2VA, or Ref2VA. Do not mix templates.
2. Record the requested duration and the role of every supplied reference. Keep every reference label stable throughout the prompt.
3. Build the visual timeline from the opening state to the end state: composition, subject invariants, environment, lighting, one dominant action, body mechanics, framing, camera motion, and the intended final moment.
4. Build the sound timeline separately: master audio or copied reference audio, diegetic sounds, non-diegetic music, speaker ownership, vocal onset, and whether the mouth must remain closed.
5. Add the mode-specific reference-alignment sentence or Ref2VA retention sections required by the official guide.
6. Write the exact H3 fields in the mode's required order. Keep lyrics, dialogue, and visible text exact when text is required; never paraphrase them.
7. Audit the prompt with `references/h3-prompt-quality-checklist.md`. If an input is missing, mark the assumption instead of inventing a factual timing, identity, or reference relationship.

## Mode contracts

### T2VA

Use the base three-field contract for text-to-video/audio. Describe a complete shot in `integrated_multimodal_description`, then provide `overall_soundscape` and `non_diegetic_music`. Do not imply a visual reference that was not supplied.

### I2VA

Use the base three-field contract and begin the visual description with the official opening-anchor form:

`For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`

Then describe the action that grows from that anchor. If the picture is only an identity or style reference rather than the literal first frame, define it as a subject/style reference instead of falsely claiming full-frame preservation.

### FL2VA

Use the official first-frame and last-frame alignment form. Treat the two supplied pictures as endpoints: describe a physically plausible continuous path between them. Do not turn the middle of the shot into a hidden camera cut or a second unrelated setup.

### L2VA

Use the official last-frame alignment form, with the requested final time written using the guide's exact two-decimal notation. Describe a plausible preceding state that converges to the supplied final frame. Do not make the subject appear to teleport into the endpoint.

### Ref2VA

Use exactly these six sections, in this order:

`subject_definitions`

`summary`

`retention_analysis`

`detailed_description`

`overall_soundscape`

`non_diegetic_music`

Use stable labels such as `<Subject 1>`, `<Picture 1>`, `<Video 1>`, and `<Audio 1>`. `summary` begins with the appropriate bracketed task type from the official guide. State whether each visible reference is fully preserved, partially preserved, transferred by attribute, or weak; do not claim full preservation when only identity/style is intended. Reference audio and copied lyrics/voice use Audio labels, not Picture labels.

## Writing the visual description

Use concrete, filmable facts rather than adjective piles. A strong description answers:

- What is in frame, where it is, and how large it appears.
- Which identity details are invariant: face, skin tone, eye color, hair/dreadlock pattern, body build, wardrobe, jewelry, markings, and signature props.
- What the environment physically contains and how it is lit.
- What one primary action happens first, next, and last.
- How the performer moves with believable weight, balance, hand articulation, foot contact, and reaction to the beat.
- What the camera is doing: shot size, angle, direction, motion type, and meaningful amplitude or speed.
- What state the shot should reach before the next cut.

Use one camera setup per shot. A push, pan, truck, tilt, pedestal, arc, tracking move, roll, zoom, POV move, static setup, or restrained shake is acceptable when its path and magnitude are clear. A major angle or location change belongs between shots and must be written as an explicit cut, not hidden inside a vague phrase such as "the camera moves dynamically."

For realistic music video prompts, make the performance specific: "the lead performer shifts weight onto the rear foot, rolls one shoulder on the snare, and raises two fingers toward lens" is useful; "he looks cool and dances energetically" is not. Preserve the approved character instead of allowing a new face, hair pattern, eye color, wardrobe, or body type to be invented.

## Writing sound and vocals

Keep the visual description and the sound description distinct. `overall_soundscape` covers physical and ambient sound in one to four English sentences; it must not repeat the words of dialogue or singing. `non_diegetic_music` covers instrumentation, rhythm, speed, arrangement, and audible changes in one to three English sentences; do not use it as a mood-only label.

Use stable speaker identifiers such as `(S1)` and `(S2)`. On first appearance, identify the voice; thereafter keep the identifier unchanged. If text-based vocal conditioning is requested, put only the language tag and the exact supplied words inside the official dialogue/singing element. Do not rewrite lyrics, normalize slang, or invent ad-libs. Visible text must remain in English double quotes exactly as approved.

Assign the vocal owner explicitly. If the Phantom sings a chorus, the main performer must not be described as singing at the same time. If a character is present during an instrumental passage, say that the mouth stays closed and there is no lip movement; describe dance, gesture, and reaction instead. For an off-screen voiceover, use the official "says in an off-screen voiceover" wording and explicitly state that the lips remain closed.

When a supplied audio file is the master track, it is the timing authority. Do not manufacture a second song, soundtrack, or unrelated generated audio. If the local workflow has native audio locking, describe visible performance against the locked segment and let the execution manifest carry the file, trim, and model parameters.

## Music-video continuity overlay

This skill supports a segmented music-video workflow, but the editorial manifest remains authoritative for exact start/end times, generated audio windows, trims, overlap, model choice, and output dimensions.

For a shot with an incoming overlap, the prompt must make the opening state a continuation: the performer is already mid-gesture, already in the established body rhythm, and, when that lead-in contains vocals, already inside the same vocal phrase. The generated audio window begins earlier than the shot's real edit-in point; the editor removes that lead-in and cuts where both neighboring renders are already in motion. Example: a shot displayed at `05-10` may be generated from `04-10`, with `04-05` used only as lead-in. The exact integer/trim policy belongs in the manifest, not as an improvised claim in the prose.

Do not use overlap to excuse a frozen opening frame. State the continuation action, preserve screen direction and lighting, and give the next shot a compatible exit state. If a cut crosses a lyric or dialogue phrase, use the official scene-transition/cutoff conventions and state that the audio continues; never duplicate the master audio in assembly.

For instrumental passages, choose regular Turbo or the local native-audio path according to the approved technical plan. The prompt must still describe the performer dancing to the actual rhythmic accents, not silently lip-syncing. Supporting dancers may share the rave styling while remaining visibly distinct from the lead.

## Local bridge separation rules

The repository's native-audio-lock workflow and the official H3 prompt contract solve different problems. Keep them separate:

- H3 prompt: visible action, identity preservation, camera, soundscape, music, vocal ownership, and reference alignment.
- Editorial manifest: phrase-safe cut points, integer shot durations when requested, overlap lead-in and trim, real timeline placement, and adjacent-shot transition.
- Technical settings: megapixels, legal dimensions, steps, sampler, VRAM policy, workflow, and runtime diagnostics.

Never invent dimensions, step counts, seeds, or performance claims inside a creative prompt. If the user specifies a production constraint such as five-second shots, 1:1 or 9:16, or 1.5 MP, record it in the technical/editorial plan and ensure the prompt's requested duration agrees with the generated window.

## Final prompt audit

Before returning an H3 prompt, confirm:

1. The selected mode and template are unambiguous.
2. Every reference label is defined once and reused consistently.
3. The opening anchor, action order, end state, framing, and camera path are physically coherent.
4. Identity invariants are stated where preservation matters.
5. The correct character owns each vocal line; non-singers have closed mouths.
6. Lyrics/dialogue/visible text are exact and not duplicated in the wrong audio field.
7. Soundscape and non-diegetic music are concrete and non-redundant.
8. Any overlap is represented as continuation plus manifest metadata, not a hidden reset.
9. No contradictory camera directions, simultaneous incompatible actions, invented references, unrelated soundtrack, or abstract-only adjectives remain.
10. The prompt contains no execution mutation or claim that a live service was tested.

When reporting a prompt, return the exact prompt first, followed by a short audit note listing assumptions or unresolved inputs. Do not silently "fix" an approved lyric, character, or shot decision.

## Supporting references

- `references/official-sources.md` - official MiniMax H3 prompt and music-video sources.
- `references/h3-prompt-quality-checklist.md` - reusable acceptance checklist and common failure patterns.
- `references/local-comfy-h3-profile.md` - local bridge boundaries and stable H3 execution facts that should not be mixed into creative prose.
