[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$modulePath = Join-Path $repositoryRoot 'scripts\Install-DotNetSdk.Core.psm1'
$script:failureCount = 0

function Invoke-TestCase {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [scriptblock]$Body
    )

    try {
        & $Body
        Write-Output "PASS: $Name"
    }
    catch {
        $script:failureCount++
        Write-Error -ErrorAction Continue "FAIL: $Name - $($_.Exception.Message)"
    }
}

function Assert-Throws {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Action,

        [Parameter(Mandatory)]
        [string]$MessagePattern
    )

    $caughtException = $null
    try {
        & $Action
    }
    catch {
        $caughtException = $_.Exception
    }

    if ($null -eq $caughtException) {
        throw "Expected an exception matching '$MessagePattern', but no exception was thrown."
    }

    if ($caughtException.Message -notmatch $MessagePattern) {
        throw "Expected an exception matching '$MessagePattern', but received '$($caughtException.Message)'."
    }
}

Invoke-TestCase 'Rejects an installer without a valid Authenticode signature' {
    if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
        throw "Expected installer module '$modulePath' to exist."
    }

    Import-Module $modulePath -Force
    $testDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "JingXu-sdk-test-$([Guid]::NewGuid().ToString('N'))"
    try {
        New-Item -ItemType Directory -Path $testDirectory | Out-Null
        $unsignedInstaller = Join-Path $testDirectory 'unsigned-installer.ps1'
        Set-Content -LiteralPath $unsignedInstaller -Value 'exit 0' -Encoding UTF8

        Assert-Throws -Action {
            Assert-MicrosoftInstallerSignature -InstallerPath $unsignedInstaller
        } -MessagePattern 'signature status.*Valid'
    }
    finally {
        if (Test-Path -LiteralPath $testDirectory) {
            Remove-Item -LiteralPath $testDirectory -Recurse -Force
        }
    }
}

Invoke-TestCase 'Rejects a non-zero installer subprocess exit code' {
    Import-Module $modulePath -Force
    $testDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "JingXu-sdk-test-$([Guid]::NewGuid().ToString('N'))"
    try {
        New-Item -ItemType Directory -Path $testDirectory | Out-Null
        $failingInstaller = Join-Path $testDirectory 'failing-installer.ps1'
        Set-Content -LiteralPath $failingInstaller -Value @(
            "[Console]::Error.WriteLine('simulated installer failure')"
            'exit 37'
        ) -Encoding UTF8

        Assert-Throws -Action {
            Invoke-DotNetInstallerProcess `
                -InstallerPath $failingInstaller `
                -InstallDirectory (Join-Path $testDirectory 'sdk')
        } -MessagePattern 'exited with code 37'
    }
    finally {
        if (Test-Path -LiteralPath $testDirectory) {
            Remove-Item -LiteralPath $testDirectory -Recurse -Force
        }
    }
}

Invoke-TestCase 'Removes the unique temporary directory when installation fails' {
    Import-Module $modulePath -Force
    $testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "JingXu-sdk-test-$([Guid]::NewGuid().ToString('N'))"
    try {
        New-Item -ItemType Directory -Path $testRoot | Out-Null
        $observedPathFile = Join-Path $testRoot 'observed-path.txt'
        $failingAction = {
            param([string]$TemporaryDirectory)

            Set-Content -LiteralPath $observedPathFile -Value $TemporaryDirectory -Encoding UTF8
            New-Item -ItemType File -Path (Join-Path $TemporaryDirectory 'partial-download') | Out-Null
            throw 'forced installation failure'
        }.GetNewClosure()

        Assert-Throws -Action {
            Invoke-WithTemporaryDirectory -TemporaryRoot $testRoot -Action $failingAction
        } -MessagePattern 'forced installation failure'

        $observedPath = (Get-Content -Raw -LiteralPath $observedPathFile).Trim()
        if ((Split-Path -Leaf $observedPath) -notmatch '^JingXu-dotnet-[0-9a-f]{32}$') {
            throw "Temporary directory '$observedPath' does not use the expected unique name."
        }
        if (Test-Path -LiteralPath $observedPath) {
            throw "Temporary directory '$observedPath' was not removed by finally."
        }
    }
    finally {
        if (Test-Path -LiteralPath $testRoot) {
            Remove-Item -LiteralPath $testRoot -Recurse -Force
        }
    }
}

