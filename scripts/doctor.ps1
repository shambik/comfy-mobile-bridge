param(
    [switch]$Deep,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$checks = [System.Collections.Generic.List[object]]::new()

function Add-DoctorCheck {
    param([string]$Name, [bool]$Passed, [string]$Detail, [int]$Code = 5)
    $checks.Add([pscustomobject]@{name=$Name; passed=$Passed; detail=$Detail; failure_code=$Code})
}

try {
    $config = Get-BridgeConfig -RepoRoot $repo
    Add-DoctorCheck 'local_config' $true $config.ConfigPath
    Add-DoctorCheck 'app_bind_policy' ($config.AppHost -eq '127.0.0.1') $config.AppHost
    Add-DoctorCheck 'comfy_bind_policy' ($config.ComfyHost -eq '127.0.0.1') $config.ComfyHost
    Add-DoctorCheck 'app_listener_local' (Test-LocalOnlyListener -Port $config.AppPort) "127.0.0.1:$($config.AppPort)"
    Add-DoctorCheck 'comfy_listener_local' (Test-LocalOnlyListener -Port $config.ComfyPort) "127.0.0.1:$($config.ComfyPort)"

    $deps = Get-JsonFile -Path (Join-Path $repo 'manifests\dependencies.json')
    $templateTarget = $deps.repositories | Where-Object { $_.name -eq 'Official workflow templates' }
    if ($templateTarget) {
        $templatePath = Resolve-ManifestTarget -Target ([string]$templateTarget.target) -Config $config -RepoRoot $repo
        if (-not (Test-Path -LiteralPath $templatePath -PathType Container)) {
            Write-Verbose "Official workflow templates are optional for the bridge health check: $templatePath"
        }
    }
    foreach ($item in $deps.repositories) {
        $target = Resolve-ManifestTarget -Target ([string]$item.target) -Config $config -RepoRoot $repo
        $head = if (Test-Path -LiteralPath $target) { (& git -C $target rev-parse HEAD 2>$null).Trim() } else { '' }
        $optionalTemplate = $item.name -eq 'Official workflow templates'
        $passed = $head -eq [string]$item.revision -or ($optionalTemplate -and -not (Test-Path -LiteralPath $target))
        $detail = if ($optionalTemplate -and -not (Test-Path -LiteralPath $target)) { 'optional template checkout not present' } else { "expected=$($item.revision), actual=$head" }
        Add-DoctorCheck "pin_$($item.name)" $passed $detail 4
    }

    $models = Get-JsonFile -Path (Join-Path $repo 'manifests\models.json')
    foreach ($model in $models.models) {
        $path = Resolve-ModelTargetDirectory -Model $model -Config $config
        $path = Join-Path $path ([string]$model.filename)
        if ($Deep) {
            try { Assert-VerifiedFile -Path $path -ExpectedBytes ([int64]$model.bytes) -ExpectedSha256 ([string]$model.sha256); Add-DoctorCheck "model_$($model.filename)" $true 'size and SHA-256 verified' 4 }
            catch { Add-DoctorCheck "model_$($model.filename)" $false $_.Exception.Message 4 }
        } else {
            Add-DoctorCheck "model_$($model.filename)" (Test-Path -LiteralPath $path -PathType Leaf) $path 4
        }
    }

    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($config.AppPort)/api/health" -TimeoutSec 10
        $version = if ($health.PSObject.Properties.Name -contains 'version') { [string]$health.version } else { 'missing' }
        Add-DoctorCheck 'bridge_health' ($health.ok -eq $true -and $version -ne 'missing') ("version=$version") 5
    } catch {
        Add-DoctorCheck 'bridge_health' $false $_.Exception.Message 5
    }

    if ($Deep) {
        try {
            $objectInfo = Invoke-RestMethod -Uri "http://127.0.0.1:$($config.ComfyPort)/object_info" -TimeoutSec 20
            $required = @('MiniMaxH3ImageToVideo', 'MiniMaxH3ReferenceToVideo', 'MiniMaxH3TurboSampler', 'MiniMaxH3SigmaShift', 'ResolutionSelector', 'ComfyMathExpression')
            foreach ($node in $required) { Add-DoctorCheck "node_$node" ($null -ne $objectInfo.$node) 'loaded' 5 }
        } catch {
            Add-DoctorCheck 'comfy_object_info' $false $_.Exception.Message 5
        }
    }

    if ($config.TailscaleEnabled) {
        $tailscale = Get-TailscaleExe
        if (-not $tailscale) {
            Add-DoctorCheck 'tailscale_installed' $false 'not found' 2
        } else {
            $status = Get-TailscaleStatusObject -Executable $tailscale
            $running = $status -and [string]$status.BackendState -eq 'Running'
            Add-DoctorCheck 'tailscale_logged_in' $running $(if ($status) { [string]$status.BackendState } else { 'status unavailable' }) 3
            $hostname = if ($status -and $status.Self) { ([string]$status.Self.DNSName).TrimEnd('.') } else { '' }
            Add-DoctorCheck 'tailscale_hostname' ([bool]$hostname) $hostname 3
            $serveRaw = & $tailscale serve status --json 2>$null
            $serveText = $serveRaw -join [Environment]::NewLine
            Add-DoctorCheck 'tailscale_serve' ($serveText -match [regex]::Escape("127.0.0.1:$($config.AppPort)")) $serveText 5
            Add-DoctorCheck 'tailscale_no_funnel' ($serveText -notmatch '(?i)"?funnel"?\s*:\s*true') 'Funnel disabled' 5
        }
    }
} catch {
    Add-DoctorCheck 'doctor_script' $false $_.Exception.Message 5
}

$failed = @($checks | Where-Object { -not $_.passed })
$result = [pscustomobject]@{ok=($failed.Count -eq 0); deep=$Deep.IsPresent; checks=$checks; exit_code=0}
if ($failed.Count -gt 0) {
    $codes = @($failed | ForEach-Object { [int]$_.failure_code })
    $result.exit_code = if ($codes -contains 5) { 5 } elseif ($codes -contains 4) { 4 } elseif ($codes -contains 3) { 3 } else { 2 }
}
if ($Json) { Write-JsonResult $result } else { $result | Format-List }
exit $result.exit_code
