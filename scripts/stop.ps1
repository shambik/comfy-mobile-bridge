$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
$pidPath = Join-Path $config.RuntimeRoot 'bridge.pid'
if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) { Write-Host 'No bridge PID file found.'; exit 0 }
$bridgePid = [int](Get-Content -LiteralPath $pidPath -Raw)
$bridge = Get-CimInstance Win32_Process -Filter "ProcessId=$bridgePid" -ErrorAction SilentlyContinue
if ($bridge -and ([string]$bridge.CommandLine -match [regex]::Escape($repo))) {
    $children = Get-CimInstance Win32_Process | Where-Object {
        $_.ParentProcessId -eq $bridgePid -and [string]$_.CommandLine -match [regex]::Escape($config.ComfyRoot)
    }
    foreach ($child in $children) {
        Stop-Process -Id ([int]$child.ProcessId) -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $bridgePid -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped bridge process $bridgePid and only its owned ComfyUI children."
} else {
    Write-Host 'PID file did not identify a bridge process; no process was stopped.'
}
Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
exit 0
