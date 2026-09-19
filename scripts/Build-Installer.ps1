[CmdletBinding()]
param(
    [string] $Configuration = 'Release',
    [string] $PortableDirectory = ""
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

function Find-WixExecutable {
    $cmd = Get-Command wix -ErrorAction SilentlyContinue
    $candidates = @()
    if ($cmd) { $candidates += $cmd.Source }
    $candidates += 'C:\Program Files\WiX Toolset v6.0\bin\wix.exe'
    $candidates += 'C:\Program Files (x86)\WiX Toolset v3.11\bin\candle.exe'
    return $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

$repoRoot = Resolve-RepoRoot
if ([string]::IsNullOrWhiteSpace($PortableDirectory)) {
    $PortableDirectory = Join-Path (Join-Path (Join-Path $repoRoot 'artifacts') 'staging') 'portable'
}
$installerDir = Join-Path (Join-Path $repoRoot 'build') 'Installer'
$releaseDir = Join-Path (Join-Path $repoRoot 'artifacts') 'release'
$msiPath = Join-Path $releaseDir 'JingXu.Workbench.msi'

if (-not (Test-Path $PortableDirectory)) {
    Write-Error "Portable directory not found: $PortableDirectory. Run scripts/Build-Portable.ps1 first."
    exit 1
}

if (-not (Test-Path $releaseDir)) { New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null }

$wix = Find-WixExecutable
if (-not $wix) {
    Write-Warning "BLOCKER: WiX Toolset not installed or not on PATH."
    Write-Warning "WiX sources are in build/Installer but installer build cannot run."
    exit 2
}

Write-Host "Using WiX: $wix"
$publishDir = (Resolve-Path $PortableDirectory).Path

if ($wix -like '*wix.exe') {
    Write-Host '=== Build MSI Installer ==='
    $productWxs = Join-Path $installerDir 'Product.wxs'
    $packageWxs = Join-Path $installerDir 'Package.wxs'
    $licenseFile = (Resolve-Path (Join-Path $installerDir 'License.rtf')).Path
    & $wix build $productWxs $packageWxs -ext WixToolset.UI.wixext -bindpath $installerDir -d PublishDir=$publishDir -d LicenseRtf=$licenseFile -o $msiPath -arch x64
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $namedMsiPath = Join-Path $releaseDir '炳恒快速混剪-win-x64.msi'
    Copy-Item $msiPath $namedMsiPath -Force
}
else {
    Write-Warning 'BLOCKER: Legacy candle/light detected. This repository requires WiX Toolset 6 (wix.exe).'
    exit 2
}

$msiHash = (Get-FileHash -Path $msiPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sumsContent = "$msiHash  炳恒快速混剪-win-x64.msi`r`n$msiHash  JingXu.Workbench.msi`r`n"

$releaseSums = Join-Path $releaseDir 'SHA256SUMS.txt'
Set-Content -Path $releaseSums -Value $sumsContent -Encoding UTF8

Write-Host "MSI Package generated: $namedMsiPath"
Write-Host "SHA-256 (MSI): $msiHash"

exit 0
