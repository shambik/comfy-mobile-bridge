# H3 Mobile Bridge code review

Review date: 2026-10-05. Reviewed the working tree at commit `bdbecdc`, including the existing uncommitted changes and new source files. Line references refer to that working tree, rather than the committed revision alone.

The most consequential findings concern production control and artifact integrity: approvals can consume a decision while returning an error, stale decisions can complete a production, Council pause/stop can prevent resuming, retries and edits do not consistently invalidate dependent work, and continuity/timing settings differ between the two production engines. Network exposure and dependency maintenance also need attention before expanding access to the bridge.

This report contains 38 findings and additional improvement suggestions. No fixes were applied. Existing source files were compared against a SHA-256 snapshot of 239 tracked and nonignored untracked files; their contents remained unchanged. Tests, reproductions, dependency inspection, and the browser preview used temporary review directories. The only new repository deliverable is this report.

## Scope and evidence

Reviewed the shared API, configuration, security checks, database operations, queue/ComfyUI integration, generation and media utilities, agent invocation, both production engines, Production Room, Studio, H3 still, Image lab, startup/maintenance scripts, dependencies, and test/CI coverage.

**Excluded:** the Video Vault page and its dedicated implementation, and the Frame review page and its dedicated implementation. Shared media functions used by Production remain in scope. Running the existing full unit suite does not constitute a review of the excluded pages.

Evidence labels used below:

- **Reproduced:** exercised against temporary databases/files using the actual application functions or API. GPU/provider calls were mocked where necessary.
- **Browser:** inspected the actual compiled React page using a temporary server with synthetic production data and mutation routes disabled.
- **Static:** traced through the relevant implementation; the described path was not exercised against a live production or GPU.
- **Audit:** dependency versions were checked against current advisory data, with relevant claims cross-checked against upstream advisories. Package advisories are distinguished from demonstrated exploits.

Priorities:

- **P1:** address before relying on the affected workflow or expanding network exposure; potential unauthorized control, invalid approval, broken production recovery, incorrect media, or unreliable backup.
- **P2:** address in the next hardening cycle; correctness, durability, resource use, accessibility, or reproducibility problems.
- **P3:** usability and maintenance improvements with lower immediate impact.

## Verification results

| Check | Result | What the result establishes |
| --- | --- | --- |
| TypeScript application check | Passed | `tsc -p tsconfig.app.json --noEmit --incremental false`; no repository build metadata was written. |
| Vite production bundle | Passed | Built to a temporary output directory. JavaScript approximately 444.55 kB / 127.29 kB gzip; CSS approximately 128.41 kB / 25.02 kB gzip. |
| Python unit discovery | **242 passed, 1 failed**, 243 total | Python 3.12 with pinned bridge requirements, isolated state, and read-only access to the configured external workflow/runtime fixtures. Approximately 100.6 seconds. The remaining assertion compares short and long spellings of the same Windows path; see R35. |
| Clean-path test attempts | Not portable as currently written | Several tests require external bot workflow recipes or an installed ComfyUI runtime. Supplying the configured fixtures resolved those additional failures; this is a coverage/reproducibility issue, not evidence that all those application features are broken. |
| Manifest validation | Passed | `scripts/validate-manifests.ps1`. |
| PowerShell parsing | Passed | Parsed the scripts without executing installation or maintenance actions. |
| Preflight | **Failed environment readiness** | Installed Node is 24.13.1 while the script requires 22; Tailscale is stopped. Windows/GPU/RAM/disk checks passed. The frontend nevertheless built with the installed Node version. |
| Doctor | **Not ready** | Bridge/ComfyUI listeners were absent; bind policy disagreed with the configured all-interface app host; runtime/node pins and some optional extension/model checks failed; Tailscale was stopped. |
| Repository scan, including untracked files | **Failed** | Existing personal Windows paths and a fixed tailnet hostname were found; see R37. No matched private details are copied into this report. |
| npm audit | **2 high-severity dependency records** | Direct Vite and transitive nanoid. Multiple Vite advisories attach to its dependency record; see R03 and the advisory inventory. |
| Python dependency audit | **3 packages affected** | Resolved requirements selected `python-multipart 0.0.20`, `Pillow 12.2.0`, and `Starlette 0.49.3`. The tool returned 47 records representing 24 distinct advisory IDs, including duplicate records for the same advisory. |
| Production Room browser inspection | Completed with fixtures | Inspected desktop 1280x720 and phone 390x844 layouts, shot-plan dialog, intake, and Council configuration. No horizontal overflow or console errors were observed in those states. Keyboard/accessibility issues were found. |

The equivalent frontend build steps were used instead of writing the normal `dist` and TypeScript cache files. Neither the live bridge nor ComfyUI was started. No real production was created, modified, approved, retried, or deleted; no paid provider or GPU generation was requested. Real provider capability, GPU execution, media quality, and end-to-end song synchronization therefore remain unverified.

## Findings

### R01 — P1 — All-interface binding exposes control without application authentication

**Evidence:** Reproduced and static. **Locations:** `backend/config.py:64-77`, `backend/main.py:393-394`, `backend/main.py:633-637`, `backend/security.py:14-18`, `scripts/common.ps1:50-51`, `scripts/doctor.ps1:19-22`.

The bridge accepts `app.host = 0.0.0.0`, discovers local addresses for the Host allowlist, and permits this through the launcher. However, the session endpoint issues a token to any caller and accepts an existing caller-supplied token. Mutation authorization only compares a cookie with the CSRF header. Reads have no session requirement. In an isolated API check, production listing returned HTTP 200 without a session, and an archive mutation returned HTTP 200 using a client-chosen cookie/header pair.

This proves the API has no application identity check. CSRF and Host validation do not identify a trusted device. With a reachable LAN listener, another network client can use the same controls as the owner. Reachability still depends on firewall and network configuration; the live service was not running during review. Doctor and the documented setup policy continue to require loopback, so the security policy is also inconsistent between components.

**Suggested change:** keep loopback as the default and use the intended tailnet boundary. If LAN access is supported, make it an explicit mode with device pairing or authenticated sessions, protect sensitive reads as well as writes, enforce appropriate Origin checks, and make Python, launchers, documentation, and Doctor agree on the policy.

**Verification to add:** unauthenticated network clients cannot list private production data or invoke control routes, even when they choose matching cookie/header values. Pairing/session revocation and allowed-host behavior should have separate tests.

### R02 — P1 — Backend dependency pins include relevant published vulnerabilities

