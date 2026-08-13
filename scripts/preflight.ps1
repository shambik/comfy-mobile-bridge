param(
    [switch]$Json,
    [ValidateSet('Full')][string]$Profile = 'Full',
    [switch]$SkipGpu,
    [switch]$SkipTailscale
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$checks = [System.Collections.Generic.List[object]]::new()
$actions = [System.Collections.Generic.List[string]]::new()

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail, [int]$FailureCode = 2)
    $checks.Add([pscustomobject]@{name=$Name; passed=$Passed; detail=$Detail; failure_code=$FailureCode})
}

try {
    $windows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
    Add-Check 'windows' $windows ([Environment]::OSVersion.VersionString)
    if ($windows) {
        $os = Get-CimInstance Win32_OperatingSystem
        Add-Check 'x64' ([Environment]::Is64BitOperatingSystem) $os.OSArchitecture
        $version = [version]$os.Version
        Add-Check 'windows_version' ($version.Major -ge 10) $os.Caption
        $ram = Get-CimInstance Win32_ComputerSystem
        $ramGb = [math]::Round($ram.TotalPhysicalMemory / 1e9, 1)
        $ramGiB = [math]::Round($ram.TotalPhysicalMemory / 1GB, 1)
        Add-Check 'ram_32_gib' ($ram.TotalPhysicalMemory -ge [int64]32000000000) "$ramGiB GiB ($ramGb GB) detected"
        $drive = (Split-Path -Qualifier $repo).TrimEnd(':')
        $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($drive):'"
        $freeGiB = [math]::Round($disk.FreeSpace / 1GB, 1)
        Add-Check 'free_disk_100_gib' ($freeGiB -ge 100) "$freeGiB GiB free on $($drive):"
    }

    foreach ($tool in @('git', 'node', 'npm', 'ffmpeg', 'ffprobe', 'curl')) {
        $lookup = if ($tool -eq 'curl') { 'curl.exe' } else { $tool }
        $command = Get-Command $lookup -ErrorAction SilentlyContinue
        Add-Check "tool_$tool" ([bool]$command) $(if ($command) { $command.Source } else { 'not found' })
    }

    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) {
        $pythonVersion = (& $python.Source -3.12 --version 2>&1 | Out-String).Trim()
        Add-Check 'python_3_12' ($LASTEXITCODE -eq 0 -and $pythonVersion -match 'Python 3\.12\.') $pythonVersion
    } else {
        Add-Check 'python_3_12' $false 'py launcher not found'
    }

    $nodeVersion = (& node --version 2>$null).Trim()
    $nodeMajor = 0
    if ($nodeVersion -match '^v(\d+)') { $nodeMajor = [int]$Matches[1] }
    Add-Check 'node_22' ($nodeMajor -eq 22) $nodeVersion

    if (-not $SkipGpu) {
        $gpuOutput = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null
        $gpuOk = $LASTEXITCODE -eq 0 -and [bool]$gpuOutput
        $vram = 0
        if ($gpuOutput -and ([string]$gpuOutput -match ',\s*(\d+)')) { $vram = [int]$Matches[1] }
        Add-Check 'nvidia_gpu' $gpuOk ([string]$gpuOutput)
        Add-Check 'vram_8_gib' ($gpuOk -and $vram -ge 7680) "$vram MiB detected"
    } else {
        Add-Check 'nvidia_gpu' $true 'skipped'
        Add-Check 'vram_8_gib' $true 'skipped'
    }

    $configPath = Join-Path $repo 'config.local.json'
    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        try { $null = Get-BridgeConfig -RepoRoot $repo; Add-Check 'local_config' $true $configPath } catch { Add-Check 'local_config' $false $_.Exception.Message }
    } else {
        Add-Check 'local_config' $true 'not created yet; bootstrap will generate it'
    }

    if (-not $SkipTailscale) {
        $tailscale = Get-TailscaleExe
        Add-Check 'tailscale_installed' ([bool]$tailscale) $(if ($tailscale) { $tailscale } else { 'not found' })
        if ($tailscale) {
            $status = Get-TailscaleStatusObject -Executable $tailscale
            $running = $status -and [string]$status.BackendState -eq 'Running'
            Add-Check 'tailscale_logged_in' $running $(if ($status) { [string]$status.BackendState } else { 'status unavailable' }) 3
            $hostname = if ($status -and $status.Self) { ([string]$status.Self.DNSName).TrimEnd('.') } else { '' }
            Add-Check 'tailscale_hostname' ([bool]$hostname) $(if ($hostname) { $hostname } else { 'not available' }) 3
        }
    } else {
        Add-Check 'tailscale_installed' $true 'skipped'
        Add-Check 'tailscale_logged_in' $true 'skipped'
        Add-Check 'tailscale_hostname' $true 'skipped'
    }
} catch {
    Add-Check 'preflight_script' $false $_.Exception.Message
}

$failed = @($checks | Where-Object { -not $_.passed })
$result = [pscustomobject]@{
    ok = ($failed.Count -eq 0)
    profile = $Profile
    checks = $checks
    actions = $actions
    exit_code = 0
}
if ($failed.Count -gt 0) {
    $result.exit_code = if (@($failed | Where-Object { $_.failure_code -eq 3 }).Count -gt 0) { 3 } else { 2 }
}
if ($Json) { Write-JsonResult $result } else { $result | Format-List }
exit $result.exit_code
