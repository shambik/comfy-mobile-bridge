# H3 Studio code review

**Review date:** 2026-08-23  
**Repository:** `shambik/comfy-mobile-bridge`  
**Branch reviewed:** `main`  
**Reviewed revision:** `dad5f10` (`Improve production agents and studio flow`)  
**Scope:** application code, production orchestration, agent integrations, ComfyUI integration, persistence, media/file handling, frontend/mobile behavior, networking, startup/setup scripts, tests, CI, dependencies, and documentation.

This document is a review only. No application code was changed while preparing it. The unrelated untracked `temp.json` file was not modified.

## Executive summary

The project has grown from a focused mobile ComfyUI bridge into a capable production system with agent orchestration, resumable productions, asset organization, media review, and machine controls. Several important foundations are already present: consistent CSRF checks on mutation routes, path containment checks, model manifests with hashes, broad backend tests, ComfyUI history/WebSocket fallbacks, persisted production data, and useful generation runtime metadata.

The main risk is no longer an isolated UI bug. The system has several competing sources of truth:

1. SQLite production and job state.
2. In-memory bridge tasks, subprocesses, queues, and current-job maps.
3. The independent ComfyUI process and prompt queue.
4. Codex and AGY CLI sessions and their streamed events.
5. Frontend polling/SSE state and cached browser data.

These sources can disagree after a crash, restart, timeout, intervention, file move, or provider retry. That explains the recurring symptoms seen during development: a card says “generating” while ComfyUI is down, an approved shot regenerates, a controller appears active with no agent process, interventions are accepted but do not advance, old agent text is presented as current activity, and moved assets become unreadable.

The highest-priority work is therefore to establish a durable operation state machine and a real authentication boundary, then make every UI status derive from verified operation state. Agent reliability, file organization, startup performance, and frontend modularization should follow.

## Verification performed

| Check | Result | Notes |
|---|---:|---|
| `npm run build` | Pass | Vite built 1,802 modules. Main JS was about 372 kB and CSS about 91 kB before gzip. |
| `npm run lint` | Pass | The current “lint” script runs only `tsc -b`; it is a type check, not a lint/format check. |
| `python -m compileall -q backend` | Pass | Backend modules compile. |
| Manifest validation | Pass | `scripts/validate-manifests.ps1` completed successfully. |
| `git diff --check` | Pass | No whitespace errors in tracked changes. |
| Backend tests in configured bridge Python | **133 pass, 1 error** | 134 tests discovered. One test escaped its mocks and invoked the real Codex CLI, then failed on the account usage limit. |
| Backend tests with system Python 3.12 | Fail before collection | FastAPI, HTTPX, and Pillow were unavailable in that interpreter. The documented bare `python` command is environment-dependent. |
| Repository portability scan | **Fail** | Four tracked files contain personal absolute paths or a personal Tailscale hostname. |
| `npm audit --omit=dev` | **Fail** | Two high-severity findings: direct Vite advisories and transitive NanoID advisory. |

The failing backend test was:

`test_autonomous_intervention_continues_when_agents_request_pause_or_regeneration`

It reached `production_orchestrator._intervention_followup`, launched the actual Codex CLI, and returned a usage-limit error. This is evidence of a test-isolation defect, not merely a temporary account problem.

## Severity guide

- **P0 — critical:** security boundary or data/control risk that should be fixed before exposing the app beyond a tightly trusted machine/network.
- **P1 — high:** causes incorrect state, stuck work, repeated costly generations, data inconsistency, or unreliable releases.
- **P2 — medium:** materially affects maintainability, performance, portability, UX, or diagnosis.
- **P3 — low:** cleanup or quality improvement with limited immediate operational risk.

## Prioritized findings

### P0-1 — There is no user authentication or authorization

**Evidence**

- `backend/security.py` implements a double-submit CSRF token, not a user identity.
- `/api/session` issues a CSRF/session token to any client that can reach the bridge.
- The same reachable client can invoke high-impact routes: start/stop ComfyUI, kill Fortnite, lock Windows, upload/delete/move media, modify skills, and invoke Codex/AGY.
- File and media GET routes use the same network trust boundary.

**Impact**

