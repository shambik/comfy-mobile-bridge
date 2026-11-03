# LTX 2.5 production plan: "Night Train" (episode 1, "The Stowaway")

A fresh plan. It does not reuse any earlier prompt style, storyboard or test
result. It changes how the episode is conceived, built, stitched and scored,
then **tests each method on its own before production** and lets the
measurements decide.

All rendering goes through the H3 Mobile Bridge app (`http://127.0.0.1:8787`)
so the user can watch every job in the app. Never post graphs straight to
ComfyUI, and do not change app code or workflows without asking the user and
explaining why with evidence.

---

## 1. The approach

| Old way (dropped) | New way |
| --- | --- |
| Separate shots, each from its own still, cut together | **One continuous journey.** The episode is a chain: every clip starts exactly where the previous clip ended, so the whole episode plays as one connected piece. |
| Dialogue scenes, lip-sync problems | **No dialogue.** A pantomime comedy (like Shaun the Sheep or Pingu): the story is told by action, faces and sound. Characters hum, gasp, sniff, giggle, go "shh", but never speak lines. |
| Each clip's own sound, changing at every cut | **One soundtrack for the whole episode**: a continuous location bed and a recurring music motif built separately, with each clip's own foley mixed on top. |
| Many unrelated stills | **A keyframe storyboard**: 9 planned keyframes, all derived from one master set so light, lens and look stay identical. Clips are the motion *between* keyframes. |
| Guessing what works | **Pilot tests first** (section 5), with measured decision rules. |

Why a train: a sleeper train at night gives a natural continuous path
(corridor → carriages), a natural continuous sound (wheels on rails, the
carriage rocking) that glues every clip together, and passengers in every
carriage, so the background is always alive.

---

## 2. Series

**Night Train** — a cosy, wordless **claymation stop-motion** comedy in the
tradition of Aardman's *Wallace & Gromit* and *Shaun the Sheep*: plasticine
characters with visible thumbprints and tool marks, chunky rounded shapes,
big expressive eyes and brows, hand-built miniature sets, warm practical
lamps, and slightly stepped, handmade stop-motion movement. It must look like
real puppets animated frame by frame on a miniature set, **not** smooth 3D
CGI, not Pixar-style rendering, not 2D.

**Episode 1, "The Stowaway".** Bramble, the night porter of the 11:50 sleeper
train, is doing his quiet midnight rounds when a tiny duckling slips out of a
sleeping compartment. Bramble must get it back before anyone wakes up, while
the duckling waddles through the whole train causing small chaos. The episode
moves forward through the train from the sleeper carriage to the dining car
to the luggage van and back, ending at dawn.

### Characters (looks are for the stills only)

| Character | Look | Sound (non-verbal) |
| --- | --- | --- |
| **Bramble** | a tall, gentle clay badger in a dark green porter's uniform with brass buttons and a peaked cap, carrying a little brass lantern | soft humming, a worried "mm-mm", a sharp "shh!", a tired sigh |
| **The duckling** | a tiny round yellow clay duckling with an orange beak and a wobbly walk | tiny peeps, a happy squeak, a hiccup |
| **Mother Duck** | a large white clay duck in a lace nightcap, fast asleep | snoring, one sleepy quack |
| Passengers (background) | a snoring walrus in a hairnet, two mice playing cards by candle, a goat reading a newspaper, a hedgehog chef in the dining car | snores, a page turning, cards slapping, pans clinking |

### Look bible (put this sentence in every still prompt)

"claymation stop-motion, plasticine characters with visible thumbprints and
sculpting marks, hand-built miniature train interior with polished wood
panels, brass fittings and velvet curtains, warm amber lamplight, deep blue
night outside the windows, shallow depth of field, cosy and tactile"

---

## 3. The keyframe storyboard (9 keyframes, 8 clips, ~75 s)

The camera travels with Bramble the whole time at the same height (his
shoulder level, 35 mm feel). Each clip goes **from keyframe Kn to Kn+1**.

