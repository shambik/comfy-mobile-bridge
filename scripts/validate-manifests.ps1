$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$dependencies = Get-JsonFile -Path (Join-Path $repo 'manifests\dependencies.json')
$models = Get-JsonFile -Path (Join-Path $repo 'manifests\models.json')
$commitPattern = '^[0-9a-f]{40}$'
$hashPattern = '^[0-9a-f]{64}$'

$groups = @($models.groups.PSObject.Properties.Name)
foreach ($group in $groups) {
    foreach ($need in @($models.groups.$group.needs)) {
        if ($need -and $groups -notcontains $need) { throw "Group $group needs unknown group $need" }
    }
}
foreach ($item in $dependencies.repositories) {
    if ([string]$item.revision -notmatch $commitPattern) { throw "Invalid pinned commit for $($item.name)" }
    if ([string]$item.url -notmatch '^https://') { throw "Repository URL must use HTTPS for $($item.name)" }
    if ([string]$item.target -match '(^|/|\\)\.\.(?=/|\\|$)') { throw "Unsafe repository target: $($item.target)" }
    foreach ($group in (Get-ManifestItemGroups -Item $item)) {
        if ($groups -notcontains $group) { throw "Unknown group $group for $($item.name)" }
    }
}
if (@($models.models | Where-Object { $_.group -eq 'h3' }).Count -ne 9) { throw 'Expected nine pinned H3 base model files.' }
$seen = @{}
foreach ($model in @($models.models) + @($dependencies.files)) {
    if ($groups -notcontains [string]$model.group) { throw "Unknown group $($model.group) for $($model.name)" }
    $root = if ($model.PSObject.Properties.Name -contains 'target_root') { [string]$model.target_root } else { 'models' }
    if ($root -notin @('models', 'runtime', 'state')) { throw "Unknown target_root $root for $($model.name)" }
    $key = "$root|$($model.target_directory)|$($model.filename)"
    if ($seen.ContainsKey($key)) { throw "Two entries install the same file: $key" }
    $seen[$key] = $true
    if ($model.PSObject.Properties.Name -contains 'release_tag' -and [string]$model.source_repository -notmatch '^https://github\.com/') {
        throw "release_tag is only for GitHub releases: $($model.name)"
    }
    if ([int64]$model.bytes -le 0) { throw "Invalid byte count for $($model.name)" }
    if ([string]$model.sha256 -notmatch $hashPattern) { throw "Invalid SHA-256 for $($model.name)" }
    if ([string]$model.revision -notmatch $commitPattern) { throw "Invalid model revision for $($model.name)" }
    if ([string]$model.target_directory -match '(^|/|\\)\.\.(?=/|\\|$)') { throw "Unsafe model target: $($model.target_directory)" }
    if ([string]$model.filename -match '[\\/:]') { throw "Model filename must be a leaf name: $($model.filename)" }
    if ([string]$model.source_repository -notmatch '^https://(?:huggingface\.co|github\.com)/') { throw "Model source must be a trusted HTTPS repository: $($model.name)" }
}
foreach ($lock in $dependencies.python_locks) {
    foreach ($line in Get-Content -LiteralPath (Join-Path $repo ([string]$lock.file))) {
        if ($line.Trim() -and $line.Trim() -notmatch '^#' -and $line.Trim() -notmatch '^[A-Za-z0-9_.-]+==[A-Za-z0-9.+!-]+$') {
            throw "Python lock line is not pinned in $($lock.file): $line"
        }
    }
}
Write-Host 'Manifest validation passed.'
exit 0
