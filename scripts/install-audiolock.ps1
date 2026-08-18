$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
$source = Join-Path $repo 'custom_nodes\ComfyUI-H3-NativeAudioLock'
$target = Join-Path $config.ComfyRoot 'custom_nodes\ComfyUI-H3-NativeAudioLock'

if (-not (Test-Path -LiteralPath (Join-Path $source '__init__.py') -PathType Leaf)) {
    throw "Native AudioLock source is missing: $source"
}
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $source '__init__.py') -Destination (Join-Path $target '__init__.py') -Force
Write-Host "Installed local Native AudioLock node at $target"