**Evidence:** Audit, static, and a benign image-format reproduction. **Locations:** `requirements.txt:1-7`, `backend/main.py:2452-2472`, `backend/main.py:1565-1573`, `backend/main.py:3334`.

Three packages in the resolved bridge environment have published advisories:

| Package | Observed version | Application relevance and suggested action |
| --- | --- | --- |
| Starlette | 0.49.3 | The Windows application serves `/assets` through `StaticFiles`. Upstream describes outbound SMB/NTLM exposure when UNC paths reach its resolver, fixed in 1.1.0. Upgrade FastAPI/Starlette as a compatible set and assess the other Starlette advisories listed below. |
| python-multipart | 0.0.20 | FastAPI upload routes parse multipart bodies before their handler-level upload checks run. Published parser-header and preamble/epilogue DoS issues are relevant to that parsing path. Upgrade to a supported release covering the applicable fixes; the audit's complete fix set reaches 0.0.31. |
| Pillow | 12.2.0 | Uploaded images are opened from disk without restricting Pillow's format handlers, then can be decoded for thumbnails. The McIdas mmap advisory describes this usage pattern and is fixed in 12.3.0. Update Pillow and restrict accepted formats before decoding. |

These applicability judgments are based on the upstream [Starlette Windows StaticFiles advisory](https://github.com/Kludex/starlette/security/advisories/GHSA-wqp7-x3pw-xc5r), [multipart header-parsing advisory](https://github.com/Kludex/python-multipart/security/advisories/GHSA-pp6c-gr5w-3c5g), and [Pillow McIdas advisory](https://github.com/python-pillow/Pillow/security/advisories/GHSA-62p4-gmf7-7g93). No malicious media, UNC connection, credential disclosure, or parser exhaustion was attempted.

The upload MIME allowlist is insufficient: a harmless GIF uploaded as `image/png` passed `save_image()` and was stored with a `.png` suffix. This confirms that the allowlist does not constrain the actual decoder. It does not itself demonstrate the Pillow exploit.

**Suggested change:** update the backend dependency set together, regenerate/record the resolved dependency set, use `Image.open(..., formats=[...])` plus explicit format and pixel-budget checks, and apply request limits before multipart parsing. FastAPI 0.121.1 currently requires `Starlette >=0.40.0,<0.50.0`, so forcing a patched Starlette major underneath that pin is not a valid coordinated upgrade. Some audited issues concern unused APIs or configurations; do not describe every advisory as a reachable application exploit.

**Verification to add:** installation compatibility, regular uploads, rejected MIME/format mismatches, bounded oversized/malformed forms, and safe static-path handling on Windows.

### R03 — P1 when exposed — Vite is vulnerable; the lockfile also contains vulnerable nanoid

**Evidence:** Audit and static. **Locations:** `package.json`, `package-lock.json`, `vite.config.ts`, tailnet/development-server configuration.

Vite 6.3.5 is affected by multiple file-access advisories, including Windows `server.fs.deny` bypass and WebSocket arbitrary file reads. The upstream fixes for those cited issues are 6.4.3 and 6.4.2 respectively. The local Serve configuration includes a development-server target on port 5173, making review of development-server exposure material. The installed server was not running, and an exploit was not attempted. See the upstream [Windows bypass advisory](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff) and [WebSocket file-read advisory](https://github.com/vitejs/vite/security/advisories/GHSA-p9ff-h696-f583).

The transitive nanoid version is below the audit's patched target of 3.3.18. Its advisory concerns custom generators with size zero. No application call accepting attacker-controlled nanoid sizes was identified, so this is a dependency maintenance finding with narrower demonstrated relevance. The maintainer's [zero-size generator fix](https://github.com/ai/nanoid/commit/f9d13f150847d117877adee3460a46eceb0cf49b) adds the relevant early return.

**Suggested change:** update Vite to a supported patched version and refresh the affected transitive dependency. Review whether the development server needs remote access at all; serve the built UI for normal use. Preserve required development Host/Origin restrictions.

**Verification to add:** build/preview checks after upgrading and an audit gate with documented treatment of unreachable toolchain advisories.

### R04 — P1 — Approval is not atomic and can approve the wrong checkpoint

**Evidence:** Reproduced. **Locations:** `backend/main.py:2319-2357`, especially lines 2331, 2334, 2340-2344, and 2347.

Two distinct approval failures were confirmed:

1. A pending Council shot decision with no preserved waiting task returned HTTP 409, but the decision had already been saved as `approved`. The user cannot retry the same pending decision because it has been consumed.
2. A production at `user_review` with an old pending `prompt_review` decision became `completed` when that old decision was approved, despite having no final-video artifact. The route chooses the transition from the production's current stage instead of requiring the decision to describe that checkpoint.

**Suggested change:** validate the checkpoint, decision stage, task/attempt/configuration revision, and required artifact first. Resolve the decision and apply its transition in one transaction, with a conditional update preventing duplicate resolution. Final approval must refer to the current validated final artifact, not merely to the string `user_review`.

**Verification to add:** failed approval leaves a decision pending; stale decisions cannot advance a new stage; missing final media cannot complete a production; repeated requests are safely idempotent.

### R05 — P1 — Council pause/stop can leave an unresumable production

**Evidence:** Reproduced with the actual controller loop and a controlled temporary task. **Locations:** `backend/main.py:2048-2054`, `backend/main.py:2064-2065`, `backend/main.py:2081-2090`, `backend/council/controller.py:141-170`, `backend/council/controller.py:199-208`, `backend/council/controller.py:2361-2363`.

The routes save `pausing` or `stopping`, then cancel the Council owner. Cancellation bypasses the loop's normal transition to `paused` or `stopped`; its `finally` block only gathers child tasks. Reproductions ended with the owner finished and removed, the persisted status still `pausing`/`stopping`, the production absent from the runnable query, and Resume returning HTTP 409. The legacy watchdog does not reconcile Council rows.

There is also a policy discrepancy: Council `cancel()` always cancels its current video job. The stop route's `cancel_generation` option is only applied separately for legacy productions, and the same Council cancel method is used by Pause. The Council behavior therefore does not follow the requested preserve-versus-cancel policy consistently.

**Suggested change:** distinguish graceful pause/stop from explicit generation cancellation. Persist a recoverable terminal control state after cancellation, reconcile child-task leases and checkpoint state, and add a Council watchdog for unowned active/control states.

**Verification to add:** pause/stop during provider work and during ComfyUI work, with both generation policies, followed by successful resume without restarting the bridge or duplicating work.

### R06 — P1 — Manual Council retry does not reset the Council task graph

**Evidence:** Reproduced. **Locations:** `backend/main.py:1697-1725`; compare `backend/council/controller.py` shot-task reset helpers.

The shared retry route resets a shot row and queues the production at `shot_generation`, but notifies the legacy orchestrator and leaves Council generation/review tasks completed. In the reproduction, HTTP 200 was returned, the video task remained `completed`, legacy notification occurred, and Council notification did not. Council's polling alone cannot make a completed generation task rerun.

**Suggested change:** route retries through an engine-specific command that resets affected scene/prompt/generation/review/acceptance tasks, invalidates assembly and final review, and wakes the correct controller. Preserve prior attempts as historical artifacts.

**Verification to add:** a completed Council shot produces a new attempt after manual retry, and dependent outputs/final approvals are rebuilt from that attempt.

### R07 — P1 — Editing an accepted shot leaves dependent work and the production stage stale

**Evidence:** Reproduced. **Locations:** `backend/main.py:1608-1694`, especially lines 1690-1693; retry invalidation at lines 1718-1721.

Editing an accepted upstream shot only clears that shot's acceptance. A two-shot sequential reproduction left the second shot accepted and the production at `assembly`, while the first shot was now planned. Resuming at assembly then has no accepted clip for the edited shot. Other stale outputs and pending final approvals are not invalidated by this route. Council task/deliverable state is also not reconciled here.

The retry route has the opposite scope problem: it resets every later sequential shot, including those after an intervening hard cut, rather than following the actual dependency chain.

**Suggested change:** invalidate from the edited shot through its continuity/dependency segment, stop at a genuine independence boundary, invalidate final outputs/decisions, and move the production to the correct resumable generation stage. Apply the same dependency logic to edit, retry, intervention, and configuration changes.

**Verification to add:** edits before assembly/final review, mixed sequential/hard-cut sequences, and equivalent operations in both engines.

### R08 — P1 — Duplicate loses the production engine and reusable policy

**Evidence:** Reproduced. **Locations:** `backend/main.py:1765-1816`, `backend/production_db.py:492-500`, `backend/production.py:229-232`.

Duplication omits `pipeline`, `generation_audio_mode`, Council configuration, and shot editorial/trim fields. A Council copy returned HTTP 200 with pipeline `music_video_v1`, audio mode `auto` instead of `silent`, and missing/zeroed editorial timing. That default pipeline is different from the defined legacy pipeline `legacy_music_video_v1`. The legacy scheduler accepts non-Council rows, but its recovery filter requires the actual legacy constant, creating an additional recovery inconsistency.

**Suggested change:** define an explicit reusable-production clone contract. Preserve the engine, validated Council seats/settings, audio policy, reference mapping, and editorial timing while deliberately starting new attempts/results. Replace the historical default pipeline string with the shared constant and migrate affected rows deliberately.

**Verification to add:** clone round trips for both engines and all reusable fields, including recovery of the copied production.

### R09 — P1 — Council sequential mode does not hand off the previous accepted video's frame

**Evidence:** Static. **Locations:** `backend/council/controller.py:523-587`, `backend/council/controller.py:940-1028`, `backend/council/controller.py:1035-1087`.

All scene frames are rendered behind a batch barrier before any video generation. Sequential scene design depends on the previous scene render, not the previous video's acceptance. Opening-frame generation uses assigned reference images; it does not extract the preceding accepted video's editorial end frame. The `extract_last_frame` import is not used in this execution path.

Consequently, selecting sequential continuity cannot provide the promised continuation of actual motion/camera state. Ordered preparation of still images is insufficient to establish a continuous take.

**Suggested change:** retain early preparation of character/location references, but make each sequential shot's executable opening frame depend on the preceding accepted clip and its exact kept out-frame. Batch independent hard-cut shots separately, without introducing a graph cycle. Until implemented, make the supported continuity behavior explicit in the UI.

**Verification to add:** dependency-graph assertions plus a short real two-shot acceptance test showing that shot B's opening input comes from shot A's accepted editorial endpoint.

### R10 — P1 — The extracted continuity frame is earlier than the final frame

**Evidence:** Reproduced with a synthetic lossless 24 fps clip. **Location:** `backend/media.py:25-39`; consumers include legacy sequential generation and generated last-frame extraction.

The command seeks to 0.20 seconds before EOF and saves the first decoded frame. It does not select the final displayed frame. A 24-frame test clip with distinct red values per frame returned pixel `(200,0,0)` while the actual final frame was `(230,0,0)`. This can rewind action at a continuity handoff.

**Suggested change:** locate and decode the final displayed frame, or the exact editorial out-frame when trims are present, using frame/timestamp information. Avoid replacing one fixed EOF offset with another.

**Verification to add:** uniquely numbered/color-coded frames, short clips, variable frame rate, and editorial trims; compare the extracted frame to the expected decoded endpoint.

### R11 — P1 — Legacy production discards editorial overlap and trim timing

**Evidence:** Reproduced normalization loss and static assembly tracing. **Locations:** `backend/production.py:1442-1610`, `backend/production.py:3445-3467`, `backend/media.py:189-203`, `backend/media.py:206-218`.

Legacy normalization discards `editorial_start`, `editorial_end`, `trim_in`, and `trim_out`. Assembly concatenates full clips without passing the segment data supported by `assemble_clips()`; the single-clip path copies the entire clip. A supplied overlap/trim plan therefore does not survive into the edit. This can offset later vocal phrases or repeat overlap footage. `attach_song()` uses `-shortest`, which can also hide a short assembly by truncating the original song.

**Suggested change:** persist one frame-based editorial manifest for both engines and always assemble the exact kept ranges, including a single shot. Validate song coverage and the final duration against the approved edit rather than relying on `-shortest` to reconcile mismatches.

**Verification to add:** overlapping generation windows, fractional editorial timing, single-shot trims, and a final master whose kept frame count matches the approved song timeline.

### R12 — P2 — Council lip-sync ignores the selected uploaded audio reference

**Evidence:** Reproduced with audio preparation mocked to capture its source. **Locations:** `backend/main.py:1653-1666`, `backend/council/controller.py:1063-1068`.

The API accepts and validates `audio_source = reference` and `audio_reference_id`. Council's queue builder nevertheless always prepares audio from `production['song_path']`. The captured preparation source was the song even when a reference was selected. A shot can therefore synchronize against the wrong audio.

**Suggested change:** use a shared source resolver that validates the selected production-owned audio reference and timing. If Council does not support this source yet, reject it explicitly and disable the corresponding UI option rather than silently substituting the song.

**Verification to add:** distinct song/reference fixtures and an assertion on the exact audio segment passed into the queued lip-sync workflow.

### R13 — P2 — Legacy does not enforce the production-wide generation audio policy

**Evidence:** Reproduced. **Locations:** `backend/production.py:1570-1571`; compare `backend/council/controller.py:478-486` and `backend/main.py:1902-1903`.

Legacy derives each shot's audio mode from the agent row and ignores the project's `generation_audio_mode`. A project configured as `silent` retained a supplied lip-sync shot in the reproduction. Council applies the project policy, so identical settings behave differently by engine.

**Suggested change:** establish the precedence of project policy, shot overrides, and automatic selection in a shared normalization function. Enforce that policy again at queue submission and expose it in the Production form/settings.

**Verification to add:** `auto`, `silent`, and forced `lip_sync` across both engines, including incompatible input modes.

### R14 — P2 — Shot editing accepts invalid duration values

**Evidence:** Reproduced. **Locations:** `backend/main.py:493-509`, `backend/main.py:1623-1689`, `backend/production_db.py:243`.

The edit body accepts a plain float, the route does not validate duration, and the shot table has no duration constraint. A PATCH with duration `-5` returned HTTP 200 and persisted `-5.0`. Generation settings validation covers other fields but receives no duration. Later queueing can fail after planning/frame work has already been performed.

**Suggested change:** use shared finite, range, and frame-precision validation appropriate to the selected workflow. Validate duration together with audio timing and editorial trims. Reject inconsistent state before writing a shot, with a database constraint where practical.

**Verification to add:** negative/zero/excessive/nonfinite durations and trims/audio spans that do not fit the generation window.

### R15 — P2 — Production song intake accepts empty or invalid audio

**Evidence:** Reproduced for an empty file and static. **Locations:** `backend/main.py:1917-1929`, `backend/main.py:1991-2012`; compare reference-audio validation at lines 2493-2502.

Song intake checks the supplied MIME type and maximum bytes, but does not require nonempty content, probe an audio stream, or establish duration before creating the production. An empty `.wav` submitted with `audio/wav` returned HTTP 200 and created a production. Failure is deferred to later analysis or media work.

**Suggested change:** save to a temporary intake location, validate actual format/stream/duration with the existing audio probing infrastructure, establish a supported duration limit, and record verified metadata before committing the production.

**Verification to add:** empty files, wrong bytes with an allowed MIME type, video-only WebM, malformed duration, and valid audio in each supported container.

### R16 — P2 — Failed reference intake removes files but leaves the production row

**Evidence:** Reproduced. **Locations:** `backend/main.py:1996-2020`.

The production is inserted before references are processed. If a reference fails, the exception handler removes the production folder but does not roll back/delete the production row and related records. Submitting a disallowed reference returned HTTP 400 while leaving one production whose song path no longer existed.

**Suggested change:** validate/stage all intake media before publishing the production, then commit its database state atomically. On failure, remove both staged files and created database records, including copied ComfyUI inputs. Apply equivalent cleanup to partial duplication failures.

**Verification to add:** failure on the first and a later reference, Council-config persistence failure, and disk/database errors; no dangling production or copied input should remain.

### R17 — P2 — Deleting a regular job can remove media still used by Production

**Evidence:** Static. **Locations:** `backend/main.py:3065-3099`, `backend/production_db.py:263-270`, `backend/production.py:3379-3384`.

Job deletion protects active sequence assemblies and shared job input paths, but does not check production attempts/tasks/artifacts that reference the job or its output. Production attempts retain `job_id` and output paths; accepted/generated video can live in ComfyUI output. Deleting that job can remove the clip still needed for production playback, review, continuity, or assembly.

**Suggested change:** resolve all asset consumers before deletion. Either refuse with a clear list of dependent productions or preserve an immutable production-owned copy and update consumer records. Use one consumer-aware deletion policy for jobs, sequences, references, and generated artifacts.

**Verification to add:** an accepted production attempt, an imported job, and a pending assembly retain their required media when the history entry is removed.

### R18 — P2 — Production export is not a consistent, portable snapshot

**Evidence:** Static. **Locations:** `backend/main.py:1825-1839`, `backend/production.py:3379-3384`.

Export overwrites one shared ZIP and manifest within the production directory while recursively reading that directory. There is no snapshot boundary with active production work. Repeated downloads can overlap an earlier response streaming the same file, and production changes can occur between manifest creation and file inclusion. The archive only includes files beneath the production folder, so job clips/imported media stored in external ComfyUI output are not automatically included. URLs in the manifest do not make those assets portable.

**Suggested change:** build each export into a unique temporary artifact from a consistent database/asset revision. Include every referenced asset needed for the intended export contract, with relative paths and checksums, and publish only after validation. Clearly distinguish a portable production package from a diagnostic folder archive.

**Verification to add:** two downloads in quick succession, export during a changing production, and inspection on a machine without the original ComfyUI paths/server.

### R19 — P2 — Blocking media and filesystem work runs on the event loop

**Evidence:** Static. **Locations:** `backend/main.py:1826-1838`, `backend/main.py:2452-2472`, `backend/main.py:2475-2497`, `backend/main.py:2567-2585`, `backend/main.py:2589-2660`, `backend/council/controller.py:1035-1067`.

Several async paths execute synchronous image operations, large file writes, ZIP compression, or `subprocess.run()` directly. Reference video processing includes probes and FFmpeg calls with 60/120-second timeouts. Council queue preparation synchronously trims audio before submission. During these operations, the same process can delay health responses, production controls, SSE delivery, and other requests.

**Suggested change:** move bounded CPU/subprocess/file operations to worker threads or background jobs, stream uploads to disk under explicit quotas, and return job IDs for long work. Keep queue ownership and database transitions outside lengthy transactions.

**Verification to add:** concurrent health/SSE/control latency while uploading/validating media, preparing audio, and exporting a large project. Measure latency rather than only checking the final HTTP response.

### R20 — P2 — Council bypasses configured production concurrency limits

**Evidence:** Static. **Locations:** `backend/council/controller.py:173-180`, `backend/council/controller.py:1397-1408`; compare `backend/production.py:236`.

The Council loop starts an owner for every runnable Council production. Its resource occupancy checks are scoped to one production, while legacy uses `PRODUCTION_CONCURRENCY`. Multiple Council productions can therefore initiate provider/FFmpeg work beyond the configured production limit, and the two engines do not share admission control. The video queue's serialization does not bound provider calls or other CPU work.

**Suggested change:** use shared production admission limits plus provider/seat, CPU, and GPU resource budgets. Enforce limits globally across both engines and expose queued/waiting reasons in Production Room.

**Verification to add:** start more productions than the configured limit and assert bounded work across both engines, including cancellation releasing capacity.

### R21 — P2 — H3 still's single-active-run guard has a submission race

**Evidence:** Reproduced with concurrent submissions and a delayed mocked ComfyUI response. **Locations:** `backend/h3_still.py:481-482`, `backend/h3_still.py:502-524`.

The active-run check happens before awaiting the submission lock, and the run is registered after releasing that lock. Two requests can both pass the check before the first submission completes. The reproduction accepted two requests and submitted two prompts despite the single-active-run contract.

**Suggested change:** reserve/check ownership inside the lock and retain the reservation through submission/registration, releasing it on failure. Coordinate H3 still and video admission through the same resource policy where they use the same ComfyUI instance.

**Verification to add:** simultaneous requests accept exactly one run; rejected/failed submission releases the reservation without allowing duplicate prompts.

### R22 — P2 — H3 still metadata is lost on bridge restart

**Evidence:** Static. **Locations:** `backend/h3_still.py` module-level `_runs`/`_watchers`, lines 523-529; `src/main.tsx:308`, `src/main.tsx:340-347`.

H3 still runs exist only in memory. The browser stores a run ID in local storage, but the backend cannot reconstruct that run after a restart; lookup returns nothing and the browser removes the saved ID. A generated file or in-flight ComfyUI prompt can outlive the metadata needed to show, reconcile, or delete it. The separate Image lab already has a persisted run-record approach.

**Suggested change:** persist still-run ownership, prompt IDs, status, settings, and output identity. On restart, reconcile only owned prompts/artifacts and restore completed runs safely. Bound retained history and garbage-collect obsolete metadata.

**Verification to add:** restart during submission, during generation, and after completion, with the same browser run ID resolving appropriately afterward.

### R23 — P2 — Analysis/review agents receive an overly broad execution profile

**Evidence:** Static. **Locations:** `backend/agents.py:752-758`, `backend/agents.py:981-994`; compare the orchestration's structured-response design in `backend/production.py`.

AGY invocation uses `accept-edits` and skips interactive permission checks, including for roles intended to analyze/review media. Every subprocess inherits the full bridge environment. A working directory and `--add-dir` do not establish an OS-level filesystem boundary in this implementation. Therefore, a requirement to return structured data does not itself enforce read-only behavior or prevent unrelated environment credentials from being available to child tools. No unexpected agent modification was observed; no live agent was invoked.

**Suggested change:** separate read-only analysis/review from controlled artifact-writing profiles, permit only the required project directories/tools, and pass a minimal environment with explicit necessary credentials. Preserve authorized image generation and media inspection without relying solely on prompt instructions for confinement.

**Verification to add:** inspect the actual runtime's capability enforcement; review roles cannot write outside approved scratch/artifact locations or inherit unrelated credentials, while required media analysis remains functional.

### R24 — P2 — Agent pipe handling can fail on large events or hang before its timeout

**Evidence:** Static plus a controlled default-reader reproduction. **Locations:** `backend/agents.py:753-764`, `backend/agents.py:773-780`, `backend/agents.py:813-837`, `backend/agents.py:839-843`.

The process streams use the default asyncio reader limit and `readline()`. A 70,000-byte newline-delimited event exceeded that limit in a reproduction. Completed reader exceptions are gathered with `return_exceptions=True` and discarded, so a valid large structured result can become truncated/missing output, or the child can stall if its pipe is no longer drained. Collected stdout/stderr lists also have no aggregate budget.

Prompt writing/draining happens before stdout/stderr readers start and before the process-wait timeout is installed. A provider that emits output before consuming a large stdin prompt can deadlock during this phase, outside the intended timeout.

**Suggested change:** start stream consumption immediately, apply one overall lifecycle deadline including stdin delivery, explicitly handle reader failures, and use bounded chunk/event parsing or a documented larger event limit with a total-output quota. Keep only a bounded diagnostic tail or spool logs to disk.

**Verification to add:** large valid JSON events, a child that writes before reading stdin, output flooding, and cancellation in each lifecycle phase without orphaned processes/readers.

### R25 — P2 — ComfyUI shutdown can kill an unrelated configured-port owner

**Evidence:** Static. **Locations:** `backend/comfy.py:530-566`, `backend/comfy.py:98`, `scripts/start.ps1:14`.

If no tracked process or command-line-matched ComfyUI process is available, shutdown falls back to whichever PID owns the configured port and kills its process tree, including an elevation retry. Owning that port does not prove the process is the configured ComfyUI instance. Startup similarly treats an existing listener as sufficient to report the bridge already running. A port collision can therefore attach to the wrong service or terminate unrelated work.

**Suggested change:** verify process executable, command line/runtime root, start identity, and service health signature before reusing or terminating a listener. When identity cannot be established, return a clear collision/ownership error rather than treating the PID as trusted solely because of its port.

**Verification to add:** a foreign listener is neither reported as the bridge nor killed; the known owned/recovered ComfyUI process still stops correctly.

### R26 — P1 — Update/rollback copies do not guarantee a valid SQLite backup

**Evidence:** Static. **Locations:** `backend/db.py:16-20`, `scripts/update.ps1:5-14`, `scripts/rollback.ps1:11-13`.

SQLite connections use WAL mode, but maintenance scripts copy only `jobs.sqlite3` while the bridge may still write. An idle ComfyUI queue does not imply idle production planning, agent traces, settings, or database transactions. A failed queue probe is also treated as a reason to proceed. Committed state may remain in the WAL or a copy may overlap changes, so the advertised backup is not a guaranteed consistent recovery point. SQLite documents that committed changes can reside in the WAL and provides an online backup mechanism. See [SQLite WAL documentation](https://www.sqlite.org/wal.html) and [SQLite Backup API](https://www.sqlite.org/backup.html).

**Suggested change:** use SQLite's backup API for a consistent database snapshot, or fully quiesce all writers and perform a verified checkpoint/close before a filesystem copy. Include the intended production assets/configuration in the recovery contract and verify the backup before changing versions. Fail closed when readiness cannot be established.

**Verification to add:** concurrent committed writes during backup, restored integrity/foreign-key checks, and a recovery drill preserving the latest production checkpoint.

### R27 — P2 — Update/rollback does not deploy a coherent running version

**Evidence:** Static. **Locations:** `scripts/update.ps1:15-22`, `scripts/rollback.ps1:14-17`.

Update changes Git and frontend dependencies/build but does not synchronize Python requirements, restart/reconcile the running bridge, or run a post-update health/preflight check. Rollback changes the checkout without rebuilding the ignored frontend output or synchronizing dependencies. The running Python process can remain on old imported code, and the UI can remain built from a different revision. Both npm commands also depend on the caller's current directory rather than explicitly using the repository root.

**Suggested change:** implement a controlled version transition: verified backup, quiesce, install dependencies for the target revision in the correct working directory, build to staging, account for schema compatibility, publish/restart, and run health checks. Keep a tested recovery path that restores a compatible database/runtime/UI set, not just a Git checkout.

**Verification to add:** invoke maintenance from outside the repo, update across a requirements change, roll back after a UI change, and confirm the reported running revision agrees across API/UI/dependency metadata.

### R28 — P2 — Late mutation responses can replace the selected production

**Evidence:** Static. **Locations:** `src/production.tsx:943-995`, `src/production.tsx:1070`, `src/production.tsx:1144-1158`, `src/production.tsx:1187`, `src/production.tsx:1289`.

Detail loading has request/abort guards, but mutation handlers apply `setProduction(updated)` without checking the currently selected ID. The production picker remains usable during a pending mutation. Start an operation on A, select B while it is pending, and A's response can replace the displayed production beneath B's selected dropdown value. Subsequent decisions/actions can target a production the user did not expect.

**Suggested change:** associate every mutation with its production ID/revision and only apply its response to that cache entry. Update the visible view only if the selection still matches. Reset or associate per-production editors/previews and feedback with the same identity.

**Verification to add:** delayed controls, shot saves, reference generation, and settings updates while switching A to B; B must remain displayed and subsequent actions must target B.

### R29 — P2 — Production mutations have no bounded request lifecycle

**Evidence:** Static. **Locations:** `src/production.tsx:807-810`, reference/control mutation callers; compare timeout handling in `src/main.tsx`.

Production's shared mutation helper has no AbortController, request deadline, or operation-specific recovery. Long reference/provider work or an interrupted connection can keep the page busy without a reliable result. Cancelling a browser request alone would also leave uncertainty about whether the server operation completed.

**Suggested change:** use a shared typed API client with bounded request deadlines and clear error handling. For long work, acknowledge a durable operation ID and track progress through SSE/polling. Provide an explicit reattach/status path and use idempotency keys for safely retried creation/control operations.

**Verification to add:** stalled and disconnected requests, a response lost after server success, navigation away from pending work, and recovery without duplicated productions/generations.

### R30 — P2 — Production intake/settings diverge from backend capabilities

**Evidence:** Static and browser. **Locations:** `src/production.tsx:904-936`, `src/production.tsx:1171-1181`; compare `backend/main.py:1892-1903`, `backend/main.py:1963-1967`.

Three contract mismatches were found:

- The UI always requires lyrics, while Council deliberately permits empty lyrics for audio-led analysis. Valid Council intake is blocked by the frontend.
- Creation and settings hardcode the producer runtime as `codex`, although saved defaults and the backend support the producer seat using AGY. A model selected from AGY defaults can be sent with the wrong runtime or the intended runtime can be silently replaced.
- The backend supports `generation_audio_mode`, but the new-production/settings payloads do not provide that choice. Users cannot express the same audio policy available to API callers.

**Suggested change:** derive requirements and request fields from the selected engine/runtime, use the actual selected producer runtime, and expose supported audio policy with consistent backend validation. Prefer shared/generated request types and contract tests to duplicated field rules.

**Verification to add:** Council without pasted lyrics, legacy with an AGY producer and AGY model, and all supported project audio policies round-tripping through UI creation/settings.

### R31 — P2 — Catalog refresh can overwrite user draft choices

**Evidence:** Static. **Locations:** `src/production.tsx:615-617`, `src/production.tsx:764-766`.

An intentionally empty selected-skills array is interpreted as uninitialized, so the next catalog load repopulates every enabled valid skill. Settings refresh also resets the runtime/model/effort draft whenever a new settings object arrives. A user can lose deliberate choices while still composing a new production.

**Suggested change:** track whether drafts have been initialized and whether they are dirty. Initialize defaults once per new draft, preserve an explicit empty selection, and reconcile removed models/skills without overwriting valid unsaved input. Show deliberate reset-to-default controls.

**Verification to add:** deselect all skills or edit agent choices, refresh catalogs/defaults, and verify the draft remains intact.

### R32 — P2 — Production dialogs and controls need keyboard/accessibility fixes

**Evidence:** Browser and static. **Locations:** `src/production.tsx:418`, `src/production.tsx:1289`, `src/production.tsx:1403`, `src/production.tsx:1410`; `src/app-modal.tsx`.

Opening the shot-plan dialog left focus on the button behind it; the focused element was not within the dialog. Escape did not close that dialog. There is no focus trap/background inert handling in this overlay implementation. The intervention send icon has no accessible name, and the production picker and recipient selector are unlabeled. The shared confirmation modal also lacks a dialog title association and complete focus management, although it does implement Escape handling.

**Suggested change:** use one accessible dialog primitive with initial focus, focus containment, inert background, Escape dismissal where appropriate, and focus restoration. Associate dialog headings, label selects, and give icon-only actions descriptive names.

**Verification to add:** keyboard-only opening/editing/closing, focus restoration, named controls in the accessibility tree, and screen-reader checks for the main Production workflows.

### R33 — P3 — Live conversation updates can pull the reader away from older messages

**Evidence:** Static. **Location:** `src/production.tsx:793-805`.

Except for the special older-page restoration path, a message-count change always scrolls to the bottom. A user reading prior conversation can lose their position when a new message arrives. This is especially disruptive when reviewing long agent decisions during an active production.

**Suggested change:** auto-follow only when the reader is already near the bottom or has explicitly enabled following. Otherwise preserve position and show a new-message indicator. Keep the existing older-page restoration behavior.

**Verification to add:** scroll up, append live messages, load older pages, and switch productions without unexpected jumps.

### R34 — P3 — Studio contains corrupted Hebrew text

**Evidence:** Static. **Location:** `src/main.tsx:1915`.

The Megapixels help text begins with visibly corrupted Hebrew characters. This appears to be a source encoding/text corruption issue, rather than a browser font issue.

**Suggested change:** restore the intended UTF-8 text and move repeated translated strings to a small reviewed message catalog. Keep directionality explicit for mixed Hebrew/numeric fields.

**Verification to add:** inspect the corrected hint in the rendered page and include a lightweight encoding/text review in localization changes.

### R35 — P2 — The unit suite depends on private machine fixtures and path spelling

**Evidence:** Test runs and static. **Locations:** `tests/test_bot_images.py:13`, `tests/test_bot_images.py:30`, `tests/test_bot_images.py:99`, `backend/config.py:47-50`, `tests/test_portability.py:198`, ComfyUI readiness tests.

Bot-image tests expect at least 32 workflows and specific external recipe files, while the repository's optional external workflow directory is not populated by the checkout. The feature's external workflow design is documented; requiring that private collection for ordinary unit tests is the defect. Some runtime/readiness tests also depend on actual local ComfyUI paths rather than fully isolated fixtures. Initial clean-path runs failed until the configured external/runtime fixtures were supplied read-only.

The final remaining failure compares the unnormalized temporary path with a `.resolve()` result. Windows expanded an 8.3 directory name to its long equivalent, so the string assertion failed even though it referred to the same file. This specific failure does not establish an application path bug.

**Suggested change:** provide small repository-owned workflow fixtures and mock hardware/runtime readiness consistently. Make external recipe/runtime integration tests opt-in. Compare normalized `Path` values or canonical expected references rather than raw path spelling.

**Verification to add:** ordinary discovery passes on a clean Windows/Python 3.12 checkout without a private bot workflow collection, ComfyUI installation, or specific TEMP naming behavior.

### R36 — P2 — CI does not cover the Production browser workflows or dependency audits

**Evidence:** Static. **Locations:** `.github/workflows/ci.yml`, `tests/ui_smoke.py:32`, `tests/ui_smoke.py:47-48`, `tests/ui_smoke.py:66`.

CI builds TypeScript/UI and runs Python discovery, but has no fixture-backed browser coverage or dependency audit step. The existing UI smoke script references removed/changed controls such as `.resolution-grid` and a duration button, and assumes a particular running application/data set. It is not a reliable automated check for the current Production page. Media tests can skip when FFmpeg/ffprobe are unavailable, and CI does not explicitly guarantee those tools for the media checks.

**Suggested change:** add a deterministic, isolated API/UI fixture server and browser checks for Production intake, selection races, control/retry/approval state, and dialogs. Install/verify media tooling in a dedicated media test lane. Add dependency scanning with triage criteria, and keep paid/GPU/provider acceptance tests separate from routine CI.

**Verification to add:** a clean CI run executes meaningful Production interactions and media tests, and the new scenarios described in R04-R14 fail before their fixes and pass afterward.

### R37 — P2 — Existing repository files fail the personal-data/portability scan

**Evidence:** Repository scan and static. **Locations:** `scripts/e2e_music_video.py:14`, `start-project.bat:68`, `diff.patch:424-425`.

The repository's own scan flagged personal Windows paths in the Python utility and tracked patch artifact, and a fixed tailnet hostname in the launcher. These files are tracked. Apart from unnecessary disclosure when shared, hardcoded paths/hostnames undermine the portable setup and the scan can fail CI. This report deliberately omits the private values; the finding is not a claim that a credential was exposed.

**Suggested change:** derive paths and the tailnet URL from validated configuration or command arguments, remove obsolete patch artifacts from the distributable source after preserving any needed work, and keep machine-specific details in ignored configuration. Re-run the existing scan before release.

**Verification to add:** a fresh checkout under a different user/path/tailnet works without edits and passes both tracked and untracked scans.

### R38 — P2 — Skill ZIP extraction has no total expanded-size budget

**Evidence:** Static. **Location:** `backend/skill_catalog.py:113-128`.

Installation permits up to 500 files and up to 20 MiB per file, then extracts the archive without a summed expanded-size limit. Those individual limits permit nearly 10 GiB of extracted content. A highly compressible package can consume substantial disk and extraction time while remaining a small upload. The existing path-containment checks are useful but do not bound this resource use.

**Suggested change:** validate total declared expanded bytes, compression ratios, available space, and a practical package budget before extraction; enforce an actual streaming extraction quota as well. Keep installation off the event loop and clean partial targets reliably.

**Verification to add:** a small compressed archive exceeding the total expanded budget is rejected before extraction, while a normal single-skill package and the existing traversal rejection continue to work.

## Additional improvement suggestions

These are engineering proposals, not claims that each item is a separately reproduced defect.

1. **Centralize production commands and transitions.** Give start/pause/resume/stop/edit/retry/approve a shared service interface with explicit engine dispatch. Keep stage/task/decision/artifact changes in transactional commands. This directly reduces the inconsistent behavior in R04-R08 and R12-R13.
2. **Represent artifact lineage explicitly.** Record which production/config revision, shot, attempt, frame, audio segment, and upstream artifact produced each result. Use that lineage for invalidation, exports, deletion, and approval instead of relying on mutable stage strings and file paths.
3. **Reduce the largest modules gradually.** `backend/main.py` is about 3,341 lines, `backend/production.py` 3,601, Council controller 3,251, `src/main.tsx` 2,230, and `src/production.tsx` 1,415. Extract API routers/services, pure timing/policy functions, reusable frontend API handling, and dialog/production components around stable boundaries. Avoid a wholesale rewrite before the state defects are fixed.
4. **Share typed contracts across API and UI.** Generate request/response types from OpenAPI where practical, use explicit production/task state unions, and validate versioned media/editorial contracts. Reduce runtime/model/audio-policy field duplication and ambiguous dictionary defaults.
5. **Separate page bundles and consolidate styles.** The current single UI bundle and approximately 128 kB stylesheet warrant measurement on a phone. Lazy-load page entry points and move repeated visual rules into reusable components/tokens. Treat this as a measured optimization, not a claimed current rendering failure.
6. **Make runtime diagnostics consistent and visible.** Reconcile the Node support policy, app bind policy, selected dependency/runtime versions, and optional extension readiness across preflight, Doctor, startup, and UI. Report the running revision and whether model/media capabilities were actually verified. Avoid declaring operational success from a bundle build alone.
7. **Add durable operation status and bounded logs.** Standardize operation IDs, stage/retry reasons, provider activity, progress, and failure classes. Retain bounded diagnostic logs with structured identifiers so the UI can distinguish waiting, slow work, interruption, and an abandoned owner without exposing unrelated environment data.
8. **Define retention and cleanup policy.** Account for copied reference inputs, generated scene frames, failed uploads, export ZIPs, provider request files, old attempts, and unused ComfyUI outputs. Garbage collection should follow recorded consumers and support a dry-run preview; it should not infer safety from filenames alone.
9. **Separate demo-specific helpers from reusable product APIs.** For example, `backend/main.py:3267` hardcodes one song project's final-video path. Formalize demonstration artifacts separately or resolve the selected production's final artifact through the same production API used elsewhere.
10. **Publish a practical acceptance matrix.** Cover both engines, interactive/autonomous operation, supported continuity modes, audio source/policy, Turbo profile, media tools, restart recovery, and approved final duration. Distinguish mocked unit checks from real provider/GPU/media acceptance evidence.

Useful foundations to retain include owned-prompt cancellation checks, output probing/full video decode validation, pinned runtime/model metadata, reference ownership checks, path-containment checks, production checkpoint records, bounded detail/message loading, and abort/request guards already present in frontend detail loading. Extend these patterns consistently rather than replacing them indiscriminately.

## Suggested implementation order

1. Address network identity/exposure, coordinate the dependency upgrades, and bound skill extraction: R01-R03 and R38.
2. Fix approval integrity and recoverable production controls: R04-R08.
3. Establish the shared editorial, continuity, and audio execution contract: R09-R14.
4. Fix intake, consumer-aware media ownership, export, and consistent maintenance recovery: R15-R18 and R25-R27.
5. Bound runtime work and improve durable operation tracking: R19-R24.
6. Resolve frontend contract/race/accessibility issues and make CI reproducible: R28-R37.

Add targeted regression checks alongside each fix. Real GPU/provider validation should then use a short approved fixture song and a small matrix of shots, including a sequential handoff and overlapping lip-sync windows. A long full-song run should follow evidence that these smaller transitions work correctly.

## Dependency advisory inventory

This inventory records the audit findings as of the review date. It is not a claim that all listed APIs are exercised by the application. Duplicated audit records have been collapsed by advisory ID. The relevance of the principal findings is discussed in R02-R03.

| Python package | Advisory | Subject |
| --- | --- | --- |
| python-multipart 0.0.20 | GHSA-wp53-j4wj-2cfg | Upload path traversal under specific nondefault upload-directory/filename configuration. That configuration was not identified here. |
| python-multipart 0.0.20 | GHSA-mj87-hwqh-73pj | Multipart preamble/epilogue parsing resource exhaustion. |
| python-multipart 0.0.20 | GHSA-pp6c-gr5w-3c5g | Unbounded multipart part-header parsing. |
| python-multipart 0.0.20 | GHSA-v9pg-7xvm-68hf | Negative Content-Length in direct `parse_form()` use; not automatically applicable to FastAPI's direct MultipartParser path. |
| python-multipart 0.0.20 | GHSA-5rvq-cxj2-64vf | URL-encoded field-separator parsing resource consumption. |
| python-multipart 0.0.20 | GHSA-6jv3-5f52-599m | Semicolon treated as a URL-encoded field separator. |
| Pillow 12.2.0 | GHSA-8v84-f9pq-wr9x | PCF font bitmap dimensions. |
| Pillow 12.2.0 | GHSA-45hq-cxwh-f6vc | BDF font dimensions. |
| Pillow 12.2.0 | GHSA-4x4j-2g7c-83w6 | WindowsViewer shell-command construction. No application Image.show/WindowsViewer use identified. |
| Pillow 12.2.0 | GHSA-phj9-mv4w-65pm | GD image dimensions. |
| Pillow 12.2.0 | GHSA-5x94-69rx-g8h2 | Font bitmap compilation dimensions. |
| Pillow 12.2.0 | GHSA-9hw9-ch79-4vh6 | ImageCms transform buffer handling. |
| Pillow 12.2.0 | GHSA-6r8x-57c9-28j4 | Image-coordinate native buffer handling. |
| Pillow 12.2.0 | GHSA-pg7v-jwj7-p798 | EPS binary-length handling. |
| Pillow 12.2.0 | GHSA-62p4-gmf7-7g93 | McIdas/mmap row stride, affecting path-based decode patterns. |
| Pillow 12.2.0 | GHSA-xj96-63gp-2gmr | Rank-filter native buffer handling. |
| Pillow 12.2.0 | GHSA-fj7v-r99m-22gq | TGA mode-1 encoder buffer read. |
| Pillow 12.2.0 | GHSA-jjj6-mw9f-p565 | PDF stream decompression budgeting. |
| Pillow 12.2.0 | GHSA-vjc4-5qp5-m44j | JPEG2000 tiled component-width accumulation. |
| Starlette 0.49.3 | GHSA-86qp-5c8j-p5mr | Host header and URL reconstruction. |
| Starlette 0.49.3 | GHSA-wqp7-x3pw-xc5r | Windows StaticFiles UNC/SMB exposure. |
| Starlette 0.49.3 | GHSA-x746-7m8f-x49c | HTTPEndpoint method/attribute dispatch. No application HTTPEndpoint subclass use identified. |
| Starlette 0.49.3 | GHSA-82w8-qh3p-5jfq | URL-encoded form limit enforcement. |
| Starlette 0.49.3 | GHSA-jp82-jpqv-5vv3 | Request-path URL reconstruction. |

| npm dependency | Advisory | Subject |
| --- | --- | --- |
| Vite 6.3.5 | GHSA-g4jq-h2w9-997c | Public-directory path-prefix handling. |
| Vite 6.3.5 | GHSA-jqfw-vq24-v9c3 | HTML filesystem access restrictions. |
| Vite 6.3.5 | GHSA-93m4-6634-74q7 | Windows backslash path handling. |
| Vite 6.3.5 | GHSA-4w7w-66w2-5vf9 | Sourcemap path traversal. |
| Vite 6.3.5 | GHSA-p9ff-h696-f583 | WebSocket arbitrary file reads. |
| Vite 6.3.5 | GHSA-v6wh-96g9-6wx3 | Windows UNC/NTLM exposure. |
| Vite 6.3.5 | GHSA-fx2h-pf6j-xcff | Windows `server.fs.deny` bypass. |
| nanoid, transitive, below 3.3.18 | GHSA-2v37-7h3g-55p8 | Zero-size custom-generator infinite loop. No matching application caller identified. |
