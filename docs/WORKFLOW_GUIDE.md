# Workflow guide

Times below were measured on ComfyUI 0.33. Since 2026-11-04 the app runs ComfyUI 0.44, which was faster or equal on
every flow (`LAB_2026-11_COMFYUI_044.md` has the per-flow numbers).

## LTX 2.5 nine-second production comparison (2026-10-25)

Two native-audio opening-frame jobs on the RTX 3080 10 GB used the same
1600×896 image, seed 1060001, Balanced quality, 8 steps, sharp decode on,
calm sampler off and 9-second request. Only the action/camera prompt changed.
Job `1d40b1ba00b8465593ce567998f2c63f` took 540.9 seconds of generation;
job `b120685b9f33412fa061c8d2be7abc42` took 835.4 seconds. Both produced
217 frames at 24 fps with native audio and passed ffprobe/full FFmpeg decode.
Peak recorded VRAM was 9893 and 9877 MiB respectively. In the slower run,
sampling reached step 8 after approximately 371 seconds and decoding/finishing
occupied approximately another 464 seconds, including several minutes on one
spatial decode tile. This is evidence of a decode bottleneck; memory pressure
is plausible but the logs do not establish why the repeat was slower.

The second source lowered the kite but had user-reported rope defects and did
not establish a reliable internal hard cut. Neither run is artistic approval.
The revised episode uses separate camera-angle clips and explicit first/last
frames for selected prop-state transitions, through the existing bridge queue.
No model, environment, tiling or runtime flags were changed. Per-shot durations
and queue requests are recorded under the ignored production state directory;
the queued batch is not yet proof of a faster or defect-free recipe.

## MiniMax pinwheel recovery measurement (2026-10-23)

On the RTX 3080 10 GB, a five-second **H3 Fused SLA Direct** opening-frame job
at **1.5 MP**, six steps, native encoder/audio and sparse 0.90/64 completed in
**597.9 s**, job `212e3b3be95748cf92f4294fec7b09d9`. Actual output: 1664×928,
24 fps, 124 frames, 5.167 s. The lab used legacy loading with dynamic VRAM,
async offloading and pinned memory disabled. Peak GPU use was 9851 MiB and
system RAM 64174 MiB. Actual SLA execution: 300 calls, zero dense fall-throughs;
effective sparsity was 83.5% after protecting the audio/conditioning prefix.

The eight-second 1.5 MP attempts stalled or advanced too slowly with GPU
allocations spilling into shared memory. Use the tested five-second production
request for this scene; the recovery settings are not proof that longer clips
fit. Both native and music-mixed MP4s passed full FFmpeg decode. The mixed file
adds an original mallet/plucked-string cue while retaining generated foley and
copying the picture stream. Artistic review remains with the user. Exact
requests, repair comparisons and restart instructions:
`docs/ltx25_test/TUMBLE_PUFFS_HANDOFF_PLAN.md`.

A repeat through the main bridge with seed 1023611 completed in **660.3 s**
(job `93c2578c1bdb4a0e9b0da3738b01a516`), with the same dimensions, frame count
and actual SLA call/fallback results. Peak GPU/system RAM was 9845/64801 MiB.
Native and music-mixed files passed full decode; the mixed repeat is also
stored in the main bridge's Video Vault.

Which workflow to use for what, the settings that worked best, and how long
each takes. Every time and finding below was measured on the reference machine
(RTX 3080 10 GB, 64 GB RAM; see `docs/HARDWARE_AND_VRAM.md`) with real jobs.
Test IDs in brackets point to the speed-lab and app test runs behind each claim.
Anything marked **untested** is a reasonable default, not a measured result.

## Quick pick