| Key | Picture | Clip to next key (what happens) |
| --- | --- | --- |
| K0 | Sleeper corridor, wide: Bramble walks toward camera with his lantern; compartment doors along the left; rain on the windows on the right. | **C1** He walks, hums, checks a door. Behind him a compartment door slides open a crack and the duckling hops out unseen. |
| K1 | Corridor, medium: Bramble stops, ears up; the duckling is behind his heel. | **C2** He turns slowly; nothing there (the duckling hides behind his leg, keeping behind him). He frowns, turns back. Peep. He freezes. |
| K2 | Corridor, low angle: Bramble looking down at the duckling between his boots. | **C3** The duckling squeaks happily and waddles off down the corridor; Bramble tiptoes after it, "shh!". |
| K3 | Dining car doorway: a hedgehog chef at a stove, two mice playing cards, candles. | **C4** The duckling waddles under the tables; the mice freeze mid-card; Bramble crawls under a table after it, cap knocked crooked. |
| K4 | Dining car, close: the duckling on a table next to a pudding, Bramble's paw reaching in from below. | **C5** The duckling hops into the pudding with a splat; the chef turns around; Bramble smiles innocently, holding the pudding. |
| K5 | Luggage van, dim: suitcases and parcels stacked, a single swinging lamp. | **C6** Bramble searches with his lantern; peeps echo; he finds the duckling asleep in an open hat box. |
| K6 | Luggage van, close: Bramble lifting the sleeping duckling in both paws. | **C7** He carries it back along the corridor on tiptoe; the walrus snores; a floorboard creaks; everyone stays asleep. |
| K7 | Sleeper compartment, dim: Mother Duck asleep in a bunk, an empty dent beside her. | **C8** Bramble lays the duckling beside her; she tucks it under a wing without waking; Bramble backs out, slides the door shut, and sighs. Dawn light starts at the window. |
| K8 | Corridor at dawn: Bramble leaning on the window, pink sky, the train crossing a bridge. | (end: a held shot, the music motif resolves) |

---

## 4. Building the keyframes (Image Lab, in the app)

1. List the Image Lab catalog through the app and choose one **text-to-image**
   workflow (Flux Krea or Qwen Image) and one **image-edit** workflow
   (Qwen Image Edit 2509 or Flux Kontext).
2. Make **three masters** with text-to-image: the sleeper corridor (K0), the
   dining car (K3) and the luggage van (K5), each with Bramble in it, using the
   look bible plus the keyframe description. Then make a clean **character
   sheet** of Bramble and the duckling (front, side, back) on a plain
   background.
3. Derive **every other keyframe by editing a master** ("same scene, same
   lighting; Bramble now stands with his ears up and the duckling behind his
   heel", and so on), so the set, light and characters stay identical.
4. Rules for every keyframe: 16:9, at least 1600×896; the same camera height;
   the same light direction (lamps above-left, night or dawn through the
   windows on the right); no readable text; no extra limbs; Bramble's face
   readable.
5. Put the 9 keyframes side by side in one contact sheet and check that they
   look like one continuous film before animating anything.

---

## 5. Pilot tests (run these first, at Balanced, and decide by measurement)

Use the app's Balanced preset (1600×896) and 5 s clips for every pilot.

### P1. How to chain clips: three methods, same pair of keyframes (K1→K2)

| Method | App mode | How |
| --- | --- | --- |
| **P1a Planned frames** | `frames` (`first_frame` = K1, `last_frame` = K2) | the clip must land exactly on K2 |
| **P1b Native hand-off** | `opening` (`image` = K1); the next clip opens on P1b's own decoded last frame | the chain grows from real output |
| **P1c Opening + closing** | first clip `opening` on K1; a second clip `closing` on K2 | both ends anchored separately |

Measure for each: (1) **seam jump**: mean absolute pixel difference between
the last frame of one clip and the first frame of the next (lower is better;
under ~3% of the 0–255 range is invisible); (2) **landing accuracy**: how close
P1a's last frame is to K2; (3) watch the seam at full speed for a speed or
direction jump in the motion. **Use the method with the smallest visible
seam** for the whole episode. P1b drifts in look over a long chain; check
that too by chaining three P1b clips.

### P2. Motion feel

Same clip twice: once with "smooth, fluid animation", once with "stepped
stop-motion movement, slightly staccato like real claymation at 12 frames per
second". Pick the one that reads as handmade without jitter.

### P3. The soundtrack beds

- **P3a Location bed**: a `text`-mode clip whose prompt asks for sound only:
  "The camera holds on a dark, empty sleeper-train corridor. Only sound: the
  steady rhythmic clack of wheels over rail joints, the soft creak of wood
  panels as the carriage rocks, rain on the windows, a faint distant whistle.
  No voices, no music." Extract its audio. Check: no voices (Whisper should
  return nothing), and that a 10 s loop with a 1 s crossfade sounds seamless.
- **P3b Music motif**: a `text`-mode clip with "Only sound: a gentle music-box
  waltz melody, slow and sleepy, solo celesta and soft pizzicato strings, no
  voices." Keep the best 8–10 s phrase as the episode's theme.
