param([Parameter(Mandatory)][ValidatePattern('^v[0-9]+\.[0-9]+\.[0-9]+$')][string]$Version)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
if ((git -C $repo status --porcelain)) { Write-Error 'Working tree is dirty. Rollback stopped.'; exit 2 }
git -C $repo show-ref --verify --quiet "refs/tags/$Version"
if ($LASTEXITCODE -ne 0) { Write-Error "Tag not found: $Version"; exit 4 }
$backupDir = Join-Path $config.RuntimeRoot ('backups\rollback-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$db = Join-Path $repo 'state\jobs.sqlite3'
if (Test-Path -LiteralPath $db) { Copy-Item -LiteralPath $db -Destination (Join-Path $backupDir 'jobs.sqlite3') }
git -C $repo switch --detach $Version
if ($LASTEXITCODE -ne 0) { Write-Error 'Rollback checkout failed.'; exit 4 }
Write-Host "Rolled back to $Version. State backup: $backupDir"
exit 0
