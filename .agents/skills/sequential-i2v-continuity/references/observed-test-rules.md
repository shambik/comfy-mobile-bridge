# Observed sequential-test rules

This reference records the local experiments that motivated `sequential-i2v-continuity`. It is evidence for the workflow rules, not a requirement that every future production use the same subject, aspect ratio, audio policy, or megapixel value.

## 1. Basic three-shot sandbox

Source records:

- `D:\repository\state\sequential_flow_sandbox_20260905\README.md`
- `D:\repository\state\sequential_flow_sandbox_20260905\test_spec_v001.md`
- `D:\repository\state\sequential_flow_sandbox_20260905\run_manifest.json`

The test used three requested five-second Regular Turbo clips at 1:1 and 1 MP. It was silent and unrelated to a song. Shot 1 used the character anchor; Shot 2 used Shot 1's verified actual final frame; Shot 3 used Shot 2's verified actual final frame. The action was a restrained walk through a rain-wet transit concourse, and the camera stayed on one stable physical setup with small motivated movement.

The runner preserved ComfyUI's native output. The files were recorded at approximately `5.166667` seconds, and the native final frame—not a trimmed or re-encoded substitute—was extracted for the next handoff. The test specification explicitly notes that a five-second visible shot plus a one-second hidden lead-in would require a six-second generation window; this test did not use music overlap.

## 2. Multi-person continuation

Source records:

- `D:\repository\state\sequential_flow_sandbox_20260905\multi_person_motion_v001\run_manifest.json`
- `D:\repository\state\sequential_flow_sandbox_20260905\multi_person_motion_v002\run_manifest.json`
- `D:\repository\state\sequential_flow_sandbox_20260905\multi_person_sequel_v001\run_manifest.json`
- `D:\repository\state\sequential_flow_sandbox_20260905\run_multi_person_sequel_v001.py`

Two standalone motion tests were made first. A later three-part sequence used the second motion test as the anchor, then generated continuation Shots 2 and 3 from the preceding verified final frames. The assembly used a one-frame fade at each handoff. The lesson was that the next shot must inherit the actual last state and that the seam treatment should remain subtle.

## 3. Woman entering the room and radio sequence

Source records:

- `D:\repository\state\sequential_flow_sandbox_20260905\movie_noir_story_v001.md`
- `D:\repository\state\sequential_flow_sandbox_20260905\movie_noir_sound_v001\run_manifest.json`
- `D:\repository\state\sequential_flow_sandbox_20260905\movie_noir_sound_v004\run_manifest_v005.json`
- `D:\repository\state\sequential_flow_sandbox_20260905\assemble_movie_noir_sound_v005.py`

The three shots were: the woman opening the steel door, continuing into the maintenance room, and walking to/tuning the analog radio. Each dependent shot started from the previous accepted final frame, with the action and camera already in progress. The sound version used native clip audio, a one-frame video fade, and a short audio crossfade at each handoff.

The first Shot 3 drifted into emissive green eyes and was rejected. Later attempts used a controlled composition and, finally, explicit first and last anchors so the shot could begin from the panel reach and finish on a controlled face endpoint. The final corrected assembly was `movie_noir_sound_sequential_v005.mp4`. This demonstrates why a bad final frame must trigger a corrected anchor rather than blind reuse.

## 4. Failure lessons carried into the skill

- A new static opening pose can make a continuation look like a restart even when the location and character match.
- A poor previous final frame can propagate identity, eye, hair, framing, or hand defects into every dependent shot.
- Long dissolves mask rather than solve continuity and can create ghosting.
- Sequential frame handoff does not automatically provide the one-second lip-sync lead-in required by a music-video overlap plan.
- Extending a clip with a repeated final frame creates a visible freeze; preserve and record the native output instead.
- A sequence must be reviewed at every handoff. A technically completed ComfyUI job is not automatically an approved continuation.
