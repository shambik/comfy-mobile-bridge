---
name: sequential-i2v-continuity
description: Generate and assemble sequential image-to-video shots that continue the previous shot's action and camera state, using verified last-frame handoffs and frame-accurate editorial seams. Use when multiple I2V shots must feel like one continuous take; do not use it to redesign unrelated independent shots.
---

# Sequential I2V Continuity

Use this skill for the continuity/execution layer of a sequential I2V production. It governs the handoff between generated shots, the smooth editorial seam, checkpointing, and continuity QC. It does not replace audio analysis, storyboarding, visual-reference design, or model-specific prompt writing; pair it with those skills when the production requires them.

Read [observed-test-rules.md](references/observed-test-rules.md) when starting or resuming a sequential production. It records the real sandbox and movie-sequence behavior this skill was derived from.

## Non-negotiable distinction

Sequential generation and editorial smoothing solve different problems:

- **Generation continuity:** Shot B starts from Shot A's verified actual final frame and continues the action/camera state already in progress.
- **Editorial smoothing:** The assembly applies a one-frame visual fade at the handoff and, when audio exists, a very short audio crossfade. This is a subtle seam, not a long dissolve.
- **Music overlap:** A lip-sync shot may need an extra lead-in window before its visible edit point. That is separate from sequential frame handoff and must be recorded explicitly.

Never use an editorial dissolve to hide a bad handoff. If the character, action, camera direction, or screen geography jumps, reject the shot and correct the input/prompt.

## Scope and control

- Keep the user's requested engine, aspect ratio, megapixel value, duration policy, audio policy, and app/ComfyUI execution path. Do not silently substitute R2V, another workflow, or another runtime.
- Treat `requested_duration` and the file's `native_duration` as separate values. ComfyUI may return a native frame count slightly longer than the requested duration; record it rather than padding with a repeated final frame.
- Do not trim, drop frames, or re-encode a source before extracting the handoff frame. Any later editorial trim must be explicitly present in the approved manifest and must not create a freeze.
- Use a fresh, non-sequential seed for each attempt unless the user explicitly requests a fixed seed. Preserve the seed in the manifest; never silently switch to sequential seeds.
- Do not cancel, restart, or alter unrelated ComfyUI jobs or services. Preserve every failed attempt and never overwrite an approved artifact.
- Default to interactive approval gates: approve the continuity map, inspect the opening frame, approve each dependent shot, then approve the assembly.

## Continuity modes

Record one mode per shot boundary:

- `fresh`: a new shot-specific opening frame; no previous-frame handoff.
- `sequential`: the next I2V shot starts from the previous accepted shot's actual final frame.
- `sequential_corrected_anchor`: the previous final state is preserved, but a corrected opening frame is created because the raw final frame is a poor I2V input.
- `hybrid`: use sequential handoffs only where the same action and camera path should continue; use fresh frames for intentional location, scale, performer, or visual resets.

Do not make every shot sequential by default. A hard visual reset is often better than forcing incompatible locations or compositions through one frame.

## Required handoff procedure

For every dependent boundary:

1. Finish Shot A with the action and camera still in progress. Avoid a pose freeze, a held endpoint, or a camera move that cannot be continued.
2. Preserve Shot A's native MP4 and extract its actual last frame from that exact file.
3. Inspect the extracted frame for identity, face/eyes, hair, wardrobe, props, hands, body state, framing, screen direction, lighting, and usable geometry.
4. If the frame is rear-facing, cropped, obscured, malformed, frozen, or otherwise a poor anchor, create a corrected anchor that preserves the intended final state. Record why the raw frame was rejected.
5. Submit Shot B through the approved I2V path with the selected handoff frame. The prompt must say that the action and camera are already in progress and must continue naturally; it must not describe a new start pose.
6. Check Shot B's first motion against Shot A's final motion before approving it. Do not continue the chain from an unreviewed or rejected shot.

When scene references are needed for a new composition, use a shot-specific frame composed from the approved references plus the previous final frame as continuity context. The previous frame preserves identity, unfinished action, camera direction, and geography; it must not override an intentionally new location or composition. A library/reference image is not automatically the I2V opening frame.