| You want | Use | Settings that worked best |
| --- | --- | --- |
| A person singing or talking to your audio track | **H3 lip-sync** (most natural mouth) or **LTX lip-sync** (faster) | H3: Turbo + Sage + sparse attention. LTX: face close-up as the opening image, Balanced size, a prompt that describes that same close-up |
| A video from a text prompt only | **Text** mode, H3 Turbo or LTX | H3 Turbo + Sage + sparse is fastest; LTX also generates matching sound |
| Animate one still image | **Opening frame** mode | H3 Turbo + sparse, or LTX with "sharp decode" on |
| Move from one image to another | **First + last frame** (I2V) | H3 Turbo + Sage + sparse, Fused SLA I2V/FL2V, or LTX |
| End on a chosen image | **Closing frame** mode | H3 or LTX |
| Keep a character, outfit or place from reference images | **Reference** mode: H3 Ref2VA, Omni (follows a song or a video's moves), or LTX with one reference sheet | H3: Turbo Ref2VA + sparse, or Fused Ref2VA (multi-reference takes up to 9 images, 3 videos and audio). LTX: landscape only, up to 5 s. A reference video makes H3 much slower (see below) |
| A vertical clip of characters from a sheet | Make a vertical still from the sheet (any image tool), then **LTX opening frame** | LTX reference does not do vertical (see below) |
| Several clips that must continue one another (only when you ask for continuity) | **Connected sequence** (2–20 text prompts, H3 engines only) | From the second clip on, each starts from the previous clip's last frame. Independent clips do not need this |
| A bigger or smoother copy of a finished shot | The **הגדלה** / **החלקת תנועה** buttons on its card | RIFE for 48/60 fps, Lanczos, Real-ESRGAN ×2 or RTX VSR for 2560 px; sources up to 1080p, any length (long clips run in chunks inside one job), uploads too (see below) |
| More real detail in a finished Pika or Turbo v4 lip-sync shot | **RTX VSR** to 1920, then **פרטים H3** on that card | Strength 0.45 (recommended) or 0.30-0.75; about 5.5 min per 5 s, up to 15 s (see "RTX VSR + H3 detail" below) |
| Still images | **Image Lab** or **H3 still** | Recipes listed per workflow in the Image Lab page |

## H3 engines

| Engine | Steps (recommended) | Best for | Notes |
| --- | --- | --- | --- |
| Turbo v1 (default) | 4 (4–12) | Fast everyday clips | Steadier with fast motion |
| Turbo v4 | 6 (4–8) | Faces and fine detail | Uses its own Turbo LoRA; needs it installed |
| Standard | 20 (8–30) | Reference mode without Turbo; maximum fidelity | Slow; **untested** for speed in the lab |
| Spectrum | 16 (8–30) | Native sampling with its own acceleration | **Untested** for speed or quality in the lab |
| H3 Fused SLA | 4 (4–8; some variants fixed at 4) | Low-VRAM official graphs with sparse attention built in | 8 steps is slower and can sharpen detail |

Fused SLA variants: **Direct** (text or images, 4–8 steps), **I2V/FL2V**
(opening/closing frame), **Ref2VA** (exactly one reference image),
**Ref2VA multi-reference** (up to 9 images, 3 videos, one audio), **De-rope**
(two-pass recovery) and **DyRoPE** (temporal adapter). Measured: Fused SLA
first + last frame 2:41, Fused SLA reference 6:44 [Results by mode].

Lip-sync with H3 uses the native 32B text encoder and Native AudioLock, which
keeps the uploaded audio exact. The music-video skills
(`lipsync-skill`, `agy-turbo-lipsync-pipeline`,
`realistic-rap-turbo-music-video`) cover song analysis, shot planning and when
to use lip-sync versus regular Turbo; `h3-prompt-writing-master` covers prompt
structure for every H3 mode.

### Reference videos are slow (2026-11-05)

Until 2026-11-05 the Standard, Turbo, Spectrum, Singularity and Pika reference graphs sent their
references in a form ComfyUI ignores, so those jobs rendered from the prompt alone (issue #20). With the
references wired, a reference video adds about as many tokens as the clip being generated. Measured on
the 3080: Turbo reference at 1 MP (1344x736) with one 5 s reference video ran about 375 s per step
(3,147 s, 52 min, for 8 steps) at 9.9 GB, against 452 s in total when the video was ignored. Omni ran a
reference video at 0.6 MP in 721 s. The app does not limit the size: the form warns when a reference
video is attached. Recommended: 0.6 MP with a reference video, and close other GPU apps first.
Reference images and audio add far less.

### Turbo reference LoRA (2026-11-05)

Until 2026-11-05 Turbo reference loaded Lightx2v/ModelTC's Ref2V Turbo 4-step LoRA through larryvrh's
`MiniMaxH3TurboLoRA` node, which patched none of its weights (issue #25): Turbo reference ran on the plain Ref2VA
model, so 4 steps came out smeared and 8 steps looked fine only because the plain model nearly converges in 8. It
now follows ModelTC's own graph (`LoraLoaderModelOnly`, shift 12/3, euler, simple); the ComfyUI log shows "208
patches attached". Lab A/B, fighter sheets, 1 MP 16:9, 5 s, one seed, about 9.5 GB:

| Setup | Time | Result |
| --- | --- | --- |
| no LoRA, 4 steps (old) | 306 s | smeared |
| no LoRA, 8 steps (old) | 534 s | clean |
| **Ref2V 4-step LoRA, 4 steps** | **302 s** | **clean** |
| Ref2V 4-step LoRA, 8 steps | 539 s | clean, a little more detail |
| Ref2V 8-step v1.0 LoRA, 8 steps | 540 s | clean, slightly cleaner fast motion |
| larryvrh v4 (EMA-600), 8 steps | 534 s | clean, close to the old 8-step take |

Use 4 steps: same look as 8 in about 40 % less time. The old "Results by mode" Turbo reference times above were
measured without the LoRA. H3 reference stills (Turbo, 8 steps) take the same path: 56 s against 61 s before.

## H3 speed options: attention modes

Same job, same seed, re-rendered with each mode on Turbo (5 s clips, 6 steps,
around 0.7–1.5 MP) [Results by mode, job45cc]:

| Mode | Original | Sage | Sparse (SLA) | Sage + sparse |
| --- | --- | --- | --- | --- |
| Lip-sync | 12:17 | 9:13 | 8:43 | **5:01** |
| Opening frame | 12:12 | 7:48 | **4:58** | 5:06 |
| First + last frame | 12:17 | 7:53 | 4:58 | **4:51** |
| Text to video | 17:33 | 7:09 | 4:29 | **3:55** |
| Turbo reference | 7:55 | 5:42 | **3:32** | 3:37 |
| Fused SLA reference | 6:44 | 9:03 (slower) | built in | — |
| Fused SLA first + last | 2:41 | 2:07 | built in | — |

- **Sage** keeps the same image and is about 25–35% faster.
- **Sparse (SLA)** is about 55–75% faster but changes the image slightly;
  compare faces, lips and hands against the original before trusting it.
- **Sage + sparse** is the fastest on most modes; on opening frame and Turbo
  reference, sparse alone is as fast.
- **Do not use Sage on Fused SLA reference** (slower there), and check Sage on
  Fused SLA at 1.5 MP against the standard mode; its speed is inconsistent.
- **Chunked feed-forward** was tested and gave no speed-up (it only saves
  memory), so it is not offered [C].

### Int8 attention (opt-in, 2026-11-06)

ComfyUI 0.44's built-in Comfy Kitchen INT8 attention (`ModelAttentionBackend`,
"comfy kitchen attention"). No install, launch flag or restart; the FastH3 Omni
graph already uses it. Offered as attention mode **Int8** only where the lab
tested it; the defaults did not change. Same seeds per row, ComfyUI 0.44:

| Engine and mode | Before | Int8 | Look |
| --- | --- | --- | --- |
| Turbo v4 lip-sync, 1.5 MP 9:16, 5 s (with the INT8 decode VAE) | 722 s standard | **351 s** | same character and performance |
| Turbo v4 two-character scene, 3 shots (opening, first + last, opening), 1.5 MP 9:16 | 2,208 s standard | **1,086 s** | same |
| Singularity Ref2V God, 3 shots, 1.5 MP 9:16 | 1,612 s Sage, 2,648 s standard | **1,348 s** | same faces and performance |
| Singularity Pika flow opening frame, 1.5 MP 9:16 | 413 s Sage, 666 s standard | **348 s** | same performance |
| LTX lip-sync, 1600×896, 6 s | 259 s standard | **153 s** | frames nearly identical (PSNR 28) |
| LTX two-character scene at 2 MP (1056×1888), 3 shots | 910 s standard | **667 s** | same motion |

- **Where it is offered:** Turbo opening frame, lip-sync and first + last
  frame; Singularity reference and opening frame; LTX lip-sync, opening frame
  and first + last frame. Everything else refuses it until it is tested.
- **On Turbo, Int8 also decodes with the INT8 video VAE**
  (`minimax_h3_video_vae_int8_convrot`): 63 s -> 27 s at 1.5 MP, PSNR 42-47 dB
  against the fp16 VAE on the same latent. Turbo was tested that way.
- **Memory:** the same GPU peak as standard (9.4-9.8 GB at 1.5 MP and 2 MP).
- **Same seed, slightly different take:** like Sage, it changes the numerics,
  so the same seed gives the same scene and beats with small differences in
  motion (PSNR 21-29 against standard).
- **At LTX 2 MP the decode dominates:** sharp decode takes 86 s per shot with
  either attention, so the gain there is 27% instead of 41%.
- **Not offered:** block skipping. Skipping 6 or 12 quiet transformer blocks
  saved another 10-20% on Turbo but softened fine detail in motion (lab
  K2/K4).
- **ClipProj 4B** is a lighter text encoder, marked experimental in the app;
  its quality and speed are **untested** in the lab.
- **Full lab write-up:** `docs/H3_PERFORMANCE_TESTS_RTX3080.md` has every
  measurement (one-step profile, VAE decode, block probe and skipping, what did
  not help) and a checklist for repeating the tests on another machine.

## LTX

LTX 2.5 runs one distilled 8-step pass and generates sound with the video. All
modes accept 1–10 s, except reference (up to 5 s).

| Mode | Size | Time for 5 s | Source |
| --- | --- | --- | --- |
| Text | 1600×896 (Balanced, 16:9) | 3:25–3:45 | app T10, T7 |
| Opening frame | 896×1600 (Balanced, 9:16) | 2:49 (4:50 with both options on) | app T11, lab AV1 |
| Closing frame | 896×1600 | 3:50 | app T8 |
| First + last frame | 896×1600 | 3:45 | app T9 |
| Lip-sync | 896×1600 | 2:54–3:46 | app T12, lab D2 |
| Reference, LTX 2.5 | 1536×896 | 3:12–4:21 | app T1–T3 |
| Reference, LTX 2.3 | 1536×896 | 5:08–5:23 | app T4, T5 |
| Opening frame, 10 s | 896×1600 | 7:23 with both options on | lab AV2 |

### LTX lip-sync

- Use a **close-up opening image** (face filling most of the frame) and a
  prompt that describes **that same framing** with a **static camera**. A
  prompt asking for different framing (for example "knees to head") made the
  camera pull back and the face drift [T2 vs T3]; close-ups made the mouth
  movement big and clear on every seed [C1, C2].
- **Balanced (896×1600) is the sweet spot**: lip-sync as good as the 1 MP run
  and clearly sharper [D2]. **High (1056×1888)** is sharper but the mouth moves
  less [D1]. Upscaling a finished clip adds sharpening, not detail [D3].
- One full-size pass, no latent upscaler: the two-stage graph loosened lip
  timing [C3, C4].
- Compared with H3 on the same audio: LTX is faster, but H3's mouth movement
  was more natural, and LTX occasionally warped the face for a frame or two on
  a 7-second speech clip [E-D1, E-D2].

### LTX text and image-to-video

- **Describe motion, camera and sound** in the prompt; LTX makes the audio.
- **Keep actions gentle.** A fast spin made the character's parts pop between
  frames; removing the spin cut flicker by 25% [V4 vs V7].
- **"Sharp decode"** removes the soft frames that the default decode leaves at
  every 2-second mark (seen at 4 s on [T11], absent on [T6]). It was slower in
  the app while another ComfyUI held GPU memory [T6]. Turn it on for anything
  you will watch closely.
- **"Calm sampler"** reduced detail flicker by 14% in the lab [V6], but only
  1–4% in the app tests [T6 vs T11, T7 vs T10]. Optional.
- Both options apply to text, opening, closing and first + last frame only.

### LTX reference

- **One reference sheet** (characters, props and location laid out in panels).
  Describe each element by its position on the sheet, then the scene, motion,
  camera and sound.
- **Landscape only, 1536×896, up to 5 s.** The Ingredients LoRA was trained only
  at 768×448; vertical sheets [R8] and other sizes [R15, R16] animated the sheet
  instead of making a scene, and 10 s clips cut to a new shot halfway [R13, R14].
- **2.5 or 2.3:** 2.5 kept every character in frame in the lab where 2.3 lost
  one [R9 vs R21, R22] and is faster; 2.3 is a separate checkpoint that needs
  about 43 GB of RAM.
- **Both models sometimes open on the sheet** before cutting to the scene
  (2.5: [T1, A1]; 2.3: [T4, T5]). The app checks every reference clip and
  re-renders it with a new seed, up to three times
  (`backend/reference_check.py`). The reference times in the table are single
  renders measured before that check existed; a re-rendered clip takes
  proportionally longer.
- For 2.5, prompts in the `### Reference Sheet Description` /
  `### Target Description` format needed fewer re-renders than
  `Reference sheet:` / `Generated video:`.
- **Vertical character scenes:** make a vertical still from the sheet, then use
  opening-frame mode. That route gave the cleanest vertical clips [V1, AV1, AV2].

Details of each LTX recipe: `docs/ltx-2.5-ia2v-workflow.md`.

### High-resolution comedy production measurement (2026-10-22)

The first Snack Cartel opening-frame job (`a1e979661e104d909841d09a91acff9f`)
used LTX 2.5, High landscape 1888×1056, 8 steps, sharp decode and calm
sampler enabled, native generated audio, and an 8-second request. Generation
took **574.4 seconds (9:34)** on the reference machine. The actual file had
193 decoded frames at 24 fps (8.041667 seconds), with one audio stream
(8.010 seconds). FFprobe and full FFmpeg audio/video decode passed. This is
one measured run, not a timing guarantee for all clips or a quality benchmark.

For a native last-frame continuation, preserve the source and extract frame
`nb_read_frames - 1` by decoded frame index. The current `backend/media.py`
helper seeks 0.20 seconds before EOF and takes the first frame there, so it is
a near-end frame rather than the exact final decoded frame. The production
uses a project-local exact-frame extraction without changing the app helper.

### Night Train image preparation (2026-10-23)

Through the app's Image Lab on the same RTX 3080 10 GB, Flux Krea's
`krea_t2i_simplified_workflow.json` made 1600×896 masters in **63.6–71.2 s**
(20 steps; corridor, dining car and luggage van). A character sheet took
50.9 s. These are render timings, not perceptual-quality acceptance.

Qwen Image Edit 2509's `qwen2509_i2i_1input.json` defaults to the encoded
source-image latent scaled to about 1 MP, even when the app's output size is
1600×896. Select its exposed **Switch latent** option (`boolean=true`) so the
empty-latent width and height govern the output. An actual native 1600×896
edit completed in **165.2 s**, seed 102302, app run
`4e15201822e74eb18f6a16ff625875f0`. This used normal per-run controls; no
saved workflow or runtime was modified. The app currently treats an integer
default for the image-scale megapixel field as an integer-only override;
do not pass a fractional override for that field.

Night Train's user performs visual/listening review and requested that strict
inspection gates be skipped. Exact submissions and timing records are in
`state/night_train/execution.json`; pilot comparisons are documented in
`docs/ltx25_test/PILOT_RESULTS.md` once rendered.

The first real Night Train LTX first+last-frame pilot
(`2ba038d02a8c458ebac5f9e279bfe4df`, seed 102351) took **262.1 s** at
Balanced 1600×896, 5 s, 8 steps, sharp decode on and calm sampler off.
App-recorded peak VRAM was **9908 MiB / 10240 MiB**. Its file has 121 frames
at 24 fps, duration 5.041667 s and AAC audio; ffprobe and full FFmpeg decode
passed. This is a technical result; visual acceptance belongs to the user.

### Tumble Puffs opening-image sample (2026-10-23)

The six-second Tumble Puffs opening-image job
(`a857ca583bce433a9389470ae6736820`, seed 1023603) used **LTX High
1888×1056**, 8 steps, sharp decode on, calm sampler off and generated audio.
It took **415.8 s (6:56)**, with app-recorded peak VRAM **9339 MiB** and RAM
37641 MiB. The file has 145 frames at 24 fps, duration 6.041667 s and AAC
audio. FFprobe and full FFmpeg decode passed. This is a technical proof;
the user supplies visual feedback.

The selected cast and opening images were generated directly with **Codex
built-in ImageGen**, following the user's correction. Their source files
are 1672×941; the LTX job used the app's High landscape output size. Exact
image prompts and video settings are retained under `state/tumble_puffs/`.
The Tumble Puffs runner refuses app image submissions. Use built-in ImageGen
for future stills and the bridge app for LTX video generation.

### Fluffies native-audio production measurements (2026-10-23)

The main bridge rendered Fluffies using **LTX 2.5 Balanced landscape
1600×896**, eight steps, sharp decode enabled, calm sampler disabled and
native audio enabled. These measurements used the existing legacy ComfyUI
memory mode on the RTX 3080 10 GB; no model, workflow or environment change
was made for production.

| Job / mode | Request | Generation time | Peak VRAM | Source file |
| --- | --- | --- | --- | --- |
| `b3f6adb0caf7449d9a600d6085adf638` / first + last frame logo | 8 s | 433.0 s | 8817 MiB | 193 frames, AAC |
| `2405e969351044bb97f9b7c465eb84b2` / opening image E01 | 8 s | 402.8 s | 8817 MiB | 193 frames, AAC |
| `043411bc0ea54de6a13254fcdb3c98ea` / opening image E02 | 6 s | 285.0 s | 7825 MiB | 145 frames, AAC |
| `2630d65f261044d98a21cf0e1c3c5181` / opening image, eight-character intro | 10 s | 519.5 s | 9755 MiB | 241 frames, AAC |

All four passed ffprobe and full FFmpeg audio/video decode. Sources have
one extra video frame at 24 fps; exact edits use 192 frames for eight seconds
and 144 for six. The 22-second intro/E01/E02 preview has exactly 528 frames
and preserves native sounds with an original instrumental score mixed below
them. These are measured technical results; the user reviews movement,
character sounds and creative quality.

Production handoff: `docs/ltx25_test/FLUFFIES_PRODUCTION_PLAN.md`. The
native-audio editor is `docs/ltx25_test/fluffies_shortcut_finish.py`; do not
use the older silent-source assembler for this episode.

User feedback on the initial 22-second preview identified posed opening holds
and an unstable generated logo letter. A corrected nine-second demonstration
cuts 2.5 seconds off each of the first two story sources. The active episode
revision renders ten-second sources and uses eight-second cuts after a
two-second lead-in. The eight-character intro v4 preserves the selected full
RGBA wordmark as a separate animated foreground layer over app-generated
character motion; the model does not synthesize letters. See
`docs/ltx25_test/FLUFFIES_MOTION_REVISION.md` for current manifests, exact trims,
output IDs and resume commands.

The later **Wobbly Surprise** production keeps the user's uploaded ten-second
1080p opener and uses variable-length story cuts with a 2.5-second source
lead-in removed. Same main-app LTX Balanced settings, native audio, sharp
decode and legacy runtime. Measured source renders:

| Job | Request | Generation time | Peak VRAM |
| --- | --- | --- | --- |
| `8f444a1475f34d8a829fcba6f77ec006` / C01 | 9 s | 498.2 s | 9639 MiB |
| `78772d66eb6b4c318b9b107ecdc86677` / C02 | 9 s | 462.2 s | 9637 MiB |
| `e3f3e26368a04e3798db1e980810ff03` / C03 | 7 s | 345.2 s | 8904 MiB |
| `d80cd147d7824bc18f8e39ffb92c1795` / C04 | 8 s | 401.8 s | 9159 MiB |

All four source renders passed ffprobe and full decode. The 31.5-second
1080p preview has exactly 756 frames at 24 fps and includes the selected
opener plus all eight characters across four settings. The story source
frames are normalized from native 1600×896 into the opener's 1920×1080 canvas
in post; the app generation size was not changed. Current production plan:
`docs/ltx25_test/FLUFFIES_WOBBLY_SURPRISE_PLAN.md`.

### Rainbow Engine source measurement (2026-10-24)

Fluffies Episode 05 uses the existing main-app LTX 2.5 Balanced landscape
recipe (1600×896, eight steps, sharp decode and calm sampler enabled, native
audio, existing legacy runtime). Its first nine-second source, job
`ea741934e07d4b5c8d75fb00cfe21325`, took **555.3 seconds** and peaked at
**9711 MiB** of VRAM and 46273 MiB of system RAM. The actual file has 217
frames at 24 fps, duration 9.041667 seconds, and AAC audio. FFprobe and full
FFmpeg audio/video decode passed. This is one measured source, not a timing
guarantee for every shot.

The superseded draft authored 100 seconds of story plus the selected ten-second intro
and outro. Each story source includes three extra seconds; the initial edit
begins two seconds into the source and retains its authored six or seven
seconds. This reserves room for removing reference-pose holds without
shortening the story action. The first cut's body/foot changes were inspected
at 0.125-second intervals; camera/water pixel changes alone are not accepted
as evidence of character motion. Remaining sources and the final master
require their own checks. Plan, exact in-points and evidence:
`state/fluffies_ep05_rainbow_engine/`.

**Creative correction, 2026-10-25:** the user rejected the initial sources
for green ribbon-like intrusions, inconsistent wheel motion, opening holds
and an unstable indigo character. The narrow onset checks above did not
establish full action quality. Technical decode proofs remain valid; the
original scenes are not approved final footage. Full production is held
while prompt revisions are researched and tested. See
`docs/ltx25_test/FLUFFIES_LTX25_PROMPT_REVIEW.md`.

**Revised production, 2026-10-25:** the active plan is
`state/fluffies_ep05_rainbow_engine/review_v3/`. The user clarified **120
seconds of story excluding bookends**, so the master target is **140 seconds /
3360 frames** at 24 fps. The wheel is removed entirely; a stationary stone
basin supplies the obstruction. Lumi now has an upright two-arm/two-leg body
without a tail. A wheel-free test that duplicated its tail was rejected.

With the same Balanced/eight-step/sharp/calm/native-audio recipe, accepted
Lumi source `6e8f3312bbf94113908f228c54e2f593` requested nine seconds and took
**520.6 seconds**, peaking at **9384 MiB VRAM / 44397 MiB system RAM**.
Delivery source `723397d02f0f400cbcd8c7fbfb7385cd` requested ten seconds and
took **597.9 seconds**, peaking at **9867 MiB VRAM / 46551 MiB system RAM**.
They contain 217 and 241 frames respectively, with AAC audio and passed full
FFmpeg decode. These are individual measured runs, not a duration or memory
guarantee for other settings.

The actual delivery cut starts at frame 90 for six seconds; the Lumi cut
starts at frame 18 for seven seconds. A replacement arrival source, job
`8dcc30610333441786dba8a2ba6d34c2`, also passed frame-based motion/anatomy
review with a frame-18 six-second cut; a preceding side-profile walk was
rejected for an invented Bobo tail. Do not apply a universal two-second trim
or count water/camera pixel changes as body motion. The complete source and
the chosen action window both require inspection. The original Python score
was regenerated to the corrected timeline. The full episode remains in
production and has not yet been assembled or uploaded.

**Story replacement, 2026-10-25:** the user subsequently rejected the entire
basin treatment for repetitive staging, one location and weak storytelling.
Its sources remain preserved but must not be assembled or published. The
active production is now `state/fluffies_ep05_runaway_light_seed/`: 32 shots
across six sequences and five connected locations, retaining exactly 120
seconds of story plus the selected 10-second intro and 10-second outro.

The new lighthouse establishing source, job
`94cf6ae4b0e749a2875d16f523d30f39`, requested eight seconds using the unchanged
Balanced 1600x896/eight-step/sharp/calm/native-audio recipe. App metrics report
**432.8 seconds**, peaking at **8939 MiB VRAM / 44041 MiB system RAM**. Its
193 frames at 24 fps, H.264 video and AAC audio passed ffprobe and full FFmpeg
decode. A frame-based review selected source frames 48-131 for the 3.5-second
establishing cut. This is an environment-only shot: its moving camera and
clouds establish no evidence about character animation. The complete new
episode is still in production; no replacement master has been published.

## Upscale and motion smoothing (finished or uploaded videos, 2026-11-08)

Every finished video card has two buttons, **החלקת תנועה** (motion smoothing) and **הגדלה** (upscale).
The **עיבוד וידאו חיצוני** button above the results does the same for an uploaded video (MP4, MOV, WebM
or MKV, up to 500 MB and 60 s). Each request queues a new job (engine `post`). A job made from a card is
filed in the same project folder as its source and never changes the source.

Uploads are first re-encoded with FFmpeg (H.264 CRF 10, AAC). That applies a phone's rotation flag and
turns a variable frame rate into a constant one.

Measured through the lab bridge on the RTX 3080. Every output passed `ffprobe` and a full FFmpeg decode
with its sound:

| Method | Result | 5 s, 1632×928, 24 fps | 5 s, 1920×1080, 30 fps (upload) |
| --- | --- | --- | --- |
| RIFE 4.26 | 2× frames (24 → 48 or 30 → 60 fps), same size | 21 s · 2.1 GB | 31 s · 2.5 GB (also 1080×1920) |
| FILM | the same, a little smoother on large motion | 78 s · 7.4 GB | 123 s · **9.77 GB**, so the app refuses it |
| Lanczos | resize to a 1920 or 2560 long side; adds no detail | 23 s to 1920×1080 · 1.5 GB | 42 s to 2560×1440 (also 1440×2560) |
| Real-ESRGAN ×2 | sharpens edges and textures, then Lanczos to the target | 232 s to 2560×1456 · 4.7 GB | 378 s to 2560×1440 · 6.1 GB |
| Lanczos on 299–300 frames | a smoothed clip or a 60 fps clip to 2560×1440 | 62 s (48 fps, 247 frames) | 73 s (60 fps, 300 frames) |
| Real-ESRGAN on a smoothed shot | 247 frames, 48 fps, to 2560×1440 in one pass | 454 s · 6.8 GB VRAM · 31 GB ComfyUI RAM | not allowed (not tested) |

Limits (the server refuses anything else and says why):

- Real-ESRGAN takes sources up to 1920×1080 (either way round). RIFE and FSR 3 take up to 2560×1456, so an
  upscaled clip can be smoothed too (issue #41). FILM takes up to 1632×928.
  At 1080p FILM peaked at 9.77 GB, the edge where this card spills into shared memory.
- Any length (issue #44). One pass of the 18 s character-swap clip (432 frames, 736×1280, 24 fps)
  worked for every method on the 3080: RIFE 42 s / 1.5 GB, FILM 143 s / 4.7 GB, Lanczos 110 s / 1.1 GB,
  Real-ESRGAN ×2 to 1472×2560 530 s / 6.8 GB, RTX VSR 48 s / 1.9 GB, FSR 3 14 s / 1.3 GB. RIFE, FILM,
  Real-ESRGAN and Lanczos keep the whole clip in RAM, so one pass takes up to that many frame-pixels
  (432 frames at 736×1280, about 270 at 1632×928, never fewer than 150); a longer clip is cut into chunks
  inside one job, each processed like a short clip, and joined in order with the source's sound. Smoothing
  chunks also read the next chunk's first frame, so the frame between two chunks is still made. RTX VSR and
  FSR 3 stream frame by frame and never split. The job card shows the chunk count (for example 2/3).
- Smoothing takes sources up to 30 fps. A clip at 48 or 60 fps cannot be smoothed again.
- **RIFE 60 and 120 fps** (issue #52): extra choices next to the usual ×2. RIFE ×5 turns 24 fps into 120 fps (four new
  frames between each pair); 60 fps keeps every second frame of that (an FFmpeg step on the CPU), which lands on exactly
  60 fps. Lab 2026-11-10, Missed Bus face and the rooftop jump (1632×928, 124 frames): 36 s and 42 s, 3.7 GB, 616 frames at
  120 fps; the user watched 24, 48, 60 and 120 fps side by side and rated 60 and 120 good. ×5 holds 5× the frames in RAM,
  so only that tested size is allowed: **24 fps clips of up to 124 frames (5.2 s) at up to 1632×928**, one whole run. 120 fps
  files are 9-42 MB; most sites play 60 fps at most.
- Upscale targets have a 1920 or 2560 long side. Near-16:9 and near-9:16 sources get the standard sizes
  1920×1080 / 2560×1440 (or 1080×1920 / 1440×2560). The app's frame sizes are 1.75–1.83 wide, not
  exactly 1.78, so up to 2.6% is cut from the center to fit; 1632×928 loses 1.1%. Standard sizes keep
  every upscaled shot the same size, whatever engine made it, and match what video sites expect. Other
  shapes (1:1, 4:3) keep their own proportions.
- To do both on one shot, either order works with RIFE or FSR 3: smooth first, then upscale the result (Lanczos,
  or Real-ESRGAN up to 1632×928), or upscale first and smooth the 2560 clip. Whole 2560×1440 shots, measured in the
  lab on 2026-11-09: RIFE 37–47 s at 2.3 GB, FSR 3 13–16 s at 1.5 GB (124–141 frames, 24 → 48 fps). FILM at
  2560×1456 used 9.8 GB plus 4 GB of shared memory (about 1 h 16 min per 15 s cut), so it is not offered there.
  In the lab, smoothing first was about 10× faster than upscaling first.

Why these limits: FILM at 2560×1456 spilled past 10 GB (12+ minutes per window), and longer clips need
the lab's frame windows, which the app does not have. The models are in `models/frame_interpolation`
and `models/upscale_models` of the app's ComfyUI.

### RTX VSR and FSR 3 through Visual Enhancer (issue #39, 2026-11-09)

Two more choices appear in the same sheet when Visual Enhancer is set up: **RTX VSR** (upscale) and
**FSR 3** (smoothing). They are not ComfyUI nodes. The worker runs the user's own `VE_CLI.exe` from
[Visual Enhancer](https://github.com/Merserk/dlss5-visual-enhancer) v22.0 in the same job queue, after
freeing ComfyUI's models, with a 15-minute limit; a cancel stops the process.

Setup: Visual Enhancer's license forbids redistributing it, so the app never downloads or ships it.
Download it yourself and set `visual_enhancer_cli` in the ignored `config.local.json` to the full path of
`VE_CLI.exe`. Without it the choices are hidden and the server refuses them with that reason.

Measured as app jobs on the RTX 3080 (uploads to an isolated test instance, 2026-11-09). Time is the
whole job, VE plus the crop and encode; VRAM is the whole-GPU peak. Every output passed `ffprobe` and a
full FFmpeg decode with the source's sound:

| Method | 5 s, 1632×928, 24 fps | 5 s, 1920×1080, 30 fps (also 1080×1920) |
| --- | --- | --- |
| RTX VSR to 2560 wide | 16–18 s · 1.6 GB → 2560×1440 | 18 s · 1.7 GB → 2560×1440 / 1440×2560 |
| RTX VSR to 1920 wide | 10 s · 1.5 GB → 1920×1080 | not offered (already that size) |
| FSR 3 frame generation ×2 | 6–10 s · 0.9 GB → 48 fps, 248 frames | 13 s · 1.0 GB → 60 fps, 300 frames |

For comparison on the same 1632×928 shots: Real-ESRGAN takes about 232 s and RIFE about 21 s.

- RTX VSR kept natural skin where Real-ESRGAN retouched it, and it is about 20× faster. It is the
  recommended upscaler when Visual Enhancer is installed.
- FSR 3 is four times faster than RIFE, but on fast action (the Pika jump) the face smeared and edges
  broke into blocks, and a slow face showed small specks. It looked good on the slow Missed Bus shot.
  Check fast shots before using it; RIFE stays the default.
- Limits: RTX VSR takes sources up to 1920×1080, FSR 3 up to 2560×1456 (so it can smooth an upscaled clip,
  issue #41); both up to 30 fps and 150 frames, the tested range. RTX VSR does not run on a smoothed clip (not
  tested): upscale first with RTX VSR, then smooth the 2560 clip with RIFE or FSR 3.
- VE stretches to the size it is given, so the app renders RTX VSR at the source's own shape (for example
  2560×1456) and then cuts the center to the standard size like the other upscalers. VE re-encodes the
  sound at a lower bitrate, so the app copies the source's original track back. The final file is H.264
  CRF 12 like the ComfyUI jobs.
- Not offered: DLSS frame generation (refused on RTX 30 cards), PeakMagnetar (about 2.5 hours per shot),
  DLSS Super Resolution (its modes fix the output at 2× or more, so it needs another resize).

## RTX VSR + H3 detail (2026-11-10, issue #50)

RTX VSR, Real-ESRGAN and Lanczos only sharpen what is in the clip. On an **RTX VSR 1920** card the **פרטים H3**
button runs a short second H3 pass that redraws real detail (fabric, skin, eyes, hair, background) with the original
clip's prompt and model, keeping its motion, face, lips and sound. It uses bbaudio-2025's MMH3 Ultimate Upscale node
(time chunks of 68 frames with 17 frames of overlap; the sound passes through untouched).

Lab A/B on the RTX 3080, 2026-11-10, against RTX VSR alone on the same frames
(`D:\h3-omnilab\tests\h3_detail_pass\RESULTS.md`). The user rated every one of these good:

| Clip | Source | Time | Result |
| --- | --- | --- | --- |
| Missed Bus S02, slow face | Pika flow 1632×928, 5 s | 332 s | same face; 0.30 slightly crisper lips and lashes, 0.60 starts to retouch the skin |
| The Package rooftop jump | Pika flow 1632×928, 5 s | 332 s | the clearest gain: RTX VSR leaves motion smear, the pass redraws the bag, fabric, sweat, hair and the town |
| Yoni lip-sync | Turbo v4 928×1632, 4.5 s | 275 s (2 steps), 331 s (3 steps) | mouth shapes match RTX VSR at every checked frame up to 0.75 × 3 steps; 0.75 starts to change painted patterns |
| The Last Fold | Pika flow 1024×576, 15 s, two hard cuts | 901-913 s | clean at both cuts, no chunk seams; the close-up's lashes, iris and pores clearly sharper than RTX VSR |

Peak VRAM was 9.5-9.7 GB in every run, peak RAM 47-58 GB for 5 s and 61 GB of 64 for 15 s.

Strengths (explicit noise levels; a scheduler "denoise" at shift 6 starts much higher and redrew mouths in the lab):
**0.30** (light), **0.45** (recommended), **0.60**, and with 3 steps **0.60** or **0.75** (the sharpest).

Limits, enforced by the server:

- Only on RTX VSR 1920 clips (1920×1080 or 1080×1920, 24 fps), made from a **Pika-flow opening-frame** clip (the
  Pika engine, or Singularity with the Pika speed LoRA on the base model) or a **Turbo v4 lip-sync** clip. Those are
  the sources that were tested; other engines, other modes and uploads are refused with the reason.
- 107 to 362 frames (4.5-15 s). H3 needs 17n+5 frames, so up to 16 frames at the end are trimmed; the card says how
  many (RTX VSR returned 360 of The Last Fold's 362 frames, so 15 were trimmed).
- 1920 only: 2560 would need spatial tiles, which were not tested.
- **To 2560:** press **הגדלה** on the H3 detail card and choose RTX VSR (about 17 s, 2.3 GB). Lab 2026-11-10, same two
  clips: H3 detail at 1920 then RTX VSR to 2560 took about 6 min and added almost no flicker (+0.014 on the face, against
  +0.12 for native 2560 with 512 px tiles, which also left a blue streak on the rooftop arm). Native 2560 is not offered:
  the pack's seam-free tiling removed the flicker (+0.006) in 12 min but used 62 of the PC's 64 GB of RAM.
- Not offered (rejected in the same lab): the "draft, then latent upscale" two-pass route (10 s clips came out "not
  good") and RelayVSR ("low quality" on The Last Fold).

## Character swap (2026-11-09/10, issue #46)

Swap people in a finished job (its card's **החלפת דמות** button) or an uploaded video (the button in the results
header) with characters from a library. How it works, the API and how to make painted frames:
[`CHARACTER_SWAP_GUIDE.md`](CHARACTER_SWAP_GUIDE.md).

| Flow | Result on the 3080 (10 GB) | Time per ~5 s | Notes |
|---|---|---|---|
| Viggle, painted frames per part | best: 2 people on an 18 s stage clip right in every part, helpers untouched, window joins seamless | ~9 min (+ painting) | 1280×736 / 736×1280, int8 attention, 9.5 GB; up to 4 windows per job, longer clips chain jobs and join them. App run: 18 s (432 frames, 4 windows) in 2067 s; re-rendering one window 519 s plus a few seconds to stitch, every frame on time |
| Viggle, character picture only | good for one person close to the camera; with two look-alike people the characters blended, a far person kept the original face | ~8-9 min | the app run on a 5 s shot: 491 s, 9.5 GB |
| akatz V1.5 | one person; follows them through cuts and camera swings, but swaps whoever matches the description when they leave the shot | ~6 min | 512×928 at its "480" setting; the app run on a 5 s shot: 351 s, 9.5 GB; up to 149 s |

Painted frames: Codex refuses frames it classifies as showing a public figure; use another image editor or a frame
from another render of the same clip (an akatz run) for those parts. Paint each later part from the first painted
frame of the same character, or he changes look at the window join.

## Singularity, Pika and the official LTX templates

Ported from the H3 skin lab (October 2026). Each job is a single shot; none of these work in connected jobs.

**Singularity** (engine `singularity`, realistic skin): Prompt Mastery's model on the T8 Dual-Clock sampler, or on the
app's Turbo v4 graph (tier App flow). 2-7 s, 1.0 or 1.5 MP, 9:16 or 16:9, 4-16 steps (default 8), Sage or standard
attention, native encoder. The tiers pick the LoRAs: God (People + Turbo v4), Balanced (People + Ref2V 8-step), Max
(Ref2V 8-step), App flow (People on the Turbo v4 graph, no reference). Well tested: reference (about 40 jobs) and
lip-sync (8 jobs, keepers `cef0958e`, `d8dd0490`). Until 2026-11-05 every Singularity reference job ran without its
pictures (issue #20), which is why reference mode "never held" the singer's face and paint. With the fix, God and
Balanced kept the Shadow singer's face, paint and jewellery at 9:16, 1.5 MP (lab, 623 s and 621 s).

Sampler (advanced panel): T8 Dual-Clock (default, steps/scheduler/shift apply) or Pika (lcm on Pika's 6 fixed steps; the
other sampling controls are locked). Lab A/B 2026-11-05, Shadow reference, God Tier, 9:16, 1.5 MP, same seed: T8 8 steps
623 s, Pika 6 steps 480 s (23% faster), the same likeness; the Pika run opened in profile with the face visible where
T8 opened on the back of his head. Text mode, two characters, same seeds: T8 473/468 s, Pika 366/361 s; Pika gave a
different take of each (same description, different face and framing) and softer, less defined hands on the
fisherman. One seed per case. App flow keeps its own Turbo sampler.

**Pika** (engine `pika`, action): H3's own pruned base + the matching Pika H3 Flex LoRA, Pika's fixed 6 knots, ref size
`match`. 1.5 MP, 9:16 or 16:9, 2-7 s. Standard attention by default: a 5 s job takes about 10.5-13 min (reference 630 s,
text 667 s, lip-sync 713 s, opening 692-734 s, first + last 780 s). Clearly ahead of LTX for fights (keeper `620f17b2`), but
standard-attention quality has not been compared with that Sage keeper. Closing frame is refused because it was never
tested. Use timed beats ("0-1 s: ...") and "NO slow motion" in prompts. Never stack it with a Turbo LoRA.

Pika with Sage runs with the Steady Memory node (see `HARDWARE_AND_VRAM.md`) and is faster than standard: 453-501 s for
an opening frame or reference, 516-582 s for first + last (2026-11-03, 5 s, 1.5 MP). Sparse attention is still refused for
opening frame and first + last. Close games, launchers and browsers before long H3 batches: other programs on the GPU
make H3 jobs spill and run 2-4x slower.

**Pika Turbo 4-step** (engine `pika`, workflow variant `turbo4`; the "Turbo · 4 steps" switch under Pika): Pika-Labs'
Pika H3 Flex Turbo 4-step FL2VA LoRA at strength 1 on H3's pruned FL2VA base, T8 Dual-Clock sampler, scheduler `simple`,
shift 12 video / 3 audio, 4 steps, Sage with the Steady Memory node. Lab-tested 2026-11-03/04 at 1.5 MP and 5 s, all approved
in review: opening frame `24af717b` 341 s, `8cb338ce` 326 s, `b2d4b58c` 321 s (Pika 6-step about 459-470 s); first + last
`cac8dc06` 377 s (vs 488 s), `2ae0ff85` 356 s (vs 483 s); lip-sync `566ccb0d` 321 s (vs 442 s), `78605697` 326 s (vs 480 s).
Fast moves blur a little more than with Pika 6-step. The code allows only what was tested: opening frame, first + last and
lip-sync, Sage, up to 5 s. Refused, with the reasons: reference (every Turbo reference job looked bad: keep Pika 6-step),
text and other attention modes (not tested). The model card's shift 6 broke fight anatomy, so shift is fixed at 12. The
8-step HD LoRA was slower than Pika 6-step (544-575 s) and is not used. App replays with the lab inputs and seeds
(2026-11-04): first + last `e21d9b34` (346 s) and lip-sync `5cded6ab` (316 s) came out bit-identical to the lab jobs;
the opening frames `9134a451` (rerun `1d8fb64d`, identical) and `8da3a670` (316 s) differ from their lab jobs, which ran
right after 8-step HD jobs on the same cached base model, so those lab renders likely carried the previous LoRA's changes.

**Omni** (engine `omni`, reference mode only): Comfy-Org's FastH3 OmniRef 8-step template
(`video_fasth3_ominiref_r2v`): `fasth3_omniref_8step_pruned_int8_convrot.safetensors`, 8 steps, euler + simple, shift 12/3,
Comfy Kitchen attention with VSA sparse attention (keep 10 %). 0.6, 1.0 or 1.5 MP at 9:16 or 16:9, 2-7 s, up to 9 images,
one reference video and one audio reference; a reference video goes in without its soundtrack. Measured on the 3080 at
5 s (ComfyUI 0.44 + PyTorch 2.11, lab bridge, 2026-11-05): two image sheets at 1.5 MP 351 s; sheet + song at 1.5 MP
300 s, and it follows the song (envelope correlation 0.70); sheet + reference video at 0.6 MP 722 s, copying the video's
moves; all at about 9.5 GB. Same results as the earlier PyTorch 2.14 lab runs. A reference video at 1 MP or more spills
past 10 GB (about 11 min a step); the app allows it and the form warns, recommending 0.6 MP.

**Reference prompts:** define each person and name their picture ("<Subject 1> is the man from <Picture 1> (left): ...").
The earlier evidence for this is void: `985f52a1`, `a6732612`, `cab0a33f` and `8c355493` all ran without their pictures
(issue #20), so the subject definitions helped only as text. Still define each person; it costs nothing. Many hard cuts and whip pans in 5 s look
chaotic; prefer one or two shots.

**LTX recipe** (`ltx_recipe=official`, opening frame and first + last): ComfyUI's own LTX-2.5 templates instead of the app's
one-pass recipe. i2v is two-stage; both run about 5-15% faster. No consistent quality gain: official i2v was fine on two
Fluffies shots; official first + last was rejected in review.

LTX group dances: LTX moves everyone in a group with one shared motion, so give each of 2-3 characters a physically
different move; a character drawn mid-air floats for the whole clip; a dense far crowd freezes, so draw a few big close
extras; low-passed lip-sync audio makes characters freeze, so always send the real track.

## Not tested yet

- Standard and Spectrum engine speed and quality on this card.
- Int8 attention on Turbo text and reference, Singularity frame and lip-sync
  modes, the Pika engine, Fused SLA, Standard, Spectrum, LTX text, closing
  frame and reference, and H3 stills (the app refuses Int8 there until tested).
- ClipProj quality versus the native 32B encoder.
- "Sharp decode" and "calm sampler" on closing and first + last frame beyond a
  single app run each [T8, T9].
- LTX 2.5 reference in vertical (2.3 vertical failed [R8]).
- Any GPU other than the RTX 3080 10 GB.

When you test one of these, add the result here with the test conditions.
