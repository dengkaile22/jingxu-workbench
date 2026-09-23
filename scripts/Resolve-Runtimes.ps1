[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $CacheDirectory,

    [string] $ManifestPath = "",
    [string] $OutputDirectory = "",

    [switch] $AllowPlaceholderHash,
    [switch] $PrintHashes,
    [switch] $BootstrapFromPath
)

$ErrorActionPreference = 'Stop'

$PlaceholderSha256 = '0000000000000000000000000000000000000000000000000000000000000000'

function Resolve-RepoRoot {
    $dir = (Resolve-Path $PSScriptRoot).Path
    while ($dir) {
        if (Test-Path (Join-Path $dir 'build\runtime-manifest.json')) { return $dir }
        $parent = Split-Path $dir -Parent
        if ($parent -eq $dir) { break }
        $dir = $parent
    }
    throw 'Cannot locate repository root.'
}

function Get-FileSha256([string] $Path) {
    $hash = Get-FileHash -Path $Path -Algorithm SHA256
    return $hash.Hash.ToLowerInvariant()
}

function Find-PathExecutable([string] $ToolName) {
    if ($env:OS -like '*Windows*') { $name = "$ToolName.exe" } else { $name = $ToolName }
    $pathEnv = [Environment]::GetEnvironmentVariable('PATH')
    if ([string]::IsNullOrWhiteSpace($pathEnv)) { return $null }
    foreach ($dir in $pathEnv.Split(';')) {
        if ([string]::IsNullOrWhiteSpace($dir)) { continue }
        $candidate = Join-Path $dir.Trim() $name
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Ensure-CacheFile([string] $RelativePath, [string] $Kind, [bool] $Required) {
    $cacheFile = Join-Path $CacheDirectory ($RelativePath -replace '/', '\')
    if (Test-Path $cacheFile) { return $cacheFile }

    if (-not $BootstrapFromPath) {
        if (-not $Required) {
            $parent = Split-Path $cacheFile -Parent
            if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
            [IO.File]::WriteAllBytes($cacheFile, [byte[]](0x00))
            Write-Warning "Created optional stub: $cacheFile"
            return $cacheFile
        }
        throw "Missing cache file: $RelativePath in $CacheDirectory"
    }

    $tool = $null
    if ($RelativePath -match 'ffmpeg/ffmpeg\.exe$') { $tool = 'ffmpeg' }
    elseif ($RelativePath -match 'ffmpeg/ffprobe\.exe$') { $tool = 'ffprobe' }
    elseif ($RelativePath -match 'whisper/whisper-cli\.exe$') { $tool = 'whisper-cli' }
    elseif ($RelativePath -match 'tesseract/tesseract\.exe$') { $tool = 'tesseract' }

    if ($tool) {
        $source = Find-PathExecutable $tool
        if ($source) {
            $parent = Split-Path $cacheFile -Parent
            if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
            Copy-Item -Path $source -Destination $cacheFile -Force
            Write-Host "Bootstrapped from PATH: $source -> $cacheFile"
            return $cacheFile
        }
    }

    if ($Kind -eq 'WhisperModel' -or -not $Required) {
        $parent = Split-Path $cacheFile -Parent
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        [IO.File]::WriteAllBytes($cacheFile, [byte[]](0x00))
        Write-Warning "Created optional stub: $cacheFile"
        return $cacheFile
    }

    throw "Missing cache file and PATH bootstrap failed: $RelativePath"
}

$repoRoot = Resolve-RepoRoot
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path (Join-Path $repoRoot 'build') 'runtime-manifest.json'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path (Join-Path (Join-Path $repoRoot 'artifacts') 'staging') 'runtime'
}
if (-not [IO.Path]::IsPathRooted($ManifestPath)) { $ManifestPath = Join-Path $repoRoot $ManifestPath }
if (-not [IO.Path]::IsPathRooted($OutputDirectory)) { $OutputDirectory = Join-Path $repoRoot $OutputDirectory }

if (-not (Test-Path $ManifestPath)) { throw "Manifest not found: $ManifestPath" }
if (-not (Test-Path $CacheDirectory)) { throw "Cache directory not found: $CacheDirectory" }

$manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
if (-not $manifest.components) { throw 'Manifest has no components.' }

if ($PrintHashes) { Write-Host '=== Cache SHA-256 hashes ===' }
if (Test-Path $OutputDirectory) { Remove-Item -Path $OutputDirectory -Recurse -Force }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$failures = @()
foreach ($component in $manifest.components) {
    $relative = $component.relativePath
    $display = $component.displayName
    $expectedHash = $component.sha256
    $kind = $component.kind
    $required = [bool]$component.required

    try { $source = Ensure-CacheFile $relative $kind $required }
    catch {
        $failures += "$display : $($_.Exception.Message)"
        continue
    }

    $actualHash = Get-FileSha256 $source
    if ($PrintHashes) {
        Write-Host "$relative  $actualHash"
        continue
    }

    if ([string]::IsNullOrWhiteSpace($expectedHash)) {
        $failures += "$display : missing sha256 in manifest"
        continue
    }

    if ($expectedHash -eq $PlaceholderSha256) {
        if (-not $AllowPlaceholderHash) {
            $failures += "$display : placeholder sha256; run -PrintHashes or use -AllowPlaceholderHash"
            continue
        }
        Write-Warning "$display : accepting placeholder sha256 (dev only)"
    }
    elseif ($actualHash -ne $expectedHash.ToLowerInvariant()) {
        $failures += "$display : hash mismatch expected $expectedHash actual $actualHash"
        continue
    }

    $destination = Join-Path $OutputDirectory ($relative -replace '/', '\')
    $destParent = Split-Path $destination -Parent
    if (-not (Test-Path $destParent)) { New-Item -ItemType Directory -Path $destParent -Force | Out-Null }
    Copy-Item -Path $source -Destination $destination -Force
    Write-Host "Staged: $relative"

    # whisper-cli 依赖同目录的 ggml/whisper DLL 与运行库，整目录一起暂存。
    if ($relative -match 'whisper/whisper-cli\.exe$') {
        $sourceDirectory = Split-Path $source -Parent
        Get-ChildItem -Path $sourceDirectory -File | Where-Object { $_.Extension -in '.dll', '.json' } | ForEach-Object {
            Copy-Item -Path $_.FullName -Destination (Join-Path $destParent $_.Name) -Force
        }
        Write-Host "Staged: whisper 运行库（DLL）"
    }
}

if ($PrintHashes) { exit 0 }
if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "Runtime staging complete: $OutputDirectory"
exit 0
