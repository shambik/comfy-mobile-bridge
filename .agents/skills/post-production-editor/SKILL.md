---
name: post-production-editor
description: Assemble approved shot artifacts from an editorial manifest, applying exact trims and the configured audio policy, then validate the final master. Supports silent, generated-audio, master-track, and explicit mixed-audio productions.
---

# Post-Production Editor

Execute the approved editorial manifest deterministically.

## Responsibilities

- resolve approved clips by artifact ID;
- apply exact lead-in/lead-out trims and editorial order;
- use hard cuts unless the manifest explicitly requests another transition;
- apply the configured audio policy: master replacement, preserve generated audio, or explicit mix;
- validate streams, duration, frame rate, resolution, sync offsets, and missing/blank segments;
- register the final master and validation evidence.

## Boundaries

- Do not change cut points or substitute unapproved attempts.
- Do not assume every source clip is silent.
- Do not perform creative revisions or generation QC.
- Do not delete source artifacts.

Return the canonical envelope with an `assembly_result.v1` deliverable.
