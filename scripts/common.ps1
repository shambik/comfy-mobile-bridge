Set-StrictMode -Version Latest

function Get-RepoRoot {
    return [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
}

function Get-JsonFile {
    param([Parameter(Mandatory)][string]$Path)
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Invalid JSON file: $Path"
    }
}

function Resolve-LocalPath {
    param(
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)][string]$BasePath
    )
    if ([IO.Path]::IsPathRooted($Value)) { return [IO.Path]::GetFullPath($Value) }
    return [IO.Path]::GetFullPath((Join-Path $BasePath $Value))
}

function Get-BridgeConfig {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [string]$RuntimeRootOverride
    )
    $localPath = Join-Path $RepoRoot 'config.local.json'
    if (Test-Path -LiteralPath $localPath -PathType Leaf) {
        $local = Get-JsonFile -Path $localPath
    } else {
        $local = Get-JsonFile -Path (Join-Path $RepoRoot 'config.example.json')
    }
    $runtimeValue = if ($RuntimeRootOverride) { $RuntimeRootOverride } else { [string]$local.runtime_root }
    $runtime = if ([IO.Path]::IsPathRooted($runtimeValue)) {
        [IO.Path]::GetFullPath($runtimeValue)
    } else {
        Resolve-LocalPath -Value $runtimeValue -BasePath $RepoRoot
    }
    $comfy = $local.comfy
    $usePortableOverride = [bool]$RuntimeRootOverride
    $comfyRootValue = if (-not $usePortableOverride -and $comfy.PSObject.Properties.Name -contains 'root') { [string]$comfy.root } else { '' }
    $pythonValue = if (-not $usePortableOverride -and $comfy.PSObject.Properties.Name -contains 'python') { [string]$comfy.python } else { '' }
    $modelsValue = if (-not $usePortableOverride -and $comfy.PSObject.Properties.Name -contains 'models') { [string]$comfy.models } else { '' }
    $comfyRoot = if ($comfyRootValue) { Resolve-LocalPath -Value $comfyRootValue -BasePath $runtime } else { Join-Path $runtime 'comfyui' }
    $python = if ($pythonValue) { Resolve-LocalPath -Value $pythonValue -BasePath $runtime } else { Join-Path $runtime 'python\Scripts\python.exe' }
    $models = if ($modelsValue) { Resolve-LocalPath -Value $modelsValue -BasePath $runtime } else { Join-Path $runtime 'models' }
    if (([string]$local.app.host -ne '127.0.0.1' -and [string]$local.app.host -ne '0.0.0.0') -or [string]$local.comfy.host -ne '127.0.0.1') {
        throw 'comfy.host must be 127.0.0.1; app.host may be 127.0.0.1 or 0.0.0.0'
    }
    if ([int]$local.app.port -lt 1 -or [int]$local.comfy.port -lt 1) {
        throw 'app and ComfyUI ports must be positive'
    }
    $hostname = if ($local.tailscale.PSObject.Properties.Name -contains 'hostname') { [string]$local.tailscale.hostname } else { '' }
    $bridgePythonValue = if ($local.app.PSObject.Properties.Name -contains 'python') { [string]$local.app.python } else { '' }
    return [pscustomobject]@{
        RepoRoot = $RepoRoot
        RuntimeRoot = [IO.Path]::GetFullPath($runtime)
        ComfyRoot = [IO.Path]::GetFullPath($comfyRoot)
        Python = [IO.Path]::GetFullPath($python)
        BridgePython = if ($bridgePythonValue) { Resolve-LocalPath -Value $bridgePythonValue -BasePath $RepoRoot } else { [IO.Path]::GetFullPath($python) }
        Models = [IO.Path]::GetFullPath($models)
        AppHost = [string]$local.app.host
        AppPort = [int]$local.app.port
        ComfyHost = [string]$local.comfy.host
        ComfyPort = [int]$local.comfy.port
        TailscaleEnabled = [bool]$local.tailscale.enabled
        TailscaleHostname = $hostname
        ConfigPath = $localPath
    }
}

