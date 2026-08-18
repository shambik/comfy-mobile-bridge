# Agent Production Studio architecture

## Purpose

The Production Studio adds a responsive, persistent production council to the
existing H3 bridge. The three creative participants are the user, Codex, and
AGY. The user owns the production and has final authority; Codex and AGY are
equal co-producers. A deterministic FastAPI orchestrator owns state, tools,
ComfyUI submissions, retries, and filesystem changes.

The first pipeline is `music_video_v1`. Shared records and APIs deliberately
use the generic term `Production` so later pipelines can support shorts,
trailers, commercials, narrative video, and films without replacing the
orchestrator.

## Component model

```text
                          User
                           |
                 Responsive Production Room
                           |
                       REST + SSE
                           |
                Production Orchestrator
               /           |           \
    Runtime adapter A  AGY media seat  User gateway
               \           |           /
                   Joint decisions
                           |
              ComfyUI queue + FFmpeg media
                           |
                  SQLite + artifacts
```

- The React client renders projects, the three-party conversation, decisions,
  model/effort selectors, skill settings, controls, and reviews.
- The production orchestrator is a background worker independent of browser
  connections. It checkpoints before advancing stages.
- Producer A can use either authenticated Codex CLI or AGY CLI. The media
  producer is pinned to AGY because song and video inspection are mandatory.
  Codex runs non-interactively with JSONL and a required response schema. AGY
  runs in stream-JSON plan mode against the production directory.
- Agents receive read-only production context. They cannot submit jobs or
  mutate application state directly.
- The existing `QueueWorker` remains the sole owner of ComfyUI generation.

## User authority and collaboration

Production modes are interactive and autonomous. Autonomous mode may advance
routine Codex/AGY decisions but remains observable and interruptible. In
interactive mode the orchestrator waits at configured decision gates.

The user can address Codex, AGY, or both; pause, stop, resume, edit, approve,
reject, override, and request reconsideration. User instructions are persisted
as high-priority constraints. Neither agent may declare a production complete:
final completion requires Codex review, AGY review, and explicit user approval.

Material decisions use this protocol:

1. Codex proposes.
2. AGY critiques.
3. Codex revises or explains disagreement.
4. AGY confirms or counters.
5. The joint result is recorded or escalated to the user.

Three repetitions of the same unresolved defect or disagreement trigger a
pause rather than an unbounded loop.

## State and persistence

The music-video pipeline is:

```text
intake -> song_analysis -> treatment_consultation -> reference_development
       -> reference_generation -> prompt_consultation -> shot_generation -> shot_review
       -> assembly -> final_review -> user_review -> completed
```

Control states include `awaiting_user`, `pausing`, `paused`, `retrying`,
`stopping`, `stopped`, and `failed`. Restart recovery moves interrupted work to
a safe paused checkpoint. Stopping a production never stops the bridge; active
agent subprocesses and, only when requested, the active ComfyUI job are
cancelled.

SQLite stores productions, configuration revisions, skill selections, messages,
decisions, events, references, shot attempts, reviews, and checkpoints. Large
artifacts live under `state/productions/<id>/`. Approved artifacts are
immutable; corrections use numbered attempts.

## Implemented execution contract

The reference plan contains executable still specifications. A tightly scoped
Codex CLI child uses the installed ImageGen skill and authenticated built-in
image tool, copies one selected PNG into the production folder, and cannot
write outside that production workspace. The backend validates the bitmap,
AGY inspects the actual image, and Codex reviews AGY's findings. Only a jointly
accepted still is copied into the ComfyUI input folder and registered. This
stage does not launch or call ComfyUI.

Users can also generate one reference still manually from Reference Media.
`Auto` tries Codex ImageGen first and falls back to AGY ImageGen; either
provider can be selected explicitly. Manual stills pass the same AGY inspection
and Codex co-producer review before registration. Upload remains available when
neither provider is usable.

The normalized prompt package persists each shot and numbered attempt before
any side effect. Production jobs are ordinary `jobs` rows with `no_audio=1`;
the existing `QueueWorker` remains the only ComfyUI caller. Megapixels and
aspect ratio are forwarded to `ResolutionSelector`, and duration is forwarded
to the workflow duration expression. The production layer does not calculate
latent dimensions or frame counts itself.

After each job, FFmpeg extracts a bounded dense frame sample. AGY receives the
actual MP4 path and frame directory; Codex receives the sampled images plus
AGY's report. Both must approve. Three repetitions of the same defect, or five
non-converging attempts, creates a user decision instead of continuing.

Accepted clips are normalized and assembled with deterministic hard cuts. The
original uploaded song is then muxed as AAC over the silent master. AGY reviews
the complete audio/video file, Codex reviews its frame sample and AGY's report,
and the production remains at `user_review` until the user approves it.

## Models and reasoning

AGY models are discovered from `agy models`. Codex models and supported
reasoning levels are read from the authenticated CLI's server-populated
`models_cache.json`, with a small current fallback for first-run availability.
The UI switches catalogs when Producer A changes runtime and filters reasoning
levels by model. Global defaults apply to new projects; each production keeps
its own runtime, model, reasoning, and skill configuration.

Changing a production configuration requires a pause and creates a revision.
Every agent message records the effective model, reasoning effort, session,
and selected skills.

## Skill catalog

The application discovers repository and app-managed skills and can register
external folders. Settings provides enable/disable checkboxes and per-project
selection. Only enabled selected skills are injected into production context.

Unregistering removes the catalog entry but preserves files. Complete deletion
is available only for skills copied into `state/skills`; repository, system,
and arbitrary external skill files are protected.

## API and events

The backend exposes agent health/model discovery, agent defaults, skill CRUD,
production CRUD/control, reference upload, shot editing/retry, completed-job
import, lifecycle/export, user interventions, decision resolution, artifacts,
and production-specific SSE. Event IDs are monotonically increasing so mobile
clients can reconnect without losing the production history.

Productions are durable and up to `agents.production_concurrency` production
state machines run concurrently (three by default). Song analysis, agent
consultation, reference work, reviews, and assembly can overlap across
projects. Every video-generation request still enters the existing single
ComfyUI queue, so only one GPU job runs at a time on this host. Active job IDs
are tracked per production so pause and stop target only the chosen project.

All mutations use the bridge's existing CSRF protection. Agent credentials
remain backend-only and the CLIs run as the authenticated Windows user.

## Responsive interface

The Production Room follows the approved near-black, slate, violet, cyan, and
green visual direction. New styles are namespaced so the existing H3 Studio is
not recolored.

- Below 640 px: single-column screens, sticky production controls, bottom-sheet
  decisions, 44 px touch targets, and no horizontal page scrolling.
- 640-1023 px: two-column layout with slide-over storyboard or inspector.
- 1024 px and above: storyboard, conversation/video, and decision/QC panes in a
  workspace up to approximately 1440 px wide.

Codex, AGY, and user messages always have distinct labels and visual identities.

## Security and verification

Uploads are type/size validated; artifact and skill paths are resolved and
checked against allowed roots; ZIP traversal is rejected; complete skill
deletion is restricted to the managed root. ComfyUI remains loopback-only.

Tests cover migrations, dynamic model discovery, skill safety, state
transitions, controls, agent response parsing, mocked reference generation and
joint review, lifecycle duplication/reference remapping, API CSRF behavior,
responsive builds, and backward compatibility with existing generation jobs.
Live authenticated agent calls, ImageGen output quality, full ComfyUI GPU
generation, and second-device Tailscale access remain runtime acceptance tests.
