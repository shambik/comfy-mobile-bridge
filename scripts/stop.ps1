$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$config = Get-BridgeConfig -RepoRoot $repo
$pidPath = Join-Path $config.RuntimeRoot 'bridge.pid'
if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) { Write-Host 'No bridge PID file found.'; exit 0 }
$bridgePid = [int](Get-Content -LiteralPath $pidPath -Raw)
$bridge = Get-CimInstance Win32_Process -Filter "ProcessId=$bridgePid" -ErrorAction SilentlyContinue
if ($bridge -and ([string]$bridge.CommandLine -match [regex]::Escape($repo))) {
    $runScript = [regex]::Escape((Join-Path $repo 'run.py'))
    # A Windows venv python.exe is a launcher and can start the real Python as
    # a child. Stopping only the PID recorded by start.ps1 leaves that child
    # serving the old bridge code on port 8787. Stop only processes whose own
    # command line identifies this repository's run.py; never match or stop
    # the separately managed ComfyUI main.py process.
    $bridgeProcesses = @(Get-CimInstance Win32_Process | Where-Object {
        ([int]$_.ProcessId -eq $bridgePid -or [int]$_.ParentProcessId -eq $bridgePid) -and
        [string]$_.CommandLine -match $runScript
    } | Sort-Object { if ([int]$_.ProcessId -eq $bridgePid) { 1 } else { 0 } })
    foreach ($process in $bridgeProcesses) {
        Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped $($bridgeProcesses.Count) bridge process(es). ComfyUI was left running."
} else {
    Write-Host 'PID file did not identify a bridge process; no process was stopped.'
}
Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
exit 0
