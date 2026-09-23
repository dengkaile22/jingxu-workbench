# 镜序工作台 Implementation Plan

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（`src/JingXu.Workbench.Py`），文中 `.cs`/`.xaml` 路径仅作历史记录。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可离线运行的 Windows x64 专业视频批处理软件，完整实现批量随机/序号拼接、差异化处理、三类蒙版、离线去字幕/换字幕、可靠任务队列、便携包和安装程序。

**Architecture:** 使用四项目 Clean Architecture：Domain 保存纯业务规则，Application 编排用例，Infrastructure 隔离 FFmpeg/FFprobe/Tesseract/Whisper/文件系统/Windows Job Object，WPF 项目只负责 MVVM 和视觉呈现。每个渲染任务在入队时形成不可变快照，经有界并发队列执行，输出先写同卷临时目录，验证后原子移动。

**Tech Stack:** .NET 10 LTS、C#、WPF、xUnit、System.Text.Json、FFmpeg/FFprobe 8.x sidecar、Tesseract OCR sidecar、whisper.cpp sidecar、WiX Toolset 6、PowerShell 构建脚本。

---

## 里程碑与依赖顺序

1. **M1 工程与可靠队列（任务 1–8）**：可启动的专业 WPF 壳、素材导入、持久化和外部进程队列。
2. **M2 混剪与蒙版（任务 9–14）**：可真实生成随机/序号成片，覆盖质量、画幅、效果、蒙版、BGM、封面。
3. **M3 离线字幕实验室（任务 15–18）**：手动/自动去字幕、Whisper 字幕、编辑与烧录。
4. **M4 发布与验收（任务 19–22）**：媒体集成验收、运行时许可、便携版、WiX 安装器和最终验证。

每个里程碑结束时必须有可运行、可测试的软件；不得为后续里程碑留下空按钮或假数据。

## 文件结构

```text
JingXu.Workbench.sln
global.json
Directory.Build.props
Directory.Packages.props
src/
  JingXu.Workbench.Domain/
    Common/Result.cs
    Common/NormalizedRect.cs
    Media/MediaAsset.cs
    Media/MediaInfo.cs
    Composition/FileSequenceParser.cs
    Composition/CompositionPlanner.cs
    Composition/CompositionModels.cs
    Composition/DeterministicRandom.cs
    Effects/EffectTemplate.cs
    Overlays/OverlayModels.cs
    Overlays/OverlayTimelineResolver.cs
    Rendering/RenderJob.cs
    Rendering/RenderProfile.cs
    Subtitles/SubtitleModels.cs
    Subtitles/SubtitleTimeline.cs
  JingXu.Workbench.Application/
    Abstractions/IAtomicJsonStore.cs
    Abstractions/IExternalProcessRunner.cs
    Abstractions/IMediaProbe.cs
    Abstractions/IRenderExecutor.cs
    Projects/ProjectDocument.cs
    Projects/ProjectService.cs
    Rendering/RenderCoordinator.cs
    Rendering/RenderPreflight.cs
    Subtitles/SubtitleWorkflow.cs
  JingXu.Workbench.Infrastructure/
    Persistence/AtomicJsonStore.cs
    Processes/ExternalProcessRunner.cs
    Processes/ProcessModels.cs
    Processes/WindowsJobObject.cs
    Runtime/RuntimeResolver.cs
    Media/FfprobeJsonParser.cs
    Media/FfprobeMediaProbe.cs
    Rendering/FfmpegCommand.cs
    Rendering/FfmpegCommandCompiler.cs
    Rendering/FfmpegProgressParser.cs
    Rendering/FfmpegRenderExecutor.cs
    Subtitles/TesseractTsvParser.cs
    Subtitles/TesseractRunner.cs
    Subtitles/WhisperSrtParser.cs
    Subtitles/WhisperRunner.cs
  JingXu.Workbench/
    App.xaml
    App.xaml.cs
    ShellWindow.xaml
    ShellWindow.xaml.cs
    Bootstrap/AppCompositionRoot.cs
    Themes/Colors.xaml
    Themes/Typography.xaml
    Themes/Controls.xaml
    Features/Shell/ShellViewModel.cs
    Features/Materials/MaterialsViewModel.cs
    Features/Composition/CompositionViewModel.cs
    Features/Composition/CompositionView.xaml
    Features/Overlays/OverlayEditorViewModel.cs
    Features/Overlays/OverlayEditorView.xaml
    Features/Subtitles/SubtitleLabViewModel.cs
    Features/Subtitles/SubtitleLabView.xaml
    Features/Queue/RenderQueueViewModel.cs
    Features/Queue/RenderQueueView.xaml
    Features/Settings/SettingsViewModel.cs
tests/
  JingXu.Workbench.Domain.Tests/
  JingXu.Workbench.Application.Tests/
  JingXu.Workbench.Infrastructure.Tests/
  JingXu.Workbench.Presentation.Tests/
  JingXu.Workbench.IntegrationTests/
build/
  Installer/Package.wxs
  Installer/Product.wxs
  Installer/JingXu.Workbench.Msi.wixproj
scripts/
  Install-DotNetSdk.ps1
  Resolve-Runtimes.ps1
  New-MediaFixtures.ps1
  Build-Portable.ps1
  Build-Installer.ps1
  Verify-Release.ps1
runtime/README.md
README.md
THIRD_PARTY_NOTICES.md
```

## 通用执行纪律

- 每个生产行为先写一个最小失败测试并运行，确认失败原因是行为缺失；再写最小实现；再运行相关测试和全套快速测试。
- 测试不得断言私有实现细节；外部进程集成测试使用真实短进程或真实 FFmpeg，单元测试使用手写 fake，不引入 mock 框架。
- 所有进程参数通过 `ProcessStartInfo.ArgumentList` 传递；任何评审中发现的字符串 shell 拼接都视为阻断问题。
- 每个任务末尾执行 `git diff --check`，再按计划提交；提交失败时不得继续堆叠后续任务。

### Task 1: 安装固定 SDK 并建立可编译解决方案

**Files:**
- Create: `global.json`
- Create: `Directory.Build.props`
- Create: `Directory.Packages.props`
- Create: `JingXu.Workbench.sln`
- Create: `src/JingXu.Workbench.Domain/JingXu.Workbench.Domain.csproj`
- Create: `src/JingXu.Workbench.Application/JingXu.Workbench.Application.csproj`
- Create: `src/JingXu.Workbench.Infrastructure/JingXu.Workbench.Infrastructure.csproj`
- Create: `src/JingXu.Workbench/JingXu.Workbench.csproj`
- Create: `tests/JingXu.Workbench.Domain.Tests/JingXu.Workbench.Domain.Tests.csproj`
- Create: `tests/JingXu.Workbench.Application.Tests/JingXu.Workbench.Application.Tests.csproj`
- Create: `tests/JingXu.Workbench.Infrastructure.Tests/JingXu.Workbench.Infrastructure.Tests.csproj`
- Create: `tests/JingXu.Workbench.Presentation.Tests/JingXu.Workbench.Presentation.Tests.csproj`
- Create: `tests/JingXu.Workbench.IntegrationTests/JingXu.Workbench.IntegrationTests.csproj`
- Create: `scripts/Install-DotNetSdk.ps1`
- Modify: `.gitignore`

- [ ] **Step 1: 写 SDK 安装脚本与固定版本策略**

`scripts/Install-DotNetSdk.ps1` 必须下载微软官方 `dotnet-install.ps1`，以 `-Channel 10.0 -Quality GA` 安装到仓库外的 `$env:LOCALAPPDATA\JingXu\dotnet`，并输出解析后的 `dotnet.exe` 绝对路径。`global.json` 使用：

```json
{
  "sdk": {
    "version": "10.0.100",
    "rollForward": "latestFeature",
    "allowPrerelease": false
  }
}
```

Extend `.gitignore` with `.tools/`, `runtime/*`, `!runtime/README.md` and generated release directories so runtime binaries/models never enter source commits accidentally.

- [ ] **Step 2: 生成四个生产项目和五个测试项目**

Run:

```powershell
dotnet new sln --format sln -n JingXu.Workbench
dotnet new classlib -n JingXu.Workbench.Domain -o src/JingXu.Workbench.Domain -f net10.0
dotnet new classlib -n JingXu.Workbench.Application -o src/JingXu.Workbench.Application -f net10.0
dotnet new classlib -n JingXu.Workbench.Infrastructure -o src/JingXu.Workbench.Infrastructure -f net10.0
dotnet new wpf -n JingXu.Workbench -o src/JingXu.Workbench -f net10.0
dotnet new xunit -n JingXu.Workbench.Domain.Tests -o tests/JingXu.Workbench.Domain.Tests -f net10.0
dotnet new xunit -n JingXu.Workbench.Application.Tests -o tests/JingXu.Workbench.Application.Tests -f net10.0
dotnet new xunit -n JingXu.Workbench.Infrastructure.Tests -o tests/JingXu.Workbench.Infrastructure.Tests -f net10.0
dotnet new xunit -n JingXu.Workbench.Presentation.Tests -o tests/JingXu.Workbench.Presentation.Tests -f net10.0
dotnet new xunit -n JingXu.Workbench.IntegrationTests -o tests/JingXu.Workbench.IntegrationTests -f net10.0
```

Set Presentation.Tests and IntegrationTests to `net10.0-windows`. Add every project to the solution, then add references only in this direction: `Application → Domain`, `Infrastructure → Application + Domain`, `WPF → Application + Infrastructure + Domain`; tests reference their target project. Use:

```powershell
Get-ChildItem src,tests -Recurse -Filter *.csproj | ForEach-Object { dotnet sln JingXu.Workbench.sln add $_.FullName }
dotnet add src/JingXu.Workbench.Application reference src/JingXu.Workbench.Domain
dotnet add src/JingXu.Workbench.Infrastructure reference src/JingXu.Workbench.Application src/JingXu.Workbench.Domain
dotnet add src/JingXu.Workbench reference src/JingXu.Workbench.Application src/JingXu.Workbench.Infrastructure src/JingXu.Workbench.Domain
dotnet add tests/JingXu.Workbench.Domain.Tests reference src/JingXu.Workbench.Domain
dotnet add tests/JingXu.Workbench.Application.Tests reference src/JingXu.Workbench.Application src/JingXu.Workbench.Domain
dotnet add tests/JingXu.Workbench.Infrastructure.Tests reference src/JingXu.Workbench.Infrastructure src/JingXu.Workbench.Application src/JingXu.Workbench.Domain
dotnet add tests/JingXu.Workbench.Presentation.Tests reference src/JingXu.Workbench
dotnet add tests/JingXu.Workbench.IntegrationTests reference src/JingXu.Workbench src/JingXu.Workbench.Infrastructure
```

