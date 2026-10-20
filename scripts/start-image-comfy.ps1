param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
$localPath = if (Test-Path -LiteralPath $config.ConfigPath -PathType Leaf) { $config.ConfigPath } else { Join-Path $repo 'config.example.json' }
$local = Get-JsonFile -Path $localPath
$imageConfig = if ($local.PSObject.Properties.Name -contains 'image_comfy') { $local.image_comfy } else { $null }
$port = if ($imageConfig -and $imageConfig.port) { [int]$imageConfig.port } else { 8192 }
$python = Join-Path $config.RuntimeRoot 'image_comfy_venv\Scripts\python.exe'
$code = Join-Path $config.RuntimeRoot 'image_comfy_code'
$main = Join-Path $code 'main.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $main -PathType Leaf)) {
    Write-Host 'Isolated image ComfyUI is not installed; skipping.'
    exit 0
}
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Image ComfyUI is already listening on $port."
    exit 0
}
$state = Join-Path $repo 'state\image_comfy'
$logs = Join-Path $state 'logs'
$inputDir = if ($imageConfig -and $imageConfig.input) { Resolve-LocalPath -Value ([string]$imageConfig.input) -BasePath $repo } else { Join-Path $state 'input' }
$outputDir = if ($imageConfig -and $imageConfig.output) { Resolve-LocalPath -Value ([string]$imageConfig.output) -BasePath $repo } else { Join-Path $state 'output' }
foreach ($name in @('input', 'output', 'temp', 'user', 'logs')) {
    New-Item -ItemType Directory -Path (Join-Path $state $name) -Force | Out-Null
}
New-Item -ItemType Directory -Path $inputDir, $outputDir -Force | Out-Null
$imageArgs = @('-u', $main, '--listen', '127.0.0.1', '--port', [string]$port,
          '--disable-auto-launch', '--models-directory', $config.Models,
          '--input-directory', $inputDir,
          '--output-directory', $outputDir,
          '--temp-directory', (Join-Path $state 'temp'),
          '--user-directory', (Join-Path $state 'user'))
$process = Start-Process -FilePath $python -ArgumentList $imageArgs -WorkingDirectory $code -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log') -PassThru
$process.Id | Set-Content -LiteralPath (Join-Path $config.RuntimeRoot 'image_comfy.pid') -Encoding ASCII
Write-Host "Image ComfyUI starting on http://127.0.0.1:$port (PID $($process.Id))."
