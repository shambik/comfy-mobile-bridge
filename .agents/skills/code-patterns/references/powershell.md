# PowerShell safety pattern

    $ErrorActionPreference = 'Stop'
    $root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $target = Join-Path $root '.runtime'
    New-Item -ItemType Directory -LiteralPath $target -Force | Out-Null

Use -LiteralPath for user paths. Check the resolved target before recursive
operations. Use fixed exit codes and keep a failed .part file for resume.
