param(
    [string]$Range = '',
    [string]$Branch = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repo = Get-RepoRoot
$types = 'feat|fix|perf|refactor|docs|test|build|ci|chore|revert'
$scopes = 'app|backend|ui|bootstrap|comfy|models|tailscale|docs|tests|ci|deps|release'
$subjectPattern = "^($types)\(($scopes)\)!?: [a-z0-9][^.]{0,70}$"
$branchName = if ($Branch) { $Branch } else { (git -C $repo branch --show-current).Trim() }
if ($branchName -and $branchName -ne 'main' -and $branchName -notmatch "^($types)/[0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*$") {
    throw "Branch does not follow <type>/<issue-number>-<short-slug>: $branchName"
}
$subjects = if ($Range) { @(git -C $repo log $Range --format=%s) } else { @(git -C $repo log -1 --format=%s) }
foreach ($subject in $subjects) {
    if ($subject.Length -gt 72 -or $subject -notmatch $subjectPattern) {
        throw "Commit subject violates Git standards: $subject"
    }
}
foreach ($candidate in @('.runtime\probe.part', 'state\probe.log', 'config.local.json', 'models\probe.safetensors', 'logs\probe.log')) {
    git -C $repo check-ignore -q --no-index -- $candidate
    if ($LASTEXITCODE -ne 0) { throw "Required ignored path is not ignored: $candidate" }
}
Write-Host 'Git standards and ignore policy passed.'
exit 0
