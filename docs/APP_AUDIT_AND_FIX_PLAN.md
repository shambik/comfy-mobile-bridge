# H3 Studio application audit and fix plan

Date: 2026-08-23

## Executive summary

H3 Studio already has a substantial working foundation: the React production
build succeeds, all 116 backend tests pass, manifests validate, state survives
restarts, generated assets can be organized, and the Production Room connects
Codex, AGY, ComfyUI, and the user in one application.

The largest remaining problems are architectural rather than isolated UI bugs.
Production truth is currently distributed across SQLite, in-memory orchestrator
tasks, agent subprocesses, the ComfyUI queue, SSE events, and frontend polling.
That makes stale status, ignored interventions, duplicate messages, and
"running" jobs after a process failure much easier to create. File paths are
also used as asset identity in several places, so Windows file locks and moves
can invalidate production references. Finally, several large modules now own
too many responsibilities, increasing regression risk.

The recommended order is:

1. Make lifecycle and asset identity authoritative and self-reconciling.
2. Make agent execution observable, cancellable, and contract-driven.
3. Replace full-state polling with incremental updates.
4. Split the largest backend and frontend modules by domain.
5. Tighten access control, runtime reproducibility, migrations, and diagnostics.

## Scope and evidence

Reviewed areas:

- FastAPI routes, security middleware, uploads, process controls, and errors.
- ComfyUI process management, workflow construction, queue handling, and jobs.
- Production orchestration, agent sessions, intervention, persistence, and QC.
- Studio projects, folders, file moves, path rewriting, and Windows lock retry.
- React Studio and Production Room state, polling, SSE, and responsive layout.
- Bootstrap, preflight, doctor, start/stop scripts, manifests, and documentation.
- Existing automated tests and CI configuration.

Verification performed during this audit:

- `npm run build`: passed.
- `python -m unittest discover -s tests -p "test_*.py"`: 116 passed.
- Python compile check: passed.
- Manifest validation: passed.
- Repository state inspected without changing existing application code.
- `scripts/preflight.ps1 -Json -SkipGpu -SkipTailscale`: rejected installed
  Node.js 24 because it requires exactly Node.js 22, although the UI builds.
- `scripts/doctor.ps1 -Deep`: model hashing produced no progress for more than
  two minutes and was stopped manually.

The working tree already contained active, unrelated changes when this report
was created. This audit does not revert or rewrite them.

## What is working well

- Mutating API routes consistently apply CSRF validation.
- Trusted-host checks, CSP, upload size limits, media probing, and path boundary
  checks are present.
- The application separates bridge state, input, output, projects, logs, and
  runtime configuration from Git.
- Studio path rewriting covers regular jobs, sequences, production artifacts,
  references, attempt outputs, and review frames.
- Production checkpoints, messages, attempts, configuration revisions, and
  agent session IDs are persisted.
- ComfyUI generation stays serialized while agent work can advance separately.
- Backend coverage is broad and CI builds the frontend, runs tests, validates
  manifests, scans tracked files, and parses PowerShell scripts.
- Workflow-owned resolution calculation is preserved instead of duplicating
  final pixel calculation in the UI.

## Prioritized findings

### P0 — fix before treating the app as reliable or sharing it broadly

#### 1. Production lifecycle has multiple competing sources of truth

Evidence:

- Persisted production/job status lives in SQLite.
- Active work also lives in in-memory orchestrator tasks and agent process maps.
- Actual GPU work lives in the independent ComfyUI queue/process.
- The browser combines SSE events with periodic full-state requests.

Impact:

- A card can remain "generating" after ComfyUI exits.
- A resumed production can wait on stale work or repeat an accepted shot.
- The fixed progress banner can describe a previous agent response rather than
  the work currently running or queued.
- Restart recovery requires many special cases and can diverge from reality.

Fix:

- Define one explicit production state machine with validated transitions.
- Persist every transition with `run_id`, `stage_run_id`, `shot_attempt_id`,
  actor, reason, and timestamp in one transaction.
- Treat in-memory tasks as executors, never as authoritative status.
- Add a reconciler that compares persisted state with agent PIDs and ComfyUI
  queue/history on startup and periodically while active.
- Distinguish `agent_running`, `waiting_for_gpu`, `comfy_running`, `reviewing`,
  `waiting_for_user`, `paused`, `failed`, and `completed`.
- Make retries idempotent with a unique operation key so an accepted attempt
  cannot be generated again accidentally.

Acceptance criteria:

- Killing ComfyUI changes the affected job and production stage to a truthful
  recoverable state within one health interval.
