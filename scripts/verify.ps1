param([switch]$Deep)
& (Join-Path $PSScriptRoot 'doctor.ps1') -Deep:$Deep
exit $LASTEXITCODE
