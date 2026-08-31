[CmdletBinding()]
param(
    [string] $Configuration = 'Release',
    [switch] $SkipBuild,
    [switch] $SkipTests,
    [switch] $SkipPortable,
    [switch] $SkipInstaller
)

$ErrorActionPreference = 'Stop'

$ProhibitedPatterns = @(
    '\bTODO\b',
    '\bFIXME\b',
    '(?-i:\bLATER\b)',
    'placeholder button',
    'OPENAI_API_KEY'
)

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

function Invoke-Step([string] $Name, [scriptblock] $Action) {
    Write-Host "=== $Name ==="
    & $Action
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Test-PlaceholderScan([string] $RepoRoot) {
    $excludedDocumentationRoots = @(
        (Join-Path (Join-Path $RepoRoot 'docs') 'plans'),
        (Join-Path (Join-Path $RepoRoot 'docs') 'superpowers')
    )
    $targets = @(
        (Join-Path $RepoRoot 'README.md'),
        (Join-Path $RepoRoot 'THIRD_PARTY_NOTICES.md'),
        (Join-Path $RepoRoot 'docs'),
        (Join-Path $RepoRoot 'runtime')
    )

    $hits = @()
    foreach ($target in $targets) {
        if (-not (Test-Path $target)) { continue }
        if ((Get-Item $target).PSIsContainer) {
            $files = Get-ChildItem $target -Recurse -File -Include '*.md','*.txt','*.ps1'
        }
        else { $files = @(Get-Item $target) }

        foreach ($file in $files) {
            if ($excludedDocumentationRoots | Where-Object {
                $file.FullName.StartsWith($_ + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
            }) {
                continue
            }

            $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
            if (-not $content) { continue }
            foreach ($pattern in $ProhibitedPatterns) {
                if ($content -match $pattern) { $hits += "$($file.FullName): $pattern" }
            }
        }
    }

    if ($hits.Count -gt 0) {
        $hits | ForEach-Object { Write-Error "Prohibited marker: $_" }
        throw 'Placeholder scan failed.'
    }
}

function Test-RequiredArtifacts([string] $RepoRoot) {
    $releaseDir = Join-Path (Join-Path $RepoRoot 'artifacts') 'release'
    $required = @(
        (Join-Path $releaseDir '炳恒快速混剪-Portable-win-x64.zip'),
        (Join-Path $releaseDir '炳恒快速混剪-win-x64.msi'),
        (Join-Path $RepoRoot 'THIRD_PARTY_NOTICES.md'),
        (Join-Path (Join-Path $RepoRoot 'build') 'runtime-manifest.json')
    )
    foreach ($path in $required) {
        if (-not (Test-Path $path)) { throw "Missing release artifact or doc: $path" }
    }
    $zip = Join-Path $releaseDir '炳恒快速混剪-Portable-win-x64.zip'
    if ((Get-Item $zip).Length -eq 0) { throw 'Portable ZIP is zero bytes.' }
    $msi = Join-Path $releaseDir '炳恒快速混剪-win-x64.msi'
    if ((Get-Item $msi).Length -eq 0) { throw 'MSI package is zero bytes.' }
}

$repoRoot = Resolve-RepoRoot
$sln = Join-Path $repoRoot 'JingXu.Workbench.sln'
$dotnet = Join-Path $env:LOCALAPPDATA 'JingXu\dotnet\dotnet.exe'
if (-not (Test-Path $dotnet)) { $dotnet = 'dotnet' }

try {
    if (-not $SkipBuild) {
        Invoke-Step 'Restore' { & $dotnet restore $sln --locked-mode }
        Invoke-Step 'Build' { & $dotnet build $sln -c $Configuration --no-restore -m:1 }
    }

    if (-not $SkipTests) {
        Invoke-Step 'Tests' { & $dotnet test $sln -c $Configuration --no-build --logger "trx;LogFileName=release.trx" }
        $integrationTests = Join-Path (Join-Path $repoRoot 'tests') 'JingXu.Workbench.IntegrationTests'
        Invoke-Step 'Packaging tests' {
            & $dotnet test $integrationTests -c $Configuration --no-build --filter "FullyQualifiedName~Packaging"
        }
    }

    Invoke-Step 'Placeholder scan' { Test-PlaceholderScan $repoRoot }

    if (-not $SkipPortable) {
        Invoke-Step 'Portable build' {
            & (Join-Path $PSScriptRoot 'Build-Portable.ps1') -AllowPlaceholderHash -BootstrapFromPath
        }
    }

    if (-not $SkipInstaller) {
        Invoke-Step 'Installer build' {
            & (Join-Path $PSScriptRoot 'Build-Installer.ps1')
            if ($LASTEXITCODE -eq 2) {
                Write-Warning 'WiX not installed: installer build skipped (non-fatal).'
            }
            elseif ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 0) {
                Write-Warning "Installer build returned $LASTEXITCODE."
            }
        }
    }

    Invoke-Step 'Artifact check' { Test-RequiredArtifacts $repoRoot }
    Write-Host 'Release verification passed.'
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