- **P3c Mix check**: lay P1's winning chain over the P3a bed (bed at about
  −14 dB under the clips' own sound) and decide whether the clips' own
  ambience fights the bed. If it does, prompt the production clips for
  foley only ("only the sounds this action makes: …; no background
  ambience").

### P4. Pantomime clarity

One clip (C2) with the performance written as clear physical beats ("he
turns slowly… nothing there… he frowns… turns back… a tiny peep… he freezes,
eyes wide"). Check: is the gag readable with the sound off? If not, slow it
down and give each beat its own sentence.

Write the pilot results (numbers, chosen methods, which seed) into
`docs/ltx25_test/PILOT_RESULTS.md` and show them to the user before production.

---

## 6. Clip prompts (production)

Write each prompt in this order, as one flowing paragraph in present tense:

0. **the style line, first, word for word in every clip**: "A claymation
   stop-motion scene with handmade plasticine puppets on a miniature set,
   animated with the slightly stepped motion of real stop-motion." (Use the
   P2 winner's wording for the motion part.);
1. the camera and where it moves, relative to Bramble;
2. the action, one physical beat per sentence, with the timing written in
   ("a beat", "he waits", "slowly");
3. the background life of that carriage (passengers, rain, lamps swaying with
   the train);
4. the sound the action makes (foley) and any one short musical gesture tied
   to a beat; per P3c, include or exclude the location ambience.

Do not re-describe the characters' looks (the keyframes carry them) and do
not write cuts. Example (C1, from K0 to K1):

```
A claymation stop-motion scene with handmade plasticine puppets on a miniature set, animated with the slightly stepped motion of real stop-motion. The camera glides backward ahead of Bramble at his shoulder height as he walks slowly down the swaying sleeper corridor, his lantern swinging gently with the train. He hums softly to himself, stops at a compartment door, listens with one ear, nods, and walks on. Behind him, unseen, a door slides open a crack and a tiny duckling hops out onto the carpet and waddles after him. Rain streaks the windows and the lamps sway with the carriage. His footsteps thud softly on the carpet, the door rolls open with a tiny squeak, and the duckling's feet patter; a single plucked string note lands when the duckling appears.
```

Write C2–C8 the same way from the keyframe table in section 3. Durations:
8–10 s each. Seeds: record each one; on a retry change only the seed.

---

## 7. Stitching the episode

1. **Order and seams**: join C1…C8 with the chain method chosen in P1. Where a
   seam still shows a small jump, use a 2–4 frame cross-dissolve; for scene
   changes between carriages (C3→C4, C5→C6) use a deliberate **door wipe**
   (the camera passes through a carriage door) or a 0.5 s dip through the
   dark gangway, which hides any change in light.
2. **One look**: apply the same grade to every clip in the edit (the same
   ffmpeg `eq`/`curves` settings), then add one uniform film grain over the
   whole episode (`noise=alls=5:allf=t`) so the clips read as one film.
3. **The soundtrack** (three layers, mixed in ffmpeg):
   - the **P3a bed** looped under the entire episode with 1 s crossfades at the
     loop points, brightened slightly in the dining car and muffled in the
     luggage van (`lowpass`);
   - the clips' own **foley** on top;
   - the **P3b motif** at the start (title), at the dawn ending (resolved), and
     once softly mid-episode (when Bramble finds the sleeping duckling).
   - Normalise the final mix to −16 LUFS (`loudnorm`).
4. **Titles**: a 2 s title card at the start ("Night Train", made in post,
   not by LTX) over the motif, and a 2 s end card.

---

## 8. Checks for every clip and for the episode

- `ffprobe -count_frames` (expected size, 24 fps, an audio stream) and a full
  decode with `ffmpeg -v error -xerror -i clip.mp4 -f null -`.
- A 2 fps contact sheet: no morphing, no extra limbs, the duckling never
  doubles, Bramble's face consistent.
- Seam check at every join (the P1 measure).
- Whisper on the bed and the motif (no voices); on clips, that no stray words
  were invented (the app's system Python 3.12 has Whisper with the
  `large-v3-turbo` model cached; do not install anything).
- The final episode: ffprobe, full decode, loudness, and one full watch.

---

## 9. Operations notes

- The bridge (8787) and the one ComfyUI (8190) both run non-elevated; keep
  them at the same level and run one ComfyUI only.
- ComfyUI's progress bars go to `state/logs/comfy-8190.err.log`. The first
  sampling step normally takes under 90 s at Balanced. If sampling makes no
  progress for 3+ minutes (the decode prints no bar and takes 2–4 min; that is
  normal), report it to the user. Cancel through the app
  (`POST /api/jobs/{id}/cancel`) only if the user asks.
- Submitting: `GET /api/session` for the CSRF token (keep the cookie), then
  `POST /api/jobs` as multipart. Fields: `prompt`, `mode`
  (`text`/`opening`/`closing`/`frames`), `duration`, `engine=ltx`, `steps=8`,
  `aspect_ratio=16:9`, `ltx_quality` (`balanced` for pilots, `high` for
  finals), `ltx_sharp_decode=true`, `seed`, `no_audio=false`; images go in
  `image` (opening/closing) or `first_frame`/`last_frame` (frames). Never
  retry a POST automatically.
- Uncommitted app change in the working tree: `backend/workflows.py`
  `LTX_DECODE_OVERLAP = 4` (removes faint tile rectangles in the sharp decode)
  with a test in `tests/test_ltx_lipsync.py`. At High, the decode peaked near
  9.8 GB of 10 GB; watch long High clips.

## 10. Report to the user

After the pilots: `PILOT_RESULTS.md` with the numbers and the chosen methods.
After production: the episode file, the contact sheet of all keyframes, the
seam numbers per join, the render time, and what was retried.
