# Character swap: guide for agents

How to run a character swap in the app, step by step, with any image generator for the painted frames.
Written for an agent working on this project (Claude, Codex, Antigravity or another), and for people.

Code: `backend/character_swap.py` (flow), `backend/main.py` (`/api/swap…` routes, `_queue_swap_job`),
`backend/worker.py` (swap jobs, engine `swap`), `src/swap.tsx` (the sheet). Issue #46.

## Installation (models and nodes)

The swap needs these in ComfyUI; the job card says "not installed" with the missing file when one is absent. They
are not in `manifests/` yet (the manifests have no optional groups; adding them would download ~24 GB on every
install), so install them by hand:

| Piece | Where it goes | Source | License |
|---|---|---|---|
| `viggle_remake_swap_pruned_int8_convrot.safetensors` (19.5 GB) | `models/diffusion_models` | `Viggle/Viggle-Remake` on Hugging Face, `int8/` | Viggle's own terms (model card) |
| ComfyUI-Viggle-Remake nodes | `custom_nodes/ComfyUI-Viggle-Remake` | the same repo, `comfyui/ComfyUI-Viggle-Remake` | Apache-2.0 |
| `sam3.1_multiplex_fp16.safetensors` (1.6 GB, akatz only) | `models/checkpoints` | `Comfy-Org/sam3.1`, `checkpoints/` | model card |
| `h3_character_swap_v1.5.safetensors` (akatz only) | `models/loras/character_swap` | `akatz-ai/MiniMax-H3-Character-Swap-LoRA` | model card |
| `minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors` (akatz only) | `models/loras/character_swap` | `lightx2v/Minimax-h3-Turbo` | model card |
| H3 Relay nodes (akatz only) | `custom_nodes/h3-relay` | `akatz-ai/h3-relay` (v2.0.1) | GPL-3.0 |

The H3 text encoder, VAEs and the Ref2VA int8 model are the app's own. akatz's graph is read from
`custom_nodes/h3-relay/example_workflows/toolkit/H3-Character-Swap.api.json`, so no GPL file is copied into this
MIT repository; the Viggle graph is built in code (`character_swap.viggle_base_graph`).

H3 Relay installs a pass-through wrapper on H3's packed layout the first time an akatz job runs, for the rest of that
ComfyUI process. A normal H3 Turbo render with the same seed before and after an akatz job came out bit-identical
(all 124 frames, 2026-11-10), so no restart is needed.

## Rules that always apply

- **Every render is a bridge job** the user can see and repeat: use the API below (or the sheet), never send graphs
  to ComfyUI yourself and never run renders from scripts.
- One ComfyUI at a time. Do not start another, do not stop one that is busy.
- Never cancel or interrupt a job unless the user asks.
- Each job gets its own random seed; the bridge does this and records it.
- Never modify model files.
- **Never work around an image generator's safety filter** (no blurring, masking or cropping faces to slip past a
  public-figure check). If a generator refuses a frame, use another way from "Painted frames" below and tell the
  user which part was refused and why.
- Check results yourself before you report (see "Check the result").

## How it works

1. **Upload or pick a video.** The bridge converts it to 24 fps (short edge at most 736) and finds hard cuts
   (isolated jumps only; fast camera swings are not cuts).
2. **Parts.** Viggle renders ~5 s windows (124 frames). Each window opens with the previous window's last 17 frames
   locked, so joins are seamless. The clip is split into **parts**: one shot inside one window's own frames. Each
   part has one frame (its middle frame) where you mark people and, in painted mode, paint.
3. **Marks.** On a part's frame, tap each person to replace, pick a character from the library and write who the
   person is in English (hair, clothes, what they do). Later parts of the same shot **carry the marks over** unless
   you mark them again or set "nobody here". With Viggle, every ~5 s window needs at least one person to swap.
4. **Split a part** at a chosen moment when people appear at different times in the same part (for example one
   person walks out and another walks in): each half gets its own frame.
5. **Render.** Up to 4 windows (~18 s) run as one job. Longer clips run as a chain of jobs, each opening with the
   previous job's last frames, and a final job joins them with the original sound. The job card shows
   "window k/N".

### Engines and modes (measured on the RTX 3080, 2026-11-09)