CSRF protects against a different website silently sending a request from the browser. It does not prevent another device or user on the LAN/tailnet from opening the app, obtaining a token, and controlling the machine. Tailscale encryption also does not decide which tailnet user is allowed to use destructive endpoints.

**Recommendation**

Add an explicit authentication layer before any further public/tailnet expansion:

- Support a local admin PIN or passkey and a short-lived signed session.
- Prefer Tailscale identity headers only when the app is behind a trusted Tailscale Serve/Funnel identity-aware proxy; never trust client-supplied identity headers directly.
- Add permissions such as `view`, `generate`, `organize`, and `machine-control`.
- Make machine-control endpoints disabled by default and independently configurable.
- Require reauthentication for file deletion, Fortnite termination, and Windows lock.
- Add an audit trail containing actor, action, target, timestamp, and result.

**Acceptance criteria**

An unauthenticated LAN or tailnet client cannot read private media or call any mutation route. A normal authenticated viewer cannot execute machine-control actions without the relevant permission.

### P0-2 — Agent subprocesses receive broader filesystem permissions than the application policy claims

**Evidence**

- `backend/agents.py` starts AGY with `--dangerously-skip-permissions` and `--mode accept-edits`.
- Production prompts tell agents not to mutate the workspace, but technical enforcement still permits it.
- Agent calls receive the production root and additional media directories.

**Impact**

A prompt mistake, provider behavior change, injected media/text, or tool-call error could alter files outside the intended generated-output handoff. Policy text is not a security boundary.

**Recommendation**

- Create a per-operation staging directory containing read-only copies or links to only the required media and manifests.
- Give analysis/review calls read-only access.
- Give image generation a single request-specific writable directory.
- Remove `accept-edits` and dangerous permission bypass from calls that do not require writes.
- Validate every returned path against the request-specific output directory.
- Record the exact executable, arguments, environment, working directory, allowed paths, and process ID in the operation audit record.

### P1-1 — Production state has no single durable source of truth

**Evidence**

- Production status is persisted in SQLite.
- Active orchestration tasks, agent processes, and current jobs are held in memory.
- ComfyUI owns a separate process, queue, prompt IDs, history, and output lifecycle.
- Frontend state is rebuilt from a mixture of SSE, polling, and detail reloads.
- Restart recovery infers orphan state from active in-memory task IDs but cannot reconstruct every external operation.

**Impact**

The app can truthfully know that a production row says `running` while being unable to prove that an agent or Comfy prompt is active. This produces stale cards, duplicate attempts, accepted-shot regeneration, false “controller working” banners, and manual resume requirements.

**Recommendation**

Add a durable `production_operations` table and make it the authoritative execution ledger. Suggested fields:

- `operation_id`, `production_id`, `shot_id`, `attempt_id`
- `kind` (`song_analysis`, `reference_generation`, `agent_review`, `comfy_generation`, `assembly`, etc.)
- `state` (`queued`, `starting`, `running`, `waiting_external`, `cancelling`, `succeeded`, `failed`, `cancelled`, `orphaned`)
- `owner_instance_id`, `lease_expires_at`, `heartbeat_at`
- provider/runtime/model/session/process/prompt IDs
- input and output asset IDs
- `started_at`, `finished_at`, safe error code, internal diagnostic ID

All state changes should pass through one transition service with compare-and-set/idempotency guards. On startup, a reconciler should compare operations with actual processes and ComfyUI queue/history before changing status.

**Acceptance criteria**

- A bridge restart does not regenerate an already accepted shot.
- A dead ComfyUI process changes its active operation to a truthful failed/orphaned state within a bounded period.
- Every visible “working” state has a verifiable active operation, lease, and owner.

### P1-2 — Current watchdogs detect total age, not meaningful progress

**Evidence**

`backend/worker.py` calculates a generation watchdog of at least 3,600 seconds (`max(3600, estimated_total * 10 + 600)`). Agent calls can wait up to 1,800 seconds. Synthetic “still working” messages are emitted even when no provider event is received.

**Impact**

A dead or disconnected job can appear active for 30–60 minutes. Users cannot distinguish useful work from a stuck provider. Long timeouts also delay queue recovery.

**Recommendation**

Track separate deadlines:

- startup deadline: process/prompt must start within N seconds;
- no-progress deadline: sampler step, provider event, output byte growth, or heartbeat must advance;
- total runtime deadline: generous cap based on duration/MP/profile;
- output-finalization deadline: history is complete but file is being verified.

When no-progress expires, query actual Comfy queue/history/process state before deciding whether to retry, fail, or keep waiting. The UI must label synthetic timers as “No provider event for …”, never as agent activity.

### P1-3 — The test suite can invoke real agents and consume account quota

**Evidence**

The current test run executed the real Codex CLI from `_intervention_followup`. The test mocked one intervention path but not the second follow-up path.

**Impact**

Tests are non-deterministic, depend on login/network/quota, can leak local prompt/media context, consume paid limits, and may alter external state. A developer can believe tests cover a branch while that branch actually reaches production integrations.

**Recommendation**

- Add a process-level guard: external agent, network, and Comfy calls are forbidden in tests unless `H3_INTEGRATION_TESTS=1` is explicitly set.
- Inject agent/comfy/process interfaces into the orchestrator; use fakes by default.
- Fail immediately with a clear “unexpected external call” assertion.
- Move authenticated live checks into a separately named, manually triggered integration suite.
- Add captured Codex/AGY stream fixtures for parser and retry behavior.

### P1-4 — Effective generation settings can silently fall back to old values

**Evidence**

Defaults such as `16:9`, Turbo V1, four steps, and 0.7 MP appear in backend normalization, database defaults, shot-plan replacement, agent reference generation, and frontend initial/reset state. The creation UI also sends a hardcoded baseline `generation_megapixels: 0.7` beside duration-based MP rules.

**Impact**

If a legacy row, missing field, failed migration, stage restart, or alternate code path omits a value, the system can silently generate at 16:9/V1/four steps despite a production being configured for 1:1/V4/six steps. Generated opening frames and video attempts may then disagree.

**Recommendation**

- Make `effective_generation_settings` mandatory after intake.
- Store a versioned immutable settings snapshot on every opening-frame request and video attempt.
- Remove internal fallbacks after validation; missing settings should stop with a typed configuration error.
- Keep one MP policy object rather than a hidden baseline plus rules.
- When settings change, explicitly invalidate only unstarted derived frames/attempts.
- Add stage-boundary assertions for ratio, dimensions, profile, steps, workflow mode, and MP rule.

### P1-5 — Raw internal exception text is returned to clients

**Evidence**

The global exception handler in `backend/main.py` returns `Internal server error: {exc}`. Users have already seen absolute Windows paths, SQLite constraints, provider internals, and command failures in cards.

**Impact**

This leaks implementation and filesystem details, produces unreadable UX, and couples UI behavior to arbitrary exception strings.

**Recommendation**

Return a safe structured envelope:

```json
{
  "error": {
    "code": "ASSET_FILE_BUSY",
    "message": "The video is still open on another device. Close playback and retry.",
    "diagnostic_id": "...",
    "retryable": true
  }
}
```

Write the traceback and technical context to structured server logs keyed by `diagnostic_id`. Map domain exceptions to appropriate HTTP status codes.

### P1-6 — Asset moves are recoverable but not transactionally safe

**Evidence**

`backend/library.py` correctly rewrites references in jobs, sequences, productions, attempts, artifacts, references, and frame JSON. It retries Windows file-busy errors 10 times. However, filesystem movement and database rewrites cannot be one atomic transaction. A process crash between the two leaves inconsistent state. A browser-held MP4 handle can remain locked longer than the retry window.

**Impact**

Cards can say a file does not exist even when a copy is present elsewhere. Agent reviews can receive stale absolute paths. Rollback is best-effort and cannot cover process termination.

**Recommendation**

- Make immutable asset IDs the primary reference everywhere; resolve current paths through an `assets` table.
- Add a durable `asset_operations` journal.
- Prefer copy → fsync/hash → database pointer swap → deferred delete for Windows media.
- Reconcile unfinished operations on startup.
- Serve media through app-managed streaming with prompt handle cleanup before moves.
- Keep legacy-path repair, but add a UI repair tool for ambiguous duplicate filenames.

### P1-7 — Startup and model discovery can block application readiness

**Evidence**

The backend lifespan requests the model catalog before normal worker/orchestrator readiness. Model discovery invokes external CLIs. The frontend also fetches agent models as part of production catalog loading.