- Restarting the bridge never duplicates an accepted shot.
- Every visible status can be traced to one persisted current operation.

#### 2. Filesystem paths are acting as asset identity

Evidence:

- Studio moves rewrite paths across several tables.
- Production artifact endpoints sometimes repair stale paths by resolving the
  related job and then updating the attempt.
- Windows move retries exist because a browser/stream can hold an MP4 open.

Impact:

- Moving or renaming a file can break AGY/Codex review, production playback,
  attempts, or final assembly.
- Full-table path rewriting becomes slower as history grows.
- A transient Windows file lock makes an otherwise valid organize operation
  fail or block a request.

Fix:

- Introduce a stable `asset_id` registry with current path, media type, size,
  hash, owner/project, and lifecycle state.
- Store `asset_id` references in jobs, attempts, references, and artifacts;
  resolve the current path only at the filesystem boundary.
- Perform moves through one asset service using a database transaction plus a
  recoverable move journal.
- Return `202 Accepted` for a locked move and retry it in a background queue;
  keep the stable media URL working during the transition.
- Use copy-then-atomic-register for files that are actively streamed on Windows.

Acceptance criteria:

- A file can be moved while its video card is open without breaking playback.
- No production table requires a bulk text path rewrite.
- AGY, Codex, final assembly, and Studio always resolve the same current asset.

#### 3. LAN/Tailscale access has no user authentication boundary

Evidence:

- `/api/session` issues a CSRF token to any client that can reach the bridge.
- CSRF prevents cross-site submission but does not authenticate a person.
- The reachable API can control ComfyUI, terminate Fortnite, lock Windows,
  delete/move files, and launch local agent CLIs.

Impact:

- On a LAN bind, any reachable device can potentially obtain a valid session
  and invoke privileged controls. Tailscale network membership alone may be an
  acceptable personal trust boundary, but it must be explicit.

Fix:

- Default to localhost plus Tailscale Serve.
- Add optional application authentication for LAN mode: a local password,
  passkey, or trusted Tailscale identity/header verified by a local proxy.
- Add role/permission checks for machine controls and destructive file actions.
- Log actor identity for every destructive or machine-level command.

Acceptance criteria:

- A new LAN client cannot mutate state without explicit authorization.
- Tailscale and LAN exposure modes clearly show their security posture in UI
  and diagnostics.

### P1 — reliability and maintainability

#### 4. Production loading and live updates transfer too much state

Evidence:

- Production uses SSE but also polls as fallback.
- An incoming event can trigger a complete production-detail reload.
- Detail responses include nested shots, attempts, references, artifacts, and
  up to 200 recent messages.
- The main page separately polls jobs, session/health, ComfyUI status, and logs.

Impact:

- Many repeated requests, slow mobile refreshes, duplicate renders, and higher
  SQLite contention as production history grows.

Fix:

- Use one incremental event stream with monotonically increasing revisions.
- Apply message/status/attempt deltas directly instead of refetching all detail.
- Split summary, messages, shots, references, and artifacts into lazy endpoints.
- Add ETags or `revision`/`after` cursors and visibility-aware polling.
- Pause log and production polling when the tab is hidden.

Acceptance criteria:

- Opening a production performs a bounded initial request set.
- New agent output appends one delta without downloading all prior messages.
- Refresh remains fast with thousands of messages and hundreds of attempts.

#### 5. Agent execution contracts and lifecycle are too permissive and complex

Evidence:

- AGY/Codex output needs multiple schema-normalization and retry paths.
- Silent periods, timeout handling, duplicate live/final messages, and session
  resume are managed across several layers.
- AGY is launched with broad edit/permission bypass flags.

Impact:

- Schema placeholders, malformed `issues`, connection loss, and timeout errors
  can stop a production even when useful output exists.
- An intervention may update UI state before the real subprocess is stopped.
- Broad filesystem access increases accidental-change risk.

Fix:

- Define versioned, minimal response schemas per task: analysis, QC, image
  review, prompt consultation, and final review.
- Add adapters for each CLI/runtime version and contract tests using captured
  real CLI event streams.
- Persist invocation ID, PID, process group, session ID, command metadata,
  start/heartbeat/exit times, and terminal reason.
- Derive live state only from real process events and explicit heartbeats; do
  not synthesize agent replies.
- Make intervention a hard cancellation handshake: request, process-tree stop,
  confirmed exit, checkpoint persist, session resume with user message.
- Give agents read-only project/reference access and a dedicated writable
  output directory wherever the CLI supports it.

Acceptance criteria:

