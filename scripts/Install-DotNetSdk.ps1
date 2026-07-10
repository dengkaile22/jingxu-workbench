[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$installDirectory = Join-Path $env:LOCALAPPDATA 'JingXu\dotnet'
$dotnetPath = [System.IO.Path]::GetFullPath((Join-Path $installDirectory 'dotnet.exe'))
$minimumSdkVersion = [Version]'10.0.100'

function Test-CompatibleSdk {
    if (-not (Test-Path -LiteralPath $dotnetPath -PathType Leaf)) {
        return $false
    }

    $installedVersions = & $dotnetPath --list-sdks 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    foreach ($installedVersion in $installedVersions) {
        if ($installedVersion -match '^(?<Version>\d+\.\d+\.\d+)\s') {
            $version = [Version]$Matches.Version
            if ($version.Major -eq 10 -and
                $version.Minor -eq 0 -and
                $version -ge $minimumSdkVersion) {
                return $true
            }
        }
    }

    return $false
}

if (-not (Test-CompatibleSdk)) {
    New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null

    $installerPath = Join-Path ([System.IO.Path]::GetTempPath()) 'JingXu-dotnet-install.ps1'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://dot.net/v1/dotnet-install.ps1' -OutFile $installerPath

    & $installerPath -Channel '10.0' -Quality 'GA' -InstallDir $installDirectory -NoPath | Out-Host
    if (-not (Test-CompatibleSdk)) {
        throw "A compatible .NET 10 SDK was not found in '$installDirectory' after installation."
    }
}

(Get-Item -LiteralPath $dotnetPath).FullName
