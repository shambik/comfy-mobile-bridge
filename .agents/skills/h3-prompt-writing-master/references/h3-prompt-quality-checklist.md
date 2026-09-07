# H3 prompt quality checklist

Use this checklist after drafting and before handing the prompt to an execution workflow.

## Contract

- [ ] The mode is exactly one of T2VA, I2VA, FL2VA, L2VA, or Ref2VA.
- [ ] The selected official template is used without changing field names or section order.
- [ ] The requested duration is explicit and agrees with the generation window.
- [ ] Mode-specific timestamp notation and alignment language are correct.

## References

- [ ] Each reference has one role: literal frame, identity, wardrobe, style, location, video continuation, or audio.
- [ ] Labels are stable (`<Picture 1>`, `<Subject 1>`, `<Video 1>`, `<Audio 1>`).
- [ ] Preservation claims match the actual intent; identity/style transfer is not falsely called full-frame preservation.
- [ ] Ref2VA uses all six official sections in the required order.

## Visual performance

- [ ] The opening composition is concrete and filmable.
- [ ] Face, eye color, hair, body build, clothing, markings, and important props are locked where required.
- [ ] There is one dominant action with a clear physical sequence and end state.
- [ ] Body motion includes believable balance, weight, hands, and foot contact.
- [ ] The camera has one setup and a named motion with direction and meaningful amplitude/speed.
- [ ] A major angle/location change is an explicit cut, not hidden camera drift.
- [ ] No prompt relies on "cool," "cinematic," "professional," or "dynamic" without physical detail.

## Audio and vocals

- [ ] The master audio/reference-audio policy is explicit.
- [ ] `(S1)`, `(S2)`, and other speaker IDs remain stable.
- [ ] Vocal ownership is unambiguous, especially for chorus/feature/Phantom sections.
- [ ] Text is exact when text conditioning is required; no paraphrase or invented ad-lib appears.
- [ ] Instrumental performers have closed mouths and no lip movement.
- [ ] `overall_soundscape` does not repeat lyrics; `non_diegetic_music` describes audible instrumentation and rhythm.
- [ ] No unrelated generated soundtrack is requested.

## Continuity and overlap

- [ ] Adjacent shot context is known before writing the opening and exit states.
- [ ] An overlapped shot opens mid-action, rather than restarting at the gesture's first frame.
- [ ] The audio lead-in, real edit-in, trim, and transition point are recorded in the editorial manifest.
- [ ] Screen direction, wardrobe, lighting, and action phase agree across the cut.
- [ ] The master song is assembled once; per-shot audio is not accidentally stacked.

## Local execution boundary

- [ ] Creative prose does not invent steps, seeds, dimensions, VRAM settings, or runtime claims.
- [ ] Resolution, megapixels, model, and workflow are supplied by the technical plan.
- [ ] No live process was stopped, restarted, queued, or modified while merely authoring or auditing a prompt.

## Common failure patterns

Reject or revise prompts that:

- use a generic style paragraph with no opening frame, action order, or end state;
- say "the camera moves dynamically" while actually requiring a hidden angle change;
- ask two characters to sing the same line when only one owns the vocal;
- paste lyrics into a native-audio prompt without confirming the workflow needs text conditioning;
- describe an instrumental shot with open-mouth lip-sync;
- label a character reference as a fully preserved picture when it is only an identity anchor;
- restart an overlapped shot at a pose instead of continuing the neighboring action;
- add a second soundtrack or duplicate the master audio;
- pile up conflicting negative prompts instead of stating the desired physical behavior.