**Impact**

A slow, logged-out, rate-limited, or disconnected CLI can make Studio/Production appear to take 30–60 seconds to load even though existing jobs and assets are local.

**Recommendation**

- Start the API from cached model data immediately.
- Refresh provider catalogs in the background with per-provider status and timeout.
- Fetch models lazily when settings or a model dropdown is opened.
- Use stale-while-revalidate and retain the last successful list.
- Expose separate readiness: database, library, ComfyUI, Codex, AGY, and Tailscale.

### P1-8 — Agent review latency and retries multiply unnecessarily

**Evidence**

- AGY and Codex shot reviews are sequential.
- An intervention can run a council turn and then a follow-up; targeting both agents can produce up to four agent calls.
- AGY responses sometimes echo the schema or return `issues` with an invalid type, triggering a fresh-session retry.
- Codex transport can repeatedly retry WebSocket before falling back to HTTP.

**Impact**

Minutes can pass without a decision even when the required review is simple. Provider retries are presented as production progress, and interventions may feel ignored.

**Recommendation**

- Define a single intervention contract and normally perform one turn per selected agent.
- Parallelize independent reviews, or designate one primary reviewer and invoke the second only for configured checks/tie-breaks.
- Use runtime-specific response adapters and captured stream fixtures.
- Normalize tolerant provider output into a strict internal domain model.
- Permit only one bounded schema repair attempt.
- Remember transport health and bypass a repeatedly failing WebSocket for a cooling period.

### P1-9 — Current dependency and portability gates are failing

**Evidence**

`npm audit --omit=dev` reports:

- Vite `<=6.4.2`: several dev-server file-read/path handling advisories, with a non-major fix available at 6.4.3.
- NanoID `<3.3.18`: custom zero-size generator infinite-loop advisory, fix available.

The repository scan reports personal path/hostname patterns in:

- `diff.patch`
- `scripts/e2e_music_video.py`
- `skills/e2e-music-video/scripts/e2e_runner.py`
- `start-project.bat`

**Impact**

The current branch does not satisfy its own portability scan. Vite is primarily a development/build concern because production assets are served by FastAPI, but exposing the Vite dev server on the LAN would increase the advisory relevance.

**Recommendation**

- Upgrade Vite and refresh the lockfile after build/browser verification.
- Resolve NanoID through dependency updates and rerun the audit.
- Keep the Vite dev server loopback-only.
- Replace all personal paths/hostnames with config-derived values or documented examples.
- Make `start-project.bat` call the common PowerShell startup path instead of duplicating local configuration.

## Production orchestration and agent findings

### P2-1 — Agent sessions and process activity disappear on bridge restart

Current CLI processes and activity maps are in memory. The database may retain session IDs and messages, but it does not retain enough operation ownership to prove that the provider is still executing.

**Suggestion:** persist provider operation/session/process metadata in the operation ledger. After restart, never claim a process is running unless its PID/session/lease can be verified. Resume creative sessions when safe; use a compact production-memory artifact for fresh QC calls.

### P2-2 — Fresh QC sessions reduce context but break conversational continuity

Shot and final reviews intentionally use fresh sessions to avoid enormous histories. This helps token usage, but it conflicts with the expectation that agents remember accepted exceptions, prior interventions, and production policy.

**Suggestion:** separate conversational history from durable production memory. Maintain a concise, versioned record of:

- approved concept and treatment;
- user interventions and standing policies;
- character/location/prop identities;
- shot manifest and accepted attempts;
- known exceptions;
- current effective generation settings;
- unresolved questions.

Pass that artifact to fresh QC sessions. Preserve long-running sessions for collaborative creative work where conversational continuity is valuable.

### P2-3 — Prompt context is repeatedly large and expensive

The base context can include full lyrics, concept, all reference paths, many user messages, and complete selected skill text. Re-sending it increases latency and can bury the current task.

**Suggestion:** use content-addressed context sections, task-specific excerpts, deltas, and explicit token budgets. Reference installed skills by name/version/hash and include only the relevant rules in the turn prompt.

### P2-4 — Image provider handoff can select a file by discovery rather than identity

Reference generation scans production reference/agent-context directories and detects newly changed image candidates. If multiple provider calls write concurrently, newest-file selection can bind the wrong image.

