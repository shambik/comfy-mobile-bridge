param([switch]$Wait)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
$pidPath = Join-Path $config.RuntimeRoot 'bridge.pid'
$logDir = Join-Path $repo 'state\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
New-Item -ItemType Directory -Path $config.RuntimeRoot -Force | Out-Null

$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $config.AppPort -State Listen -ErrorAction SilentlyContinue
if ($existing) { Write-Host "Bridge is already listening on $($config.AppPort)."; exit 0 }
if (-not (Test-Path -LiteralPath $config.BridgePython -PathType Leaf)) {
    $fallback = Get-Command python -ErrorAction SilentlyContinue
    if (-not $fallback) { Write-Error 'Runtime Python is missing. Run bootstrap first.'; exit 2 }
    $python = $fallback.Source
} else { $python = $config.BridgePython }

$stdout = Join-Path $logDir 'bridge.stdout.log'
$stderr = Join-Path $logDir 'bridge.stderr.log'
$process = Start-Process -FilePath $python -ArgumentList @('-u', (Join-Path $repo 'run.py')) -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$process.Id | Set-Content -LiteralPath $pidPath -Encoding ASCII
if ($Wait) {
    Wait-Process -Id $process.Id
} else {
    Start-Sleep -Milliseconds 800
    if ($process.HasExited) { Write-Error "Bridge exited with code $($process.ExitCode)."; exit 5 }
    Write-Host "Bridge started on http://127.0.0.1:$($config.AppPort)."
}
exit 0
