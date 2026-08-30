---
name: council-roles
description: Index for reusable specialist and supervisor skills used by a media-production council. Use when configuring, auditing, or extending role-scoped production work; pipeline sequencing remains the controller's responsibility.
---

# Council Roles

This package groups reusable media-production roles. The package itself is not an assignable production role. A production may use one solo seat or several seats. Assign one or more role entries from `manifest.json` to each seat and load only the corresponding active role `SKILL.md` for that seat's current task.

## Operating contract

- The controller owns state transitions, retries, dependencies, gates, and artifact paths.
- Role skills guide analysis or review; they do not advance the workflow.
- One seat may perform several roles across separate role-scoped turns. Record the active role on every deliverable and never represent a solo self-review as independent multi-agent consensus.
- Inputs arrive as versioned deliverables and artifact IDs selected by a tested context policy.
- Every role returns the canonical council envelope requested by the controller. Role-specific content belongs in `deliverable`.
- Media claims require evidence from files actually inspected by a seat with verified capability.
- User references are optional. When absent or partial, the assigned visual roles must design and jointly review the missing reference set before shot-scene frames are created.
- Prepare the complete planning-reference bundle and every shot-specific scene frame before releasing any video-generation task. Never alternate one reference and one video while later scene references are still pending.
- Editorial boundaries may be fractional, but every submitted generation duration must be a positive whole number of seconds.
- A delivered user intervention is a binding production constraint for the affected task versions; acknowledge it and revise the relevant deliverable instead of silently continuing the stale plan.
- The user remains the final authority.

## Specialist roles

| Role | Purpose |
|---|---|
| Audio Analyst | Decode audio, map structure, vocals, lyrics, energy, and edit points |
| Visual Director | Define treatment and reusable character/location/prop bibles |
| Storyboard Editor | Convert treatment and timing into an editorial shot plan |
| Scene Frame Designer | Compose actual opening and optional closing frames from approved anchors |
| Prompt Engineer | Write model-specific prompts for an already planned shot and its scene frames |
| Technical Director | Resolve integer generation windows, overlap/trim, MP, and validated job parameters |
| Technical QC | Inspect generated media for visible rendering/physics/text defects |
| A/V Sync Reviewer | Inspect source audio and generated video for lip-sync and timing quality |
| Continuity Editor | Review identity, action, camera, and spatial flow across shots |
| Post-Production Editor | Trim, assemble, mix audio according to policy, and validate the master |

## Supervisor roles

| Role | Purpose |
|---|---|
| Executive Producer | Review feasibility, cross-domain consistency, constraints, and escalation needs |
| Creative Director | Review narrative, emotion, style, and audience impact |

## Routing

The application reads `manifest.json` for role metadata. A role's `SKILL.md` is instructions for the assigned agent, not a replacement for the manifest, response schema, or context builder.

Do not infer capabilities from a role name or user checkbox. The controller must intersect role requirements with verified runtime/model/tool capabilities.
