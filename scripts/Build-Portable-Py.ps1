[CmdletBinding()]
param(
    # 运行时缓存目录（含 ffmpeg/whisper/tesseract/python）
    [string] $RuntimeDirectory = "",
    # 输出目录；默认 artifacts/release（与 .NET 版统一到同一交付目录）
    [string] $OutputDirectory = "",
    # 不做 ZIP 与哈希（仅本地快速验证）
    [switch] $SkipArchive,
    # 打包后运行 --self-test 验证（默认执行）
    [switch] $SkipSelfTest
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

# Windows PowerShell 5.1 会把原生命令写入 stderr 的内容包装成 NativeCommandError，
# 在 $ErrorActionPreference='Stop' 下会直接终止脚本——即使该命令其实成功
# （PyInstaller 的 INFO 日志就走 stderr，曾导致"构建成功但退出码 1"）。
# 因此所有原生命令统一通过本函数调用：局部放宽错误偏好，成败只看退出码。
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

function Copy-Tree([string] $Source, [string] $Target) {
    if (-not (Test-Path $Source)) { return 0 }
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    Invoke-NativeQuiet robocopy @($Source, $Target, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP') | Out-Null
    if ($script:NativeExitCode -ge 8) { throw "robocopy 复制失败（$script:NativeExitCode）：$Source → $Target" }
    return 1
}

$repoRoot = Resolve-RepoRoot
$packageDir = Join-Path $repoRoot 'src\JingXu.Workbench.Py'
$specPath = Join-Path $PSScriptRoot 'jingxu.spec'
$buildRoot = Join-Path $repoRoot 'artifacts\py-build'

if ([string]::IsNullOrWhiteSpace($RuntimeDirectory)) {
    $RuntimeDirectory = Join-Path $repoRoot 'runtime'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    # 与 .NET 版统一到 artifacts/release，交付只认一个目录。
    $OutputDirectory = Join-Path $repoRoot 'artifacts\release'
}

Write-Host '=== 1. 检查打包依赖 ==='
Invoke-NativeQuiet python @('-c', 'import PyInstaller, PySide6') | Out-Null
if ($script:NativeExitCode -ne 0) {
    throw '缺少打包依赖（需要 PyInstaller 与 PySide6）。请先执行：python -m pip install pyinstaller PySide6'
}
$pyInstallerVersion = Invoke-NativeQuiet python @('-m', 'PyInstaller', '--version')
Write-Host ("PyInstaller " + ($pyInstallerVersion -join ' ').Trim())

Write-Host '=== 2. PyInstaller onedir 构建 ==='
if (Test-Path $buildRoot) { Remove-Item $buildRoot -Recurse -Force }
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
# PyInstaller 的 INFO 日志走 stderr；Invoke-NativeQuiet 已隔离该差异，
# 成败只看退出码，不再出现"构建成功却以 1 退出"。
Invoke-NativeQuiet python @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--clean',
    '--distpath', $buildRoot,
    '--workpath', (Join-Path $buildRoot '_work'),
    $specPath
) | ForEach-Object { Write-Host $_ }
if ($script:NativeExitCode -ne 0) { throw "PyInstaller 构建失败（$script:NativeExitCode）" }

$appName = '炳恒快速混剪'
$stagedApp = Join-Path $buildRoot $appName
$exePath = Join-Path $stagedApp "$appName.exe"
if (-not (Test-Path $exePath)) { throw "未找到构建产物：$exePath" }

Write-Host '=== 3. 随包运行时（放在 exe 同级 runtime/）==='
$stagedRuntime = Join-Path $stagedApp 'runtime'
New-Item -ItemType Directory -Path $stagedRuntime -Force | Out-Null

$optionalComponents = @()
foreach ($component in @('ffmpeg', 'whisper', 'tesseract', 'python')) {
    $source = Join-Path $RuntimeDirectory $component
    if (Copy-Tree $source (Join-Path $stagedRuntime $component)) {
        Write-Host "  已随包：$component"
    } else {
        $optionalComponents += $component
        Write-Warning "  未找到 runtime/$component（该项功能将不可用）"
    }
}

# tesseract 占位文件（历史上发布流水线会放 1 字节文件）不应随包，避免被误判为可用。
$tesseractExe = Join-Path $stagedRuntime 'tesseract\tesseract.exe'
if (Test-Path $tesseractExe) {
    $size = (Get-Item $tesseractExe).Length
    if ($size -lt 64KB) {
        Remove-Item (Split-Path $tesseractExe -Parent) -Recurse -Force
        $optionalComponents += 'tesseract'
        Write-Warning ("  已移除 tesseract 占位文件（{0} 字节，非真实可执行文件）" -f $size)
    }
}

Write-Host '=== 4. 选品爬虫源码（runtime/spider）==='
$spiderSource = Join-Path $repoRoot 'src\JingXu.Spider'
$stagedSpider = Join-Path $stagedRuntime 'spider'
if (Test-Path (Join-Path $spiderSource 'run.py')) {
    if (Test-Path $stagedSpider) { Remove-Item $stagedSpider -Recurse -Force }
    New-Item -ItemType Directory -Path $stagedSpider -Force | Out-Null
    Invoke-NativeQuiet robocopy @(
        $spiderSource, $stagedSpider, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP',
        '/XD', '__pycache__', 'data', 'tests', 'examples', 'gui', '.venv', '.pytest_cache',
        '/XF', '*.pyc', '*.xlsx', '*.log'
    ) | Out-Null
    if ($script:NativeExitCode -ge 8) { throw "爬虫源码复制失败（$script:NativeExitCode）" }
    Write-Host '  已随包：runtime/spider'
} else {
    Write-Warning '  未找到爬虫源码（选品模块将不可用）'
}

Write-Host '=== 5. 清单与声明文件 ==='
Copy-Item (Join-Path $repoRoot 'build\runtime-manifest.json') (Join-Path $stagedApp 'runtime-manifest.json') -Force
foreach ($notice in @('THIRD_PARTY_NOTICES.md', 'README.md')) {
    $source = Join-Path $repoRoot $notice
    if (Test-Path $source) { Copy-Item $source (Join-Path $stagedApp $notice) -Force }
}
Copy-Item (Join-Path $packageDir 'README.md') (Join-Path $stagedApp '使用说明-Python版.md') -Force

Write-Host '=== 6. 启动自检（在打包目录内执行）==='
if (-not $SkipSelfTest) {
    $reportPath = Join-Path $buildRoot 'self-test.json'
    if (Test-Path $reportPath) { Remove-Item $reportPath -Force }
    # 打包产物是窗口程序（--windowed）：既没有控制台，也拿不到可靠的标准输出；
    # 且在重定向时其退出码并不可靠。因此以「报告文件」为唯一权威判据：
    # 让 exe 把 JSON 写进文件，脚本只解析该文件；退出码仅作为补充信息打印。
    # 用 Start-Process -Wait 确保进程真正结束：窗口子系统程序（--windowed）在
    # 直接调用时不会被可靠等待，报告文件可能还没写完就被读取。
    # 之所以不用管道重定向，是因为重定向 stderr 会让 Python 刷新缓冲失败。
    # Start-Process 在本机曾因进程环境块存在大小写重复键（NO_PROXY/no_proxy）
    # 报 "Item has already been added"，因此这里临时移除该键再调用。
    $proxyBackup = @{}
    foreach ($name in @('NO_PROXY', 'no_proxy', 'HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy')) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if ($null -ne $value) { $proxyBackup[$name] = $value }
    }
    try {
        foreach ($name in $proxyBackup.Keys) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
        $process = Start-Process -FilePath $exePath `
            -ArgumentList @('--self-test', '--report-file', $reportPath) `
            -WorkingDirectory $stagedApp -NoNewWindow -Wait -PassThru
        $selfTestExit = $process.ExitCode
    } finally {
        foreach ($entry in $proxyBackup.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
        }
    }
    if (-not (Test-Path $reportPath)) {
        throw "自检未生成报告文件（进程退出码 $selfTestExit）：$reportPath"
    }
    Write-Host ("  进程退出码 = $selfTestExit")
    $report = Get-Content $reportPath -Raw -ErrorAction SilentlyContinue
    if (-not $report) { throw '自检报告为空。' }
    $jsonLine = ($report -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') } | Select-Object -First 1)
    if (-not $jsonLine) { throw "自检报告中未找到 JSON：$report" }
    $parsed = $jsonLine | ConvertFrom-Json
    if (-not $parsed.success) { throw "自检报告 success=false：$($parsed.error)" }
    Write-Host ("  自检通过；FFmpeg = " + $parsed.ffmpeg)
    Write-Host ("  清单有效 = " + $parsed.manifestValid + "；缺失必需组件 = " + ($parsed.missingRequired -join '、'))
    foreach ($component in $parsed.components) {
        Write-Host ("    {0,-26} {1}" -f $component.displayName, ($(if ($component.available) { '就绪' } else { '缺失' })))
    }
} else {
    Write-Warning '  已跳过启动自检（-SkipSelfTest）'
}

Write-Host '=== 7. 生成交付物 ==='
# 交付目录与 .NET 版共用 artifacts/release，因此绝不能整目录删除
# （那会连带删掉 .NET 版的 MSI 与便携包）；只覆盖本次要产出的同名文件。
if (-not (Test-Path $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}

$zipName = "$appName-Py-Portable-win-x64.zip"
$zipPath = Join-Path $OutputDirectory $zipName
if (-not $SkipArchive) {
    if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $stagedApp '*') -DestinationPath $zipPath -CompressionLevel Optimal
    $zipHash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()

    # 校验和写到独立文件，避免覆盖 .NET 版维护的 SHA256SUMS.txt。
    $sumsName = 'SHA256SUMS-PyPortable.txt'
    Set-Content -Path (Join-Path $OutputDirectory $sumsName) `
        -Value "$zipHash  $zipName" -Encoding UTF8
    Write-Host "  ZIP：$zipPath"
    Write-Host "  SHA-256：$zipHash"
    Write-Host "  校验和：$(Join-Path $OutputDirectory $sumsName)"
} else {
    Write-Warning '  已跳过 ZIP 打包（-SkipArchive）'
}

$sizeMb = [math]::Round(((Get-ChildItem $stagedApp -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host ''
Write-Host '=== 完成 ==='
Write-Host "  便携目录：$stagedApp"
Write-Host "  目录体积：$sizeMb MB"
Write-Host "  可执行：  $exePath"
if ($optionalComponents.Count -gt 0) {
    Write-Host ("  缺失可选组件：" + ($optionalComponents -join '、'))
}
exit 0
