# Rap-video POC regression lessons

This note records the concrete lessons extracted from the prior realistic sci-fi rap-video session. It is a regression checklist for the next clip, not a replacement for the user’s creative decisions.

| Observed problem | Likely process failure | Prevention in the POC |
| --- | --- | --- |
| Six-second jobs appeared after a five-second requirement | A helper/workflow default overrode the requested duration | Validate the request immediately before queueing; reject anything except integer `5` for raw generation |
| Overlap was missing on many lip-sync shots | Overlap lived in prose instead of being required per shot | Require model window, overlap, trim, and transition fields on every lip-sync record; fail preflight when any is blank |
| The wrong character sang the chorus | No explicit vocal-owner field and prompts allowed both performers to sing | `performance_owner` is mandatory; Phantom owns the chorus; main MC is explicitly closed-mouth unless assigned a line |
| The Phantom appeared before the intended scratch/action beat | Opening action phase was not specified | Record `scratch_before_vocal` or `vocal_already_in_progress`; review the first seconds against the source onset |
| MC/Phantom shots did not look like a real rap video | Frames optimized for isolated character depiction instead of artist performance | Use cinematic performance framing, cool rapper styling, controlled lighting, and a stable shot-specific camera |
| Two previews seemed to have no sound | Internal lip-sync audio and final soundtrack policy were conflated | Label model-driving audio separately; create an explicit muxed review copy and add the original song once to the final master |
| The assembled pilot contained visible freezes | A one-second gap was filled by duplicating the previous frame | Never use frame holds; use documented incoming overlap coverage or revise the editorial map; run `freezedetect` |
| A good approved take was later lost/replaced | Resume/reconcile logic used a generic shot filename rather than the approved artifact | Lock exact approved path/job/attempt in an approval ledger; final assembly may resolve only through that ledger |
| ComfyUI became unavailable repeatedly | Runtime failure and job state were treated as the same problem; retries created duplicate work | Keep one controller, recover submitted jobs by id, retry transport only, and checkpoint every transition |
| Timing was discussed from lyrics/metadata without enough audio evidence | Text was treated as a substitute for listening | Send the actual song to a fresh AGY session; retain raw response and normalized timeline; label uncertain timing |
| A restart or old production could contaminate the next attempt | Fresh-start boundary was not enforced | Use only the current source audio/lyrics/references when the user says start fresh; version every manifest and render |
| A technically valid file still felt wrong | Technical checks were mistaken for creative acceptance | Require AGY + Codex review of the whole clip and exact audio window, then separate user approval from technical QC |

## Successful pattern to preserve

The good take was not produced by adding more random generations. It came from a targeted correction: preserve the accepted character design, define who owns the vocal, define the opening action, keep one camera setup, use the intended overlap, and review the exact artifact. Future retries should change only the rejected shot’s documented defect while retaining all approved decisions.

## Minimum manifest invariants

Before a runner starts, verify:

- raw `generation_duration == 5` for every Turbo shot;
- all execution duration fields are integers;
- `aspect_ratio == "1:1"` and target megapixels are `1.0`;
- every lip-sync shot has `model_audio_start`, `model_audio_end`, `overlap_seconds`, and `trim_in_seconds`;
- every performance shot has exactly one `performance_owner`;
- chorus owner is `phantom` when the treatment assigns the metallic Phantom vocal;
- each shot has an approved opening-frame path;
- final assembly references only exact user-approved artifacts;
- no assembly gap uses a frame hold or duplicated still;
- silent assembly and final master pass freeze detection and full decode.
