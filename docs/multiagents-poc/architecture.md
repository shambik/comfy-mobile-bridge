# Multi-Agent Production Council — Architecture and Delivery Plan

> **Status:** Council pipeline implemented through final user review; deterministic verification complete, real-provider rollout smoke pending
>
> **Branch:** `feat/multiagents-poc`
>
> **Revised:** 2026-08-24
> **Scope:** reusable media-production council for music videos, shorts, trailers, commercials, and narrative clips

### Current implementation boundary

The isolated Council pipeline supports configurable solo or multi-seat councils, multi-role seat assignments, live model/effort validation, conservative server-verified capabilities, durable per-seat provider sessions, project-native role-skill handoff, persisted tasks/deliverables/interventions/activity, bounded retries, truthful provider stream milestones, reference preparation, scene-frame creation, I2V/lip-sync ComfyUI submission, technical and A/V review, bounded regeneration, editorial assembly, final review, and explicit user override. Legacy remains available as a separate pipeline and retains its existing behavior.

The deterministic controller now runs every dependency-ready task that can safely overlap. Each saved agent seat is its own serialized lane, ComfyUI remains one GPU lane, and FFmpeg/controller work has explicit resource lanes. Hard-cut shots may prepare in parallel; sequential shots wait for the prior accepted shot. The implementation has deterministic unit/integration coverage. A real-provider/real-ComfyUI end-to-end smoke remains a rollout requirement and is intentionally not performed while another GPU workload is active.

## 1. Objective

Build a configurable production council in which one or more Codex, AGY, or future agent runtimes work as named seats with assigned roles. A council may therefore be a single solo agent or a multi-agent team. Specialists create versioned deliverables. Supervisors challenge those deliverables against explicit acceptance gates when configured. The user remains the final authority and can inspect, intervene, pause, resume, or override the process.

The council must improve quality without reproducing the failure modes of the earlier two-agent pipeline:

- agents must not control the workflow state machine;
- UI status must reflect verified processes and persisted task state, never inferred text;
- a model response must not be treated as an executable command;
- conversation memory must supplement, not replace, durable project state;
- capabilities must be verified by the runtime/model adapter;
- retries must be bounded, observable, and idempotent;
- moving an asset must not invalidate a production.

## 2. Architectural principles

### 2.1 Deterministic controller, creative agents

The production controller owns stage/task transitions, dependencies, queueing, cancellation, retry budgets, artifact registration, acceptance gates, interventions, and final assembly commands.

Agents own analysis, creative proposals, structured reviews, revisions, and media inspection when their verified capabilities allow it.

An agent may recommend `approve`, `revise`, or `escalate`, but it cannot advance the production directly. The controller validates the response and applies the configured gate policy.

The controller is a durable scheduler and rule engine, not another creative agent. One controller cycle:

1. loads the production, configuration revision, tasks, deliverables, interventions, and artifact references;
2. reconciles verified provider processes and ComfyUI queue/history state;
3. delivers any intervention that has reached a safe checkpoint;
4. finds dependency-ready tasks;
5. selects a seat whose role and effective capabilities satisfy the task;
6. builds scoped context and resumes that seat's saved provider session;
7. validates and persists the response as a new deliverable version;
8. evaluates gates, retry/revision budgets, and user policy;
9. creates the next task exactly once, or records an explicit wait, failure, or completion state; and
10. emits truthful UI events backed by that persisted or verified state.

It never invents creative output and never claims that an agent is working without a confirmed provider process. If only controller rules are running, the UI says `Controller · evaluating ...`; while waiting for ComfyUI it identifies the verified ComfyUI job instead.

### 2.2 Durable project ledger before conversational memory

Every accepted input, decision, artifact, review, and user intervention is persisted in a production ledger. Agent sessions retain conversational continuity, but a production must remain recoverable if a session is lost or a provider requires a fresh conversation.

### 2.3 Versioned artifacts, not fragile paths

Agents and production records refer to assets by immutable `artifact_id`. The current filesystem path is resolved only when a provider or tool needs the file. Organizing or renaming a file updates the artifact record atomically; historical tasks continue to resolve the same asset.

### 2.4 Skills describe behavior; manifests drive routing

