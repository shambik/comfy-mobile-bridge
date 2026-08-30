# Project-scoped agent skills

The bridge keeps production skills in two deliberately separate layers:

- `skills/` remains the application catalog and the Council role manifest source.
- `.agents/skills/` is the project-native skill installation visible to both Codex and AGY.

Run this from the repository root after changing a production skill:

```powershell
.\scripts\install-project-skills.ps1
```

The script installs the E2E/lip-sync packages, the Council package, and one
project-native skill for every Council specialist role. It does not touch
`.runtime`, `state`, model files, ComfyUI, or global agent configuration.

The production UI remains the authority for specialist selection. A skill being
installed does not mean it is active for every production. The bridge sends the
selected skill names, descriptions, and project paths to the agent, and the
agent reads the selected `SKILL.md` through its normal file/skill mechanism.
The skill body is intentionally not copied into every request. Each installed
production skill is marked explicit-only in `agents/openai.yaml`, so an
unselected specialist cannot be implicitly activated by a matching phrase.

Council role selection is independent: the configured seat role determines the
role skill for that turn, while the production skill checkboxes determine the
additional user-selected production skills. Legacy production behavior remains
unchanged apart from using the same project-native skill handoff.