Invoke-TestCase 'Reuses a compatible SDK without invoking installation' {
    Import-Module $modulePath -Force
    $testDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "JingXu-sdk-test-$([Guid]::NewGuid().ToString('N'))"
    try {
        New-Item -ItemType Directory -Path $testDirectory | Out-Null
        $fakeDotNetPath = Join-Path $testDirectory 'dotnet.exe'
        New-Item -ItemType File -Path $fakeDotNetPath | Out-Null
        $installationMarker = Join-Path $testDirectory 'installation-was-invoked'
        $compatibilityProbe = {
            param(
                [string]$DotNetPath,
                [Version]$MinimumSdkVersion
            )

            return (Test-Path -LiteralPath $DotNetPath -PathType Leaf) -and
                $MinimumSdkVersion -eq [Version]'10.0.100'
        }
        $installAction = {
            Set-Content -LiteralPath $installationMarker -Value 'unexpected' -Encoding UTF8
            throw 'Installation must not run for a compatible SDK.'
        }.GetNewClosure()

        $firstResult = Invoke-DotNetSdkBootstrap `
            -DotNetPath $fakeDotNetPath `
            -MinimumSdkVersion ([Version]'10.0.100') `
            -CompatibilityProbe $compatibilityProbe `
            -InstallAction $installAction
        $secondResult = Invoke-DotNetSdkBootstrap `
            -DotNetPath $fakeDotNetPath `
            -MinimumSdkVersion ([Version]'10.0.100') `
            -CompatibilityProbe $compatibilityProbe `
            -InstallAction $installAction

        if ($firstResult -ne (Get-Item -LiteralPath $fakeDotNetPath).FullName) {
            throw "First idempotent result returned '$firstResult'."
        }
        if ($secondResult -ne $firstResult) {
            throw "Second idempotent result '$secondResult' differs from '$firstResult'."
        }
        if (Test-Path -LiteralPath $installationMarker) {
            throw 'The installation action ran for an already-compatible SDK.'
        }
    }
    finally {
        if (Test-Path -LiteralPath $testDirectory) {
            Remove-Item -LiteralPath $testDirectory -Recurse -Force
        }
    }
}

Invoke-TestCase 'Wires download, signature validation, and subprocess execution in order' {
    $tokens = $null
    $parseErrors = $null
    $moduleAst = [System.Management.Automation.Language.Parser]::ParseFile(
        $modulePath,
        [ref]$tokens,
        [ref]$parseErrors)
    if ($parseErrors.Count -ne 0) {
        throw "Installer module has $($parseErrors.Count) parse error(s)."
    }

    $installFunction = $moduleAst.FindAll({
        param($Node)
        $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $Node.Name -eq 'Install-DotNetSdk'
    }, $true) | Select-Object -First 1
    if ($null -eq $installFunction) {
        throw 'Install-DotNetSdk composition function was not found.'
    }

    $commands = @($installFunction.Body.FindAll({
        param($Node)
        $Node -is [System.Management.Automation.Language.CommandAst]
    }, $true))
    $downloadCommand = $commands | Where-Object { $_.GetCommandName() -eq 'Invoke-WebRequest' } | Select-Object -First 1
    $signatureCommand = $commands | Where-Object { $_.GetCommandName() -eq 'Assert-MicrosoftInstallerSignature' } | Select-Object -First 1
    $processCommand = $commands | Where-Object { $_.GetCommandName() -eq 'Invoke-DotNetInstallerProcess' } | Select-Object -First 1

    $requiredCommands = [ordered]@{
        'Invoke-WebRequest' = $downloadCommand
        'Assert-MicrosoftInstallerSignature' = $signatureCommand
        'Invoke-DotNetInstallerProcess' = $processCommand
    }
    foreach ($requiredCommand in $requiredCommands.GetEnumerator()) {
        if ($null -eq $requiredCommand.Value) {
            throw "Install-DotNetSdk does not call $($requiredCommand.Key)."
        }
    }

    $usesBasicParsing = $downloadCommand.CommandElements | Where-Object {
        $_ -is [System.Management.Automation.Language.CommandParameterAst] -and
            $_.ParameterName -eq 'UseBasicParsing'
    }
    if ($null -eq $usesBasicParsing) {
        throw 'Invoke-WebRequest does not use -UseBasicParsing.'
    }
    if ($downloadCommand.Extent.StartOffset -ge $signatureCommand.Extent.StartOffset -or
        $signatureCommand.Extent.StartOffset -ge $processCommand.Extent.StartOffset) {
        throw 'Installer operations are not ordered as download, signature validation, then subprocess execution.'
    }
}

Invoke-TestCase 'Keeps the executable script as a thin module entry point' {
    $entryScriptPath = Join-Path $repositoryRoot 'scripts\Install-DotNetSdk.ps1'
    $tokens = $null
    $parseErrors = $null
    $entryAst = [System.Management.Automation.Language.Parser]::ParseFile(
        $entryScriptPath,
        [ref]$tokens,
        [ref]$parseErrors)
    if ($parseErrors.Count -ne 0) {
        throw "Installer entry script has $($parseErrors.Count) parse error(s)."
    }

    $entryCommands = @($entryAst.FindAll({
        param($Node)
        $Node -is [System.Management.Automation.Language.CommandAst]
    }, $true))
    if ($null -eq ($entryCommands | Where-Object { $_.GetCommandName() -eq 'Import-Module' })) {
        throw 'Installer entry script does not import its core module.'
    }
    if ($null -eq ($entryCommands | Where-Object { $_.GetCommandName() -eq 'Install-DotNetSdk' })) {
        throw 'Installer entry script does not invoke Install-DotNetSdk.'
    }
    if ($null -ne ($entryCommands | Where-Object { $_.GetCommandName() -eq 'Invoke-WebRequest' })) {
        throw 'Installer entry script duplicates download logic from its core module.'
    }
}

if ($script:failureCount -ne 0) {
    throw "$script:failureCount SDK installer test(s) failed."
}