- A malformed provider response produces one actionable error and preserved raw
  diagnostics, not repeated opaque retries.
- The UI never labels generated status text as a real agent message.
- Intervention confirms which process stopped and which saved session resumed.

#### 6. Blocking file and media work runs inside async API handlers

Evidence:

- Library routes call synchronous move/rename/delete functions directly.
- Those functions may sleep repeatedly while handling Windows locks.
- Upload handlers write files and invoke blocking `ffprobe`/`ffmpeg` calls.

Impact:

- One locked MP4 or media probe can block the FastAPI event loop, delaying
  health, production refresh, SSE, and unrelated UI actions.

Fix:

- Move filesystem operations, probes, copies, and FFmpeg work to `asyncio.to_thread`
  or a dedicated bounded executor/job queue.
- Stream uploads to temporary files instead of reading entire uploads into RAM.
- Report operation progress and cancellation separately from request lifetime.

Acceptance criteria:

- A 10-second locked-file retry does not delay `/api/health` or SSE heartbeats.
- A 500 MB upload does not require a second 500 MB in-process byte buffer.

#### 7. Major modules are monolithic

Current concentration includes approximately:

- `backend/production.py`: 2,000+ lines.
- `backend/main.py`: 1,900+ lines.
- `src/main.tsx`: 1,400+ lines.
- `src/production.tsx`: 1,100+ lines.
- `backend/agents.py`, `backend/worker.py`, and `backend/production_db.py`:
  roughly 900–1,100 lines each.

Impact:

- UI changes can alter lifecycle behavior accidentally.
- Tests require large fixtures and regressions are difficult to localize.

Fix:

- Split FastAPI routers by health/control, jobs, library, production, uploads,
  and media delivery.
- Split production into state machine, scheduler, stages, QC policy, assembly,
  references, and recovery services.
- Split agents into runtime adapters, event parser, process supervisor, schema
  contracts, and catalog discovery.
- Split React into domain hooks/stores and focused page/card/modal components.

Acceptance criteria:

- Route modules contain transport logic only.
- Production transitions are unit-testable without FastAPI or subprocesses.
- Components can be tested independently at mobile and desktop widths.

#### 8. Settings and capability rules are duplicated

Examples:

- Default megapixel rules exist in frontend and backend.
- Turbo profile/step constraints are enforced in several layers.
- Workflow capability differences are represented in UI conditionals, backend
  validation, and workflow builders separately.

Impact:

- UI can offer a setting the backend rejects, or show metadata different from
  what the workflow actually ran.

Fix:

- Expose a backend capability document for modes, profiles, step ranges,
  encoders, audio behavior, resolutions/aspect ratios, and installed models.
- Make forms render from that document and keep backend validation authoritative.
- Store the normalized submitted settings and actual resolved workflow settings
  separately on every job card.

Acceptance criteria:

- One capability change updates UI, validation, docs generation, and tests.
- Cards distinguish requested MP from actual calculated dimensions/MP.

#### 9. Database evolution, retention, and backup need formal policies

Evidence:

- Schema changes are handled with in-code conditional migrations/table rebuilds.
- Messages, events, attempts, logs, and generated review frames can grow without
  a documented retention/compaction policy.
- Current `state/` contains about 1.41 GiB across roughly 1,367 files; media is
  the dominant cost, but production history will continue growing.

Fix:

- Add explicit schema versioning and ordered, transactional migrations.
- Back up SQLite before migration and expose migration status in doctor output.
- Define retention separately for user-visible messages, raw CLI events, logs,
  rejected attempts, sampled frames, and accepted/final assets.
- Add a storage report and safe cleanup preview to Settings.

Acceptance criteria:

- Every release can migrate forward from the prior supported schema in tests.
- Cleanup never removes accepted/final assets or active production dependencies.

#### 10. Runtime discovery can delay startup and reduce reproducibility

Evidence:

- Model catalogs are queried during application lifespan startup.
- `scripts/start.ps1` silently falls back to any global `python` when the
  configured bridge interpreter is missing.
- This machine has previously run materially different Torch/CUDA/Python stacks.

Impact:

- Offline/slow CLI catalog calls can delay availability.
- A missing environment can launch an unintended interpreter and make behavior
  difficult to reproduce.

Fix:

- Start the API from cached settings immediately and refresh catalogs in the
  background with visible freshness/error metadata.
- Make start fail closed when the configured interpreter is missing; require an
  explicit `-AllowSystemPython` override for diagnostics only.
- Record bridge Python, ComfyUI Python, Comfy commit/version, Torch, CUDA,
  command line, workflow revision, custom-node revisions, and model hashes on
  every job automatically.

