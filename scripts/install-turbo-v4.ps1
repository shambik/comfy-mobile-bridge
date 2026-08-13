Write-Warning 'Turbo v4 is pinned in manifests and installed by bootstrap.ps1.'
& (Join-Path $PSScriptRoot 'bootstrap.ps1') -Profile Full -AcceptLicenses
exit $LASTEXITCODE