**Suggestion:** assign each request a unique output directory and filename; require the provider to return a small manifest containing request ID, output path, dimensions, hash, and prompt hash. Reject any output outside that directory.

### P2-5 — Audio-to-AGY compatibility conversion needs lifecycle controls

The application converts audio-only files into MP4 carriers when AGY’s file viewer cannot reliably read the original audio. This is a reasonable adapter, but generated carriers can accumulate and obscure which source was analyzed.

**Suggestion:** cache carriers by source hash, store source/carrier linkage, validate duration, mark them as derived temporary assets, and garbage-collect unreferenced carriers.

### P2-6 — Review policy and autonomous behavior are not represented as explicit state

User instructions such as “skip strict QC for this test” or “accept with exceptions and continue” currently depend on agent interpretation and intervention text. One reviewer can still return `REGENERATE`, causing loops.

**Suggestion:** persist typed production policies (`qc_mode`, `max_attempts`, `allow_accept_with_exceptions`, `autonomous_on_intervention`, text strictness, reviewer requirements). The controller—not agent prose—must enforce them.

### P2-7 — Production concurrency and GPU concurrency are conflated

The default production concurrency allows several controllers/agent sessions while one ComfyUI queue serializes GPU jobs. This can overload CLIs and make operation ownership difficult.

**Suggestion:** split limits into `agent_concurrency`, `production_controller_concurrency`, and `gpu_generation_concurrency`; default the GPU lane to one and use conservative workstation defaults.

### P2-8 — Low-MP composition knowledge should be a validator, not only prompt guidance

The observed rule—moving characters below 0.8 MP should be framed closer to avoid blur and poor motion—is valuable production knowledge.

**Suggestion:** encode it in the planning schema and validation: if `mp < 0.8` and a shot contains character movement, require a close/medium framing or a documented override. Add this to both relevant skills and automated plan tests.

## Data and persistence findings

### P2-9 — Database migration detection relies on schema text inspection

`backend/db.py` detects older table shapes using SQL text fragments and can rebuild the jobs table. There is no explicit numbered schema history.

**Suggestion:** use `PRAGMA user_version` or a migration table, numbered transactional migrations, pre-migration backup, post-migration validation, and upgrade tests from every supported release.

### P2-10 — JSON fields are decoded without corruption boundaries

Many database read paths call `json.loads` directly. One truncated or manually edited row can break an entire list/detail endpoint or production resume.

**Suggestion:** centralize typed JSON decoding with table/row/field diagnostics, schema validation, controlled API errors, and a repair command. Do not silently discard corrupt production state.

### P2-11 — Dynamic update helpers lack explicit column allow-lists

Internal helpers construct SQL `SET` clauses from caller-provided keys. They are not currently exposed directly to user input, but typos or future call paths become runtime SQL failures.

**Suggestion:** use typed repositories or explicit field allow-lists per entity.

### P2-12 — Position allocation can race

MAX-plus-one ordering is vulnerable when concurrent writes create or move items in the same project/folder/sequence.

**Suggestion:** allocate ranks inside an immediate transaction with uniqueness constraints, or use stable fractional/rank keys and retry conflicts.

### P2-13 — Production deletion can leave orphaned media

Database deletion and folder removal are separate; recursive file deletion ignores some errors. Locked files can remain after the production disappears from the UI.

**Suggestion:** soft-delete first, enqueue a durable cleanup operation, expose cleanup status, and retain a repair/restore window.

## Backend and API findings

### P2-14 — `backend/main.py` and `backend/production.py` are oversized modules

Approximate sizes at review time:

- `backend/production.py`: 169 kB
- `backend/main.py`: 112 kB
- `backend/agents.py`: 57 kB
- `backend/worker.py`: 49 kB

They mix routing, persistence, state transitions, provider commands, prompt construction, media handling, and recovery.

**Suggestion:** extract:

- API routers by domain;
- application services/commands;
- durable production state machine;
- provider adapters (`CodexAdapter`, `AgyAdapter`, `ComfyAdapter`);
- repositories and migrations;
- asset service;
- media probes/assembly;
- operation event publisher.

The state machine should be testable without FastAPI, subprocesses, filesystem, or network.

