$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
$port = 8188
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listener) { Write-Host "Native diagnostic server already listens on $port."; exit 0 }
if (-not (Test-Path -LiteralPath $config.Python -PathType Leaf) -or -not (Test-Path -LiteralPath (Join-Path $config.ComfyRoot 'main.py') -PathType Leaf)) {
    Write-Error 'Portable ComfyUI runtime is missing. Run bootstrap first.'
    exit 2
}
$logDir = Join-Path $repo 'state\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$args = @(
    '-u', (Join-Path $config.ComfyRoot 'main.py'), '--listen', '127.0.0.1', '--port', $port,
    '--base-directory', $config.ComfyRoot, '--models-directory', $config.Models,
    '--input-directory', (Join-Path $repo 'state\input'), '--output-directory', (Join-Path $repo 'state\output'),
    '--temp-directory', (Join-Path $repo 'state\temp'), '--user-directory', (Join-Path $repo 'state\user'),
    '--disable-auto-launch', '--disable-api-nodes', '--disable-all-custom-nodes',
    '--lowvram', '--preview-method', 'none', '--log-stdout'
)
Start-Process -FilePath $config.Python -ArgumentList $args -WorkingDirectory $config.ComfyRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'comfy-8188.log') -RedirectStandardError (Join-Path $logDir 'comfy-8188.error.log') | Out-Null
Write-Host 'Started the isolated 8188 diagnostic server. It is not exposed through Tailscale.'
exit 0
