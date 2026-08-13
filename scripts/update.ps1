$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
$queue = try { Invoke-RestMethod -Uri "http://127.0.0.1:$($config.ComfyPort)/queue" -TimeoutSec 5 } catch { $null }
if ($queue -and (($queue.queue_running | Measure-Object).Count -gt 0 -or ($queue.queue_pending | Measure-Object).Count -gt 0)) {
    Write-Error 'ComfyUI queue is not idle. Update stopped without changing code.'
    exit 5
}
if ((git -C $repo status --porcelain)) { Write-Error 'Working tree is dirty. Commit or back up changes before update.'; exit 2 }
$backupDir = Join-Path $config.RuntimeRoot ('backups\update-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$db = Join-Path $repo 'state\jobs.sqlite3'
if (Test-Path -LiteralPath $db) { Copy-Item -LiteralPath $db -Destination (Join-Path $backupDir 'jobs.sqlite3') }
git -C $repo pull --ff-only
if ($LASTEXITCODE -ne 0) { Write-Error 'Fast-forward update failed.'; exit 4 }
& npm ci
if ($LASTEXITCODE -ne 0) { exit 4 }
& npm run build
if ($LASTEXITCODE -ne 0) { exit 4 }
Write-Host "Update completed. State backup: $backupDir"
exit 0
