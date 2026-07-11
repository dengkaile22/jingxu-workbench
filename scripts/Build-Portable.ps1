[CmdletBinding()]
param(
    [string] $Configuration = 'Release',
    [string] $RuntimeCacheDirectory = "",
    [switch] $AllowPlaceholderHash,
    [switch] $BootstrapFromPath
)

$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    $dir = (Resolve-Path $PSScriptRoot).Path
    while ($dir) {
        if (Test-Path (Join-Path $dir 'JingXu.Workbench.sln')) { return $dir }
        $parent = Split-Path $dir -Parent
        if ($parent -eq $dir) { break }
        $dir = $parent
    }
    throw 'Cannot locate repository root.'
}

function Copy-Tree([string] $Source, [string] $Destination) {
    if (-not (Test-Path $Source)) { return }
    if (-not (Test-Path $Destination)) { New-Item -ItemType Directory -Path $Destination -Force | Out-Null }
    & robocopy $Source $Destination /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed from $Source to $Destination with exit code $LASTEXITCODE" }
}

$repoRoot = Resolve-RepoRoot
$artifactsRoot = Join-Path $repoRoot 'artifacts'
$publishDir = Join-Path (Join-Path (Join-Path $artifactsRoot 'publish') 'win-x64')
$portableDir = Join-Path (Join-Path (Join-Path $artifactsRoot 'staging') 'portable')
$releaseDir = Join-Path $artifactsRoot 'release'
$zipPath = Join-Path $releaseDir 'JingXu-Workbench-Portable-win-x64.zip'
$srcRoot = Join-Path $repoRoot 'src'
$project = Join-Path (Join-Path (Join-Path $srcRoot 'JingXu.Workbench') 'JingXu.Workbench.csproj')

if ([string]::IsNullOrWhiteSpace($RuntimeCacheDirectory)) {
    $RuntimeCacheDirectory = Join-Path $repoRoot 'runtime'
}

Write-Host '=== Publish self-contained app ==='
dotnet publish $project -c $Configuration -r win-x64 --self-contained true -p:PublishTrimmed=false -p:PublishSingleFile=false -p:DebugType=None -p:DebugSymbols=false -o $publishDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '=== Stage runtime ==='
$resolveScript = Join-Path $PSScriptRoot 'Resolve-Runtimes.ps1'
$resolveParams = @{
    CacheDirectory = (Resolve-Path $RuntimeCacheDirectory).Path
}
if ($AllowPlaceholderHash) { $resolveParams['AllowPlaceholderHash'] = $true }
if ($BootstrapFromPath) { $resolveParams['BootstrapFromPath'] = $true }
& $resolveScript @resolveParams
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$stagedRuntime = Join-Path (Join-Path (Join-Path $artifactsRoot 'staging') 'runtime')
$publishRuntime = Join-Path $publishDir 'runtime'
if (Test-Path $publishRuntime) { Remove-Item $publishRuntime -Recurse -Force }
Copy-Tree $stagedRuntime $publishRuntime

foreach ($notice in @('README.md', 'THIRD_PARTY_NOTICES.md')) {
    $src = Join-Path $repoRoot $notice
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $publishDir $notice) -Force
    }
}

Write-Host '=== Assemble portable directory ==='
if (Test-Path $portableDir) { Remove-Item $portableDir -Recurse -Force }
New-Item -ItemType Directory -Path $portableDir -Force | Out-Null
Copy-Tree $publishDir $portableDir

$excludePatterns = @('*.pdb', '*Tests.dll', '*testhost*', 'coverlet.*')
Get-ChildItem -Path $portableDir -Recurse -File | Where-Object {
    $name = $_.Name
    foreach ($pattern in $excludePatterns) {
        if ($name -like $pattern) { return $true }
    }
    return $false
} | Remove-Item -Force

Write-Host '=== Create ZIP ==='
if (-not (Test-Path $releaseDir)) { New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null }
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($portableDir, $zipPath, [System.IO.Compression.CompressionLevel]::Optimal, $false)

$hash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sumsPath = Join-Path $releaseDir 'SHA256SUMS.txt'
$line = "$hash  JingXu-Workbench-Portable-win-x64.zip"
if (Test-Path $sumsPath) {
    $existing = Get-Content $sumsPath | Where-Object { $_ -notmatch 'JingXu-Workbench-Portable-win-x64\.zip' }
    @($existing + $line) | Set-Content $sumsPath -Encoding UTF8
}
else {
    Set-Content -Path $sumsPath -Value $line -Encoding UTF8
}

Write-Host "Portable package: $zipPath"
Write-Host "SHA-256: $hash"
exit 0