### P2-15 — Host allow-list discovery is a startup snapshot

Allowed IPv4 addresses are discovered at startup. DHCP, Wi-Fi interface, and Tailscale changes require a bridge restart before new addresses/hostnames are accepted.

**Suggestion:** support explicit configured CIDRs/hostnames, refresh interface data safely, and expose a network diagnostics endpoint showing bound address, accepted hostnames, local URLs, Tailscale state, and Serve state.

### P2-16 — Error ownership is not consistently tied to a subsystem

Generic “Failed to fetch” or raw provider errors can be displayed at the production-room level even when only model discovery, a card action, or a reference retry failed.

**Suggestion:** give each API request an operation ID and section owner. Keep local section errors local, show temporary success/error toasts, and reserve global errors for global readiness failures.

### P2-17 — Media output finalization is under-specified

The worker can wait for an output file after Comfy history reports completion, but the UI treats much of this period as generic generation.

**Suggestion:** expose explicit phases: queued, loading models, sampling step N/M, decoding, saving, verifying file, indexing asset, complete.

## Frontend and mobile findings

### P2-18 — Multiple polling loops and full detail reloads create slow mobile behavior

The app combines:

- frequent jobs/revision polling;
- session polling;
- Comfy status/log polling;
- Production SSE;
- Production fallback polling;
- full production-detail reloads after debounced events.

This causes repeated SQLite reads, large JSON responses, mobile battery/network use, and visible loading after refresh.

**Suggestion:** multiplex lightweight revision/events over one SSE or WebSocket channel. Fetch deltas by cursor, pause nonessential polling while the document is hidden, and use exponential backoff. Keep separate cached queries for catalog, production header, messages, references, shots, and attempts instead of replacing the full production object.

### P2-19 — The frontend is also monolithic

Approximate sizes:

- `src/main.tsx`: 118 kB
- `src/production.tsx`: 102 kB
- `src/styles.css`: 104 kB

This makes a small grid adjustment capable of changing unrelated Storyboard, Shot Review, Session References, and mobile layouts.

**Suggestion:** split domain hooks and components, for example:

- `useProductionCatalog`, `useProductionEvents`, `useComfyStatus`;
- `ProductionHeader`, `StoryboardPanel`, `CouncilPanel`, `ReferencePanel`, `ShotReviewPanel`;
- typed API client and error model;
- component-scoped styles and shared design tokens.

### P2-20 — Global busy state blocks unrelated actions

Many actions share a broad `busy` state. A slow model lookup or production request can disable unrelated page controls.

**Suggestion:** track pending state by operation/action ID. Disable only the affected control and show where the wait occurs.

### P2-21 — Live message auto-scroll can override the user

The council view can smoothly scroll when messages change. During long productions this can pull the user away from older analysis they are reading.

**Suggestion:** auto-scroll only when the user is already near the bottom; otherwise show a “New activity” button.

### P2-22 — Typography and layout need an accessibility baseline

Numerous labels use roughly 8–11 px text. Touch and modal behavior has changed repeatedly without automated viewport/keyboard checks.

**Suggestion:** establish a rem-based type scale, minimum readable secondary text, 44 px touch targets, focus trapping, Escape behavior, keyboard navigation, visible focus, and `prefers-reduced-motion` support. Test at representative Android/iPhone and desktop widths.

### P2-23 — Language direction is mixed without an i18n layer

English and Hebrew strings are embedded directly in components. Direction and punctuation can become inconsistent.

**Suggestion:** use locale dictionaries and explicit LTR/RTL containers. Respond and render in the user-selected language rather than deriving language from incidental content.

### P2-24 — Import history is artificially limited

The Production import UI uses the latest 20 completed regular jobs.

**Suggestion:** add cursor pagination, search, project/folder filters, date range, mode, duration, seed, and workflow filters.

## Testing, CI, and operational findings

### P1-10 — There are no frontend component or browser tests

Type checking cannot catch the layout and interaction regressions repeatedly observed on mobile and desktop.

**Recommendation**

- Add Vitest and React Testing Library for state/rendering behavior.
- Add Playwright for desktop and mobile viewport flows.
- Mock SSE, fetch, media playback, and slow/failing endpoints.
- Capture visual snapshots for the Production Room, Studio grids, shot modal, errors, and mobile cards.

