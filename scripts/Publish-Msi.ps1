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

$repoRoot = Resolve-RepoRoot
$artifactsRoot = Join-Path $repoRoot 'artifacts'
$publishDir = Join-Path (Join-Path $artifactsRoot 'publish') 'win-x64'
$stagingPortableDir = Join-Path (Join-Path $artifactsRoot 'staging') 'portable'
$releaseDir = Join-Path $artifactsRoot 'release'
$distDir = Join-Path $repoRoot 'dist'
$installerDir = Join-Path (Join-Path $repoRoot 'build') 'Installer'
$srcRoot = Join-Path $repoRoot 'src'
$project = Join-Path (Join-Path $srcRoot 'JingXu.Workbench') 'JingXu.Workbench.csproj'

if ([string]::IsNullOrWhiteSpace($RuntimeCacheDirectory)) {
    $RuntimeCacheDirectory = Join-Path $repoRoot 'runtime'
}

Write-Host '=== 1. 编译发布自包含应用 (Publish Self-Contained) ==='
dotnet publish $project -c $Configuration -r win-x64 --self-contained true -m:1 -p:PublishTrimmed=false -p:PublishSingleFile=false -p:DebugType=None -p:DebugSymbols=false -o $publishDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '=== 2. 组织本地离线 Runtime 组件 ==='
$resolveScript = Join-Path $PSScriptRoot 'Resolve-Runtimes.ps1'
$resolveParams = @{
    CacheDirectory = (Resolve-Path $RuntimeCacheDirectory).Path
}
if ($AllowPlaceholderHash) { $resolveParams['AllowPlaceholderHash'] = $true }
if ($BootstrapFromPath) { $resolveParams['BootstrapFromPath'] = $true }
& $resolveScript @resolveParams
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$stagedRuntime = Join-Path (Join-Path $artifactsRoot 'staging') 'runtime'
$publishRuntime = Join-Path $publishDir 'runtime'
if (Test-Path $publishRuntime) { Remove-Item $publishRuntime -Recurse -Force }
if (Test-Path $stagedRuntime) {
    if (-not (Test-Path $publishRuntime)) { New-Item -ItemType Directory -Path $publishRuntime -Force | Out-Null }
    & robocopy $stagedRuntime $publishRuntime /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
}

foreach ($notice in @('README.md', 'THIRD_PARTY_NOTICES.md')) {
    $src = Join-Path $repoRoot $notice
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $publishDir $notice) -Force
    }
}

# 自检读取应用根目录的真实清单，避免回退到内置的开发占位清单。
Copy-Item -LiteralPath (Join-Path $repoRoot 'build\runtime-manifest.json') -Destination (Join-Path $publishDir 'runtime-manifest.json') -Force

Write-Host '=== 2b. 暂存内置 Python 与选品爬虫源码 ==='
$publishRuntimeDir = Join-Path $publishDir 'runtime'
$pythonSource = Join-Path $RuntimeCacheDirectory 'python'
$pythonTarget = Join-Path $publishRuntimeDir 'python'
if (Test-Path (Join-Path $pythonSource 'python.exe')) {
    if (Test-Path $pythonTarget) { Remove-Item $pythonTarget -Recurse -Force }
    New-Item -ItemType Directory -Path $pythonTarget -Force | Out-Null
    & robocopy $pythonSource $pythonTarget /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    Write-Host "已暂存内置 Python: $pythonSource"
} else {
    Write-Warning "未找到内置 Python（$pythonSource）。选品爬虫将回退到系统 Python；如需随包分发请先运行 scripts/Resolve-SpiderRuntime.ps1。"
}

$spiderSource = Join-Path (Join-Path $repoRoot 'src') 'JingXu.Spider'
$spiderTarget = Join-Path $publishRuntimeDir 'spider'
if (Test-Path $spiderSource) {
    if (Test-Path $spiderTarget) { Remove-Item $spiderTarget -Recurse -Force }
    & robocopy $spiderSource $spiderTarget /E /NFL /NDL /NJH /NJS /NC /NS /NP `
        /XD '__pycache__' 'data' 'tests' 'examples' 'gui' '.venv' `
        /XF 'config.json' 'setup.py' 'run.py' '*.bat' '*.xlsx' '*.pyc' '*.log' | Out-Null
    Write-Host "已暂存选品爬虫源码: $spiderSource"
} else {
    Write-Warning "未找到选品爬虫源码目录：$spiderSource"
}

if (Test-Path $stagingPortableDir) { Remove-Item $stagingPortableDir -Recurse -Force }
New-Item -ItemType Directory -Path $stagingPortableDir -Force | Out-Null
& robocopy $publishDir $stagingPortableDir /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null

$excludePatterns = @('*.pdb', '*Tests.dll', '*testhost*', 'coverlet.*')
Get-ChildItem -Path $stagingPortableDir -Recurse -File | Where-Object {
    $name = $_.Name
    foreach ($pattern in $excludePatterns) {
        if ($name -like $pattern) { return $true }
    }
    return $false
} | Remove-Item -Force

Write-Host '=== 3. 构建 MSI 安装包 (WiX 6) ==='
$wixCmd = Get-Command wix -ErrorAction SilentlyContinue
$wix = if ($wixCmd) { $wixCmd.Source } else { 'C:\Program Files\WiX Toolset v6.0\bin\wix.exe' }
if (-not (Test-Path $wix)) {
    throw "未找到 WiX 6 可执行文件: $wix"
}

if (-not (Test-Path $releaseDir)) { New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null }
if (-not (Test-Path $distDir)) { New-Item -ItemType Directory -Path $distDir -Force | Out-Null }

$msiPath = Join-Path $releaseDir 'JingXu.Workbench.msi'
$namedMsiPath = Join-Path $releaseDir '炳恒快速混剪-win-x64.msi'
$distMsiPath = Join-Path $distDir '炳恒快速混剪-win-x64.msi'

$productWxs = Join-Path $installerDir 'Product.wxs'
$packageWxs = Join-Path $installerDir 'Package.wxs'
$resolvedPublishDir = (Resolve-Path $stagingPortableDir).Path
$licenseFile = (Resolve-Path (Join-Path $installerDir 'License.rtf')).Path

& $wix build $productWxs $packageWxs -ext WixToolset.UI.wixext -bindpath $installerDir -d PublishDir=$resolvedPublishDir -d LicenseRtf=$licenseFile -o $msiPath -arch x64
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Copy-Item $msiPath $namedMsiPath -Force
Copy-Item $namedMsiPath $distMsiPath -Force

$msiHash = (Get-FileHash -Path $distMsiPath -Algorithm SHA256).Hash.ToLowerInvariant()
$distSums = Join-Path $distDir 'SHA256SUMS.txt'
Set-Content -Path $distSums -Value "$msiHash  炳恒快速混剪-win-x64.msi`r`n" -Encoding UTF8

$releaseSums = Join-Path $releaseDir 'SHA256SUMS.txt'
Set-Content -Path $releaseSums -Value "$msiHash  炳恒快速混剪-win-x64.msi`r`n$msiHash  JingXu.Workbench.msi`r`n" -Encoding UTF8

Write-Host '=== 发布完成 (MSI Installer Ready) ==='
Write-Host "安装包位置: $distMsiPath"
Write-Host "文件大小: $([math]::Round((Get-Item $distMsiPath).Length / 1MB, 2)) MB"
Write-Host "SHA-256: $msiHash"
exit 0