## Prompt requirements for sequential shots

Prompts should be short, concrete, and shot-specific. Include only the action, subject invariants, camera behavior, environment, lighting, and transition-relevant constraints needed for this shot.

State the following when applicable:

- Continue the exact physical action from the input frame; no reset, restart, sudden pose change, or frozen endpoint.
- Preserve the approved identity invariants, including the exact hair silhouette, eye appearance/color, facial features, wardrobe, jewelry/props, and body proportions. Use the approved reference as the authority instead of inventing replacement descriptors.
- Keep one physically plausible camera setup through the shot. Allow only subtle motivated movement such as a small push, follow, handheld breathing, or micro-parallax; do not relocate or change to a new angle inside the shot.
- Maintain screen direction, camera height, lens feel, lighting direction, exposure, and environmental geography unless the storyboard explicitly calls for a change.
- Make body motion realistic and continuous. Do not add speech, singing, or mouth movement when the shot is marked instrumental/silent.

Do not add unrelated lore, objects, camera moves, or visual effects merely to make the prompt sound sophisticated. The continuity prompt must serve the approved shot plan.

## Per-shot checkpoint and QC

Every shot attempt must have a record containing at least:

```json
{
  "shot_id": "S02",
  "attempt": 1,
  "continuity_mode": "sequential",
  "requested_duration": 5,
  "native_duration": 5.166667,
  "input_frame": "frames/S01_last.jpg",
  "actual_last_frame": "frames/S02_last.jpg",
  "seed": 123,
  "video": "shots/S02.mp4",
  "opening_frame_strategy": "previous_last_frame",
  "seam": {
    "video": "one_frame_fade",
    "audio": "short_crossfade",
    "frame_count": 1
  },
  "qc_status": "pending",
  "rejection_reason": null
}
```

Before approval, inspect the complete clip and compare the previous last frame with the current opening and first motion. Check:

- identity, eye appearance, hair, wardrobe, jewelry, props, and hands;
- action continuity, body physics, gaze, foot/hand position, and no restart;
- no freeze, duplicated hold, body slide, warped anatomy, or sudden background jump;
- camera direction, height, lens feel, speed, screen geography, and lighting continuity;
- audio presence/absence and any unintended speech, singing, or mouth movement;
- no accidental text or visual artifacts that materially affect the shot.

On failure, preserve the attempt, write the concrete correction, select a better anchor or prompt, and generate a numbered replacement. Never silently replace the rejected file.

## Smooth assembly

Use the following default for a sequence that is meant to feel continuous:

- Apply a **one-frame video fade** at each approved sequential handoff. At 24 fps this is approximately `0.0416667` seconds; calculate one frame from the actual source frame rate rather than hardcoding 24 fps.
- When clips contain audio, apply a matching **very short audio crossfade** at the handoff. For silent clips, do not invent audio.
- Do not use a multi-frame dissolve, repeated endpoint, speed stretch, or freeze-frame padding unless the user explicitly approves that effect.
- Compute transition offsets from the actual native durations and frame rate. Do not assume every Comfy output is exactly five seconds.
- Validate the assembled file's dimensions, frame rate, duration, video stream, audio policy, and absence of unintended freezes.

The one-frame seam is editorial polish only. The source clips must already have matching motion at the boundary.

## Sequential handoff versus music overlap

For a song, record these fields separately:

```text
generation_start: 4
generation_end: 10
visible_start: 5
visible_end: 10
lead_in: 1
cut_at: 5
```

A five-second visible shot with a one-second hidden lead-in requires a six-second generation window. If the user requires every generated file itself to be exactly five seconds, it is mathematically impossible to retain five visible seconds and also hide a one-second lead-in; surface that conflict instead of silently changing the duration. A silent instrumental sequential test normally needs the frame handoff, not song overlap.

## Required user gates

Stop for user approval before:

1. creating the first opening frame for a new sequence;
2. generating a dependent shot after a continuity map or input-frame change;
3. replacing a rejected anchor or shot with a materially different action/composition;
4. assembling or publishing the final sequence.

When the user has already approved a specific shot and only a retry is requested, preserve its approved treatment and change only the recorded correction.
