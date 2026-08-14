# Tailscale access

This bridge keeps both the app and ComfyUI on the PC's loopback interface:

- Bridge: `127.0.0.1:8787`
- ComfyUI: `127.0.0.1:8190`

Tailscale Serve publishes only the bridge to devices in the same tailnet. The
bridge does not expose ComfyUI directly, and Funnel must remain disabled.

## First-time setup on the PC

Install Tailscale for Windows, then sign in to the Tailscale account that owns
this computer. The account must be the one whose tailnet you want to use; do
not copy another computer's hostname into the configuration.

From PowerShell in the repository directory:

```powershell
tailscale status
.\scripts\preflight.ps1 -Json
.\scripts\bootstrap.ps1 -Profile Full -AcceptLicenses
.\scripts\start.ps1
.\scripts\doctor.ps1 -Deep
```

`bootstrap.ps1` detects the logged-in Tailscale hostname, writes it to the
ignored `config.local.json`, and configures Tailscale Serve for port `8787`.
It does not enable Funnel.

The bootstrap command downloads the pinned runtime and models, so it can take
a long time and requires the license review described in
`THIRD_PARTY_NOTICES.md`. If the user already has ComfyUI and the models in a
different location, configure those local paths in `config.local.json` before
starting the bridge instead of downloading a second copy.

## If Tailscale is already installed

The user still needs to be signed in and connected:

```powershell
tailscale status
```

The output should show the PC as connected. If it reports that login is
required, open the Tailscale Windows application and complete sign-in. Then
run:

```powershell
.\scripts\start.ps1
.\scripts\doctor.ps1 -Deep
```

If Serve has not been configured yet, rerun bootstrap after signing in:

```powershell
.\scripts\bootstrap.ps1 -Profile Full -AcceptLicenses
```

## Connecting from a phone

1. Install Tailscale on the phone.
2. Sign in to the same tailnet as the PC.
3. Confirm the PC appears as an online device in the Tailscale app.
4. Open the HTTPS hostname reported by `tailscale status` for the PC.

The URL uses the Tailscale hostname and does not use port `8190`. Tailscale
Serve forwards that private HTTPS address to the local bridge on port `8787`.

## Verify the connection

On the PC, run:

```powershell
tailscale serve status
.\scripts\doctor.ps1 -Deep
```

The doctor checks that:

- both listeners are local-only;
- Tailscale is installed and logged in;
- a hostname is available;
- Serve forwards to `127.0.0.1:8787`;
- Funnel is disabled;
- the bridge and required ComfyUI nodes are responding.

From the phone, a successful connection should show the bridge UI and allow
the ComfyUI status page to report port `8190` through the bridge. ComfyUI's
own port should not be reachable directly from the tailnet.

## Troubleshooting

### Tailscale is not logged in

Open the Tailscale Windows app, sign in to the correct tailnet, and rerun:

```powershell
tailscale status
.\scripts\doctor.ps1 -Deep
```

### The bridge works on the PC but not on the phone

Check that both devices are in the same tailnet and that the PC is online.
Then verify Serve and restart only the bridge:

```powershell
tailscale serve status
.\scripts\start.ps1
```

### Serve points to the wrong port

The expected target is `127.0.0.1:8787`. Do not point Serve at `8190`; that
would bypass the bridge controls and authentication boundary. Rerun bootstrap
to restore the managed Serve configuration.

### The hostname changed

Do not edit the hostname into source files. Run bootstrap again while signed
in to Tailscale. It detects the current hostname and updates the ignored local
configuration.

### Security notes

- Use Tailscale access controls or device approval to restrict tailnet access.
- Never enable Funnel for this bridge.
- Never commit `config.local.json`; it contains machine-specific settings.
- Do not share Tailscale authentication keys or state files.
- The bridge is intended for a private tailnet, not direct public exposure.
