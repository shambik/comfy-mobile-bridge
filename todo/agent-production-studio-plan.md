# Agent Production Studio implementation plan

## Goal

Add a responsive Production Room where the user, Codex, and AGY collaboratively
create a complete music video. Support autonomous and interactive operation,
model/reasoning selection, selectable skills, durable checkpoints, user
intervention, ComfyUI generation, per-shot QC, assembly, and final user approval.

## Delivery stages

1. Add production persistence, agent settings, model discovery, and a protected
   skill catalog without modifying existing job records.
2. Add Codex and AGY structured-process adapters plus a persistent production
   orchestrator and user decision APIs.
3. Build the responsive Production Room and Settings interface using the
   approved dark violet/cyan design.
4. Connect approved prompt packages to the existing ComfyUI queue, persist each
   shot attempt, extract dense frames, and run Codex/AGY QC.
5. Add FFmpeg assembly, original-song attachment, final AGY/Codex review, and
   explicit user acceptance.
6. Add authenticated Codex ImageGen reference stills, optional intake source
   references, per-reference AGY/Codex review, per-shot I2V reference assignment,
   targeted retries, and imports. Keep production R2V deferred until its
   separate workflow testing is complete; do not route production shots through
   R2V in this POC.
7. Add runtime-aware model catalogs, editable frozen configurations, lifecycle
   controls, and production export.
8. Verify restart recovery, loop detection, pause/stop/resume behavior, mobile
   Tailscale access, and existing H3 generation compatibility.

## POC boundary

The first production pipeline is `music_video_v1`. Core orchestration remains
generic so future work can add shorts, trailers, commercials, and narrative
video, but those production types are not exposed until separately designed and
approved.

## Implementation status

The production POC is coded through the current shot execution contract.
Automated tests cover persistence, user authority, dynamic model catalogs,
skill safety, optional intake references, reference generation control flow,
per-shot visual/continuity/audio combinations, shot editing/retry, existing
R2V job compatibility, lifecycle duplication, media sampling/muxing, and
backward-compatible API behavior.

Runtime acceptance remains intentionally outstanding for authenticated
Codex/AGY calls, actual ImageGen quality, full ComfyUI GPU generation, and
mobile Tailscale behavior. These tests were not run while a separate manual
ComfyUI session was active and the user explicitly requested that it not be
stopped, restarted, or used by the app.