- [ ] **Step 3: 启用统一工程规则**

`Directory.Build.props` must contain:

```xml
<Project>
  <PropertyGroup>
    <LangVersion>latest</LangVersion>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
    <AnalysisLevel>latest-recommended</AnalysisLevel>
    <Deterministic>true</Deterministic>
    <RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>
  </PropertyGroup>
</Project>
```

`Directory.Packages.props` enables central package management and pins the reviewed package set:

```xml
<Project>
  <PropertyGroup>
    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
  </PropertyGroup>
  <ItemGroup>
    <PackageVersion Include="CommunityToolkit.Mvvm" Version="8.4.2" />
    <PackageVersion Include="Microsoft.NET.Test.Sdk" Version="18.7.0" />
    <PackageVersion Include="xunit.v3" Version="3.2.2" />
    <PackageVersion Include="xunit.runner.visualstudio" Version="3.1.5" />
    <PackageVersion Include="coverlet.collector" Version="10.0.1" />
  </ItemGroup>
</Project>
```

Replace generated xUnit v2 references with `xunit.v3`; test SDK, runner and coverlet references remain `PrivateAssets=all` where appropriate. Commit `packages.lock.json` for every project and set `RestorePackagesWithLockFile=true` in `Directory.Build.props`.

- [ ] **Step 4: 验证依赖方向和空解决方案**

Run:

```powershell
dotnet restore JingXu.Workbench.sln
dotnet build JingXu.Workbench.sln -c Debug
dotnet test JingXu.Workbench.sln -c Debug --no-build
```

Expected: build succeeds with 0 warnings; template tests pass.

- [ ] **Step 5: Commit**

```powershell
git add global.json Directory.Build.props Directory.Packages.props JingXu.Workbench.sln src tests scripts/Install-DotNetSdk.ps1
git diff --cached --check
git commit -m "build: scaffold .NET workbench solution"
```

### Task 2: 文件序号识别与自定义序列表达式

**Files:**
- Create: `src/JingXu.Workbench.Domain/Common/Result.cs`
- Create: `src/JingXu.Workbench.Domain/Composition/FileSequenceParser.cs`
- Test: `tests/JingXu.Workbench.Domain.Tests/Composition/FileSequenceParserTests.cs`

- [ ] **Step 1: 写失败测试**

```csharp
public sealed class FileSequenceParserTests
{
    [Theory]
    [InlineData("商品_片段_12.mp4", 12)]
    [InlineData("clip9-final.mp4", 9)]
    public void Extracts_last_numeric_token(string fileName, int expected) =>
        Assert.Equal(expected, FileSequenceParser.ExtractIndex(fileName).Value);

    [Fact]
    public void Parses_compact_single_digit_expression() =>
        Assert.Equal([2, 6, 4, 5, 1, 3], FileSequenceParser.Parse("264513").Value);

    [Fact]
    public void Parses_comma_expression_with_multi_digit_and_duplicates() =>
        Assert.Equal([2, 6, 14, 14, 3], FileSequenceParser.Parse("2,6,14,14,3").Value);

    [Theory]
    [InlineData("")]
    [InlineData("2,a,3")]
    public void Rejects_ambiguous_or_invalid_expression(string value) =>
        Assert.False(FileSequenceParser.Parse(value).IsSuccess);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Domain.Tests --filter FileSequenceParserTests`

Expected: FAIL because `FileSequenceParser` does not exist.

- [ ] **Step 3: 实现最小强类型结果和解析器**

Expose exactly:

```csharp
public readonly record struct Result<T>(T? Value, string? Error)
{
    public bool IsSuccess => Error is null;
    public static Result<T> Success(T value) => new(value, null);
    public static Result<T> Failure(string error) => new(default, error);
}

public static partial class FileSequenceParser
{
    public static Result<int> ExtractIndex(string fileName);
    public static Result<IReadOnlyList<int>> Parse(string expression);
}
```

Use a generated regex for the final numeric token, reject zero/negative indices and whitespace-only tokens, preserve duplicate comma tokens, and return Chinese validation messages.

- [ ] **Step 4: 运行 GREEN 与全套快速测试**

Run:

```powershell
dotnet test tests/JingXu.Workbench.Domain.Tests --filter FileSequenceParserTests
dotnet test JingXu.Workbench.sln --no-restore
```

Expected: all tests pass with 0 warnings.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Domain/Common src/JingXu.Workbench.Domain/Composition tests/JingXu.Workbench.Domain.Tests/Composition
git diff --cached --check
git commit -m "feat: parse material sequence numbers"
```

### Task 3: 可复现随机编排、自定义编排和累计时间轴

**Files:**
- Create: `src/JingXu.Workbench.Domain/Media/MediaInfo.cs`
- Create: `src/JingXu.Workbench.Domain/Media/MediaAsset.cs`
- Create: `src/JingXu.Workbench.Domain/Composition/CompositionModels.cs`
- Create: `src/JingXu.Workbench.Domain/Composition/DeterministicRandom.cs`
- Create: `src/JingXu.Workbench.Domain/Composition/CompositionPlanner.cs`
- Test: `tests/JingXu.Workbench.Domain.Tests/Composition/CompositionPlannerTests.cs`

- [ ] **Step 1: 写失败测试**

```csharp
public sealed class CompositionPlannerTests
{
    private static MediaAsset Asset(int index, int seconds) =>
        new(Guid.NewGuid(), $"C:\\media\\{index}.mp4", index,
            new MediaInfo(TimeSpan.FromSeconds(seconds), 1080, 1920, 30m, "h264", "aac", true, 0));

    [Fact]
    public void Custom_264513_preserves_requested_order_and_full_duration()
    {
        var assets = Enumerable.Range(1, 6).Select(i => Asset(i, 30)).ToArray();
        var plan = new CompositionPlanner().PlanCustom(assets, [2, 6, 4, 5, 1, 3], TimeSpan.Zero).Value!;
        Assert.Equal([2, 6, 4, 5, 1, 3], plan.Clips.Select(x => x.Asset.SequenceIndex));
        Assert.Equal(TimeSpan.FromSeconds(180), plan.Duration);
        Assert.Equal(TimeSpan.FromSeconds(60), plan.Clips[2].Start);
    }

    [Fact]
    public void Random_batch_is_reproducible_and_unique_until_space_exhausts()
    {
        var assets = Enumerable.Range(1, 4).Select(i => Asset(i, 1)).ToArray();
        var planner = new CompositionPlanner();
        var first = planner.PlanRandomBatch(assets, 8, seed: 264513).Value!;
        var second = planner.PlanRandomBatch(assets, 8, seed: 264513).Value!;
        Assert.Equal(first.Select(Key), second.Select(Key));
        Assert.Equal(8, first.Select(Key).Distinct().Count());
    }

