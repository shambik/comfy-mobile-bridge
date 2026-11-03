# Execute or resume Episode 01

The full creative brief and shot list are in `EPISODE_PLAN.md`. The user chose
LTX, independent hard-cut clips, no speech, original music, built-in ImageGen
stills and user-led visual review. Do not use AGY or delegated reviewers.

The visual storyboard is `state/tumble_puffs_ep01/STORYBOARD.html`; open it
locally with its `frames/` folder intact. It is a storyboard, not the animated
master. All twenty selected frames were created directly with built-in ImageGen.

Use the existing main bridge on `http://127.0.0.1:8787` and its single ComfyUI
on 8190. Do not change the runtime, models, packages or workflows. These jobs
use Balanced landscape (1600×896), eight steps, sharp decode and silent output.

From the repository root, with Python containing `requests`:

```powershell
python docs/ltx25_test/tumble_puffs_ep01/episode_runner.py render
```

The process holds a Windows byte-range lock. A second producer is refused.
Its journal is `state/tumble_puffs_ep01/execution.json`. Completed clips are
skipped; queued/running journaled IDs are polled. A `submitting` item without
an ID is uncertain: inspect `/api/jobs` and reconcile the existing ID before
resuming. Never repeat that POST blindly. A failed GPU job also needs evidence
and a deliberate recovery; there is no automatic creative regeneration loop.

The `STOPPED.json` file in that state folder stops future submissions. It does
not cancel a running job. Create it only when the user asks to stop this run;
remove it only when the user resumes. Never cancel unrelated bridge jobs.

All opening frames are `frames/S01.png` through `S20.png`; their image prompts
are in `prompts/`. Original built-in ImageGen files remain preserved. The
alternate S19 frame is retained for provenance; `S19.png` is the selected one.
Run `storyboard_html.py` to refresh the local visual storyboard.

The music is already generated. To revise/rebuild it, run `episode_score.py`
with a project or bundled Python containing numpy (never install globally).
It creates separate music/effects stems and a 120-second combined WAV.
No samples, singing, speech, voice synthesis or generated clip audio are used.

After all 20 items say `verified`:

```powershell
python docs/ltx25_test/tumble_puffs_ep01/episode_runner.py assemble
python docs/ltx25_test/tumble_puffs_ep01/episode_runner.py publish
```

Assembly uses decoded frame trims, preserves 24 fps, hard-cuts 20 clips into
exactly 2,880 frames, and attaches the original instrumental score and effects.
It checks ffprobe and full FFmpeg decode for every source, edit and master.
The H.264/AAC final master is `The_Runaway_Berry_120s.mp4` in the state folder.
Vault publishing deduplicates by SHA-256 and journals before upload. Never
retry an uncertain upload without checking for the matching hash in the vault.

Use the current Tailscale Serve hostname from `tailscale status --json` when
delivering the returned `/api/video-vault/{id}/video` route. Preserve the user's
DNS preference; verify HTTPS locally with curl `--resolve` if MagicDNS is off.
Verify the published artifact and update `docs/WORKFLOW_GUIDE.md` with measured
timings. The user judges creative quality; technical checks are not artistic
approval.

Build and preflight passed on this run. The Python suite has 301 passes and
one existing failure because the user-supplied `AGENTS.md` has 38 lines while
the portability test expects at most 20. Do not rewrite those user instructions
to make this unrelated assertion pass.

If the user later explicitly requests sub-agents, use GPT-6.1 Sol with medium
reasoning. No sub-agents are necessary for this production.
