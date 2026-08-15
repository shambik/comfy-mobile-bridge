$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$dependencies = Get-JsonFile -Path (Join-Path $repo 'manifests\dependencies.json')
$models = Get-JsonFile -Path (Join-Path $repo 'manifests\models.json')
$commitPattern = '^[0-9a-f]{40}$'
$hashPattern = '^[0-9a-f]{64}$'

foreach ($item in $dependencies.repositories) {
    if ([string]$item.revision -notmatch $commitPattern) { throw "Invalid pinned commit for $($item.name)" }
    if ([string]$item.url -notmatch '^https://') { throw "Repository URL must use HTTPS for $($item.name)" }
    if ([string]$item.target -match '(^|/|\\)\.\.(?=/|\\|$)') { throw "Unsafe repository target: $($item.target)" }
}
if ($dependencies.repositories.Count -ne 5) { throw 'Expected five pinned repositories.' }
if ($models.models.Count -ne 13) { throw 'Expected thirteen pinned model files.' }
foreach ($model in $models.models) {
    if ([int64]$model.bytes -le 0) { throw "Invalid byte count for $($model.name)" }
    if ([string]$model.sha256 -notmatch $hashPattern) { throw "Invalid SHA-256 for $($model.name)" }
    if ([string]$model.revision -notmatch $commitPattern) { throw "Invalid model revision for $($model.name)" }
    if ([string]$model.target_directory -match '(^|/|\\)\.\.(?=/|\\|$)') { throw "Unsafe model target: $($model.target_directory)" }
    if ([string]$model.filename -match '[\\/:]') { throw "Model filename must be a leaf name: $($model.filename)" }
    if ([string]$model.source_repository -notmatch '^https://(?:huggingface\.co|github\.com)/') { throw "Model source must be a trusted HTTPS repository: $($model.name)" }
}
foreach ($line in Get-Content -LiteralPath (Join-Path $repo 'manifests\python-lock.txt')) {
    if ($line.Trim() -and $line.Trim() -notmatch '^#' -and $line.Trim() -notmatch '^[A-Za-z0-9_.-]+==[A-Za-z0-9.+!-]+$') {
        throw "Python lock line is not pinned: $line"
    }
}
Write-Host 'Manifest validation passed.'
exit 0