`SKILL.md` files teach an agent how to perform a role. They are not executable configuration. A machine-readable role manifest declares task types, input artifact types, output contract, tier, and required capabilities. The controller uses the manifest; the agent is given the installed native role-skill path and reads the file through its normal skill/file mechanism. The bridge does not paste the full role or selected specialist skill body into each request.

### 2.5 Capability is an intersection

Effective capability is:

```text
runtime/model capability ∩ installed tools ∩ user-enabled capability ∩ role requirement
```

A checkbox can disable a capability, but it cannot grant one that the runtime/model does not expose.

The server verifies capabilities from four sources:

1. the provider adapter's declared baseline for the runtime;
2. discovered model metadata returned by the CLI/provider catalog;
3. health checks for required local tools and permissions; and
4. an optional cached capability probe using a known small media fixture after install, upgrade, model change, or manual recheck.

Probe results are keyed by adapter version, model identifier, tool versions, and expiry. A capability is `verified`, `stale`, `unsupported`, or `unknown`. Only `verified` capabilities satisfy a required role. `stale` may be displayed, but it must be reverified before a dependent task starts.

## 3. System layers

```text
Production UI
    │
Production API
    │
Council Controller ───── Intervention Inbox
    │
    ├── Pipeline Template / Stage Graph
    ├── Task Scheduler and Durable State Machine
    ├── Acceptance-Gate Engine
    ├── Context Builder
    ├── Artifact Ledger
    └── Provider Adapters
            ├── Codex CLI adapter
            └── AGY CLI adapter
                    │
                 Agent seats
```

The new implementation belongs under isolated modules such as `backend/council/`. Do not inject a second orchestration system into the existing large `production.py` method with string-replacement scripts.

## 4. Core concepts

### 4.1 Pipeline template

A pipeline template defines the stage graph and required deliverable types. Examples include `music_video_hybrid_v1`, `commercial_v1`, `trailer_v1`, and `narrative_short_v1`. It does not name Codex or AGY. It maps task types to role requirements.

### 4.2 Role skill

A role skill defines domain behavior, boundaries, and review criteria. It should be reusable across pipelines. The active Council seat determines which role skill is used for a task; user-selected production skills are an additional, explicit set controlled by the app.

Initial specialists:

- Audio Analyst
- Visual Director
- Storyboard Editor
- Scene Frame Designer
- Prompt Engineer
- Technical Director
- Technical QC
- A/V Sync Reviewer
- Continuity Editor
- Post-Production Editor

Initial supervisors:

- Executive Producer
- Creative Director

The user chooses the number of seats. Each seat may receive one role or several roles, and the same runtime/model may be used by several seats. Optional roles may remain unfilled. A one-seat council is valid when that seat's verified capabilities and assigned roles cover every required task type.

In solo mode, the controller still creates separate role-scoped tasks and loads only the active role skill for each turn. The same provider session may continue across those role turns, but every deliverable records which role produced it. A solo agent may review its own earlier work only when the selected gate policy permits self-review; the UI labels this honestly and may require a user gate instead of pretending that an independent reviewer exists.

### 4.3 Agent seat

A seat is an immutable production-time snapshot of an agent configuration:

```json
{
  "id": "seat_uuid",
  "label": "AGY Solo Producer",
  "tier": "mixed",
  "runtime": "agy",
  "model": "verified-catalog-id",
  "effort": "medium",
  "role_ids": ["audio-analyst", "visual-director", "storyboard-editor"],
  "user_enabled_capabilities": ["audio", "image", "video"],
  "effective_capabilities": ["audio", "image", "video"],
  "custom_instructions": "",
  "config_revision": 1
}
```

`effective_capabilities` is server-computed. The client does not submit it as trusted state.

Role assignment is many-to-many: one seat can own several roles and one role can have several eligible seats. The task scheduler selects a single accountable seat for each task according to explicit routing priority, availability, capabilities, and gate policy.

### 4.4 Task

A task is one bounded unit of work assigned to one seat. It has typed inputs, a required output contract, a retry policy, and persisted execution state.

```text
queued → starting → running → validating → completed
                     │             │
                     ├→ interrupted│
                     ├→ cancelled  └→ retry_wait → queued
                     └→ failed
```

