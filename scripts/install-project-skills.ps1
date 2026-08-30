[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$sourceRoot = Join-Path $repoRoot "skills"
$projectRoot = Join-Path $repoRoot ".agents\skills"

# These are the production skills that may be selected by a production in the
# bridge UI. The role copies are flattened so both Codex and AGY can discover
# an individual specialist as a normal project skill.
$packageNames = @(
    "e2e-music-video",
    "e2e-music-video-poc",
    "realistic-rap-turbo-poc",
    "lipsync-skill",
    "council-roles"
)

$roleManifestPath = Join-Path $sourceRoot "council-roles\manifest.json"
$roleManifest = Get-Content -LiteralPath $roleManifestPath -Raw | ConvertFrom-Json

function Write-ExplicitSelectionPolicy([string] $target) {
    $agentsDir = Join-Path $target "agents"
    New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null
    $policyPath = Join-Path $agentsDir "openai.yaml"
    @"
policy:
  allow_implicit_invocation: false
"@ | Set-Content -LiteralPath $policyPath -Encoding utf8
}

function Copy-ProjectSkill([string] $source, [string] $target) {
    $skillFile = Join-Path $source "SKILL.md"
    if (-not (Test-Path -LiteralPath $skillFile -PathType Leaf)) {
        throw "Source skill is missing SKILL.md: $source"
    }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $target -Recurse -Force
    Write-ExplicitSelectionPolicy $target
}

foreach ($name in $packageNames) {
    Copy-ProjectSkill (Join-Path $sourceRoot $name) (Join-Path $projectRoot $name)
}

foreach ($role in $roleManifest.roles) {
    $roleId = [string]$role.id
    Copy-ProjectSkill (Join-Path $sourceRoot "council-roles\roles\$roleId") (Join-Path $projectRoot $roleId)
}

$expected = @($packageNames) + @($roleManifest.roles | ForEach-Object { [string]$_.id })
$missing = @(
    foreach ($name in $expected) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "$name\SKILL.md") -PathType Leaf)) {
            $name
        }
    }
)
if ($missing.Count -gt 0) {
    throw "Project skill installation is incomplete: $($missing -join ', ')"
}

Write-Output ("Installed {0} project-scoped production skills under {1}." -f $expected.Count, $projectRoot)
