param([switch]$IncludeUntracked)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$paths = @(git -C $repo ls-files)
if ($IncludeUntracked) {
    $paths += @(git -C $repo ls-files --others --exclude-standard)
}
$patterns = @(
    '(?i)C:\\Users\\[^\\\r\n]+\\',
    '(?i)(?:100\.\d{1,3}\.\d{1,3}\.\d{1,3})',
    ('(?i)[a-z0-9-]+\.' + 'ts\.net'),
    ('(?i)(?:' + ('gh' + 'p_') + '|' + ('github' + '_pat_') + '|' + ('sk' + '-[a-z0-9]{20,}') + ')'),
    '-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----'
)
$hits = [System.Collections.Generic.List[object]]::new()
foreach ($relative in ($paths | Select-Object -Unique)) {
    $path = Join-Path $repo $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
    try { $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8 } catch { continue }
    foreach ($pattern in $patterns) {
        if ($text -match $pattern) {
            $hits.Add([pscustomobject]@{path=$relative; pattern=$pattern})
        }
    }
}
if ($hits.Count -gt 0) {
    $hits | ConvertTo-Json -Depth 5
    exit 2
}
Write-Host 'Secret and personal-data scan passed.'
exit 0
