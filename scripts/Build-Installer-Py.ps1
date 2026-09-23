[CmdletBinding()]
param(
    # 便携目录（默认取 Build-Portable-Py.ps1 的产物）
    [string] $PortableDirectory = "",
    # 输出目录；默认 artifacts/release（与 .NET 版统一到同一交付目录）
    [string] $OutputDirectory = "",
    # 产品版本（写入 MSI ProductVersion，四段数字）
    [string] $ProductVersion = "1.0.2.0",
    # 便携目录缺失时自动先跑打包脚本
    [switch] $SkipPortableBuild
)

$ErrorActionPreference = 'Stop'

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

# Windows PowerShell 5.1 会把原生命令写入 stderr 的内容包装成 NativeCommandError，
# 在 $ErrorActionPreference='Stop' 下会终止脚本——即使命令其实成功（wix 的进度
# 日志就走 stderr）。因此原生命令统一通过本函数调用，成败只看退出码。
function Invoke-NativeQuiet {
    param(
        [Parameter(Mandatory = $true)][string] $Command,
        [Parameter(ValueFromRemainingArguments = $true)][object[]] $Arguments
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Command @Arguments 2>&1
        $script:NativeExitCode = $LASTEXITCODE
        return $output
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Find-WixExecutable {
    $command = Get-Command wix -ErrorAction SilentlyContinue
    $candidates = @()
    if ($command) { $candidates += $command.Source }
    $candidates += 'C:\Program Files\WiX Toolset v6.0\bin\wix.exe'
    $candidates += 'C:\Program Files (x86)\WiX Toolset v6.0\bin\wix.exe'
    return $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

$repoRoot = Resolve-RepoRoot
$appName = '炳恒快速混剪'
if ([string]::IsNullOrWhiteSpace($PortableDirectory)) {
    $PortableDirectory = Join-Path $repoRoot 'artifacts\py-build'
    $PortableDirectory = Join-Path $PortableDirectory $appName
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    # 与 .NET 版统一到 artifacts/release，交付只认一个目录。
    $OutputDirectory = Join-Path $repoRoot 'artifacts\release'
}

Write-Host '=== 1. 检查前置条件 ==='
$wix = Find-WixExecutable
if (-not $wix) {
    Write-Warning 'BLOCKER: 未找到 WiX Toolset 6（需要 wix.exe 在 PATH 或默认安装目录）。'
    exit 2
}
$wixVersion = Invoke-NativeQuiet $wix @('--version')
Write-Host ("WiX " + ($wixVersion -join ' ').Trim())

$portableValid = (Test-Path (Join-Path $PortableDirectory "$appName.exe"))
if (-not $portableValid) {
    if ($SkipPortableBuild) {
        Write-Error "便携目录无效或缺少 $appName.exe：$PortableDirectory"
        exit 1
    }
    Write-Host '  便携目录缺失，先执行脚本打包（scripts/Build-Portable-Py.ps1）'
    Invoke-NativeQuiet powershell @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', (Join-Path $PSScriptRoot 'Build-Portable-Py.ps1')
    ) | ForEach-Object { Write-Host $_ }
    if ($script:NativeExitCode -ne 0) { throw "便携包构建失败（$($script:NativeExitCode)）" }
}
if (-not (Test-Path (Join-Path $PortableDirectory "$appName.exe"))) {
    throw "便携目录无效：$PortableDirectory"
}

$fileCount = (Get-ChildItem -LiteralPath $PortableDirectory -Recurse -File | Measure-Object).Count
$sizeMb = [math]::Round(((Get-ChildItem -LiteralPath $PortableDirectory -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "  便携目录：$PortableDirectory"
Write-Host "  文件数 $fileCount；体积 $sizeMb MB"

Write-Host '=== 2. 构建 MSI（WiX 6）==='
$installerDir = Join-Path $repoRoot 'build\Installer-Py'
$licenseFile = Join-Path $repoRoot 'build\Installer-Py\License.rtf'
if (-not (Test-Path $licenseFile)) { throw "缺少许可协议文件：$licenseFile" }

if (-not (Test-Path $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$msiPath = Join-Path $OutputDirectory "$appName-Py-win-x64.msi"
if (Test-Path $msiPath) { Remove-Item $msiPath -Force }

$resolvedPortable = (Resolve-Path $PortableDirectory).Path
$resolvedLicense = (Resolve-Path $licenseFile).Path
$arguments = @(
    'build',
    (Join-Path $installerDir 'Product.wxs'),
    (Join-Path $installerDir 'Package.wxs'),
    '-ext', 'WixToolset.UI.wixext',
    '-bindpath', $installerDir,
    '-d', "PublishDir=$resolvedPortable",
    '-d', "LicenseRtf=$resolvedLicense",
    '-d', "ProductVersion=$ProductVersion",
    '-o', $msiPath,
    '-arch', 'x64'
)
Invoke-NativeQuiet $wix $arguments | ForEach-Object { Write-Host $_ }
if ($script:NativeExitCode -ne 0) { throw "WiX 构建失败（$($script:NativeExitCode)）" }
if (-not (Test-Path $msiPath)) { throw "未生成 MSI：$msiPath" }

Write-Host '=== 3. 校验产物 ==='
$msi = Get-Item -LiteralPath $msiPath
if ($msi.Length -eq 0) { throw 'MSI 为零字节。' }

# 用 Windows Installer 直接读数据库属性，确认版本与产品名确实写进包内。
# 注意：必须用后期绑定调用（$installer.OpenDatabase(...)），用 InvokeMember
# 反射传参会抛 DISP_E_TYPEMISMATCH。
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = $installer.OpenDatabase($msiPath, 0)
$view = $database.OpenView('SELECT `Property`,`Value` FROM `Property`')
$view.Execute()
$properties = @{}
while ($true) {
    $record = $view.Fetch()
    if (-not $record) { break }
    $properties[$record.StringData(1)] = $record.StringData(2)
}
$view.Close()
$database = $null
$productName = [string]$properties['ProductName']
$productVersion = [string]$properties['ProductVersion']
$manufacturer = [string]$properties['Manufacturer']
$upgradeCode = [string]$properties['UpgradeCode']
Write-Host ("  ProductName    = {0}" -f $productName)
Write-Host ("  ProductVersion = {0}" -f $productVersion)
Write-Host ("  Manufacturer   = {0}" -f $manufacturer)
Write-Host ("  UpgradeCode    = {0}" -f $upgradeCode)

if ($productVersion -ne $ProductVersion) {
    throw "MSI ProductVersion（$productVersion）与期望（$ProductVersion）不一致。"
}
# 与 .NET 版共存的硬前提：UpgradeCode 必须不同，否则会互相触发 MajorUpgrade 卸载。
if ($upgradeCode -like '*A7C4E2B1*') {
    throw 'UpgradeCode 与 .NET 版冲突，会导致安装互相卸载。'
}

# wixpdb 是调试符号，不进交付目录
$pdb = [System.IO.Path]::ChangeExtension($msiPath, '.wixpdb')
if (Test-Path $pdb) { Remove-Item -LiteralPath $pdb -Force }

$hash = (Get-FileHash -LiteralPath $msiPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sumsPath = Join-Path $OutputDirectory 'SHA256SUMS-Py.txt'
$previous = @()
if (Test-Path $sumsPath) {
    $previous = @(Get-Content -LiteralPath $sumsPath | Where-Object { $_ -and $_ -notlike "*$($msi.Name)*" })
}
$lines = @($previous) + @("$hash  $($msi.Name)")
Set-Content -LiteralPath $sumsPath -Value $lines -Encoding UTF8

Write-Host ''
Write-Host '=== 完成 ==='
Write-Host ("  MSI：{0}（{1:N1} MB）" -f $msiPath, ($msi.Length / 1MB))
Write-Host ("  SHA-256：{0}" -f $hash)
Write-Host ("  校验和：{0}" -f $sumsPath)
exit 0
