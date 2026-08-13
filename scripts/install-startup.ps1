$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$starter = Join-Path $PSScriptRoot 'start-bridge.ps1'
$taskName = 'H3 Mobile Bridge'
$pwsh = (Get-Command powershell.exe).Source
$action = New-ScheduledTaskAction -Execute $pwsh -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$starter`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Private local MiniMax H3 mobile bridge' -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State

