# 开发指南

## 文档目的

给出可复现的本地开发方式，并区分 **规格要求的工程纪律** 与 **当前仓库真实命令/入口**。

## 目标设计

- Windows 10/11 x64；.NET 10 SDK（`global.json` 固定）。
- nullable + 分析器警告视为错误；外部进程只用 `ArgumentList`。
- 新行为测试先行；Domain 保持纯净。

## 开发现状

### 环境要求

- Windows 10/11 x64
- .NET 10 SDK（见仓库根 `global.json`，当前要求 `10.0.100`，`rollForward: latestFeature`）
- FFmpeg/FFprobe（`PATH` 或 `runtime/ffmpeg/`）用于媒体集成测试
- 可选：Whisper.cpp、Tesseract（字幕实验室）

安装 SDK：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Install-DotNetSdk.ps1
```

### 常用命令

验证缓存清理和素材库操作时，先为当前 PowerShell 会话配置独立目录，避免测试访问日常数据：

```powershell
$env:JINGXU_DATA_DIRECTORY = Join-Path $PWD 'artifacts\test-data'
$env:JINGXU_TEMP_DIRECTORY = Join-Path $PWD 'artifacts\test-temp'
$env:PATH = "$PWD\runtime\ffmpeg;$env:PATH"
```

未设置这些变量时，应用仍使用 `%LOCALAPPDATA%\JingXu` 与系统临时目录。解决方案构建使用 `-m:1`，避免多个项目实例同时写入共享 `obj` 文件。

```powershell
# 在 worktree 根目录（含 JingXu.Workbench.sln）执行
dotnet restore JingXu.Workbench.sln --locked-mode
dotnet build JingXu.Workbench.sln
dotnet test JingXu.Workbench.sln
dotnet format JingXu.Workbench.sln --verify-no-changes

# 启动 WPF（开发）
dotnet run --project src/JingXu.Workbench/JingXu.Workbench.csproj

# 无界面自检 / 冒烟（进程结束后退出）
dotnet run --project src/JingXu.Workbench/JingXu.Workbench.csproj -- --self-test
dotnet run --project src/JingXu.Workbench/JingXu.Workbench.csproj -- --import-smoke
dotnet run --project src/JingXu.Workbench/JingXu.Workbench.csproj -- --overlay-smoke
```

入口代码：`src/JingXu.Workbench/App.xaml.cs`（组合根 `Bootstrap/AppCompositionRoot.cs`）。

### 编码标准（意图 = 现状纪律）

- 启用 nullable、分析器警告视为错误（`Directory.Build.props`）
- 公共边界使用不可变 record；禁止跨层松散字典
- 长操作接受 `CancellationToken`；UI 线程禁止阻塞 I/O
- 外部进程使用 `ProcessStartInfo.ArgumentList`
- View code-behind 仅用于窗口行为；业务逻辑在 ViewModel/Application/Domain
- 新行为先写失败测试，再实现（红—绿—重构）

### 运行时开发

1. 将第三方二进制放入 `runtime/`（不提交 Git，见 `runtime/README.md`）
2. `scripts/Resolve-Runtimes.ps1 -CacheDirectory runtime -PrintHashes` 生成 SHA-256
3. 更新 `build/runtime-manifest.json` 后 staging 到 `artifacts/staging/runtime`
4. 选品爬虫内置运行时：`scripts/Resolve-SpiderRuntime.ps1`（下载嵌入式 Python + `src/JingXu.Spider/requirements.txt` 依赖到 `runtime/python`）；发布脚本会把 `runtime/python` 与爬虫源码暂存到 `runtime/spider`。国内网络可加 `-PipIndexUrl https://pypi.tuna.tsinghua.edu.cn/simple`；重建用 `-Force`。

### 项目结构（实际）

```text
src/
  JingXu.Workbench/                 # WPF 壳、Features、Bootstrap
  JingXu.Workbench.Application/     # 用例与抽象
  JingXu.Workbench.Domain/          # 纯领域（含 CompositionPlanner）
  JingXu.Workbench.Infrastructure/  # 进程、FFmpeg、Runtime、持久化
tests/                              # 五层 xUnit 项目
scripts/                            # 构建与发布
build/                              # runtime-manifest、WiX
docs/                               # 设计 + 现状索引见 docs/README.md
```

计划中的 `Features/Materials/` **未单独建目录**；素材 UI 在 `Features/Composition/`。

## 待对齐项

- 主仓 `main` 无此解决方案；克隆后若只在主根目录找不到 `sln`，请检出/打开 `.worktrees/jingxu-implementation` 或对应 feature 分支。
- 更细的功能完成度见 [docs/README.md](README.md) 中「开发现状与对齐」。
