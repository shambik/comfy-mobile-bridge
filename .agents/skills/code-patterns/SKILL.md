# Code patterns

## Trigger

Use this skill when adding a helper, PowerShell command, download flow, config
field, process lifecycle code, test, or security check.

## Patterns

- Resolve the repository root from the script location, not the current
  working directory and not a parent project.
- Read settings from generated local config and use safe localhost defaults.
- Use Path objects in Python and -LiteralPath in PowerShell.
- For downloads: destination .part, resumable transfer, exact size, SHA-256,
  atomic move, and never overwrite a valid final file.
- For subprocesses: record the PID, verify the command path, bind localhost,
  write logs under ignored state/logs, and stop only owned processes.
- For HTTP: use timeouts, local URLs, explicit status checks, and bounded error
  text.
- For SQLite: use existing connection helpers and never delete or recreate the
  database during an update.

## Security

Keep secrets, personal paths, IPs, MagicDNS names, and local model data out of
tracked files. Preserve CSRF, TrustedHost, upload limits, and media validation.
