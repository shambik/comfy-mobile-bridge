---
name: realistic-rap-turbo-music-video
description: Plan and produce realistic rap music videos with AGY-verified audio timing, Turbo lip-sync/regular Turbo shot decisions, deliberate overlap, coherent rapper styling, and approval-gated Opening Frames.
---

# Realistic Rap Turbo Music Video

Use this skill for a lyric-timed rap video where the user wants a credible,
artist-first music-video look rather than a slideshow, fashion board, or
generic AI montage. It is an audio-first planning skill and does not authorize
media generation before the plan is approved.

## Required production sequence

Keep the state machine explicit:

`fresh source intake -> source audio analysis -> propose treatment and shot plan -> AGY critique -> revise -> user approves plan -> Opening Frame/reference design -> user approves assets/manifest -> Turbo generation -> QC -> assembly`

When the user asks to start fresh, use only the current song and lyrics plus
newly supplied creative direction. Do not reuse an earlier production's
timings, prompts, references, generated media, or saved AGY conversations.
Preserve each analysis and revision under a new versioned artifact instead of
overwriting it.

Do not create Opening Frames, still references, or video until the user has
approved the refined audio/shot plan. A failed or timed-out AGY call is not an
approval signal.

## Source-audio research

Inspect the actual audio. Lyrics help identify words but are never timing
authority. Use a fresh AGY conversation for every material source-analysis or
critique pass. Give AGY the exact source file or a lossless excerpt and require
proof of the path it inspected, decoded duration, sample rate, channels, and
direct audio listening.

For the first planning block, map every meaningful event: instrumental windows,
spoken words, clean rap phrases, breaths, phrase tails, scratch/chopped vocal
samples, beat or energy changes, and transition material. Mark each event as
clean visible performance, processed lead vocal, scratch/sample, or
instrumental. Resolve disagreements with a focused AGY pass and independent
metadata/ASR/waveform checks; never average contradictory timestamps.

If the first approximately 30 seconds end inside a live phrase, extend the
planning block to the next phrase-safe boundary. State why the extension is
needed.

## Integer and five-second profile

When the user requests integer durations, square output, and roughly five
second shots:

- Use integer editorial starts, ends, and durations in the execution-facing
  manifest.
- Use five seconds as a cadence, never as a mechanical grid.
- If an integer five-second cut splits a word, phrase, breath, bar, or musical
  resolution, choose the smallest integer exception, label it, and send it to
  the user for approval. Do not silently round or trim the phrase.
- Keep source-evidence timings fractional in the audio timeline when needed;
  the integer rule applies to execution-facing windows and durations.
- Request `1:1` and `1 MP`, then resolve legal workflow dimensions in the
  technical pass and record actual pixels and actual area. Do not claim rounded
  dimensions are exactly one megapixel.

## Shot and overlap contract

Every shot has two clocks:

```text
editorial_start/end    = when the shot is visible in the edit
model_audio_start/end  = source audio sent to Turbo
overlap_before         = editorial_start - model_audio_start
trim_in                = lead-in removed at the editorial cut
trim_out               = hidden tail removed after the visible range
generation_duration    = integer duration requested from the workflow
```

For a new lip-sync angle, include a deliberate lead-in so the performer is
already moving before the visible cut. The lead-in is part of the source audio
window and is hidden only by `trim_in`; it must not be removed from the model
input just to fit a five-second clip. Recalculate every field and verify:

`editorial_duration = editorial_end - editorial_start`

`model_audio_duration = model_audio_end - model_audio_start`

`trim_out = model_audio_duration - trim_in - editorial_duration`

`trim_out` must be non-negative. The visible model range must not expose the
next lyric accidentally. Check the previous phrase's tail, the action state at
the new Opening Frame, and the following shot before accepting the overlap.

Regular Turbo shots may also have an editorial overlap window when continuity
benefits from it, but they must not imply false mouth articulation.

## Turbo mode selection

Choose the mode from the shot plus adjacent context:

- `turbo_lipsync`: a visible rapper is delivering a clean spoken/rap/sung
  phrase and the mouth must follow the supplied source audio.
- `turbo_regular`: true instrumental material, environmental or texture
  coverage, a prop/detail shot, or a scratch/chopped sample where no visible
  performer should articulate the audio. If a person remains visible, specify
  neutral/closed mouth.
- `mixed`: avoid when possible; use separate phrase-safe shots instead.

A processed low-metallic lead vocal does not prove a second singer. Unless the
source establishes a distinct vocalist, keep the real rapper as the lip-sync
source and use a second character as an intentional visual embodiment. If the
user requests that character, introduce it on the chorus or other musically
supported section and let it carry presence/action rather than a fake speaking
mouth.

## Real rap-video visual bible

Prioritize artist-first coverage: a confident rapper, readable performance,
strong silhouette, and cinematic camera grammar. For a cool contemporary/90s
rap direction, prefer worn-in premium streetwear, practical boots, controlled
accessories, coherent fit, and no accidental brand logos or generated text.
The set should feel physically shootable: real surfaces, motivated practical
lighting, believable shadows, and restrained color design.

If a sci-fi counter-character is requested, keep it human-scale and grounded:
practical matte materials, subtle articulated construction, controlled visor or
shadowed face, and one restrained light/reflection motif. Avoid cartoon robots,
floating holograms, fantasy armor, glowing eyes, unexplained duplicates, and
costume-like silhouettes unless the user explicitly asks for them.

Each generated shot is one fixed camera setup. Permit only micro handheld
vibration, breathing motion, or a small physically motivated adjustment. Change
camera angle or location only between shots through a newly composed Opening
Frame and a hard editorial cut.

## Review package before approval

The user-facing plan must list for every shot:

- integer editorial start/end/duration;
- exact model-audio start/end/duration, overlap, trim-in, and trim-out;
- Turbo mode and an adjacent-context reason;
- vocal/instrumental content and source-accurate phrase boundaries;
- character action, Opening Frame requirement, camera angle, framing, lighting,
  character motion, and camera motion;
- what comes before and after it and how the cut joins;
- unresolved choices and which items require user approval.

Run an AGY plan-critique pass before asking the user to approve. If the pass
times out, record the failure and split it into smaller fresh source-audio
audits. Do not infer approval from a timeout.

## Artifact and QC rules

Keep a versioned namespace containing the fresh source manifest, lossless
excerpts, raw AGY responses, normalized audio timeline, treatment, draft and
refined shot plans, review notes, approval record, Opening Frame briefs,
generation manifest, per-shot QC, assembly manifest, and final review.

After approval, inspect every generated shot with its exact source audio and
neighbors. Check first-word onset, wrong-word bleed, visible mouth state,
identity/wardrobe/prop continuity, fixed-camera behavior, anatomy, physics,
motion artifacts, unintended text, and whether the clip contains only intended
internal audio. Preserve rejected attempts. Add the original song once during
final assembly and validate the final master after export.