`waiting_for_generation`, `waiting_for_user`, and `waiting_for_dependency` are explicit states, not vague controller activity.

### 4.5 Deliverable

A deliverable is a versioned structured artifact: audio timeline, treatment, reference plan, storyboard, opening/closing scene frame, generation prompt, execution manifest, QC report, or final master. Each revision creates a new version. Reviews point to the exact version inspected.

## 5. Persistence model

Use normalized tables as the source of truth. Avoid mutable seat configuration in both `agent_seats` and `seats_json`.

### 5.1 Recommended tables

#### `production_seats`

Immutable seat configuration, verified capabilities, role assignments, runtime/model/effort, active flag, and config revision.

#### `agent_sessions`

Production, seat, provider session identifier, last successful turn, persisted handoff summary, status, and timestamps. One seat normally keeps one production session. A task is a new turn in that session.

#### `production_tasks`

Task type/stage, assigned seat, dependencies, state, attempt, lease, heartbeat, input/output contract versions, timestamps, and classified error.

#### `production_deliverables`

Logical deliverable ID/version, producer seat/task, structured payload, artifact IDs, supersedes relation, and validation status.

#### `production_reviews`

Reviewer seat, exact deliverable/attempt version, gate ID, decision, severity-scored findings, and targeted revision requests.

#### `production_interventions`

User message, target seats, created/delivered/acknowledged timestamps, delivery policy, and affected task IDs.

#### `artifacts`

Immutable `artifact_id`, current path, media metadata, checksum, provenance, project/folder assignment, producer task/revision, and availability status.

### 5.2 Existing live schema residue

The previous experiment already added `agent_seats`, `seats_json`, `default_seats_json`, and `reviews_json` to the live SQLite database. The implementation must include an idempotent migration that detects these additions and either adopts or supersedes them. Never patch the live database with an ad-hoc script outside the application migration path.

## 6. Role manifest contract

The package-level manifest is the controller-facing registry. Each role declares:

```json
{
  "id": "audio-analyst",
  "tier": "specialist",
  "skill_path": "roles/audio-analyst/SKILL.md",
  "task_types": ["audio_analysis"],
  "required_capabilities": ["audio"],
  "optional_capabilities": [],
  "input_types": ["source_audio", "lyrics", "creative_brief"],
  "output_contract": "audio_timeline.v1",
  "default_context_policy": "audio-analysis.v1"
}
```

The app validates the manifest at startup. A malformed role is unavailable and produces a catalog diagnostic; it must not crash production loading.

## 7. Provider adapters and verified catalogs

Every runtime adapter implements:

```text
discover_models()
probe_capabilities(model)
start_or_resume_session()
invoke(task, context, attachments, output_contract)
cancel(turn)
health()
```

Rules:

1. Model lists come from live discovery or a versioned, known-valid adapter catalog.
2. Never expose guessed cross-provider models as fallbacks.
3. Cache successful discovery briefly and preserve the last verified catalog with a timestamp/stale indicator.
4. Refresh asynchronously; model discovery must not block page startup.
5. Store provider diagnostics separately from user-facing agent messages.

## 8. Session and shared-context design

### 8.1 Per-seat continuity

Each seat resumes its own provider session throughout the production. Persist a returned session ID immediately after a successful turn.

### 8.2 Shared production ledger

Agents do not directly message one another. The controller builds each turn from role instructions, current user brief/interventions, required deliverable versions, relevant decisions/unresolved issues, and the seat's own session continuity. This enables consultation without giving every seat the full raw history.

### 8.3 Fresh-session recovery

If a provider session becomes invalid:

1. classify it as a session failure;
2. start one fresh-session attempt;
3. provide a ledger-generated handoff with accepted facts, current task, unresolved issues, and artifact IDs;
4. persist the new session ID;
5. fail visibly if the fresh attempt also fails.

Do not create fresh sessions repeatedly for schema errors or ordinary revision decisions.

## 9. Canonical response contract

All roles return one canonical envelope; role-specific data lives in `deliverable`.

```json
{
  "schema_version": "council-envelope.v1",
  "task_id": "task_uuid",
  "status": "completed",
  "summary": "Short factual result",
  "recommendation": "approve",
  "deliverable": {},
  "issues": [],
  "requested_revisions": [],
  "evidence": {
    "artifact_ids": [],
    "inspected_media": []
  }
}
```

