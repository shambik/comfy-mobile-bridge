# Bootstrap commands

    .\scripts\preflight.ps1 -Json
    .\scripts\bootstrap.ps1 -DryRun
    .\scripts\bootstrap.ps1 -Profile Full -AcceptLicenses
    .\scripts\doctor.ps1 -Deep
    .\scripts\start.ps1
    .\scripts\stop.ps1

Use Get-Content .\state\logs\*.log -Tail 80 for local diagnosis. Do not
restart while a generation is active; check the ComfyUI queue first.
