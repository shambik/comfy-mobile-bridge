# Local H3 bridge boundary

This reference keeps local execution facts out of creative prompt prose. It is not a runtime-operation guide.

## Stable local concepts

- The bridge has a native-audio-lock path for H3/Turbo-style audio-conditioned generation. In that path, the supplied audio segment is the timing authority for visible performance.
- The bridge also has a regular Turbo path for shots that do not need lip-sync. The editorial plan decides whether an instrumental shot still needs the native-audio path for beat-driven movement.
- H3 video generation uses 24 fps and requires workflow-specific frame and canvas calculations. Do not hardcode those calculations in a creative prompt.
- The local user policy may require integer durations, five-second shots, deliberate overlap, a selected aspect ratio, and a requested megapixel target. These belong in the editorial/technical manifest and must be passed unchanged to execution.
- Legal dimensions, sampler, steps, seed policy, model profile, VRAM mode, and ComfyUI process state belong to the technical director or runtime operator.

## Prompt boundary

For a native-audio shot, prompt for what should be visible at the opening frame and how the performer continues through the segment. Do not claim that prompt text alone guarantees phoneme accuracy; audio alignment and post-generation A/V review are separate responsibilities.

For an instrumental shot, explicitly request closed lips/no mouth articulation when the character is on screen. Describe body movement against the song's actual beat accents and keep any supporting dancers visually distinct from the lead.

For an overlapped shot, place the lead-in and trim in the manifest. The prompt should say that the action is already underway at frame zero and should preserve the incoming phase, screen direction, lighting, and wardrobe.

Do not use this skill to stop, restart, reconfigure, or queue a live ComfyUI process. A runtime diagnosis must be read-only unless the user separately authorizes an operational change.
