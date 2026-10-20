param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
$localPath = if (Test-Path -LiteralPath $config.ConfigPath -PathType Leaf) { $config.ConfigPath } else { Join-Path $repo 'config.example.json' }
$local = Get-JsonFile -Path $localPath
$qwenConfig = if ($local.PSObject.Properties.Name -contains 'qwen_image_comfy') { $local.qwen_image_comfy } else { $null }
$port = 8193
if ($qwenConfig -and $qwenConfig.port) { $port = [int]$qwenConfig.port }
$models = if ($qwenConfig -and $qwenConfig.models) { Resolve-LocalPath -Value ([string]$qwenConfig.models) -BasePath $repo } else { Join-Path $config.RuntimeRoot 'qwen_image_models' }
$python = Join-Path $config.RuntimeRoot 'qwen_image_venv\Scripts\python.exe'
$code = Join-Path $config.RuntimeRoot 'qwen_image_code'
$main = Join-Path $code 'main.py'
$state = Join-Path $repo 'state\qwen_image_comfy'

if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $main -PathType Leaf)) {
    Write-Host 'The isolated Qwen runtime is not installed; run scripts\install-qwen-image.ps1 -AcceptNonCommercialLicense after accepting its terms.'
    exit 2
}
if (-not (Test-Path -LiteralPath $models -PathType Container)) {
    Write-Host "The isolated Qwen model directory is missing: $models"
    exit 2
}

$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    try {
        $system = Invoke-RestMethod -Uri "http://127.0.0.1:$port/system_stats" -TimeoutSec 5
        $argv = @($system.system.argv) -join ' '
        if ($argv -notmatch 'qwen_image_code[\\/]main\.py') {
            throw "Port $port is already used by a different process; it was left untouched."
        }
        Write-Host "Isolated Qwen ComfyUI is already running on $port."
        exit 0
    } catch {
        throw "Port $port is occupied but is not confirmed as the isolated Qwen ComfyUI. No process was stopped. $($_.Exception.Message)"
    }
}

$logDir = Join-Path $state 'logs'
$inputDir = if ($qwenConfig -and $qwenConfig.input) { Resolve-LocalPath -Value ([string]$qwenConfig.input) -BasePath $repo } else { Join-Path $state 'input' }
$outputDir = if ($qwenConfig -and $qwenConfig.output) { Resolve-LocalPath -Value ([string]$qwenConfig.output) -BasePath $repo } else { Join-Path $state 'output' }
foreach ($directory in @($logDir, $inputDir, $outputDir, (Join-Path $state 'temp'), (Join-Path $state 'user'))) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
$comfyArgs = @('-u', $main, '--listen', '127.0.0.1', '--port', [string]$port,
          '--disable-auto-launch', '--lowvram', '--models-directory', $models,
          '--input-directory', $inputDir, '--output-directory', $outputDir,
          '--temp-directory', (Join-Path $state 'temp'), '--user-directory', (Join-Path $state 'user'))
$process = Start-Process -FilePath $python -ArgumentList $comfyArgs -WorkingDirectory $code -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'stdout.log') -RedirectStandardError (Join-Path $logDir 'stderr.log') -PassThru
$process.Id | Set-Content -LiteralPath (Join-Path $config.RuntimeRoot 'qwen_image.pid') -Encoding ASCII
Write-Host "Isolated low-VRAM Qwen ComfyUI starting on http://127.0.0.1:$port (PID $($process.Id)). Existing ComfyUI processes were not touched."
