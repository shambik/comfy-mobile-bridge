param([switch]$NoPrompt)

# Prints this machine's Tailscale hostname for the launcher. The hostname is
# never stored in the repository: it comes from config.local.json (ignored by
# Git), else from the Tailscale CLI, else the user is asked once. A detected or
# entered hostname is saved to config.local.json so the bridge's allowed-hosts
# list and the launcher stay in sync.

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$localPath = Join-Path $repo 'config.local.json'

function Read-LocalConfig {
    if (Test-Path -LiteralPath $localPath -PathType Leaf) {
        return (Get-Content -LiteralPath $localPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    }
    return [pscustomobject]@{}
}

function Save-Hostname([string]$Hostname) {
    $config = Read-LocalConfig
    if (-not ($config.PSObject.Properties.Name -contains 'tailscale') -or -not $config.tailscale) {
        $config | Add-Member -NotePropertyName tailscale -NotePropertyValue ([pscustomobject]@{ enabled = $true; scope = 'tailnet' }) -Force
    }
    $config.tailscale | Add-Member -NotePropertyName hostname -NotePropertyValue $Hostname -Force
    if (Test-Path -LiteralPath $localPath -PathType Leaf) {
        Copy-Item -LiteralPath $localPath -Destination "$localPath.bak" -Force
    }
    $json = $config | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($localPath, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
}

try {
    $config = Read-LocalConfig
    $saved = if ($config.PSObject.Properties.Name -contains 'tailscale' -and $config.tailscale) { [string]$config.tailscale.hostname } else { '' }
    if ($saved.Trim()) { Write-Output $saved.Trim(); exit 0 }

    $detected = ''
    $tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($tailscale) {
        try {
            $status = & $tailscale.Source status --json 2>$null | Out-String | ConvertFrom-Json
            $detected = ([string]$status.Self.DNSName).TrimEnd('.')
        } catch { $detected = '' }
    }
    if (-not $detected -and -not $NoPrompt) {
        $detected = (Read-Host 'Tailscale hostname for this PC (for example my-pc.your-tailnet.ts.net, leave empty to skip)').Trim()
    }
    if ($detected) {
        Save-Hostname $detected
        Write-Output $detected
    }
    exit 0
} catch {
    # The launcher must still start the app when the hostname cannot be resolved.
    exit 0
}
