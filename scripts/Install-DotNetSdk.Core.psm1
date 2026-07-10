Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-MicrosoftInstallerSignature {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$InstallerPath
    )

    $signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "The .NET SDK installer signature status must be Valid; found '$($signature.Status)'."
    }

    $subject = $signature.SignerCertificate.Subject
    $hasMicrosoftCommonName = $subject -match '(?i)(^|,\s*)CN=Microsoft Corporation(,|$)'
    $hasMicrosoftOrganization = $subject -match '(?i)(^|,\s*)O=Microsoft Corporation(,|$)'
    if (-not $hasMicrosoftCommonName -or -not $hasMicrosoftOrganization) {
        throw "The .NET SDK installer signer must be Microsoft Corporation; found '$subject'."
    }
}

function Invoke-DotNetInstallerProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$InstallerPath,

        [Parameter(Mandatory)]
        [string]$InstallDirectory,

        [string]$PowerShellPath = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
    )

    if (-not (Test-Path -LiteralPath $PowerShellPath -PathType Leaf)) {
        throw "Windows PowerShell was not found at '$PowerShellPath'."
    }

    $installerOutput = @(& $PowerShellPath `
        -NoLogo `
        -NoProfile `
        -NonInteractive `
        -ExecutionPolicy Bypass `
        -File $InstallerPath `
        -Channel '10.0' `
        -Quality 'GA' `
        -InstallDir $InstallDirectory `
        -NoPath)
    $installerExitCode = $LASTEXITCODE
    $installerOutput | Out-Host

    if ($installerExitCode -ne 0) {
        throw "The .NET SDK installer exited with code $installerExitCode."
    }
}

function Invoke-WithTemporaryDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$TemporaryRoot,

        [Parameter(Mandatory)]
        [scriptblock]$Action
    )

    $resolvedTemporaryRoot = [System.IO.Path]::GetFullPath($TemporaryRoot)
    New-Item -ItemType Directory -Path $resolvedTemporaryRoot -Force | Out-Null

    $temporaryDirectory = Join-Path $resolvedTemporaryRoot "JingXu-dotnet-$([Guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null

    try {
        & $Action $temporaryDirectory
    }
    finally {
        if (Test-Path -LiteralPath $temporaryDirectory) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

function Test-CompatibleDotNetSdk {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DotNetPath,

        [Parameter(Mandatory)]
        [Version]$MinimumSdkVersion
    )

    if (-not (Test-Path -LiteralPath $DotNetPath -PathType Leaf)) {
        return $false
    }

    $installedVersions = @(& $DotNetPath --list-sdks 2>$null)
    $dotnetExitCode = $LASTEXITCODE
    if ($dotnetExitCode -ne 0) {
        return $false
    }

    foreach ($installedVersion in $installedVersions) {
        if ($installedVersion -match '^(?<Version>\d+\.\d+\.\d+)\s') {
            $version = [Version]$Matches.Version
            if ($version.Major -eq 10 -and
                $version.Minor -eq 0 -and
                $version -ge $MinimumSdkVersion) {
                return $true
            }
        }
    }

    return $false
}

function Invoke-DotNetSdkBootstrap {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DotNetPath,

        [Parameter(Mandatory)]
        [Version]$MinimumSdkVersion,

        [Parameter(Mandatory)]
        [scriptblock]$CompatibilityProbe,

        [Parameter(Mandatory)]
        [scriptblock]$InstallAction
    )

    if (& $CompatibilityProbe $DotNetPath $MinimumSdkVersion) {
        return (Get-Item -LiteralPath $DotNetPath).FullName
    }

    & $InstallAction | Out-Host

    if (-not (& $CompatibilityProbe $DotNetPath $MinimumSdkVersion)) {
        throw "A compatible .NET 10 SDK was not found at '$DotNetPath' after installation."
    }

    return (Get-Item -LiteralPath $DotNetPath).FullName
}

function Install-DotNetSdk {
    [CmdletBinding()]
    param(
        [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'JingXu\dotnet'),

        [string]$TemporaryRoot = ([System.IO.Path]::GetTempPath())
    )

    $resolvedInstallDirectory = [System.IO.Path]::GetFullPath($InstallDirectory)
    $dotnetPath = Join-Path $resolvedInstallDirectory 'dotnet.exe'
    $minimumSdkVersion = [Version]'10.0.100'
    $installerUri = [Uri]'https://dot.net/v1/dotnet-install.ps1'
    $compatibilityProbe = {
        param(
            [string]$CandidatePath,
            [Version]$RequiredVersion
        )

        Test-CompatibleDotNetSdk `
            -DotNetPath $CandidatePath `
            -MinimumSdkVersion $RequiredVersion
    }
    $installAction = {
        New-Item -ItemType Directory -Path $resolvedInstallDirectory -Force | Out-Null
        $downloadAndInstall = {
            param([string]$TemporaryDirectory)

            $installerPath = Join-Path $TemporaryDirectory 'dotnet-install.ps1'
            Invoke-WebRequest `
                -UseBasicParsing `
                -Uri $installerUri `
                -OutFile $installerPath
            Assert-MicrosoftInstallerSignature -InstallerPath $installerPath
            Invoke-DotNetInstallerProcess `
                -InstallerPath $installerPath `
                -InstallDirectory $resolvedInstallDirectory
        }.GetNewClosure()

        Invoke-WithTemporaryDirectory `
            -TemporaryRoot $TemporaryRoot `
            -Action $downloadAndInstall
    }.GetNewClosure()

    Invoke-DotNetSdkBootstrap `
        -DotNetPath $dotnetPath `
        -MinimumSdkVersion $minimumSdkVersion `
        -CompatibilityProbe $compatibilityProbe `
        -InstallAction $installAction
}

Export-ModuleMember -Function @(
    'Assert-MicrosoftInstallerSignature'
    'Install-DotNetSdk'
    'Invoke-DotNetInstallerProcess'
    'Invoke-DotNetSdkBootstrap'
    'Invoke-WithTemporaryDirectory'
    'Test-CompatibleDotNetSdk'
)
