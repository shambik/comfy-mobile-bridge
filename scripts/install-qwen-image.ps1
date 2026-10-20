param([switch]$AcceptNonCommercialLicense)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
$manifestPath = Join-Path $repo 'manifests\qwen-image-2.1.json'
$manifest = Get-JsonFile -Path $manifestPath

if (-not $AcceptNonCommercialLicense) {
    throw 'Qwen Image 2.1 is non-commercial research/evaluation only. Rerun with -AcceptNonCommercialLicense after accepting the Qwen Research License Agreement.'
}

$runtime = $config.RuntimeRoot
$code = Join-Path $runtime 'qwen_image_code'
$venv = Join-Path $runtime 'qwen_image_venv'
$python = Join-Path $venv 'Scripts\python.exe'
$models = Join-Path $runtime 'qwen_image_models'
$revision = [string]$manifest.comfyui.revision

if (Test-Path -LiteralPath $code -PathType Container) {
    $head = (& git -C $code rev-parse HEAD 2>$null | Out-String).Trim()
    if ($head -ne $revision) {
        throw "Qwen ComfyUI checkout exists at '$head', not the pinned '$revision'. It was left unchanged."
    }
    Write-Host "Verified isolated Qwen ComfyUI checkout at $head"
} else {
    New-Item -ItemType Directory -Path (Split-Path -Parent $code) -Force | Out-Null
    & git clone --filter=blob:none --no-checkout ([string]$manifest.comfyui.repository) $code
    if ($LASTEXITCODE -ne 0) { throw 'Could not clone the pinned Qwen ComfyUI runtime.' }
    & git -C $code checkout --detach $revision
    if ($LASTEXITCODE -ne 0) { throw 'Could not check out the pinned Qwen ComfyUI revision.' }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    & py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated Python 3.12 Qwen environment.' }
}

& $python -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare pip in the isolated Qwen environment.' }
& $python -m pip install --disable-pip-version-check --extra-index-url https://download.pytorch.org/whl/cu126 torch==2.9.1+cu126 torchvision==0.24.1+cu126 torchaudio==2.9.1+cu126
if ($LASTEXITCODE -ne 0) { throw 'Could not install the isolated CUDA 12.6 PyTorch runtime for Qwen.' }
& $python -m pip install --disable-pip-version-check -r (Join-Path $code 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the pinned ComfyUI runtime requirements in the isolated Qwen environment.' }

foreach ($model in $manifest.models) {
    $destinationDirectory = Join-Path $models ([string]$model.target_directory)
    $destination = Join-Path $destinationDirectory ([string]$model.filename)
    $url = "$($model.source_repository)/resolve/main/$($model.source_path)?download=true"
    Install-VerifiedDownload -Url $url -Destination $destination -ExpectedBytes ([int64]$model.bytes) -ExpectedSha256 ([string]$model.sha256)
}

$licenseNotice = @'
Qwen Image 2.1 local model weights are provided under the Qwen Research License Agreement.
Use is limited to non-commercial research or evaluation. Commercial use requires a separate license.
License: https://github.com/QwenLM/Qwen-Image-2.1/blob/main/LICENSE
Attribution: Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) 2026 Hangzhou Tongyi Laboratory Technology Co., Ltd. All Rights Reserved.
'@
New-Item -ItemType Directory -Path $models -Force | Out-Null
Set-Content -LiteralPath (Join-Path $models 'NOTICE.txt') -Value $licenseNotice -Encoding UTF8
Write-Host "Verified Qwen Image 2.1 models are installed under $models"
Write-Host 'Start the isolated engine with scripts\start-qwen-image-comfy.ps1.'