Validation rules:

- `issues` and `requested_revisions` are always arrays;
- task/schema IDs must match the request;
- required evidence must exist for media-inspection tasks;
- literal schema/example echoes are invalid;
- unknown fields cannot drive state;
- use at most one contract-repair attempt before the normal retry policy.

Use native JSON schema where supported; otherwise validate server-side. Skills should not contain several incompatible response shapes.

## 10. Context policies

Context selection is declarative and tested. A role does not execute a fictional `select_context()` method from Markdown.

- Audio Analyst: source audio + lyrics + brief.
- Visual Director: brief + accepted audio timeline + user references.
- Storyboard Editor: treatment + audio timeline + continuity preference.
- Scene Frame Designer: shot specification + selected bibles/reference artifacts + adjacent-shot facts.
- Prompt Engineer: actual generated scene frame(s) + shot specification + model profile.
- Technical QC: generated media + shot acceptance criteria.
- A/V Sync Reviewer: generated media + exact source audio segment + editorial offset.
- Continuity Editor: adjacent approved clips/frames + bibles + continuity mode.
- Supervisors: structured deliverables, unresolved issues, user constraints, and raw media only when capability/gate requires it.

Context builders return artifact IDs and resolve paths only for an invocation.

## 11. Production flow

### 11.1 Planning

```text
intake
  → audio analysis (when applicable)
  → visual treatment and bibles
  → reference planning/generation/review
  → storyboard and editorial timeline
  → scene-frame plan
  → prompt and execution manifests
  → planning gate
```

User-supplied references are optional:

- with complete references, the council inspects them, creates the required character/location/prop bibles, and reuses the approved anchors;
- with partial references, it preserves the supplied material and generates only the missing reference categories; and
- with no references, the Visual Director proposes the reference plan, image-capable seats generate candidates, and the configured supervisors consult, approve, or request targeted revisions.

In interactive mode, reference approval may be a user gate when configured. In autonomous mode, the council approves within its revision budget and escalates only when it cannot resolve a blocking issue. Every candidate and accepted version remains visible to the user.

Planning references are creative anchors. They are not automatically sent directly as I2V opening frames. For each shot, the Scene Frame Designer composes the actual scene-specific opening frame from the approved references and decides whether an explicit closing frame is needed. The generated scene frame—not the planning references—is sent to I2V. R2V remains outside this POC until separately validated.

### 11.2 Generation

Generation is intentionally split into two phases:

1. resolve the approved shot specifications;
2. prepare and validate the complete planning-reference bundle;
3. compose and validate every shot-specific opening/optional closing frame;
4. wait at the persisted scene-frame barrier; no video-generation task may run before it completes;
5. resolve execution parameters from production settings;
6. queue each ComfyUI job idempotently;
7. monitor verified ComfyUI queue/history state;

This prevents the UI from alternating between “one reference, one video” while later scene references are
still being created. Sequential scene-frame planning may remain ordered, but it must not depend on a prior
video acceptance task or it would create a reference-to-video cycle. Any actual last-frame continuity input
that is required by a future workflow remains a separate generation-time dependency.
7. register output as an artifact;
8. run configured review gates;
9. accept, revise, regenerate, escalate, or apply user override;
10. advance exactly once.

Editorial timeline boundaries and audio trim offsets may be fractional. Every duration submitted to an image/video generation workflow must be a positive whole number of seconds. Decimal generation durations are rejected before ComfyUI submission; the Technical Director derives the whole-second generation window while preserving the exact fractional trim/cut instructions for assembly.

Use idempotency key `(production_id, shot_id, shot_revision, attempt)`. An approved attempt cannot regenerate unless a new explicit revision or user action supersedes it.

### 11.3 Assembly and final review

The Post-Production Editor receives approved shot artifact IDs and an editorial manifest. It trims overlaps, assembles clips, and applies the configured audio policy: master-track replacement, preserve generated audio, or explicit mix. Final gates run before presentation to the user. User rejection creates a revision request and, in autonomous mode, resumes from the earliest affected stage.

## 12. Acceptance gates and consensus

