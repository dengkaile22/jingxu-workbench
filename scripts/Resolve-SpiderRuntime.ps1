[CmdletBinding()]
param(
    [string] $Version = '3.12.10',

    [string] $TargetDirectory = "",

    [string] $SpiderDirectory = "",

    [string] $CacheDirectory = "",

    [string] $PipIndexUrl = "",

    [string] $ExpectedZipSha256 = "",

    [switch] $Force,

    [switch] $SkipDependencies,

    [switch] $PrintHashes
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

function Get-FileSha256([string] $Path) {
    $hash = Get-FileHash -Path $Path -Algorithm SHA256
    return $hash.Hash.ToLowerInvariant()
}

function Invoke-Download([string] $Url, [string] $Destination) {
    if (Test-Path $Destination) { return }
    $parent = Split-Path $Destination -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Write-Host "Downloading $Url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

function Test-SpiderDependencies([string] $PythonExe, [string] $ProbeScriptPath) {
    $output = & $PythonExe $ProbeScriptPath 2>&1
    $text = ($output | Out-String).Trim()
    return @{
        Ok = ($LASTEXITCODE -eq 0 -and $text -eq 'OK')
        Output = $text
    }
}

$probeScript = @'
import importlib.util as u
mods = ["DrissionPage", "requests", "openpyxl", "tabulate"]
missing = [m for m in mods if u.find_spec(m) is None]
print("OK" if not missing else "MISSING:" + ",".join(missing))
'@

$repoRoot = Resolve-RepoRoot
if ([string]::IsNullOrWhiteSpace($TargetDirectory)) { $TargetDirectory = Join-Path (Join-Path $repoRoot 'runtime') 'python' }
if ([string]::IsNullOrWhiteSpace($SpiderDirectory)) { $SpiderDirectory = Join-Path (Join-Path $repoRoot 'src') 'JingXu.Spider' }
if ([string]::IsNullOrWhiteSpace($CacheDirectory)) { $CacheDirectory = Join-Path (Join-Path $repoRoot 'artifacts') 'cache' }
if (-not [IO.Path]::IsPathRooted($TargetDirectory)) { $TargetDirectory = Join-Path $repoRoot $TargetDirectory }
if (-not [IO.Path]::IsPathRooted($CacheDirectory)) { $CacheDirectory = Join-Path $repoRoot $CacheDirectory }
$TargetDirectory = [IO.Path]::GetFullPath($TargetDirectory)
$CacheDirectory = [IO.Path]::GetFullPath($CacheDirectory)

$requirementsPath = Join-Path $SpiderDirectory 'requirements.txt'
if (-not $SkipDependencies -and -not (Test-Path $requirementsPath)) {
    throw "未找到爬虫依赖清单: $requirementsPath"
}

$pythonExe = Join-Path $TargetDirectory 'python.exe'
$probePath = Join-Path $CacheDirectory 'spider_env_probe.py'
if (-not (Test-Path $CacheDirectory)) { New-Item -ItemType Directory -Path $CacheDirectory -Force | Out-Null }
Set-Content -Path $probePath -Value $probeScript -Encoding UTF8

if ((Test-Path $pythonExe) -and -not $Force) {
    $existing = Test-SpiderDependencies $pythonExe $probePath
    if ($existing.Ok) {
        Write-Host "内置 Python 环境已就绪: $TargetDirectory"
        & $pythonExe --version
        if ($PrintHashes) {
            Write-Host '=== 内置 Python SHA-256 ==='
            Write-Host "python/python.exe  $(Get-FileSha256 $pythonExe)"
        }
        exit 0
    }

    if ($SkipDependencies) {
        Write-Warning "内置 Python 已存在但依赖不完整（$($existing.Output)）；已跳过依赖安装。"
        exit 0
    }

    Write-Host "内置 Python 已存在（$($existing.Output)），安装/修复依赖 ..."
}

if (-not (Test-Path $pythonExe)) {
    $zipName = "python-$Version-embed-amd64.zip"
    $zipPath = Join-Path $CacheDirectory $zipName

    Invoke-Download "https://www.python.org/ftp/python/$Version/$zipName" $zipPath

    if (-not [string]::IsNullOrWhiteSpace($ExpectedZipSha256)) {
        $actualZipHash = Get-FileSha256 $zipPath
        if ($actualZipHash -ne $ExpectedZipSha256.ToLowerInvariant()) {
            throw "Python 嵌入式包哈希不匹配：期望 $ExpectedZipSha256，实际 $actualZipHash"
        }
    }

    if (Test-Path $TargetDirectory) { Remove-Item -Path $TargetDirectory -Recurse -Force }
    New-Item -ItemType Directory -Path $TargetDirectory -Force | Out-Null

    Write-Host "解压嵌入式 Python $Version ..."
    Expand-Archive -Path $zipPath -DestinationPath $TargetDirectory -Force

    $pthFile = Get-ChildItem -Path $TargetDirectory -Filter 'python*._pth' | Select-Object -First 1
    if (-not $pthFile) { throw "未找到 $TargetDirectory 下的 python*._pth 文件" }

    $pthLines = Get-Content $pthFile.FullName
    if ($pthLines -notcontains 'import site') {
        $pthLines = $pthLines | Where-Object { $_ -notmatch '^\s*#\s*import site\s*$' }
        $pthLines += 'Lib\site-packages'
        $pthLines += 'import site'
        Set-Content -Path $pthFile.FullName -Value $pthLines -Encoding ASCII
        Write-Host "已在 _$($pthFile.BaseName) 中启用 site-packages。"
    }
}

if ($SkipDependencies) {
    Write-Host '已跳过依赖安装（-SkipDependencies）。'
    exit 0
}

$getPipPath = Join-Path $CacheDirectory 'get-pip.py'
Invoke-Download 'https://bootstrap.pypa.io/get-pip.py' $getPipPath

Write-Host '安装 pip ...'
$pipArgs = @($getPipPath, '--no-warn-script-location', '--disable-pip-version-check')
if (-not [string]::IsNullOrWhiteSpace($PipIndexUrl)) { $pipArgs += @('--index-url', $PipIndexUrl) }
& $pythonExe @pipArgs
if ($LASTEXITCODE -ne 0) { throw "get-pip.py 安装失败，退出码 $LASTEXITCODE" }

Write-Host '安装选品爬虫依赖 ...'
$installArgs = @('-m', 'pip', 'install', '--no-warn-script-location', '--disable-pip-version-check', '-r', $requirementsPath)
if (-not [string]::IsNullOrWhiteSpace($PipIndexUrl)) { $installArgs += @('--index-url', $PipIndexUrl) }
& $pythonExe @installArgs
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败，退出码 $LASTEXITCODE" }

Get-ChildItem -Path $TargetDirectory -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$probe = Test-SpiderDependencies $pythonExe $probePath
if (-not $probe.Ok) {
    throw "内置 Python 依赖自检失败：$($probe.Output)"
}

Write-Host '内置选品爬虫运行环境构建完成。'
& $pythonExe --version

if ($PrintHashes) {
    Write-Host '=== 内置 Python SHA-256 ==='
    Write-Host "python/python.exe  $(Get-FileSha256 $pythonExe)"
}

exit 0
