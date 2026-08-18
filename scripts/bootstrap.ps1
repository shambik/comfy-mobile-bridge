param(
    [ValidateSet('Full')][string]$Profile = 'Full',
    [switch]$DryRun,
    [switch]$AcceptLicenses,
    [switch]$SkipTailscale,
    [string]$RuntimeRoot
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$runtimeRootProvided = [bool]$RuntimeRoot

try {
    if (-not $AcceptLicenses -and -not $DryRun) {
        Write-Error 'Read THIRD_PARTY_NOTICES.md and rerun with -AcceptLicenses after accepting the applicable terms.'
        exit 3
    }

    $preflightArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $repo 'scripts\preflight.ps1'), '-Json')
    if ($DryRun) { $preflightArgs += @('-SkipGpu', '-SkipTailscale') }
    $preflightRaw = & powershell.exe @preflightArgs
    $preflight = $preflightRaw -join [Environment]::NewLine | ConvertFrom-Json
    if (-not $preflight.ok -and -not $DryRun) {
        $code = [int]$preflight.exit_code
        Write-Error ('Preflight failed: ' + (($preflight.checks | Where-Object { -not $_.passed } | ForEach-Object { "$($_.name): $($_.detail)" }) -join '; '))
        exit $(if ($code -in 2, 3) { $code } else { 2 })
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'scripts\validate-manifests.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Manifest validation failed.' }

    $dependencies = Get-JsonFile -Path (Join-Path $repo 'manifests\dependencies.json')
    $models = Get-JsonFile -Path (Join-Path $repo 'manifests\models.json')
    if ($DryRun) {
        Write-Host "Dry run for profile $Profile"
        Write-Host ("Repositories: " + $dependencies.repositories.Count)
        Write-Host ("Models: " + $models.models.Count)
        Write-Host 'No runtime, checkout, download, config, or Tailscale changes were made.'
        exit 0
    }

    if (-not $RuntimeRoot) { $RuntimeRoot = '.runtime' }
    $config = Get-BridgeConfig -RepoRoot $repo -RuntimeRootOverride $RuntimeRoot
    New-Item -ItemType Directory -Path $config.RuntimeRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $config.Models -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $config.RuntimeRoot 'downloads') -Force | Out-Null

    $tailscale = if (-not $SkipTailscale) { Get-TailscaleExe } else { $null }
    $hostname = ''
    if (-not $SkipTailscale) {
        if (-not $tailscale) {
            Write-Error 'Tailscale is not installed. Install it, log in to the user-owned tailnet, then rerun bootstrap.'
            exit 3
        }
        $tsStatus = Get-TailscaleStatusObject -Executable $tailscale
        if (-not $tsStatus -or [string]$tsStatus.BackendState -ne 'Running') {
            Write-Error 'Tailscale needs user login before private Serve can be configured.'
            exit 3
        }
        $hostname = ([string]$tsStatus.Self.DNSName).TrimEnd('.')
        if (-not $hostname) { Write-Error 'Tailscale did not report a local DNS hostname.'; exit 3 }
    }

    foreach ($item in $dependencies.repositories) {
        $target = Resolve-ManifestTarget -Target ([string]$item.target) -Config $config -RepoRoot $repo
        if (Test-Path -LiteralPath $target -PathType Container) {
            $head = (& git -C $target rev-parse HEAD 2>$null).Trim()
            if ($head -ne [string]$item.revision) {
                throw "$($item.name) exists at $head; expected $($item.revision). No files were overwritten."
            }
            Write-Host "Verified $($item.name) at $head"
        } else {
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            & git clone ([string]$item.url) $target
            if ($LASTEXITCODE -ne 0) { throw "Clone failed for $($item.name)." }
            & git -C $target checkout --detach ([string]$item.revision)
            if ($LASTEXITCODE -ne 0) { throw "Pinned checkout failed for $($item.name)." }
        }
    }

    $audioLockSource = Join-Path $repo 'custom_nodes\ComfyUI-H3-NativeAudioLock'
    $audioLockTarget = Join-Path $config.ComfyRoot 'custom_nodes\ComfyUI-H3-NativeAudioLock'
    if (-not (Test-Path -LiteralPath (Join-Path $audioLockSource '__init__.py') -PathType Leaf)) {
        throw 'The local Native AudioLock node source is missing.'
    }
    New-Item -ItemType Directory -Path $audioLockTarget -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $audioLockSource '__init__.py') -Destination (Join-Path $audioLockTarget '__init__.py') -Force
    Write-Host 'Installed local Native AudioLock node.'

    $patchPath = Join-Path $repo 'patches\comfyui-first-frame-center-crop.patch'
    & git -C $config.ComfyRoot apply --check --whitespace=nowarn $patchPath 2>$null
    if ($LASTEXITCODE -eq 0) {
        & git -C $config.ComfyRoot apply --whitespace=nowarn $patchPath
        if ($LASTEXITCODE -ne 0) { throw 'ComfyUI first-frame patch could not be applied.' }
    } else {
        & git -C $config.ComfyRoot apply --reverse --check --whitespace=nowarn $patchPath 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'ComfyUI is not at the expected patch base and is not already patched.' }
        Write-Host 'ComfyUI first-frame patch is already applied.'
    }

    if (-not (Test-Path -LiteralPath $config.Python -PathType Leaf)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $config.Python) -Force | Out-Null
        & py -3.12 -m venv (Join-Path $config.RuntimeRoot 'python')
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 virtual environment creation failed.' }
    }
    & $config.Python -m pip install --disable-pip-version-check --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip bootstrap failed.' }
    & $config.Python -m pip install --disable-pip-version-check --extra-index-url https://download.pytorch.org/whl/cu126 -r (Join-Path $repo 'manifests\python-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Pinned Python dependency installation failed.' }

    foreach ($model in $models.models) {
        if ([string]$model.source_repository -match '^https://huggingface\.co/([^/]+)/([^/]+)$') {
            $url = "$($model.source_repository)/resolve/$($model.revision)/$($model.source_path)?download=true"
        } elseif ([string]$model.source_repository -match '^https://github\.com/([^/]+)/([^/]+)$') {
            $url = "https://raw.githubusercontent.com/$($Matches[1])/$($Matches[2])/$($model.revision)/$($model.source_path)"
        } else {
            throw "Unsupported model source: $($model.source_repository)"
        }
        $targetDirectory = Resolve-ModelTargetDirectory -Model $model -Config $config
        $destination = Join-Path $targetDirectory ([string]$model.filename)
        Install-VerifiedDownload -Url $url -Destination $destination -ExpectedBytes ([int64]$model.bytes) -ExpectedSha256 ([string]$model.sha256)
    }

    $ref2vaTurbo = $models.models | Where-Object { $_.filename -eq 'minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors' }
    if (-not $ref2vaTurbo) { throw 'The model manifest is missing the Ref2VA Turbo LoRA entry.' }
    $ref2vaTurboPath = Join-Path (Join-Path $config.Models ([string]$ref2vaTurbo.target_directory)) ([string]$ref2vaTurbo.filename)
    Assert-VerifiedFile -Path $ref2vaTurboPath -ExpectedBytes ([int64]$ref2vaTurbo.bytes) -ExpectedSha256 ([string]$ref2vaTurbo.sha256)
    Write-Host "Verified Ref2VA Turbo LoRA: $ref2vaTurboPath"

    $localConfig = [ordered]@{
        runtime_root = $RuntimeRoot
        profile = $Profile.ToLowerInvariant()
        app = [ordered]@{ host = '127.0.0.1'; port = 8787 }
        comfy = [ordered]@{ host = '127.0.0.1'; port = 8190 }
        tailscale = [ordered]@{ enabled = (-not $SkipTailscale); scope = 'tailnet'; hostname = $hostname }
    }
    # Preserve explicit existing-ComfyUI paths when bootstrap is run against
    # an installed environment. Fresh installs remain portable by default.
    $existingConfigPath = Join-Path $repo 'config.local.json'
    $existingLocal = if (Test-Path -LiteralPath $existingConfigPath -PathType Leaf) {
        Get-JsonFile -Path $existingConfigPath
    } else {
        Get-JsonFile -Path (Join-Path $repo 'config.example.json')
    }
    if (-not $runtimeRootProvided -and $existingLocal.PSObject.Properties.Name -contains 'runtime_root' -and [string]$existingLocal.runtime_root) {
        $localConfig.runtime_root = [string]$existingLocal.runtime_root
    }
    if ($existingLocal.app.PSObject.Properties.Name -contains 'python' -and [string]$existingLocal.app.python) {
        $localConfig.app.python = [string]$existingLocal.app.python
    }
    foreach ($property in @('root', 'python', 'models', 'input', 'output', 'temp', 'user')) {
        if ($existingLocal.comfy.PSObject.Properties.Name -contains $property -and [string]$existingLocal.comfy.$property) {
            $localConfig.comfy[$property] = [string]$existingLocal.comfy.$property
        }
    }
    $localConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $repo 'config.local.json') -Encoding UTF8

    if (-not $SkipTailscale) {
        & $tailscale serve --bg --yes 8787
        if ($LASTEXITCODE -ne 0) { Write-Error 'Tailscale Serve could not be configured.'; exit 5 }
        $serveRaw = & $tailscale serve status --json 2>$null
        $serveText = $serveRaw -join [Environment]::NewLine
        if ($serveText -match '(?i)"?funnel"?\s*:\s*true') {
            throw 'Funnel is enabled; bootstrap refuses to continue.'
        }
    }

    Write-Host 'Bootstrap completed. Run scripts\doctor.ps1 -Deep, then scripts\start.ps1.'
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 4
}