Do not use one generic vote for every decision. Stages declare gates such as creative alignment, feasibility, technical quality, A/V sync, continuity, and user approval.

Decisions are `approve`, `approve_with_notes`, `revise`, or `escalate`.

When several supervisors evaluate one gate, strict majority is `floor(N / 2) + 1`. With two supervisors, both approve unless policy names one accountable owner. With one eligible seat, the configured policy chooses among transparent self-review, a required user gate, or skipping that optional review; it must never present self-review as multi-agent consensus. The user's explicit decision always overrides agent consensus.

Revision requests target a deliverable and owner role. A stage has a configured revision budget. Repeating the same defect fingerprint without material input change escalates instead of looping.

## 13. Intervention behavior

The user may submit an intervention at any time. It is acknowledged immediately and persisted as a command, not merely stored as a chat message.

- During ComfyUI generation, queue it for the next safe checkpoint unless the user explicitly cancels generation. When the job finishes, the controller determines whether the intervention invalidates that output, its prompt/scene frame, the storyboard, or only future work; it then routes the change to the affected seats and resumes from the earliest affected task.
- During an agent turn, request adapter cancellation and wait for confirmed termination before resuming that seat's session.
- While idle/waiting, deliver immediately.
- Autonomous mode applies the intervention and continues automatically.
- Interactive mode applies it and stops at the next configured user gate.

The UI shows `queued`, `delivered`, `acknowledged`, `applied`, or `failed`, including the affected task/seat. Delivery resumes each affected seat's own provider session and includes the exact affected deliverable versions. Agent acknowledgements and resulting revisions appear in chat.

## 14. Activity and UI truthfulness

The UI consumes persisted task state plus verified runtime events. It may show queue position, provider PID/session, meaningful provider progress, ComfyUI job/step progress, validation/retry state, last verified activity, and truthful quiet time.

The fixed activity bar identifies the actual worker and role, for example:

- `AGY · Audio Analyst · analyzing source audio`;
- `Codex · Storyboard Editor · revising Shot 04`;
- `ComfyUI · Shot 07 · step 4/6`;
- `Controller · validating A/V Sync Review`; or
- `Queued intervention · waiting for ComfyUI job <id> to finish`.

It must never retain an old agent message while no matching provider process exists. The truthful fallback is `Idle` or a named controller/wait state.

The chat timeline includes user messages, intervention lifecycle events, agent task starts, concise meaningful progress/tool activity, structured agent replies, revision requests, gate decisions, ComfyUI progress/completion, and controller transitions. It does not expose hidden chain-of-thought, repetitive transport events, raw warning noise, or a duplicate copy of an already-rendered structured response.

Raw warnings and transport diagnostics belong behind advanced diagnostics. Structured replies are shown once; live events must not duplicate final responses. Production shell, messages, references, and storyboard load independently with pagination/lazy media loading.

## 15. Configuration UI

The creator offers `Solo agent`, `Multi-agent council`, and custom seat presets. The user chooses one or more seats, assigns one or several roles to each seat, and selects runtime/model/effort per seat. It also offers capability toggles limited to verified capability, aspect ratio, Turbo/steps, duration-to-MP rules, continuity/lip-sync strategy, participation mode, gates, and revision limits. Reference upload is optional; the UI explains that missing references will be designed, generated, jointly reviewed when more than one eligible seat exists, or transparently self-reviewed/user-reviewed in solo mode, and exposed before shot generation.

Validation reports missing task coverage, capability gaps, and gates that require more independent reviewers than the configured seats provide before creation. It does not require multiple seats when one capable seat covers the selected pipeline. Configuration is versioned. Changes to future shots create a new revision while active/completed tasks retain their original revision.

## 16. Migration and compatibility

The existing behavior remains an explicit, untouched **Legacy Production** pipeline while the council is added as a separate pipeline.

1. Use normal idempotent startup migrations while preserving legacy records, APIs, UI behavior, generation behavior, and existing Codex/AGY orchestration.
2. Give the pipelines explicit IDs such as `legacy_music_video_v1` and `council_music_video_v1`.
3. New-production UI offers `Legacy` and `Council`; reopening an existing production always uses the pipeline revision with which it was created.
4. Put council work behind a feature flag and retain Legacy as the rollback/fallback path.
5. Never route a Legacy production through council state transitions or rewrite an active Legacy production.
6. Do not drop legacy columns or methods during the POC.
7. Produce a read-only migration report before adopting experimental schema residue.