### P2-25 — “Lint” is only TypeScript compilation

There is no ESLint, formatter check, CSS lint, or import-boundary enforcement.

**Suggestion:** add ESLint with React/TypeScript rules, Prettier, Stylelint if useful, and CI checks. Add module-boundary rules as the frontend is split.

### P2-26 — Test execution is interpreter-dependent

The documented bare `python -m unittest` command used system Python 3.12 in this review and lacked required packages, while configured bridge Python 3.10 ran the suite.

**Suggestion:** provide `scripts/test.ps1` that creates/uses a dedicated test environment and prints exact Python/package versions. CI and local developers should run the same entry point.

### P2-27 — Coverage and state-machine invariants are not measured

Backend tests are broad, but there is no coverage threshold and critical cross-system transitions remain vulnerable.

**Suggestion:** add tests for:

- bridge restart during each stage;
- Comfy crash before prompt, during sampling, during save, and after history success;
- accepted shot is never regenerated without explicit invalidation;
- intervention is applied exactly once and autonomous mode continues;
- aspect ratio/profile/steps survive restart and edit;
- file move while video is open;
- AGY schema variants and Codex transport fallback;
- no external subprocess/network access in unit tests.

### P2-28 — CI lacks dependency/security and frontend behavior gates

CI builds and runs backend tests, but does not run dependency audit, real lint/format checks, coverage, or browser tests.

**Suggestion:** add pinned audit policy, frontend tests, coverage reports, and a hard no-network unit-test environment. Keep GPU/Tailscale acceptance tests manual or on a dedicated self-hosted runner.

## Repository, setup, and documentation findings

### P2-29 — Tracked startup files contain machine-specific configuration

`start-project.bat` hardcodes local Comfy paths, state/database paths, and a personal Tailscale hostname. It duplicates behavior already available in common PowerShell scripts.

**Suggestion:** make the batch file a thin wrapper around one canonical launcher. Resolve every path and host from `config.local.json`/environment. Keep personal config ignored.

### P2-30 — Portable and optimized runtime profiles are not clearly separated

Bootstrap documentation targets a portable Python 3.12/CUDA 12.6-style setup, while the current optimized H3 installation uses a separate Python 3.10/Torch/CUDA profile. Generation cards capture some effective runtime information, but setup documentation can imply there is one canonical environment.

**Suggestion:** document named runtime profiles:

- portable supported baseline;
- local optimized H3 profile;
- optional compatibility profile.

Record profile ID, Python, Torch, CUDA, Comfy version/commit, custom-node commits, launch command, and model hashes on every attempt.

### P2-31 — The existing audit document is stale

`docs/APP_AUDIT_AND_FIX_PLAN.md` reports 116 passing tests. The current suite discovers 134 tests and one escapes to the real Codex CLI.

**Suggestion:** mark historical audits with reviewed commit/date and link to the latest report. Do not keep changing test counts in an undated “current” document.

### P3-1 — `diff.patch` has unclear provenance and lifecycle

The root patch is large, contains a personal path pattern, and does not communicate its source base revision or whether bootstrap still needs it.

**Suggestion:** if required, move it under `patches/` with a descriptive name, source repository/commit, purpose, hash, apply/check script, and removal criteria. Otherwise archive/remove it in a separate reviewed cleanup.

### P3-2 — Tracked custom-node source needs explicit documentation

The repository includes `custom_nodes/ComfyUI-H3-NativeAudioLock`. Keeping source for bootstrap can be valid, but it can be mistaken for the active ComfyUI installation.

**Suggestion:** document that this is vendored/bootstrap source, where it is copied, its upstream revision/license, and how local changes are synchronized.

## Existing strengths to preserve

The following parts should be retained while refactoring:

1. **Mutation-route CSRF coverage:** the route audit found CSRF enforcement on all 44 POST/PATCH/DELETE FastAPI handlers.
2. **Path containment and upload validation:** media operations generally validate roots, filenames, types, and sizes.
3. **Model manifests:** model source, size, SHA-256, and licensing metadata are materially better than ad hoc downloads.
4. **Broad backend coverage:** 134 tests cover many migrations, production, media, asset, and agent paths, even though isolation needs repair.
5. **ComfyUI fallbacks:** history and WebSocket handling provide useful resilience.
6. **Asset reference rewriting:** current move logic attempts to update all known consumers rather than moving only the file.
7. **Runtime diagnostics:** jobs already retain useful environment data that can support reproducibility.
8. **Reference-provider fallback and image validation:** failed providers do not automatically create fictitious successful assets.
9. **Future-shot editing guard:** planned shots without attempts can be edited while active work continues.
10. **Duration/MP rule validation:** whole-number duration rules and workflow-owned dimension calculation are conceptually sound.

## Recommended implementation roadmap

### Phase 0 — Correctness and trust boundary

1. Add authentication/authorization and disable machine controls by default.
2. Replace raw exception responses with safe error codes and diagnostic IDs.
3. Add the hard no-external-calls unit-test guard.
4. Add durable production-operation records, leases, and idempotent transitions.
5. Reconcile Comfy/agent/process truth on startup and after disconnects.
6. Split total and no-progress watchdogs.
7. Make effective generation settings mandatory and snapshot them per attempt.
8. Upgrade vulnerable JS dependencies and make the portability scan pass.

### Phase 1 — Reliable production and assets

1. Introduce runtime-specific Codex/AGY adapters and stream fixtures.
2. Persist compact production memory and typed user policies.
3. Simplify intervention to one explicit, auditable operation.
4. Use immutable asset IDs and an asset-move journal.
5. Add request-specific provider output manifests.
6. Separate agent/controller/GPU concurrency.

### Phase 2 — Performance and truthful UX

1. Replace full-detail reloads and overlapping polls with cursor-based events/deltas.
2. Lazy-load model catalogs and expose subsystem readiness.
3. Render exact operation phases and only verified live activity.
4. Split frontend components/hooks/styles.
5. Add per-action pending/error state, accessibility standards, and i18n.
6. Add frontend unit, browser, and visual regression tests.

### Phase 3 — Portability and release discipline

1. Consolidate all startup paths into one config-driven launcher.
2. Document runtime profiles and capture reproducibility metadata.
3. Introduce numbered DB migrations and recovery tooling.
4. Clean/archive patches and temporary compatibility assets with provenance.
5. Add coverage, dependency audit, lint/format, and release acceptance gates.

## Suggested target architecture

```text
FastAPI routers
    -> application commands / queries
        -> production state machine
            -> durable operations + event outbox
            -> provider adapters (Codex / AGY / ComfyUI)
            -> asset service
            -> media service
        -> typed repositories / migrations

Frontend query cache
    <- initial snapshots
    <- cursor-based operation events
    -> typed commands with operation IDs
```

Key rule: the controller may request work, but it must not claim work is active. Only a verified durable operation with a live lease/provider/prompt can produce an active status in the UI.

## Release acceptance checklist

Before calling the production feature reliable, verify all of the following:

- [ ] A fresh unauthorized phone cannot open media or call controls.
- [ ] Restarting the bridge during every production stage resumes or fails truthfully without duplication.
- [ ] Killing ComfyUI changes active generation state within the no-progress deadline.
- [ ] An accepted attempt is never regenerated unless explicitly invalidated.
- [ ] An intervention is applied exactly once and autonomous mode continues automatically.
- [ ] Production ratio/profile/steps/MP rules remain identical through planning, frame generation, video generation, restart, and rerun.
- [ ] Unit tests cannot start Codex, AGY, ComfyUI, or network requests.
- [ ] Moving a currently playing video either succeeds safely later or returns a typed retryable error without breaking references.
- [ ] Production and Studio initial local data render without waiting for model-provider discovery.
- [ ] Desktop and mobile Playwright tests cover the Production Room, shot settings, references, Studio organization, errors, and reconnect behavior.
- [ ] Repository scan, dependency audit policy, build, lint, tests, and manifest validation pass in CI.

## Conclusion

The project is feature-rich and already contains several good safeguards, but the next development cycle should prioritize execution truth over adding more production capabilities. A durable operation ledger, authenticated boundary, strict effective settings, hermetic tests, and asset IDs will remove a large class of recurring failures at once. After those foundations are in place, the agent collaboration and Production Room UI can be simplified substantially because they will consume one reliable state model instead of inferring activity from several partially synchronized systems.
