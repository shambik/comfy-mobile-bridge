---
name: council-roles
description: Bundled role-skill package for the multi-agent production council. Contains specialist and supervisor role definitions that scope each agent seat's context, responsibilities, deliverables, and boundaries. Roles are pipeline-agnostic and work across music videos, short films, commercials, trailers, and any media production built on ComfyUI generation.
---

# Council Roles — Skill Package

This package contains the role skills that power the multi-agent
production council. Each role is assigned to an agent seat and controls
what the agent sees, does, and delivers.

## Package contents

### Specialist roles

Specialists do focused work. They receive only the data slice their
domain requires and produce structured deliverables. They do not
approve or reject the production — that is the supervisor's job.

| Role | Directory | Domain |
|---|---|---|
| Audio Analyst | `roles/audio-analyst/` | Song/audio structure, timing, BPM, sections, vocal analysis (first vocal onsets) |
| Visual Director | `roles/visual-director/` | Treatment, visual language, character/location bible, composition |
| Prompt Engineer | `roles/prompt-engineer/` | Generation prompts, camera direction, action choreography, lip-sync vs non-lip-sync decisions |
| Technical Director| `roles/technical-director/`| Generation math, integer durations, overlap/trim, legal resolutions (multiples of 32) |
| Technical QC | `roles/technical-qc/` | Frame defect detection, anatomy, artifacts, text bleed |
| Continuity Editor | `roles/continuity-editor/` | Cross-shot flow, identity consistency, wardrobe, props |
| Post-Production Editor | `roles/post-production-editor/` | Trimming model lead-ins, concatenating clips, syncing master audio |

### Supervisor roles

Supervisors review structured deliverables from specialists. They
catch cross-domain conflicts, challenge weak reasoning, and make
approval or escalation decisions. They do not redo specialist work.

| Role | Directory | Domain |
|---|---|---|
| Executive Producer | `roles/executive-producer/` | Cross-domain coherence, budget, feasibility, final authority |
| Creative Director | `roles/creative-director/` | Narrative quality, emotional arc, brand, audience |

## How roles work

1. Each agent seat in a production is assigned exactly one role skill.
2. The orchestrator uses the role skill to build a scoped context for
   that seat — only the data the role needs.
3. The role skill defines the structured output schema the seat must
   return.
4. Specialists produce deliverables; supervisors review them.
5. A seat without a role skill receives the full production context
   (legacy behavior).

## Pipeline agnosticism

These roles are deliberately not tied to music videos. The same
Audio Analyst role works whether the production is a music video, a
podcast visualization, a commercial with a jingle, or a film trailer
with a score. The orchestrator maps pipeline-specific stages to
role-agnostic task types:

| Pipeline stage | Task type | Primary role |
|---|---|---|
| Song/audio analysis | `media_analysis` | Audio Analyst |
| Treatment development | `creative_proposal` | Visual Director |
| Reference development | `asset_planning` | Visual Director |
| Prompt writing | `generation_spec` | Prompt Engineer |
| Shot generation QC | `media_inspection` | Technical QC |
| Cross-shot review | `continuity_check` | Continuity Editor |
| Stage approval | `supervisor_review` | Executive Producer / Creative Director |

## Assigning roles in the GUI

When a user adds an agent seat in the production configurator, they
select a role from a dropdown populated by this package. The role
determines:
- Which capability checkboxes are pre-checked
- Which context slice the seat receives
- What model tier is recommended (shown as a hint, not enforced)
- What structured output the seat must return

## Extensibility

Custom roles can be added by placing a new directory under `roles/`
with a `SKILL.md` following the same frontmatter and section structure.
The skill catalog discovers them automatically on the next scan.