Acceptance criteria:

- The API health endpoint is available without waiting for external CLIs.
- A job's advanced log fully identifies the environment that produced it.

### P2 — quality, tooling, and documentation

#### 11. Diagnostics need fast and deep modes with progress

- Deep doctor hashes very large model files synchronously and gives no progress.
- Preflight currently rejects Node.js 24 despite a successful build because it
  expects Node.js 22 exactly.

Fix:

- Make quick existence/size checks the default.
- Cache hashes by path, size, and modification time; show current file/progress.
- Use a documented supported version range rather than an exact Node major when
  newer versions are compatible, or clearly explain why an exact pin is needed.

#### 12. Frontend automated coverage is too narrow for current UI complexity

- CI builds TypeScript but does not run the Playwright smoke script.
- The smoke script primarily covers the generation page and uses a 720 px
  "desktop" viewport; it does not exercise the current Production Room layout.

Fix:

- Add component tests for reducers/hooks and formatting.
- Run Playwright in CI for 390 px mobile and representative 1440/1920 px desktop.
- Cover production loading, SSE reconnect, intervention, queued/GPU states,
  modal navigation, references, bulk moves, file-lock behavior, and stale job
  reconciliation.

#### 13. Documentation has drifted from implementation

Examples:

- README calls production generation silent even though production lip-sync is
  now supported.
- README says independent I2V uses an assigned opening image, while the current
  intended flow creates a shot-specific scene frame from planning references.
- Architecture text still describes selected references being sent through the
  opening-frame path in places.

Fix:

- Generate capability tables from the backend capability document.
- Add a release checklist that compares README, architecture, setup scripts,
  manifests, and UI labels against current behavior.
- Separate implemented, experimental, disabled, and future functionality.

#### 14. Error handling and localization need consistency

- The global exception handler returns internal exception text to clients,
  which can expose paths and implementation details.
- English and Hebrew messages are mixed without a localization layer.
- Some background errors appear globally instead of in the owning section.

Fix:

- Return a safe user message plus correlation ID; keep stack/path details in
  server logs and advanced diagnostics.
- Introduce message keys and one locale source instead of embedded strings.
- Route errors to job, agent, reference, shot, library, or machine-control UI;
  reserve global errors for application-wide failure.

#### 15. Minor workflow and repository cleanup

- Some workflow builders compute frame-count variables that are not used.
- A tracked `diff.patch` appears to be maintenance debris and should be reviewed
  before removal.
- The untracked `temp.json` must not be deleted or committed without confirming
  ownership and purpose.

Fix:

- Remove dead calculations only with workflow snapshot tests.
- Inventory tracked helper/patch files and archive or document intentional ones.
- Keep models, runtime environments, state, and generated media outside Git.

## Recommended implementation roadmap

### Phase 1 — truthful operation

1. Add operation/run IDs and the persisted production transition service.
2. Add startup/runtime reconciliation for agents, jobs, and ComfyUI.
3. Make intervention and stop wait for confirmed process termination.
4. Replace path identity with an asset registry and stable media URLs.
5. Move blocking filesystem/media work off the event loop.

### Phase 2 — efficient production UI

1. Introduce revisioned incremental production events.
2. Lazy-load messages, references, attempts, and artifacts.
3. Remove duplicate polling and synthetic activity messages.
4. Add focused UI tests for mobile/desktop production behavior.

### Phase 3 — modularity and contracts

1. Split backend routers and production/agent services.
2. Split frontend stores/hooks/components.
3. Add runtime-specific agent schema adapters and captured-stream contract tests.
4. Centralize workflow capabilities and generation defaults.

### Phase 4 — distribution readiness

1. Add optional authentication/authorization for LAN use.
2. Formalize migrations, backups, retention, and storage reporting.
3. Make runtime startup fail closed and record complete provenance per job.
4. Align setup scripts, manifests, README, architecture, and acceptance tests.

## Suggested first delivery slice

The safest first implementation should be deliberately narrow:

1. Create `production_operations` and persist one current operation per
   production.
2. Reconcile that operation against the active agent process and ComfyUI queue.
3. Expose a small `/status` delta containing actual actor, action, elapsed time,
   heartbeat, and blocking reason.
4. Make the fixed progress banner consume only this endpoint/event.
5. Add tests for bridge restart, ComfyUI crash, intervention, accepted-attempt
   idempotency, and no duplicate agent messages.

This slice directly addresses the most visible failures without requiring the
full module split first, and creates the state foundation needed by later work.