| | Viggle, character picture only | Viggle, painted frames | akatz V1.5 |
|---|---|---|---|
| People per render | up to 4 | up to 4 | 1 |
| Input | character pictures + descriptions | one painted frame per part with people | character picture + a description of how the person looks |
| Good at | one person close to the camera | several people, far shots, people who leave and come back | one person who stays in view all clip |
| Fails when | similar-looking people (two characters blended), far/small people (kept the original face) | a part has no painted frame | the person leaves the shot: it swaps whoever matches the description (swapped a helper in a navy suit) |
| Time per 5 s | ~9 min | ~9 min + painting | ~6 min |
| Length | any | any | up to 149 s (its own limit) |

All flows: fine invented detail (dreads, beads, beard) can shimmer; that is a model limit (A/B 2026-11-09).
Painted frames give the most reliable result; use them for anything with more than one person.

## Step by step through the API

Base `http://127.0.0.1:8787` (the app's port). Every write needs the session token:

```python
import requests
B = "http://127.0.0.1:8798"
s = requests.Session()
s.headers["X-CSRF-Token"] = s.get(f"{B}/api/session").json()["csrf_token"]
```

| Step | Call |
|---|---|
| Characters in the library | `GET /api/swap/characters` |
| Add a character | `POST /api/swap/characters` form: `image` (≤ 60 MB, shrunk to 2048 px), `name`, `look` (English, optional but helps) |
| Edit name or look | `PATCH /api/swap/characters/{id}` JSON `{"name", "look"}` |
| Start a swap | `POST /api/swap` form: `job_id` (a finished bridge job) **or** `video` (upload ≤ 500 MB) |
| Read a swap | `GET /api/swap/{id}`: `shots` = the parts (`index, start, end, key_frame, scene, window, frame_url, painted_url`), `windows`, `scenes`, `marks`, `status`, `stage`, `error` |
| A part's frame | `GET /api/swap/{id}/image/shot{N}_frame.png` |
| Split a part | `POST /api/swap/{id}/parts/{N}/split` JSON `{"frame": absolute_frame}` (each half ≥ 12 frames; later part numbers move up by one) |
| Save marks | `PUT /api/swap/{id}/marks` JSON `{"marks": [{"shot": N, "x": 0-1, "y": 0-1, "character_id", "description"}], "mode": "reference"\|"painted", "engine": "viggle"\|"akatz", "notes": "...", "empty": [parts with nobody to swap]}` |
| Codex paints all missing frames | `POST /api/swap/{id}/prepare` (runs in the background; `status` "preparing", then "review" or "marking" with `error` naming refused parts) |
| Codex repaints one part | `POST /api/swap/{id}/shots/{N}/repaint` |
| Upload a painted frame | `POST /api/swap/{id}/shots/{N}/painted` form `image` (≤ 25 MB; any size, it is cover-fitted to the part frame) |
| Render | `POST /api/swap/{id}/render` → `job_id`; then follow `GET /api/swap/{id}` until `status` is `done` or `failed` |
| Remove a swap | `DELETE /api/swap/{id}` (rendered jobs stay in the queue) |

`x, y` are where the person is on the part's frame (0-1 from the top left). Left-to-right order in the prompt comes
from `x`. Descriptions describe the **original** person ("the white-haired man in the navy suit and blue tie, on the
right"), never the new character, and never only "the person on the left". The sheet's prompt is built from the marks,
descriptions and notes; read it in `swaps/{id}/prompt.txt` or on the job card ("show full prompt").

## Painted frames

A painted frame is the part's own frame with the marked people replaced by their characters. Viggle pins it at
that moment, so it must look like a real frame of the result.

**A good painted frame:**
- starts from `shot{N}_frame.png` of that part (same moment, same camera);
- replaces only the marked people; everyone else (helpers, crowd) stays exactly as is;
- keeps each person's pose, position, size, framing and lighting; the character's face, hair and outfit match
  the character picture;
- is photoreal, with no circles, numbers, text or watermarks;
- has the same aspect ratio as the part frame (other sizes are cover-cropped, which can shift people).
- shows each character **exactly the same in every part**: same hat, patches, beard, glasses, colours. Paint the
  first part, then give the editor that painted frame as an extra reference for every later part ("copy this
  character exactly; only the pose follows the new frame"). Each part is pinned in its own window, so two different
  versions of a character make him visibly change at the window join (2026-11-09: a hat and jacket patches jumped
  at 5.2 s). The built-in Codex painting does this by itself; repaint later parts after changing an earlier one.

**Prompt template for any image editor** (fill in per mark):

> Edit the first image (a frame from a video) into one new image. Replace {description of the original person} with
> the character in the reference image: {character look}. Copy the character's face, hair and outfit exactly. The
> new person keeps exactly the pose, position, size and action of the person they replace. Same camera angle,
> framing, lens, lighting, colour grade and aspect ratio. The background and every other person stay exactly as
> they are. No text, logos or watermarks.

Give the editor the part frame first, the character picture(s) after it (`GET /api/swap/characters/{id}/image`),
and the character's first painted frame from an earlier part (`GET /api/swap/{id}/image/shot{N}_painted.png`).
When several people are marked, a copy of the frame with numbered circles helps the editor tell them apart; draw
it yourself from the marks' `x, y`, or use `shot{N}_marked.png` after a Codex run. The result must not contain the
circles.

**Ways to make them**, in order of convenience:

1. **Codex (built in).** `POST /prepare` paints every part that has people and no frame yet, one at a time
   (~1-2 min each); each finished part is saved at once. Codex refuses frames its image system classifies as
   showing a public figure ("blocked ... as containing a public figure"); asking again gives the same answer. Do
   not try to get around it: use one of the other ways for those parts.
2. **Any other image generator** (a local image-edit model, Antigravity, another service): download the part frame
   and character picture, edit with the template above, check the result, upload with
   `POST /shots/{N}/painted`. A local model runs on the same GPU as the app's ComfyUI: use it only while the
   queue is idle, and run it as a bridge job if the bridge has a flow for it; otherwise ask the user first. New
   models or packages need the user's approval.
3. **A frame from another render of the same clip.** If an earlier render (for example an akatz run) already shows
   the character correctly at that moment, take its frame at the part's `key_frame`, scale it to the part frame's
   size and upload it. Check that only the marked people changed (akatz may have swapped someone else) and drop
   marks the frame does not show (for example legs left unchanged). Used on 2026-11-09 for the two parts Codex
   refused.

Painting by hand on a phone is not practical: the frame has to look like a real photo.

Look at every painted frame next to its original before rendering. Repaint or replace any frame that changed the
wrong person, moved people, or left circles or text.

## Check the result

After `status` is `done` (the job card says מוכן):

1. `ffprobe -count_frames`: the frame count equals the swap's `frames`; a full decode
   (`ffmpeg -v error -xerror -i out.mp4 -f null -`) shows no errors.
2. Look at a frame from every part next to the source frame: each marked person is their character, nobody else
   changed, people who walk out and back in are still swapped.
3. Look at the frames on both sides of every window join (window start + 17) and every job join: nothing jumps.
4. Tell the user what worked and what did not, with frames, before calling it done.

## Known problems and what to do

| Message or symptom | Meaning | Do |
|---|---|---|
| "Nobody to swap in 0:09-0:14 ..." | a Viggle window has no marked or carried-over person | mark the person in that part, or make the clip shorter |
| "Part N needs a painted frame" | painted mode, a part with people has no frame | paint or upload that part |
| "Codex did not paint part N: ... public figure" | Codex's image filter refused the frame | use way 2 or 3 above; never work around the filter |
| Two characters look alike / one missing | character-picture mode with several people | use painted frames |
| Original face kept on a far or small person | character-picture mode | painted frame for that part (split the part if needed) |
| A character changes look at a window join | parts painted separately gave him different details | repaint the later parts with the first painted part as reference |
| akatz swapped the wrong person | the person left the shot; akatz picked the closest match | Viggle with painted frames, or a clip where the person stays in view |

## Where things are

- Swaps: `state/swaps/{id}/` (`swap.json`, `source.mp4`, `shot{N}_frame.png`, `shot{N}_painted.png`, `prompt.txt`)
- Characters: `state/characters/` (`characters.json` + one PNG each)
- Results: bridge jobs, filed under the source job's folder or "Character swap / From the swap sheet"