## 17. Implementation phases

### Phase 0 — contracts and fixtures

- finalize role manifest and response schemas;
- define task states, errors, and gate policies;
- create provider fixtures including malformed AGY responses;
- record persistence/session decisions.

Exit: schemas validate independently; no production code changed.

### Phase 1 — isolated council core

- create `backend/council/`;
- implement state machine, ledger, context policies, and gate engine;
- use fake adapters for deterministic tests;
- implement idempotent migrations.

Exit: restart/recovery, duplicate suppression, bounded retry, and intervention tests pass.

### Phase 2 — provider adapters

- wrap existing Codex/AGY invocation code;
- live model discovery with verified stale-cache fallback;
- capability probing;
- per-seat sessions/cancellation;
- meaningful streamed events separated from diagnostics.

Exit: adapter conformance suite passes; unavailable models cannot be selected.

### Phase 3 — planning vertical slice (implemented)

- implement intake → audio analysis → treatment → storyboard;
- expose seats and deliverables in UI;
- no image/video generation;
- test autonomy, interaction, intervention, and restart.

Exit: one real song reaches an approved storyboard with durable sessions and no legacy-stage calls.

### Phase 4 — references and scene frames (implemented)

- generate/review bibles and references;
- implement Scene Frame Designer;
- create actual opening/optional closing frames;
- register assets by ID.

Exit: shot plans resolve valid scene-frame artifacts without direct planning-reference misuse.

### Phase 5 — one-shot generation and review (implemented)

- integrate I2V and optional lip-sync submission;
- monitor ComfyUI truthfully;
- run Technical QC, A/V Sync, and Continuity gates;
- prove approved-shot advance-once behavior.

Exit: one real shot survives restart, intervention, organization/move, retry, and approval without duplication.

### Phase 6 — full production and assembly (implemented)

- iterate storyboard shots;
- allow concurrent productions while serializing GPU jobs;
- assemble clips/audio;
- final agent review and user decision.

Exit: complete production reaches a downloadable final artifact and resumes from every persisted stage.

### Phase 7 — rollout (pending real-provider smoke and operational validation)

- feature flag and migration report;
- mobile/Tailscale load testing;
- observability/support diagnostics;
- limitations and rollback documentation.

## 18. Required tests

- contract validation and schema-echo rejection;
- capability intersection/missing-role detection;
- solo-seat role coverage, role switching, and transparent self-review policy;
- multi-seat routing and independent-review requirements;
- gate and majority behavior;
- dependency scheduling;
- persistent sessions/fresh-session recovery;
- restart in every task state;
- intervention during agent and ComfyUI work;
- generation duration is always an integer while editorial boundaries/audio trims may remain fractional;
- approved attempt cannot regenerate without revision;
- asset move/rename preserves resolution;
- missing media returns actionable errors;
- AGY timeout, malformed `issues`, and empty media result;
- adapter conformance;
- legacy API compatibility;
- Legacy and Council pipelines run side-by-side without sharing state transitions;
- mobile/desktop lazy loading.

Real-provider smoke tests remain separate from deterministic tests and never mutate an active production.

## 19. POC non-goals

- R2V production generation;
- direct agent-to-agent network messaging;
- unverified model fallbacks;
- unlimited debate/retry loops;
- changing active legacy productions;
- exposing hidden chain-of-thought. Show concise progress, tool activity, decisions, and evidence instead.

## 20. Definition of done

1. Configured seats are used for every implemented stage.
2. Every visible status has persisted or verified evidence.
3. Every seat resumes its own session and can recover from session loss.
4. Every turn uses the assigned native role skill and validated context policy. User-selected production skills are read only when enabled for that production; their bodies are never repeatedly injected into the prompt.
5. Actual scene frames—not planning references—drive I2V.
6. Media review uses verified-capability reviewers.
7. Interventions are acknowledged and affect subsequent work.
8. Retries cannot regenerate an approved revision.
9. Moving assets cannot break production.
10. Deterministic tests and one real end-to-end production pass.