function Resolve-ManifestTarget {
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)]$Config,
        [Parameter(Mandatory)][string]$RepoRoot
    )
    $normalized = $Target.Replace('/', '\')
    if ($normalized -eq '.runtime\comfyui') { return $Config.ComfyRoot }
    if ($normalized.StartsWith('.runtime\comfyui\')) {
        return Join-Path $Config.ComfyRoot $normalized.Substring('.runtime\comfyui\'.Length)
    }
    if ($normalized.StartsWith('.runtime\')) {
        return Join-Path $Config.RuntimeRoot $normalized.Substring('.runtime\'.Length)
    }
    return Join-Path $RepoRoot $normalized
}

function Resolve-ModelTargetDirectory {
    param(
        [Parameter(Mandatory)]$Model,
        [Parameter(Mandatory)]$Config
    )
    $target = ([string]$Model.target_directory).Replace('/', '\')
    $root = if ($Model.PSObject.Properties.Name -contains 'target_root') { [string]$Model.target_root } else { 'models' }
    if ($root -eq 'runtime' -and $target.StartsWith('comfyui\custom_nodes\')) {
        return Join-Path $Config.ComfyRoot $target.Substring('comfyui\'.Length)
    }
    if ($root -eq 'state') { return Join-Path (Join-Path $Config.RepoRoot 'state') $target }
    $base = if ($root -eq 'runtime') { $Config.RuntimeRoot } else { $Config.Models }
    return Join-Path $base $target
}

function Get-ManifestItemGroups {
    param([Parameter(Mandatory)]$Item)
    if ($Item.PSObject.Properties.Name -contains 'groups') { return @($Item.groups | ForEach-Object { [string]$_ }) }
    if ($Item.PSObject.Properties.Name -contains 'group') { return @([string]$Item.group) }
    return @('h3')
}

function Resolve-ManifestGroups {
    # The requested groups (or every default group) plus the groups they need; h3 always.
    param([Parameter(Mandatory)]$Models, [string[]]$Requested)
    $known = @($Models.groups.PSObject.Properties.Name)
    $wanted = if ($Requested) {
        @($Requested | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    } else {
        @($known | Where-Object { $Models.groups.$_.default })
    }
    $unknown = @($wanted | Where-Object { $known -notcontains $_ })
    if ($unknown) { throw "Unknown group(s): $($unknown -join ', '). Known: $($known -join ', ')" }
    $result = [System.Collections.Generic.List[string]]::new()
    $queue = [System.Collections.Generic.Queue[string]]::new()
    foreach ($group in @('h3') + $wanted) { $queue.Enqueue($group) }
    while ($queue.Count) {
        $group = $queue.Dequeue()
        if ($result.Contains($group)) { continue }
        $result.Add($group)
        foreach ($need in @($Models.groups.$group.needs)) { if ($need) { $queue.Enqueue([string]$need) } }
    }
    return @($known | Where-Object { $result.Contains($_) })
}

function Test-ManifestItemSelected {
    param([Parameter(Mandatory)]$Item, [Parameter(Mandatory)][string[]]$Selected)
    return [bool](Get-ManifestItemGroups -Item $Item | Where-Object { $Selected -contains $_ })
}

function Get-ManifestDownloadUrl {
    # Hugging Face resolve URL at the pinned revision, a GitHub release asset, or a raw GitHub file at the revision.
    param([Parameter(Mandatory)]$Item)
    $source = [string]$Item.source_repository
    if ($source -match '^https://huggingface\.co/([^/]+)/([^/]+)$') {
        return "$source/resolve/$($Item.revision)/$($Item.source_path)?download=true"
    }
    if ($source -match '^https://github\.com/([^/]+)/([^/]+)$') {
        if ($Item.PSObject.Properties.Name -contains 'release_tag') {
            return "$source/releases/download/$($Item.release_tag)/$($Item.source_path)"
        }
        return "https://raw.githubusercontent.com/$($Matches[1])/$($Matches[2])/$($Item.revision)/$($Item.source_path)"
    }
    throw "Unsupported model source: $source"
}

function Get-TailscaleExe {
    $command = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $known = @(
        (Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'),
        (Join-Path $env:LOCALAPPDATA 'Tailscale\tailscale.exe')
    )
    foreach ($path in $known) {
        if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) { return $path }
    }
    return $null
}

function Get-TailscaleStatusObject {
    param([Parameter(Mandatory)][string]$Executable)
    $raw = & $Executable status --json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
    try { return ($raw -join [Environment]::NewLine | ConvertFrom-Json) } catch { return $null }
}

function Get-TailscaleHostname {
    param([Parameter(Mandatory)][string]$Executable)
    $status = Get-TailscaleStatusObject -Executable $Executable
    if (-not $status -or -not $status.Self) { return $null }
    return ([string]$status.Self.DNSName).TrimEnd('.')
}

function Get-FileSha256Lower {
    param([Parameter(Mandatory)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-VerifiedFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][Int64]$ExpectedBytes,
        [Parameter(Mandatory)][string]$ExpectedSha256
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "File is missing: $Path"
    }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne $ExpectedBytes) {
        throw "Wrong file size for $Path. Expected $ExpectedBytes, got $($item.Length)."
    }
    $actual = Get-FileSha256Lower -Path $Path
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "Wrong SHA-256 for $Path. Expected $ExpectedSha256, got $actual."
    }
}

function Install-VerifiedDownload {
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][Int64]$ExpectedBytes,
        [Parameter(Mandatory)][string]$ExpectedSha256
    )
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        Assert-VerifiedFile -Path $Destination -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256
        Write-Host "Verified existing file: $Destination"
        return
    }
    $partial = "$Destination.part"
    if (Test-Path -LiteralPath $partial -PathType Leaf) {
        if ((Get-Item -LiteralPath $partial).Length -gt $ExpectedBytes) {
            throw "The partial file is larger than expected and was not changed: $partial"
        }
    }
    # Gated Hugging Face repositories (LTX-2.5) need the user's token after they accept the terms on the model page.
    # It reaches curl through a header file that is deleted right after, never on the command line.
    $headerFile = $null
    $curlArgs = @('--location', '--fail', '--retry', '8', '--retry-delay', '3', '--continue-at', '-', '--output', $partial)
    if ($env:HF_TOKEN -and $Url.StartsWith('https://huggingface.co/')) {
        $headerFile = Join-Path ([IO.Path]::GetTempPath()) ('hf-header-' + [guid]::NewGuid().ToString('N') + '.txt')
        Set-Content -LiteralPath $headerFile -Value ('Authorization: Bearer ' + $env:HF_TOKEN) -Encoding ascii -NoNewline
        $curlArgs += @('--header', "@$headerFile")
    }
    try {
        & curl.exe @curlArgs $Url
        $curlExit = $LASTEXITCODE
    } finally {
        if ($headerFile) { Remove-Item -LiteralPath $headerFile -Force -ErrorAction SilentlyContinue }
    }
    if ($curlExit -ne 0) {
        $hint = if ($Url.StartsWith('https://huggingface.co/') -and -not $env:HF_TOKEN) {
            ' If the repository is gated, accept its terms on Hugging Face and set HF_TOKEN.'
        } else { '' }
        throw "Download failed for $Destination. The .part file was preserved for resume.$hint"
    }
    Assert-VerifiedFile -Path $partial -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        Assert-VerifiedFile -Path $Destination -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256
        Remove-Item -LiteralPath $partial -Force
        Write-Host "Verified existing file after download race: $Destination"
        return
    }
    Move-Item -LiteralPath $partial -Destination $Destination
    Write-Host "Installed verified file: $Destination"
}

function Test-LocalOnlyListener {
    param([Parameter(Mandatory)][int]$Port)
    $connections = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $connections) { return $false }
    return -not ($connections | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') })
}

function Write-JsonResult {
    param([Parameter(Mandatory)]$Value)
    $Value | ConvertTo-Json -Depth 12
}
