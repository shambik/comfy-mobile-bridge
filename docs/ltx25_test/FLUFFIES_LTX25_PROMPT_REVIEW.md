# Fluffies Episode 05 — LTX 2.5 prompt correction

## Current production checkpoint, 2026-10-25

The launch restriction described below is historical. The replacement production
now has twelve completed unique sources, S01–S12, each with full FFmpeg decode
and hash-bound sampled-frame cut review in
`state/fluffies_ep05_runaway_light_seed/`. S03 attempt 1
(`bfd382fd890945e09a13f21d700e14ac`) was rejected for the seed's glass-like
appearance; attempt 2 (`193ee935567d4f71997de398b9a583ee`) supplies the cut.
The first 44 seconds of story are assembled as a work-in-progress preview,
with exact 1056-frame/44-second proof and added-seam frame evidence. S13
(`89564cdceec14708a7dfb18c58a75f5e`) is the next creek-escape source.
Standing user authorization covers necessary tests and revisions; no per-test
permission request is needed. Machine-readable current status lives in
`production-handoff.json`; this document records a checkpoint, not a live queue.

The prior tail-free Lumi test also completed successfully, as measured in
`docs/WORKFLOW_GUIDE.md`. The entire basin story was later rejected by the
user for repetitive staging and weak storytelling, so those sources are
preserved under a hold and must not be assembled or published. The replacement
is **The Runaway Light Seed**, with 32 separately designed angles across five
connected locations, 120 seconds of story plus the selected 20 seconds of
bookends. The first five-shot scene passed its sampled-frame editorial proof,
and production has expanded to the bridge and grove. The complete episode
remains unfinished and no prefix is approved for Vault publication.

The remainder of this document preserves the earlier diagnosis and test
history; its old treatment and pending-launch statements are superseded.

## Active treatment update

Latest result: the wheel-free test completed with 217 decoded frames and native
audio, but its full frame sequence and enlarged crops show a second tail by
roughly 3–4 seconds and later body turning. It is rejected. The user also finds
the tail strange. The replacement S04 still removes it entirely and makes Lumi
a compact upright creature with two arms and two legs; all Lumi actions now
use paws. No green ribbon-like object was observed in the inspected test frames.

The user explicitly authorized the replacement test and future tests without
per-test approval. Automatic approval review nevertheless rejected the new
launch after that authorization, with only “blocked by policy.” The new
tail-free test was not submitted. Standing authorization is saved in
`review_v3/test-authorization.json`; do not ask for redundant permission.
The earlier pending-review status below describes the prior checkpoint.

The user subsequently reported the wheel remaining frozen and then starting
mid-shot, and authorized removal or a consistent solution. Revision 3 removes
the wheel entirely from the environment and every shot. A stationary stone
basin outlet supplies the obstruction/repair story. The replacement S04 still
preserves Lumi's one-tail low anatomy and grounds Bobo's feet; its prompt starts
with the tail action. S03 also received a wheel-free still and a targeted
correction to ground both characters' feet while water contacts the flower.

The user explicitly approved the concrete nine-second revised S04 test after
the earlier launch was blocked by automatic approval review. Job
`4f25ac3274a9452887806a7babdaf449` was submitted once and is awaiting full motion
review. This changes image and prompt together, so it tests the proposed
treatment rather than isolating the cause of an old artifact. The earlier
same-image wheel-containing pilot described below is superseded and was not
submitted. Active files are under `review_v3/`; the original producer stays held.

The story target is now explicitly 120 seconds excluding intro/outro: 18 shots,
plus two selected ten-second bookends, for 140 seconds / 3360 frames at 24 fps.
The Python score was regenerated to the corrected timeline. Publication and
the full revised batch remain pending actual source review.

The user rejected the initial sources. The `cac9efaaec4a4ab88abd6dc338c3802d`
watering source and `140921141f2e4d0c807713e0eb764d61` Lumi source contain a
ribbon-like green intrusion. Lumi also develops unstable appendages/body
proportions, the wheel's apparent movement/geometry is inconsistent, and
opening poses are held. Earlier onset checks did not establish full action
quality. Their approvals are revoked; source files and technical proofs remain
as evidence, not approved episode footage.

## Official guidance applied

For I2V the image establishes appearance; describe the changes, camera and
sound in the text. Keep a single take unless a cut is intended.
[LTX I2V guide](https://docs.ltx.io/open-source-model/usage-guides/image-to-video)

Use a focused, chronological, present-tense paragraph, commonly four to eight
sentences for a simple take, with visible physical actions and coherent camera
direction. Simple plausible physics is more reliable; exact mechanical
continuity still requires actual inspection.
[LTX 2.5 guide](https://ltx.io/blog/ltx-2-5-prompt-guide)

The prompt enhancer is optional for local workflows, with limited benefit for
already structured prompts. The current bridge encodes supplied text directly.
No enhancer installation or workflow/environment change is part of this test.
[Open-source prompting guide](https://docs.ltx.io/open-source-model/usage-guides/prompting-guide)

## Diagnosis and controlled test

The original first three prompts are 362, 337 and 375 words. Their shared
world paragraph unnecessarily introduces a pale-green leaf ribbon into early
shots. A ribbon-like shape then appears around Nori's legs and across Lumi's
floor/body. Prompt leakage is a plausible cause, not yet proven. The prompts
also combine static restatement, prohibitions, delayed timing phases, subject
motion and moving cameras. Checking motion only after trimming concealed
unresolved source holds and failed choreography.

The revision removes unrelated props and time-phase instructions, describes
one concrete task, and uses a steady view for diagnosis. Lumi keeps four feet
planted while its single tail sweeps; it does not rotate its whole body.
The wheel receives an explicit slow, steady direction around a fixed axle.
This wording is a hypothesis to test, not a guarantee of rigid geometry.

Pilot comparison: keep the same actual opening image, seed, requested source
duration, size, model, steps, sampler, decode and native audio. Change only the
prompt. Start with the failed Lumi source. Inspect the complete source from
frame zero for onset holds, green intrusions, anatomy, contact, one tail,
wheel direction/paddle layout and intended task. Check the watering shot's
spout-to-flower relationship separately. Do not restart full production on the
strength of prompt wording or a few changing pixels.

All revision prompts, criteria, baseline ids/hashes and manifests are in
`state/fluffies_ep05_rainbow_engine/review_v2/`. The original producer has a
boundary marker so its current job completes and new original submissions
stop. Preserve that marker until the correction is settled. Each pilot has
its own durable journal and lock. Existing runtime and all previous episodes
are preserved. No delegated agents or blind retries.