    private static string Key(CompositionPlan p) =>
        string.Join(',', p.Clips.Select(x => x.Asset.SequenceIndex));
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Domain.Tests --filter CompositionPlannerTests`

Expected: FAIL because domain media and planner types do not exist.

- [ ] **Step 3: 实现不可变模型和 Fisher–Yates 编排**

Create records with these public contracts:

```csharp
public sealed record MediaInfo(TimeSpan Duration, int Width, int Height, decimal FrameRate,
    string VideoCodec, string? AudioCodec, bool HasAudio, int RotationDegrees);

public sealed record MediaAsset(Guid Id, string Path, int? SequenceIndex, MediaInfo Info);
public sealed record PlannedClip(MediaAsset Asset, TimeSpan Start, TimeSpan Duration);
public sealed record CompositionPlan(IReadOnlyList<PlannedClip> Clips, TimeSpan Duration,
    int Seed, TimeSpan TransitionDuration);

public sealed class CompositionPlanner
{
    public Result<CompositionPlan> PlanCustom(IReadOnlyList<MediaAsset> assets,
        IReadOnlyList<int> indices, TimeSpan transitionDuration);
    public Result<IReadOnlyList<CompositionPlan>> PlanRandomBatch(IReadOnlyList<MediaAsset> assets,
        int count, int seed, TimeSpan? transitionDuration = null);
}
```

Use a repository-owned SplitMix64 implementation for Fisher–Yates, never `System.Random`, so saved seeds remain stable across .NET upgrades. Normalize the random source set by filename `SequenceIndex`, then normalized absolute path and persisted asset ID; derive each attempt seed from the saved job seed, store emitted permutation keys in a `HashSet<string>`, calculate duration as sum minus `(clipCount - 1) * transitionDuration`, and return a validation failure before planning if transition overlap is not shorter than either adjacent clip.

- [ ] **Step 4: 运行 GREEN 与边界测试**

Add tests for missing sequence index, duplicate asset indices, intentional repeated custom token, one-clip input, zero clips, count above factorial and invalid transition. Run: `dotnet test tests/JingXu.Workbench.Domain.Tests --filter CompositionPlannerTests`.

Expected: all composition tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Domain/Media src/JingXu.Workbench.Domain/Composition tests/JingXu.Workbench.Domain.Tests/Composition
git diff --cached --check
git commit -m "feat: plan deterministic video compositions"
```

### Task 4: 项目、设置和队列的原子 JSON 持久化

**Files:**
- Create: `src/JingXu.Workbench.Domain/Rendering/RenderJob.cs`
- Create: `src/JingXu.Workbench.Domain/Rendering/RenderProfile.cs`
- Create: `src/JingXu.Workbench.Application/Abstractions/IAtomicJsonStore.cs`
- Create: `src/JingXu.Workbench.Application/Projects/ProjectDocument.cs`
- Create: `src/JingXu.Workbench.Application/Projects/ProjectService.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Persistence/AtomicJsonStore.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Persistence/AtomicJsonStoreTests.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Projects/ProjectServiceTests.cs`

- [ ] **Step 1: 写原子保存和恢复失败测试**

```csharp
[Fact]
public async Task Save_then_load_round_trips_schema_version_and_unicode()
{
    using var dir = new TemporaryDirectory();
    var store = new AtomicJsonStore<ProjectDocument>();
    var source = ProjectDocument.Create("口红混剪", dir.Path);
    await store.SaveAsync(Path.Combine(dir.Path, "project.jxproj"), source, DocumentAccessMode.ReadWrite, default);
    var loaded = await store.LoadAsync(Path.Combine(dir.Path, "project.jxproj"), default);
    Assert.Equal(ProjectDocument.CurrentSchemaVersion, loaded.Document.SchemaVersion);
    Assert.Equal("口红混剪", loaded.Document.Name);
}

[Fact]
public async Task Interrupted_running_jobs_recover_as_failed_retryable()
{
    var recovered = ProjectService.RecoverJobs([RenderJob.Running(Guid.NewGuid())]);
    Assert.Equal(JobState.Failed, recovered.Single().State);
    Assert.True(recovered.Single().CanRetry);
}

[Fact]
public async Task Newer_schema_opens_read_only_and_cannot_be_overwritten()
{
    using var dir = ProjectFixtures.WithSchemaVersion(ProjectDocument.CurrentSchemaVersion + 1);
    var store = new AtomicJsonStore<ProjectDocument>();
    var result = await store.LoadAsync(dir.ProjectPath, default);
    Assert.Equal(DocumentAccessMode.ReadOnlyNewerSchema, result.AccessMode);
    await Assert.ThrowsAsync<ReadOnlyDocumentException>(() =>
        store.SaveAsync(dir.ProjectPath, result.Document, result.AccessMode, default));
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter AtomicJsonStoreTests; dotnet test tests/JingXu.Workbench.Application.Tests --filter ProjectServiceTests`

Expected: FAIL because persistence contracts do not exist.

- [ ] **Step 3: 实现版本化文档和同目录原子替换**

`IAtomicJsonStore<T>` exposes `LoadAsync(path, token)` and `SaveAsync(path, document, accessMode, token)`. `AtomicJsonStore<T>` serializes UTF-8 to `<target>.tmp`, flushes with `FlushAsync` and `Flush(flushToDisk: true)`, then uses `File.Replace(temp, target, null)` when the target exists or `File.Move(temp, target)` on first save. A higher unknown `SchemaVersion` returns `DocumentLoadResult<T>` with `DocumentAccessMode.ReadOnlyNewerSchema`; save rejects that access mode and preserves the original bytes.

`RenderJob` is an immutable record with `JobState` values `Draft, Queued, Preparing, Running, Finalizing, Completed, Failed, Cancelled`; only legal transition methods return a new record.

- [ ] **Step 4: 运行 GREEN，并故障注入验证不破坏旧文件**

Inject an `IFileCommitter` fake that throws before move and assert the previous target JSON remains loadable. Run both persistence and application test projects, then `dotnet test JingXu.Workbench.sln --no-restore`.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Domain/Rendering src/JingXu.Workbench.Application src/JingXu.Workbench.Infrastructure/Persistence tests/JingXu.Workbench.Application.Tests tests/JingXu.Workbench.Infrastructure.Tests/Persistence
git diff --cached --check
git commit -m "feat: persist projects and render queue atomically"
```

### Task 5: 运行时定位、进度解析和安全外部进程执行

**Files:**
- Create: `src/JingXu.Workbench.Application/Abstractions/IExternalProcessRunner.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Runtime/RuntimeResolver.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Processes/ProcessModels.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Processes/ExternalProcessRunner.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Processes/WindowsJobObject.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegProgressParser.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Runtime/RuntimeResolverTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Processes/ExternalProcessRunnerTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/FfmpegProgressParserTests.cs`

- [ ] **Step 1: 写失败测试**

```csharp
[Fact]
public void Bundled_runtime_wins_over_user_and_path()
{
    using var dir = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe", "user/ffmpeg.exe");
    var result = new RuntimeResolver(dir.AppRoot, dir.PathLookup).Resolve("ffmpeg", dir.UserPath);
    Assert.Equal(dir.BundledFfmpeg, result.Path);
}

[Fact]
public void Parses_machine_readable_progress_block()
{
    var progress = FfmpegProgressParser.Parse("out_time_us=1500000\nspeed=0.75x\nprogress=continue\n");
    Assert.Equal(TimeSpan.FromMilliseconds(1500), progress.Position);
    Assert.Equal(0.75, progress.Speed);
}

[Fact]
public async Task Runner_drains_both_streams_and_returns_exit_code()
{
    var request = ProcessRequest.Create("powershell.exe", ["-NoProfile", "-Command", "$host.ui.WriteErrorLine('err'); 'out'; exit 7"]);
    var result = await new ExternalProcessRunner().RunAsync(request, null, default);
    Assert.Equal(7, result.ExitCode);
    Assert.Contains("out", result.StandardOutput);
    Assert.Contains("err", result.StandardError);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter "RuntimeResolverTests|ExternalProcessRunnerTests|FfmpegProgressParserTests"`

Expected: FAIL because runtime and process classes do not exist.

- [ ] **Step 3: 实现 ArgumentList、双流异步排空和 Job Object**

`ProcessRequest` contains absolute executable, immutable argument list, working directory and environment overrides. `ExternalProcessRunner` sets `UseShellExecute=false`, redirects both streams, starts `ReadToEndAsync` for stdout and stderr before awaiting `WaitForExitAsync`, associates the process with a Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, and calls `Kill(entireProcessTree: true)` plus closes the Job handle when cancellation is requested.

No public API accepts a prejoined command string.

- [ ] **Step 4: 验证取消不会留下后代进程**

Add a Windows-only integration test that starts PowerShell, spawns a child `ping -t 127.0.0.1`, cancels the token, waits up to five seconds, and asserts both parent and child process IDs no longer exist. Run infrastructure tests twice to catch races.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Application/Abstractions src/JingXu.Workbench.Infrastructure/Runtime src/JingXu.Workbench.Infrastructure/Processes src/JingXu.Workbench.Infrastructure/Rendering/FfmpegProgressParser.cs tests/JingXu.Workbench.Infrastructure.Tests
git diff --cached --check
git commit -m "feat: run media sidecars safely"
```

### Task 6: FFprobe 媒体探测与素材导入用例

**Files:**
- Create: `src/JingXu.Workbench.Application/Abstractions/IMediaProbe.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Media/FfprobeJsonParser.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Media/FfprobeMediaProbe.cs`
- Create: `tests/JingXu.Workbench.Infrastructure.Tests/Media/Fixtures/ffprobe-rotated-with-audio.json`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Media/FfprobeJsonParserTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Media/FfprobeMediaProbeTests.cs`

- [ ] **Step 1: 写 JSON 解析失败测试**

```csharp
[Fact]
public void Parses_duration_fractional_frame_rate_rotation_and_audio()
{
    var json = File.ReadAllText(Fixture("ffprobe-rotated-with-audio.json"));
    var info = FfprobeJsonParser.Parse(json);
    Assert.Equal(TimeSpan.FromMilliseconds(23040), info.Duration);
    Assert.Equal(1080, info.Width);
    Assert.Equal(1920, info.Height);
    Assert.Equal(29.97m, info.FrameRate);
    Assert.Equal(90, info.RotationDegrees);
    Assert.True(info.HasAudio);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter Ffprobe`

Expected: FAIL because parser and probe are missing.

- [ ] **Step 3: 实现 FFprobe 参数和有界错误映射**

Run FFprobe with arguments `-v error -print_format json -show_format -show_streams -show_entries stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,duration:stream_tags=rotate:stream_side_data=rotation:format=duration`. Parse rational frame rates without floating-point division, normalize rotation to `0/90/180/270`, prefer format duration when stream duration is absent, and return a typed `MediaProbeException` with path and stderr summary on non-zero exit.

- [ ] **Step 4: 使用本机 FFprobe 做真实短文件测试**

Generate a one-second rotated MP4 in the test temp directory with lavfi, probe it through `FfprobeMediaProbe`, and assert nonzero duration and expected dimensions. Skip only when runtime resolution reports FFprobe unavailable; release verification must not skip.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Application/Abstractions/IMediaProbe.cs src/JingXu.Workbench.Infrastructure/Media tests/JingXu.Workbench.Infrastructure.Tests/Media
git diff --cached --check
git commit -m "feat: probe imported media metadata"
```

### Task 7: 有界并发、失败隔离和可恢复渲染队列

**Files:**
- Create: `src/JingXu.Workbench.Application/Abstractions/IRenderExecutor.cs`
- Create: `src/JingXu.Workbench.Application/Rendering/RenderCoordinator.cs`
- Create: `src/JingXu.Workbench.Application/Rendering/RenderQueueRecovery.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Rendering/RenderCoordinatorTests.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Rendering/RenderQueueRecoveryTests.cs`

- [ ] **Step 1: 写并发和状态失败测试**

```csharp
[Fact]
public async Task Never_runs_more_than_configured_concurrency()
{
    var executor = new GateRenderExecutor();
    var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), maxConcurrency: 2);
    await coordinator.EnqueueAsync(RenderJobs.Create(4), default);
    await executor.WaitUntilStartedAsync(2);
    Assert.Equal(2, executor.MaxObservedConcurrency);
    Assert.Equal(2, executor.StartedCount);
}

[Fact]
public async Task Failure_is_isolated_and_next_job_starts()
{
    var executor = new ScriptedRenderExecutor([Outcome.Fail("坏素材"), Outcome.Success()]);
    var result = await RenderCoordinatorTestDriver.RunToIdleAsync(executor, RenderJobs.Create(2));
    Assert.Equal([JobState.Failed, JobState.Completed], result.Select(x => x.State));
}

[Fact]
public void Interrupted_active_states_recover_as_retryable_failed()
{
    foreach (var state in new[] { JobState.Preparing, JobState.Running, JobState.Finalizing })
        Assert.True(RenderQueueRecovery.Recover(RenderJobs.WithState(state)).CanRetry);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Application.Tests --filter "RenderCoordinatorTests|RenderQueueRecoveryTests"`

Expected: FAIL because coordinator and recovery policy are missing.

- [ ] **Step 3: 实现调度循环和每状态原子保存**

Use a single coordinator-owned scheduler loop plus `SemaphoreSlim` for 1–4 active jobs. Enqueue stores an immutable job snapshot before it becomes visible. Every legal state transition awaits `IAtomicJsonStore` before publishing the new observable queue. `PauseQueue` blocks new acquisitions but lets active jobs finish; `CancelJobAsync` cancels that job token only. A failed executor result maps to Chinese `RenderFailure` and does not cancel the scheduler.

- [ ] **Step 4: 覆盖暂停、取消、保存失败和关闭恢复**

Add tests proving pause starts no new jobs, cancel affects only one job, a queue-store failure does not publish a fake state, max concurrency can change only after current leases finish, and shutdown waits for state persistence. Run application tests twice.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Application/Rendering src/JingXu.Workbench.Application/Abstractions/IRenderExecutor.cs tests/JingXu.Workbench.Application.Tests/Rendering
git diff --cached --check
git commit -m "feat: coordinate persistent render jobs"
```

### Task 8: 专业 WPF 制作工作台壳层

**Files:**
- Create: `src/JingXu.Workbench/Bootstrap/AppCompositionRoot.cs`
- Create: `src/JingXu.Workbench/Themes/Colors.xaml`
- Create: `src/JingXu.Workbench/Themes/Typography.xaml`
- Create: `src/JingXu.Workbench/Themes/Controls.xaml`
- Create: `src/JingXu.Workbench/Features/Shell/WorkspaceModule.cs`
- Create: `src/JingXu.Workbench/Features/Shell/ShellViewModel.cs`
- Modify: `src/JingXu.Workbench/App.xaml`
- Modify: `src/JingXu.Workbench/App.xaml.cs`
- Create: `src/JingXu.Workbench/ShellWindow.xaml`
- Create: `src/JingXu.Workbench/ShellWindow.xaml.cs`
- Create: `src/JingXu.Workbench/Assets/AppIcon.ico`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Shell/ShellViewModelTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Themes/ThemeContractTests.cs`

- [ ] **Step 1: 写导航和主题契约失败测试**

```csharp
[Fact]
public void Navigation_changes_module_and_preserves_module_instance()
{
    var shell = ShellViewModelTestFactory.Create();
    var first = shell.CurrentModule;
    shell.NavigateCommand.Execute(WorkspaceModule.Queue);
    shell.NavigateCommand.Execute(WorkspaceModule.Composition);
    Assert.Same(first, shell.CurrentModule);
}

[Fact]
public void Every_status_exposes_text_icon_and_automation_name()
{
    foreach (var state in Enum.GetValues<JobState>())
    {
        var status = StatusPresentation.For(state);
        Assert.False(string.IsNullOrWhiteSpace(status.Text));
        Assert.False(string.IsNullOrWhiteSpace(status.IconKey));
        Assert.False(string.IsNullOrWhiteSpace(status.AutomationName));
    }
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Presentation.Tests --filter ShellViewModelTests`

Expected: FAIL because shell presentation models do not exist.

- [ ] **Step 3: 建立设计令牌和五区工作台**

Use palette tokens: warm background `#F3F1EA`, panel `#FCFBF7`, ink `#17231F`, muted `#68736E`, accent `#246B59`, accent-hover `#1C5748`, amber `#C9823C`, danger `#A8463F`, border `#D6D5CF`. Use 4/8 spacing, 6px standard radius, 1px borders, 160ms easing and visible 2px keyboard focus rings.

`ShellWindow` contains custom title bar, 56px left module rail, 260px material rail, flexible central workspace, 300px inspector and 144px collapsible bottom queue. At M1 only implemented modules are enabled; later tasks enable Composition, Overlays and Subtitles when their concrete views exist. There are no empty click targets or “coming soon” pages.

- [ ] **Step 4: 验证布局和键盘可达性**

Create a WPF dispatcher test that loads resources and measures `ShellWindow` at 1600×900 and 1920×1080 logical sizes; assert each named core region has positive size and remains inside the client area. Add automation names to icon buttons and verify Tab traversal includes title actions, nav, material area, workspace, inspector and queue. Use a restrained custom interlocking-frame app mark for `AppIcon.ico`, and assert the WPF project declares it as `ApplicationIcon` instead of shipping the default executable icon.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench tests/JingXu.Workbench.Presentation.Tests
git diff --cached --check
git commit -m "feat: build professional WPF workbench shell"
```

### Task 9: 画幅、质量和基础 FFmpeg 合成命令

**Files:**
- Create: `src/JingXu.Workbench.Domain/Rendering/RenderProfile.cs`
- Create: `src/JingXu.Workbench.Domain/Rendering/TranscodeReason.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegCommand.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegCommandCompiler.cs`
- Test: `tests/JingXu.Workbench.Domain.Tests/Rendering/RenderProfileTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/FfmpegCommandCompilerTests.cs`

- [ ] **Step 1: 写直拷资格、画幅和参数 token 失败测试**

```csharp
[Fact]
public void Effects_or_mismatched_streams_disable_lossless_copy()
{
    Assert.True(RenderDecision.For(TestPlans.CompatibleHardCut()).CanStreamCopy);
    Assert.False(RenderDecision.For(TestPlans.WithOverlay()).CanStreamCopy);
    Assert.Contains(TranscodeReason.Overlay, RenderDecision.For(TestPlans.WithOverlay()).Reasons);
}

[Theory]
[InlineData(QualityPreset.High, 18, 192)]
[InlineData(QualityPreset.Balanced, 22, 160)]
[InlineData(QualityPreset.Compact, 27, 128)]
public void Quality_presets_map_to_expected_values(QualityPreset preset, int crf, int audioKbps)
{
    var profile = RenderProfile.For(preset);
    Assert.Equal(crf, profile.Crf);
    Assert.Equal(audioKbps, profile.AudioKbps);
}

[Fact]
public void Chinese_path_is_one_argument_without_shell_quotes()
{
    var command = new FfmpegCommandCompiler().Compile(TestPlans.WithInput("C:\\素材 文件\\1.mp4"));
    Assert.Contains("C:\\素材 文件\\1.mp4", command.Arguments);
    Assert.DoesNotContain(command.Arguments, x => x.Contains("cmd.exe", StringComparison.OrdinalIgnoreCase));
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Domain.Tests --filter RenderProfileTests; dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter FfmpegCommandCompilerTests`

Expected: FAIL because render decision and compiler are missing.

- [ ] **Step 3: 实现 typed filter graph 和参数列表**

`FfmpegCommand` exposes executable path and immutable `IReadOnlyList<string> Arguments`. Compiler adds one `-i` token pair per input; normalizes video to target frame size, sample aspect ratio and pixel format; synthesizes matching silence for clips without audio; concatenates normalized streams; selects centered crop, blurred background or letterbox filter; maps `[vout]` and `[aout]`; and appends `-progress pipe:1 -nostats`.

Only compatible effect-free plans use concat demuxer plus `-c copy`. Transcode uses `libx264`, `yuv420p` and AAC for deterministic software mode. Hardware encoder selection is a typed profile override and never silently changes quality labeling.

- [ ] **Step 4: 在不同区域设置下验证小数格式与超长命令预检**

Set current culture to `de-DE` and assert frame rate, opacity and seconds still use invariant decimal points. Add a 30,000-character conservative Windows command-line budget preflight that returns a Chinese error before process start. Probe NVENC/QSV/AMF encoders; an unavailable user preference falls back to software encoding only with an explicit warning captured in the job snapshot. Run domain and infrastructure tests.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Domain/Rendering src/JingXu.Workbench.Infrastructure/Rendering tests/JingXu.Workbench.Domain.Tests/Rendering tests/JingXu.Workbench.Infrastructure.Tests/Rendering
git diff --cached --check
git commit -m "feat: compile core ffmpeg render commands"
```

### Task 10: 三类多层视频蒙版

**Files:**
- Create: `src/JingXu.Workbench.Domain/Overlays/OverlayModels.cs`
- Create: `src/JingXu.Workbench.Domain/Common/NormalizedRect.cs`
- Create: `src/JingXu.Workbench.Domain/Overlays/OverlayTimelineResolver.cs`
- Create: `src/JingXu.Workbench.Domain/Overlays/OverlaySourceSelector.cs`
- Create: `src/JingXu.Workbench.Application/Projects/OverlayLibraryService.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/OverlayFilterCompiler.cs`
- Test: `tests/JingXu.Workbench.Domain.Tests/Overlays/OverlayTimelineResolverTests.cs`
- Test: `tests/JingXu.Workbench.Domain.Tests/Overlays/OverlaySourceSelectorTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/OverlayFilterCompilerTests.cs`

- [ ] **Step 1: 写模式、默认值、循环和层级失败测试**

```csharp
[Fact]
public void Screenshot_preset_is_top_full_width_and_adjustable()
{
    var layer = OverlayLayer.CreateScreenshotPreset(TestAssets.Overlay);
    Assert.Equal(new NormalizedRect(0, 0, 1, 0.48), layer.Bounds);
    Assert.Equal(OverlayMode.FreeCover, layer.Mode);
}

[Fact]
public void Starts_at_requested_clip_and_loops_to_exact_end()
{
    var plan = TestPlans.Clips(seconds: [2, 3, 4]);
    var resolved = OverlayTimelineResolver.Resolve(plan, TestLayers.StartAt(2, sourceSeconds: 2.5));
    Assert.Equal(TimeSpan.FromSeconds(2), resolved.Start);
    Assert.Equal(TimeSpan.FromSeconds(7), resolved.ActiveDuration);
    Assert.Equal(3, resolved.LoopCount);
    Assert.Equal(TimeSpan.FromSeconds(2), resolved.LastLoopDuration);
}

[Fact]
public void Layers_are_stably_ordered_by_z_index() =>
    Assert.Equal(["back", "front"], OverlayTimelineResolver.Sort(TestLayers.Unordered()).Select(x => x.Name));

[Fact]
public void Library_random_choice_is_reproducible_from_job_seed()
{
    var library = TestAssets.OverlayLibrary(8);
    Assert.Equal(OverlaySourceSelector.Select(library, 3, 264513),
        OverlaySourceSelector.Select(library, 3, 264513));
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Domain.Tests --filter Overlay; dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter OverlayFilterCompilerTests`

Expected: FAIL because overlay model and compiler do not exist.

- [ ] **Step 3: 实现自由、全屏和形状遮罩 filter graph**

All coordinates are normalized records validated to `[0,1]`, opacity to `[0,1]`, and start clip to `1..clipCount`. Convert rectangle edges independently to pixels and clamp to frame bounds. Inputs use `-stream_loop -1`, `trim=duration=<active>`, `setpts=PTS-STARTPTS+<start>/TB`, then:

- FreeCover: selected fit chain + alpha multiplication + `overlay=x:y:enable=between(t,start,end)`.
- FullFrameLowOpacity: bounds `(0,0,1,1)`, FillCrop and default opacity `0.20`.
- ShapeMask: rectangle/rounded rectangle/ellipse generated alpha expression, or imported grayscale/alpha PNG normalized then `alphamerge`.

Discard overlay audio by default; Mix mode trims, loops, delays and mixes with `amix=duration=first`. Feed each prior overlay result into the next layer ordered by `ZIndex`.

`OverlayLibraryService` atomically stores absolute file reference, stable ID, tags, thumbnail path and last-used timestamp. Random selection uses the shared SplitMix64 implementation and records the chosen stable IDs in the immutable job snapshot.

- [ ] **Step 4: 覆盖无效参数和输入索引漂移**

Add tests for zero-area rectangles, missing alpha PNG, invalid start clip, zero-duration overlay, Contain/FillCrop/Stretch differences, overlays with and without audio, and input indexes after stickers/BGM are inserted. Run overlay tests twice.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Domain/Overlays src/JingXu.Workbench.Application/Projects/OverlayLibraryService.cs src/JingXu.Workbench.Infrastructure/Rendering/OverlayFilterCompiler.cs tests/JingXu.Workbench.Domain.Tests/Overlays tests/JingXu.Workbench.Infrastructure.Tests/Rendering/OverlayFilterCompilerTests.cs
git diff --cached --check
git commit -m "feat: render layered video masks"
```

### Task 11: 差异化效果、贴纸、BGM 和模板

**Files:**
- Create: `src/JingXu.Workbench.Domain/Effects/EffectTemplate.cs`
- Create: `src/JingXu.Workbench.Application/Projects/TemplateService.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/EffectFilterCompiler.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/AudioFilterCompiler.cs`
- Test: `tests/JingXu.Workbench.Domain.Tests/Effects/EffectTemplateTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/EffectFilterCompilerTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/AudioFilterCompilerTests.cs`

- [ ] **Step 1: 写确定性模板和音频失败测试**

```csharp
[Fact]
public void Same_seed_materializes_same_randomized_effects()
{
    var template = EffectTemplates.StandardVariation();
    Assert.Equal(template.Materialize(264513), template.Materialize(264513));
}

[Fact]
public void Variation_never_changes_speed_or_timeline_duration()
{
    var effect = EffectTemplates.StandardVariation().Materialize(1);
    Assert.Equal(1.0, effect.PlaybackRate);
    Assert.DoesNotContain("setpts", new EffectFilterCompiler().Compile(effect));
}

[Fact]
public void Bgm_defaults_keep_original_and_loop_with_fade()
{
    var graph = new AudioFilterCompiler().Compile(AudioPlans.WithBgm(durationSeconds: 10));
    Assert.Contains("aloop", graph);
    Assert.Contains("volume=0.18", graph);
    Assert.Contains("afade=t=out:st=9:d=1", graph);
    Assert.Contains("amix=duration=first", graph);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Domain.Tests --filter EffectTemplateTests; dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter "EffectFilterCompilerTests|AudioFilterCompilerTests"`

Expected: FAIL because effect and audio template types are absent.

- [ ] **Step 3: 实现固定随机算法和 typed effect stages**

Use a repository-owned SplitMix64 implementation, not `System.Random`, so saved seeds remain reproducible across .NET upgrades. Template fields cover mirror, 1–3% crop/zoom, brightness/contrast/saturation ranges, denoise strength, metadata clearing, title, image/GIF/video sticker, BGM volumes and fade. Materialization derives each value from named seed branches so adding a future field does not change existing values.

Sticker coordinates remain normalized and compile to bounded overlay filters. GIF/video stickers loop only for their configured active interval. Templates save through the same atomic JSON store with explicit schema version.

- [ ] **Step 4: 完成 round-trip、范围和无 BGM 原声测试**

Test JSON round trip, invalid ranges, same seed equality, different seed variability, original audio pass-through when BGM is absent, silent main input with BGM, and metadata clearing without changing duration.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Domain/Effects src/JingXu.Workbench.Application/Projects/TemplateService.cs src/JingXu.Workbench.Infrastructure/Rendering tests/JingXu.Workbench.Domain.Tests/Effects tests/JingXu.Workbench.Infrastructure.Tests/Rendering
git diff --cached --check
git commit -m "feat: add reusable effect and audio templates"
```

### Task 12: 预检、真实渲染、临时输出和封面

**Files:**
- Create: `src/JingXu.Workbench.Application/Rendering/RenderPreflight.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegRenderExecutor.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/OutputNamePolicy.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Rendering/RenderPreflightTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/FfmpegRenderExecutorTests.cs`

- [ ] **Step 1: 写预检和安全提交失败测试**

```csharp
[Fact]
public async Task Failed_render_never_replaces_existing_output()
{
    using var dir = new TemporaryDirectory();
    var output = dir.File("成片.mp4", contents: "existing");
    var executor = RenderExecutorFactory.WithProcessExitCode(1);
    var result = await executor.ExecuteAsync(TestJobs.To(output), null, default);
    Assert.False(result.IsSuccess);
    Assert.Equal("existing", File.ReadAllText(output));
    Assert.Empty(dir.Files("*.partial.*"));
}

[Fact]
public void Disk_preflight_requires_output_plus_temp_times_one_point_two_five()
{
    var result = RenderPreflight.CheckDisk(requiredBytes: 800, availableBytes: 999);
    Assert.False(result.IsSuccess);
    Assert.True(RenderPreflight.CheckDisk(800, 1000).IsSuccess);
}

[Fact]
public void Default_output_uses_source_or_project_storyboard_folder()
{
    Assert.Equal("C:\\素材\\分镜输出", OutputNamePolicy.DefaultDirectory(["C:\\素材"], "C:\\项目"));
    Assert.Equal("C:\\项目\\分镜输出", OutputNamePolicy.DefaultDirectory(["C:\\素材A", "D:\\素材B"], "C:\\项目"));
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Application.Tests --filter RenderPreflightTests; dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter FfmpegRenderExecutorTests`

Expected: FAIL because preflight/executor do not exist.

- [ ] **Step 3: 实现同卷 staging、进度、验证和封面**

Preflight checks all inputs, output write probe, runtime/filter/encoder capabilities, sequence validity, command budget and disk factor 1.25. Executor creates `<outputDir>/.jingxu-tmp/<jobId>/`, streams progress from stdout, logs bounded stderr, and on exit 0 probes the temp output for duration/video stream before `File.Move(..., overwritePolicy)`. On failure/cancel it deletes partial media but preserves the text log.

Generate cover JPEG with a second FFmpeg command: first source frame for `FirstSourceFrame`, or `-sseof -0.1` from completed output for `FinalOutputFrame`. Use three-digit collision suffixes and never silently overwrite.

`OutputNamePolicy` chooses `<singleSource>\分镜输出` for a one-folder job and `<project>\分镜输出` for multiple source folders, unless the immutable request contains an explicit absolute output directory.

- [ ] **Step 4: 覆盖取消、损坏零字节输出和封面错误**

Add tests proving cancellation kills process tree, zero-byte exit-0 output is rejected, duration outside tolerance is rejected, cover failure marks the job failed without deleting the valid temp video until retry, and successful finalization leaves no temp directory.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Application/Rendering src/JingXu.Workbench.Infrastructure/Rendering tests/JingXu.Workbench.Application.Tests/Rendering tests/JingXu.Workbench.Infrastructure.Tests/Rendering
git diff --cached --check
git commit -m "feat: execute and finalize safe video renders"
```

### Task 13: 素材、编排、蒙版和队列的完整 WPF 工作流

**Files:**
- Create: `src/JingXu.Workbench/Features/Materials/MaterialsViewModel.cs`
- Create: `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs`
- Create: `src/JingXu.Workbench/Features/Composition/CompositionView.xaml`
- Create: `src/JingXu.Workbench/Features/Overlays/OverlayEditorViewModel.cs`
- Create: `src/JingXu.Workbench/Features/Overlays/OverlayEditorView.xaml`
- Create: `src/JingXu.Workbench/Features/Queue/RenderQueueViewModel.cs`
- Create: `src/JingXu.Workbench/Features/Queue/RenderQueueView.xaml`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Overlays/OverlayEditorViewModelTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Queue/RenderQueueViewModelTests.cs`

- [ ] **Step 1: 写 ViewModel 行为失败测试**

```csharp
[Fact]
public async Task Import_shows_probe_metadata_and_sequence_diagnostics()
{
    var vm = ViewModels.Composition(probe: FakeProbe.ForSixClips());
    await vm.ImportFilesCommand.ExecuteAsync(TestPaths.SixClips);
    Assert.Equal(6, vm.Materials.Count);
    Assert.All(vm.Materials, x => Assert.True(x.Duration > TimeSpan.Zero));
}

[Fact]
public void Invalid_custom_expression_disables_enqueue_with_specific_message()
{
    var vm = ViewModels.LoadedComposition();
    vm.Mode = CompositionMode.CustomSequence;
    vm.SequenceExpression = "2,a,3";
    Assert.False(vm.EnqueueCommand.CanExecute(null));
    Assert.Contains("第 2 项", vm.ValidationMessage);
}

[Fact]
public void Added_overlay_uses_selected_mode_and_user_can_edit_bounds()
{
    var vm = ViewModels.OverlayEditor();
    vm.AddOverlay(OverlayMode.ShapeMask);
    vm.Selected.Bounds = new NormalizedRect(0.1, 0.1, 0.8, 0.4);
    Assert.Equal(OverlayMode.ShapeMask, vm.Selected.Mode);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Presentation.Tests --filter "CompositionViewModelTests|OverlayEditorViewModelTests|RenderQueueViewModelTests"`

Expected: FAIL because feature ViewModels do not exist.

- [ ] **Step 3: 实现无占位的生产工作流**

Materials supports file/folder dialogs and drag-drop; probes at max concurrency 4; preserves selection and shows warnings. Composition switches random/custom, previews expanded cards and exact duration, exposes quality/aspect/effect/cover/output controls, and deep-snapshots requests on enqueue. Overlay editor provides three explicit add buttons, layer list, start clip, fit, mute/mix, opacity and relative rectangle fields; preview uses generated low-resolution proxy stills rather than doing FFmpeg work on the UI thread. Queue shows Chinese state, phase, progress, speed, ETA, log link, cancel, retry and open-folder.

- [ ] **Step 4: 验证 DPI、键盘和无空命令**

Measure the finished composition workbench at 1600×900 and 125%/150% scaling. Reflect command properties from enabled views and assert each executable command has a bound handler and each disabled command exposes validation/help text. Run all M1/M2 unit tests and launch the app for an import-to-queue smoke test.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench/Features tests/JingXu.Workbench.Presentation.Tests
git diff --cached --check
git commit -m "feat: complete batch composition workbench"
```

### Task 14: M2 真实媒体端到端验收

**Files:**
- Create: `scripts/New-MediaFixtures.ps1`
- Create: `tests/JingXu.Workbench.IntegrationTests/Media/LavfiMediaFactory.cs`
- Create: `tests/JingXu.Workbench.IntegrationTests/Media/CompositionRenderTests.cs`
- Create: `tests/JingXu.Workbench.IntegrationTests/Media/OverlayRenderTests.cs`
- Create: `tests/JingXu.Workbench.IntegrationTests/Media/AudioAndCoverTests.cs`

- [ ] **Step 1: 先写真实输出失败测试**

Generate six color/tone clips and assert custom `264513` by sampling the center pixel and dominant audio frequency at each segment midpoint. Add a long-running six-by-30-second duration test with tolerance `max(one frame, 100ms)`. For overlays, sample before the selected clip, during each loop and at the final frame; assert three modes, shape interior/exterior and top `ZIndex` pixels. Test Unicode/space paths, no-audio inputs, BGM mix and both cover modes.

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.IntegrationTests --filter "CompositionRenderTests|OverlayRenderTests|AudioAndCoverTests"`

Expected: tests fail at the first still-unwired real render behavior, not fixture setup.

- [ ] **Step 3: 仅修正真实管线暴露的行为缺口**

For every failure, add the narrowest lower-level regression test before changing compiler/executor code. Use software `libx264` in integration tests; never loosen pixel/timing tolerances without recording the measured codec reason.

- [ ] **Step 4: 运行 M2 全门禁**

Run:

```powershell
dotnet test JingXu.Workbench.sln -c Release
dotnet test tests/JingXu.Workbench.IntegrationTests -c Release --filter Category=LongRunning
dotnet format JingXu.Workbench.sln --verify-no-changes
dotnet build JingXu.Workbench.sln -c Release --no-restore
```

Expected: 0 failures, 0 warnings, formatter clean.

- [ ] **Step 5: Commit**

```powershell
git add scripts/New-MediaFixtures.ps1 tests/JingXu.Workbench.IntegrationTests src
git diff --cached --check
git commit -m "test: verify composition and overlays end to end"
```

### Task 15: 字幕领域模型、SRT/ASS 编解码和手动去字幕

**Files:**
- Create: `src/JingXu.Workbench.Domain/Subtitles/SubtitleModels.cs`
- Create: `src/JingXu.Workbench.Domain/Subtitles/SubtitleTimeline.cs`
- Create: `src/JingXu.Workbench.Application/Abstractions/ISubtitleDocumentCodec.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Subtitles/SrtSubtitleCodec.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Subtitles/AssSubtitleCodec.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/SubtitleRemovalFilterCompiler.cs`
- Test: `tests/JingXu.Workbench.Domain.Tests/Subtitles/SubtitleTimelineTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Subtitles/SrtSubtitleCodecTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Subtitles/AssSubtitleCodecTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/SubtitleRemovalFilterCompilerTests.cs`

- [ ] **Step 1: 写时间轴、格式和三种手动去除失败测试**

```csharp
[Fact]
public void Invalid_cues_are_reported_and_never_silently_deleted()
{
    var cues = new[]
    {
        SubtitleCue.Create(TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(1), "倒序"),
        SubtitleCue.Create(TimeSpan.Zero, TimeSpan.FromSeconds(1), "")
    };
    var issues = SubtitleTimeline.Validate(cues);
    Assert.Equal(2, issues.Count);
    Assert.Equal(2, cues.Length);
}

[Fact]
public void Srt_round_trip_preserves_multiline_chinese_and_milliseconds()
{
    var source = "1\r\n00:00:01,250 --> 00:00:03,500\r\n第一行\r\nsecond line\r\n";
    var codec = new SrtSubtitleCodec();
    var decoded = codec.Read(source, "sample.srt");
    Assert.Equal(source.Replace("\r\n", "\n"), codec.Write(decoded).Replace("\r\n", "\n"));
}

[Theory]
[InlineData(SubtitleRemovalMode.Blur, "gblur")]
[InlineData(SubtitleRemovalMode.Delogo, "delogo")]
[InlineData(SubtitleRemovalMode.CropAndReframe, "crop=")]
public void Manual_removal_compiles_selected_mode(SubtitleRemovalMode mode, string token) =>
    Assert.Contains(token, new SubtitleRemovalFilterCompiler().Compile(TestSubtitlePlans.Manual(mode)));
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Domain.Tests --filter SubtitleTimelineTests; dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter "SubtitleCodecTests|SubtitleRemovalFilterCompilerTests"`

Expected: FAIL because subtitle contracts and codecs do not exist.

- [ ] **Step 3: 实现可审阅模型、格式编解码和 typed filters**

Define immutable `SubtitleCue`, `SubtitleStyle`, `DetectedSubtitleSegment`, `SubtitleProject`, `SubtitleRemovalPlan`, `SubtitleReviewState` and `SubtitleRemovalMode`. Normalized rectangles clamp only during explicit conversion; invalid model construction returns a validation result. Timeline validation reports empty text, end-before-start and overlap; explicit `ResolveOverlaps` may trim the earlier cue but never silently drops one.

SRT supports BOM, LF/CRLF, milliseconds and multiline text with source line diagnostics. ASS honors the declared `Format:` field order, preserves commas in `Text`, `\N`, alignment/margins/style and unknown override tags. Blur crops the ROI, blurs it, then overlays it back; Delogo uses outward-rounded pixel bounds; CropAndReframe is allowed only for a band touching top or bottom and passes the result through the existing aspect adapter.

- [ ] **Step 4: 覆盖 Windows 路径转义和导入编辑导出等价性**

Test drive-letter, backslash, apostrophe, Unicode font and subtitle paths in real FFmpeg filter arguments. Test SRT/ASS import → edit → export → import equivalence, overlap diagnostics, unreviewed auto regions blocking render and crop rejection for a floating middle rectangle.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Domain/Subtitles src/JingXu.Workbench.Application/Abstractions/ISubtitleDocumentCodec.cs src/JingXu.Workbench.Infrastructure/Subtitles src/JingXu.Workbench.Infrastructure/Rendering/SubtitleRemovalFilterCompiler.cs tests/JingXu.Workbench.Domain.Tests/Subtitles tests/JingXu.Workbench.Infrastructure.Tests/Subtitles tests/JingXu.Workbench.Infrastructure.Tests/Rendering/SubtitleRemovalFilterCompilerTests.cs
git diff --cached --check
git commit -m "feat: model and edit offline subtitles"
```

### Task 16: FFmpeg 抽帧、Tesseract OCR 和跨帧字幕区域聚类

**Files:**
- Create: `src/JingXu.Workbench.Application/Subtitles/FrameSamplingPlanner.cs`
- Create: `src/JingXu.Workbench.Application/Subtitles/SubtitleRegionClusterer.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Subtitles/TesseractTsvParser.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Subtitles/TesseractRunner.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Subtitles/SubtitleFrameExtractor.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Subtitles/FrameSamplingPlannerTests.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Subtitles/SubtitleRegionClustererTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Subtitles/TesseractTsvParserTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Subtitles/TesseractRunnerTests.cs`

- [ ] **Step 1: 写采样、TSV 和聚类失败测试**

```csharp
[Fact]
public void Short_video_samples_every_half_second_using_pts()
{
    var samples = FrameSamplingPlanner.Plan(TimeSpan.FromSeconds(2), maxFrames: 3600);
    Assert.Equal([0, .5, 1, 1.5], samples.Select(x => x.TotalSeconds));
}

[Fact]
public void Long_video_produces_exactly_3600_evenly_spaced_samples() =>
    Assert.Equal(3600, FrameSamplingPlanner.Plan(TimeSpan.FromHours(2), 3600).Count);

[Fact]
public void Tsv_words_are_grouped_by_frame_block_paragraph_and_line()
{
    var lines = TesseractTsvParser.Parse(Fixtures.Read("chi-eng.tsv"));
    Assert.Equal("紫色梅果味", lines[0].Text);
    Assert.True(lines[0].Bounds.Height > 0);
}

[Fact]
public void Jittered_boxes_cluster_but_low_confidence_remains_reviewable()
{
    var result = SubtitleRegionClusterer.Cluster(OcrFixtures.JitteredLowConfidence());
    Assert.Single(result);
    Assert.True(result[0].RequiresReview);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Application.Tests --filter "FrameSamplingPlannerTests|SubtitleRegionClustererTests"; dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter "TesseractTsvParserTests|TesseractRunnerTests"`

Expected: FAIL because OCR pipeline types are missing.

- [ ] **Step 3: 实现 PTS manifest、批量 OCR 和稳定区域聚类**

Sampling defaults to 500ms and exactly 3600 evenly spaced PTS values above the cap. ROI defaults to normalized `(0, 0.55, 1, 0.45)` and maps boxes back to full-frame coordinates. Frame extractor writes PNG plus a manifest of actual PTS. For each group of at most 200 frames, write a UTF-8 Tesseract image-list file, invoke one `tesseract <list-file> stdout -l chi_sim+eng tsv` process, and map TSV `page_num` back to the PTS manifest. OCR/ASR each use a concurrency gate of 1, so the workflow never launches unbounded processes.

Parse level-5 words, group by block/paragraph/line, preserve low confidence, cluster neighboring frames by time gap ≤1.5s and region IoU ≥0.35, and use median edges to resist outliers. A low-confidence cluster stays visible with `RequiresReview=true`.

- [ ] **Step 4: 验证取消、无文字、旋转和 VFR**

Add tests for no OCR result, ROI/full-screen switch, rotation mapping, variable-frame-rate actual PTS, nonzero Tesseract exit, cancellation cleanup and confirmation state. Diagnostic logs may include counts/confidence ranges but never recognized text.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Application/Subtitles src/JingXu.Workbench.Infrastructure/Subtitles tests/JingXu.Workbench.Application.Tests/Subtitles tests/JingXu.Workbench.Infrastructure.Tests/Subtitles
git diff --cached --check
git commit -m "feat: detect hard subtitle regions offline"
```

### Task 17: whisper.cpp 本地语音识别

**Files:**
- Create: `src/JingXu.Workbench.Application/Abstractions/ISpeechRecognizer.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Subtitles/WhisperSrtParser.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Subtitles/WhisperRunner.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Subtitles/WhisperSrtParserTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Subtitles/WhisperRunnerTests.cs`

- [ ] **Step 1: 写音频预处理、模型和结果解析失败测试**

```csharp
[Fact]
public void Parses_mixed_language_whisper_srt_without_logging_text()
{
    var cues = WhisperSrtParser.Parse(Fixtures.Read("whisper-zh-en.srt"));
    Assert.Equal(2, cues.Count);
    Assert.Equal("今天 launch 新产品", cues[0].Text);
}

[Fact]
public async Task Missing_model_fails_before_process_start()
{
    var process = new RecordingProcessRunner();
    var result = await WhisperRunnerFactory.Create(process, modelPath: "missing.bin")
        .RecognizeAsync("audio.mp4", default);
    Assert.False(result.IsSuccess);
    Assert.Empty(process.Requests);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter "WhisperSrtParserTests|WhisperRunnerTests"`

Expected: FAIL because speech recognizer and runner do not exist.

- [ ] **Step 3: 实现 16kHz 单声道预处理和锁定 CLI 契约**

Use FFmpeg to extract `pcm_s16le`, 16kHz, mono WAV in the job temp directory. Resolve `whisper-cli.exe` and a SHA-256-validated multilingual base model before starting. Pass model, WAV, language `auto`, SRT output prefix and no-console-color as independent tokens. Parse generated SRT into cues, map progress without capturing cue text, delete WAV/result temp files after success/failure/cancel, and reuse the Windows Job Object runner.

- [ ] **Step 4: 增加真实 `--help` 契约和取消测试**

Pin whisper.cpp version in runtime manifest. Integration-test the expected flags against `whisper-cli --help`, test a licensed short Chinese/English audio asset, assert at least one cue and increasing timestamps, and assert cancellation removes the process tree and temp audio.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Application/Abstractions/ISpeechRecognizer.cs src/JingXu.Workbench.Infrastructure/Subtitles tests/JingXu.Workbench.Infrastructure.Tests/Subtitles
git diff --cached --check
git commit -m "feat: transcribe audio with local whisper"
```

### Task 18: 字幕实验室工作流、编辑界面和烧录

**Files:**
- Create: `src/JingXu.Workbench.Application/Subtitles/SubtitleWorkflow.cs`
- Create: `src/JingXu.Workbench.Application/Subtitles/SubtitleWorkflowProgress.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/SubtitleBurnInFilterCompiler.cs`
- Create: `src/JingXu.Workbench/Features/Subtitles/PreviewCoordinateMapper.cs`
- Create: `src/JingXu.Workbench/Features/Subtitles/SubtitleLabViewModel.cs`
- Create: `src/JingXu.Workbench/Features/Subtitles/SubtitleLabView.xaml`
- Test: `tests/JingXu.Workbench.Application.Tests/Subtitles/SubtitleWorkflowTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Subtitles/SubtitleLabViewModelTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/SubtitleBurnInFilterCompilerTests.cs`
- Test: `tests/JingXu.Workbench.IntegrationTests/Subtitles/SubtitleLabRenderTests.cs`

- [ ] **Step 1: 写工作流、坐标和烧录失败测试**

```csharp
[Fact]
public async Task Auto_flow_orders_extract_ocr_cluster_and_marks_results_unreviewed()
{
    var workflow = SubtitleWorkflowTestFactory.Create();
    var result = await workflow.DetectAsync("video.mp4", default);
    Assert.Equal(["extract", "ocr", "cluster"], workflow.Trace);
    Assert.All(result.Segments, x => Assert.Equal(SubtitleReviewState.Unreviewed, x.State));
}

[Fact]
public void Burn_is_disabled_until_regions_and_timeline_are_valid()
{
    var vm = SubtitleLabViewModelTestFactory.WithUnreviewedRegion();
    Assert.False(vm.RenderCommand.CanExecute(null));
    Assert.Contains("确认字幕区域", vm.BlockingMessage);
}

[Fact]
public void Old_subtitle_removal_precedes_new_ass_burn_in()
{
    var graph = new SubtitleBurnInFilterCompiler().Compile(TestSubtitlePlans.Replace());
    Assert.True(graph.IndexOf("delogo", StringComparison.Ordinal) < graph.IndexOf("subtitles=", StringComparison.Ordinal));
}
```

- [ ] **Step 2: 运行并确认 RED**

Run:

```powershell
dotnet test tests/JingXu.Workbench.Application.Tests --filter SubtitleWorkflowTests
dotnet test tests/JingXu.Workbench.Presentation.Tests --filter SubtitleLabViewModelTests
dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter SubtitleBurnInFilterCompilerTests
```

Expected: FAIL because workflow, ViewModel and burn compiler do not exist.

- [ ] **Step 3: 实现完整无占位字幕工作台**

View provides media preview, lower-45%/full-screen choice, mouse/keyboard region editor, detected region list with confidence/review text, removal method, OCR detection, Whisper transcription, SRT/ASS import/export, cue grid, style controls and final render. Coordinate mapper accounts for letterbox, rotation, pixel aspect ratio and DPI. All long operations are async/cancellable; render is blocked on unreviewed regions, invalid cues or missing runtime.

Compiler always places old-subtitle removal before new ASS burn-in, escapes Windows paths through a dedicated filter-path escaper, and reuses the M2 safe temp/finalize executor.

- [ ] **Step 4: 运行断网真实字幕验收**

With network disabled, generate a high-contrast Chinese subtitle fixture, verify OCR finds the expected lower band, run blur/delogo/crop outputs, import and burn SRT/ASS, run the licensed ASR fixture, replace old subtitles then burn new ones, and cancel each runtime once to assert no orphan process. Run all tests tagged `SubtitleLab`.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Application/Subtitles src/JingXu.Workbench.Infrastructure/Rendering src/JingXu.Workbench/Features/Subtitles tests/JingXu.Workbench.Application.Tests/Subtitles tests/JingXu.Workbench.Presentation.Tests/Subtitles tests/JingXu.Workbench.Infrastructure.Tests/Rendering tests/JingXu.Workbench.IntegrationTests/Subtitles
git diff --cached --check
git commit -m "feat: complete offline subtitle laboratory"
```

### Task 19: 设置、运行时清单和首次运行诊断

**Files:**
- Create: `src/JingXu.Workbench.Infrastructure/Runtime/RuntimeManifest.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Runtime/RuntimeManifestValidator.cs`
- Create: `src/JingXu.Workbench/Features/Settings/SettingsViewModel.cs`
- Create: `src/JingXu.Workbench/Features/Settings/SettingsView.xaml`
- Create: `src/JingXu.Workbench/Bootstrap/SelfTestRunner.cs`
- Create: `build/runtime-manifest.json`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Runtime/RuntimeManifestValidatorTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Settings/SettingsViewModelTests.cs`

- [ ] **Step 1: 写清单完整性和设置诊断失败测试**

```csharp
[Fact]
public void Every_required_runtime_has_version_hash_source_and_license()
{
    var manifest = RuntimeManifest.Load(Fixtures.Read("runtime-manifest.json"));
    var issues = RuntimeManifestValidator.Validate(manifest);
    Assert.Empty(issues);
    Assert.Contains(manifest.Components, x => x.Kind == RuntimeKind.Ffmpeg);
    Assert.Contains(manifest.Components, x => x.Kind == RuntimeKind.WhisperModel);
}

[Fact]
public async Task Runtime_check_reports_actionable_chinese_status()
{
    var vm = SettingsViewModelFactory.WithMissing(RuntimeKind.Tesseract);
    await vm.RefreshRuntimeStatusCommand.ExecuteAsync(null);
    Assert.Contains("未找到 Tesseract", vm.RuntimeStatuses.Single(x => x.Kind == RuntimeKind.Tesseract).Message);
    Assert.False(string.IsNullOrWhiteSpace(vm.RuntimeStatuses.Single().SuggestedAction));
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter RuntimeManifestValidatorTests; dotnet test tests/JingXu.Workbench.Presentation.Tests --filter SettingsViewModelTests`

Expected: FAIL because manifest validation and settings ViewModel are missing.

- [ ] **Step 3: 实现可审计运行时状态和用户覆盖路径**

Manifest components are FFmpeg, FFprobe, whisper.cpp, multilingual base model, Tesseract, `chi_sim`, `eng`, Chinese UI font and monospace font. Each entry requires immutable version, relative destination, SHA-256, official/source URL, license identifier and source-code URL when applicable. Settings permits only absolute existing executable/model paths, checks version/help contracts without network, stores paths in user settings and displays bundled → user → PATH resolution source.

First launch does not block the UI; it asynchronously checks runtimes and keeps unrelated modules usable. Enqueue preflight blocks only features whose concrete runtime is unavailable. `SelfTestRunner` handles `--self-test`, validates application/runtime/model layout without opening the main window, prints a machine-readable JSON result and returns nonzero on any missing required component.

- [ ] **Step 4: 覆盖哈希错误、版本不兼容和离线状态**

Test missing fields, bad SHA-256, relative override, directory instead of executable, incompatible whisper flags, FFmpeg missing required `subtitles/delogo/overlay` filters, no network access and user path fallback.

- [ ] **Step 5: Commit**

```powershell
git add src/JingXu.Workbench.Infrastructure/Runtime src/JingXu.Workbench/Features/Settings src/JingXu.Workbench/Bootstrap/SelfTestRunner.cs build/runtime-manifest.json tests/JingXu.Workbench.Infrastructure.Tests/Runtime tests/JingXu.Workbench.Presentation.Tests/Settings
git diff --cached --check
git commit -m "feat: diagnose local media runtimes"
```

### Task 20: 第三方运行时 staging、许可和用户文档

**Files:**
- Create: `scripts/Resolve-Runtimes.ps1`
- Create: `runtime/README.md`
- Create: `README.md`
- Create: `THIRD_PARTY_NOTICES.md`
- Create: `docs/architecture.md`
- Create: `docs/development.md`
- Create: `docs/testing.md`
- Create: `docs/release.md`
- Create: `docs/runtime-licensing.md`
- Test: `tests/JingXu.Workbench.IntegrationTests/Packaging/RuntimePackageTests.cs`

- [ ] **Step 1: 写发布运行时失败测试**

```csharp
[Fact]
public void Staged_runtime_contains_every_manifest_file_with_matching_hash()
{
    var manifest = RuntimeManifest.Load(BuildPaths.RuntimeManifest);
    var result = RuntimePackageVerifier.Verify(BuildPaths.StagedRuntime, manifest);
    Assert.True(result.IsSuccess, string.Join(Environment.NewLine, result.Issues));
}

[Fact]
public void Notices_cover_every_component_and_source_offer()
{
    var result = NoticeVerifier.Verify(BuildPaths.RuntimeManifest, "THIRD_PARTY_NOTICES.md");
    Assert.Empty(result.MissingComponents);
    Assert.Empty(result.MissingSourceLinks);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.IntegrationTests --filter RuntimePackageTests`

Expected: FAIL because no staged runtime/notices exist.

- [ ] **Step 3: 实现固定哈希 staging 和完整文档**

`Resolve-Runtimes.ps1` accepts an explicit cache directory, validates each manifest SHA-256, and copies only validated files to `artifacts/staging/runtime`; it never downloads a mutable `latest` asset during release. A separate documented acquisition mode may download exact official release URLs into the cache, then prints hashes for review before manifest update.

README covers quick start, import, random/custom `264513`, three overlays, subtitle workflows, output quality, offline guarantee, runtime settings and SmartScreen. Licensing docs record FFmpeg build config/source, GPL/LGPL decision, whisper/Tesseract/model/font licenses and codec patent warning. No legal statement claims blanket commercial safety.

- [ ] **Step 4: 运行文档链接、清单和隐私扫描**

Test all local Markdown links, exact artifact names, presence of offline/privacy statements, runtime notices and absence of API-key/cloud instructions. Use `Select-String` with the repository's prohibited-placeholder token list against `README.md`, `docs`, `THIRD_PARTY_NOTICES.md` and `runtime`, and expect no matches.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Resolve-Runtimes.ps1 runtime README.md THIRD_PARTY_NOTICES.md docs build/runtime-manifest.json tests/JingXu.Workbench.IntegrationTests/Packaging
git diff --cached --check
git commit -m "docs: stage and document offline runtimes"
```

### Task 21: 自包含便携版和 WiX 安装程序

**Files:**
- Create: `scripts/Build-Portable.ps1`
- Create: `scripts/Build-Installer.ps1`
- Create: `build/Installer/Package.wxs`
- Create: `build/Installer/Product.wxs`
- Create: `build/Installer/JingXu.Workbench.Msi.wixproj`
- Create: `build/Installer/License.rtf`
- Test: `tests/JingXu.Workbench.IntegrationTests/Packaging/PortableArtifactTests.cs`
- Test: `tests/JingXu.Workbench.IntegrationTests/Packaging/WixSourceTests.cs`

- [ ] **Step 1: 写产物结构和安装范围失败测试**

```csharp
[Fact]
public void Portable_artifact_is_self_contained_and_has_required_runtime_layout()
{
    var result = PortableArtifactVerifier.Verify(BuildPaths.PortableDirectory);
    Assert.True(result.HasExecutable("JingXu.Workbench.exe"));
    Assert.True(result.HasRuntime("ffmpeg/ffmpeg.exe"));
    Assert.True(result.HasRuntime("whisper/models/ggml-base.bin"));
    Assert.Empty(result.DebugAndTestAssemblies);
}

[Fact]
public void Installer_never_manages_user_project_or_output_directories()
{
    var wix = File.ReadAllText("build/Installer/Product.wxs");
    Assert.DoesNotContain("分镜输出", wix);
    Assert.DoesNotContain("DocumentsFolder", wix);
    Assert.Contains("MajorUpgrade", wix);
}
```

- [ ] **Step 2: 运行并确认 RED**

Run: `dotnet test tests/JingXu.Workbench.IntegrationTests --filter "PortableArtifactTests|WixSourceTests"`

Expected: FAIL because release artifacts and WiX sources do not exist.

- [ ] **Step 3: 实现可重复发布脚本和固定 WiX 标识**

`Build-Portable.ps1` runs:

```powershell
dotnet publish src/JingXu.Workbench/JingXu.Workbench.csproj -c Release -r win-x64 --self-contained true -p:PublishTrimmed=false -p:PublishSingleFile=false -p:DebugType=None -p:DebugSymbols=false -o artifacts/publish/win-x64
```

Then stage validated runtimes/fonts/notices, exclude PDB/test/cache/user data, normalize timestamps for the archive, create `artifacts/release/JingXu-Workbench-Portable-win-x64.zip` and emit SHA-256.

WiX uses stable UpgradeCode/Product identity, x64 install scope, MajorUpgrade, Start menu entry, optional desktop shortcut and ARP metadata; it manages only the application directory. Build `炳恒快速混剪-win-x64.msi` as the only installer. Without a certificate it remains unsigned and documentation explicitly warns about SmartScreen.

- [ ] **Step 4: 验证安装、升级和卸载边界**

In a disposable Windows test directory/VM, silently install, launch with `--self-test`, upgrade over the prior version, assert one installed product, create a user project/output, uninstall, and assert program files are removed while user files remain. If VM automation is unavailable, keep the automated WiX source/artifact tests mandatory and record manual install/uninstall evidence before release.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Build-Portable.ps1 scripts/Build-Installer.ps1 build/Installer tests/JingXu.Workbench.IntegrationTests/Packaging
git diff --cached --check
git commit -m "build: package portable app and Windows installer"
```

### Task 22: 最终需求验收、视觉检查和发布校验

**Files:**
- Create: `scripts/Verify-Release.ps1`
- Create: `docs/acceptance-report.md`
- Modify: `README.md`

- [ ] **Step 1: 写发布校验脚本的失败条件**

`Verify-Release.ps1` must return nonzero for any build warning, failed/skipped required integration test, dirty staged artifact, missing runtime hash, missing notice, missing portable/MSI artifact, wrong filename, orphan process, zero-byte media, duration/order/overlay/subtitle acceptance failure or unresolved placeholder scan.

- [ ] **Step 2: 运行完整新鲜验证**

Run:

```powershell
dotnet restore JingXu.Workbench.sln --locked-mode
dotnet build JingXu.Workbench.sln -c Release --no-restore
dotnet test JingXu.Workbench.sln -c Release --no-build --logger "trx;LogFileName=release.trx"
dotnet test tests/JingXu.Workbench.IntegrationTests -c Release --no-build --filter Category=LongRunning
dotnet format JingXu.Workbench.sln --verify-no-changes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Portable.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Installer.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Verify-Release.ps1
```

Expected: every command exits 0; no warnings; no required test is skipped.

- [ ] **Step 3: 进行真实 UI 和核心流程检查**

Launch the built executable, inspect at 1920×1080 and 1600×900 with 100%/125%/150% scaling, and record screenshots for the workbench, three overlay dialogs, subtitle lab and queue. Complete import → `264513` preview → enqueue → render → open output; complete random batch; cancel/retry; run manual and automatic subtitle workflows. Verify professional warm-gray/ink-green appearance, no clipped controls, no raw stack traces, no purple gradient/AI decoration and no empty control.

- [ ] **Step 4: 写逐条验收报告**

`docs/acceptance-report.md` maps every section 5–14 of the design spec to exact automated test names, manual evidence and artifact path. Any unmet item remains an explicit failed acceptance row; do not describe the project as complete until every required row passes.

- [ ] **Step 5: 最终提交**

```powershell
git add scripts/Verify-Release.ps1 docs/acceptance-report.md README.md
git diff --cached --check
git commit -m "test: verify release acceptance"
git status --short --branch
```

Expected: working tree clean except ignored `artifacts/`; release directory contains:

```text
artifacts/release/炳恒快速混剪-Portable-win-x64.zip
artifacts/release/炳恒快速混剪-win-x64.msi
artifacts/release/SHA256SUMS.txt
```

## 规格覆盖矩阵

| 规格范围 | 实施任务 |
|---|---|
| 文件名序号、随机拼接、自定义序号拼接和 `264513` | 2、3、13、14 |
| 完整时长、转场实际时长 | 3、9、14 |
| 画幅、输出质量、硬件/软件回退 | 9、12、14、19 |
| 差异化、滤镜、贴纸、BGM、模板 | 11、13、14 |
| 三类蒙版、多层、随机库、循环到结尾 | 10、13、14 |
| 多任务、并发、失败隔离、恢复 | 4、5、7、12、13 |
| 自动目录、自定义目录、封面 | 12、13、14 |
| 手动/自动去字幕 | 15、16、18 |
| 本地 Whisper 换字幕、SRT/ASS | 15、17、18 |
| 专业 WPF UI、DPI、键盘 | 8、13、18、22 |
| 离线、许可、便携包、安装器 | 19、20、21、22 |

## 计划自审门禁

执行前逐项确认：

1. 所有生产行为都有先失败的测试步骤；仅 SDK/解决方案脚手架属于配置建立。
2. Domain 不引用 WPF、文件系统或进程；外部运行时都复用单一进程执行边界。
3. 规格每项都映射到至少一个单元/集成任务和最终验收行。
4. 没有空按钮、假数据、占位标记或省略具体实现内容的步骤。
5. 所有命令、文件路径、类型名、状态名在前后任务一致。
6. 发布前必须重新运行全套命令，不使用代理报告或旧日志替代新鲜证据。
