# CPU / GPU Render Selection Implementation Plan

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（`src/JingXu.Workbench.Py`），文中 `.cs`/`.xaml` 路径仅作历史记录。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-render automatic, CPU, and GPU H.264 processing selection with NVENC/QSV/AMF detection, safe CPU fallback, and visible queue notices.

**Architecture:** Store the user's processor policy on the immutable `RenderRequest`. Keep FFmpeg filter processing on software frames, select only the final H.264 encoder through a cached runtime probe, and retry once with `libx264` only for recognized hardware-encoder failures. Centralize vendor-specific FFmpeg arguments in one compiler helper and propagate successful selection/fallback information through the execution result into the queue.

**Tech Stack:** .NET 10, C#, WPF, CommunityToolkit.Mvvm, FFmpeg, xUnit

---

## File Structure

- Create `src/JingXu.Workbench.Domain/Rendering/VideoProcessingMode.cs`: user-facing processor policy.
- Modify `src/JingXu.Workbench.Domain/Rendering/RenderProfile.cs`: remove the dormant hardware preference flag.
- Modify `src/JingXu.Workbench.Domain/Rendering/RenderRequest.cs`: persist processor policy in each queued request.
- Modify `src/JingXu.Workbench.Application/Rendering/RenderRequestFactory.cs`: copy processor policy to every batch request.
- Modify `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs`: expose selection, snapshot it at enqueue, and describe it.
- Modify `src/JingXu.Workbench/Features/Composition/CompositionView.xaml`: render the three processor buttons.
- Create `src/JingXu.Workbench.Infrastructure/Rendering/VideoEncoderSelection.cs`: encoder identities, selection result, selector interface, and CPU constant.
- Create `src/JingXu.Workbench.Infrastructure/Rendering/HardwareVideoEncoderSelector.cs`: probe/cache NVENC, QSV, and AMF availability.
- Create `src/JingXu.Workbench.Infrastructure/Rendering/VideoEncoderArguments.cs`: centralized quality-to-encoder argument mapping.
- Modify `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegCommandCompiler.cs`: accept an explicit encoder and append its arguments.
- Modify `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegRenderExecutor.cs`: select encoder, execute, recognize hardware failures, retry CPU once, and write structured logs.
- Modify `src/JingXu.Workbench.Infrastructure/Bootstrap/RenderInfrastructure.cs`: wire the production selector.
- Modify `src/JingXu.Workbench.Application/Abstractions/IRenderExecutor.cs`: add an optional successful execution notice.
- Modify `src/JingXu.Workbench.Domain/Rendering/RenderJob.cs`: persist a non-error notice.
- Modify `src/JingXu.Workbench.Application/Rendering/RenderCoordinator.cs`: copy the executor notice into the completed job.
- Modify `src/JingXu.Workbench/Features/Queue/RenderJobRowViewModel.cs`: display processor/fallback notices.
- Test the above in the existing domain, application, infrastructure, presentation, and integration test projects.

### Task 1: Processor Policy Snapshot and UI

**Files:**
- Create: `src/JingXu.Workbench.Domain/Rendering/VideoProcessingMode.cs`
- Modify: `src/JingXu.Workbench.Domain/Rendering/RenderProfile.cs`
- Modify: `src/JingXu.Workbench.Domain/Rendering/RenderRequest.cs`
- Modify: `src/JingXu.Workbench.Application/Rendering/RenderRequestFactory.cs`
- Modify: `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs`
- Modify: `src/JingXu.Workbench/Features/Composition/CompositionView.xaml`
- Test: `tests/JingXu.Workbench.Domain.Tests/Rendering/RenderProfileTests.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Rendering/RenderRequestFactoryTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewTests.cs`

- [ ] **Step 1: Write failing domain and request-factory tests**

Add tests that demand a default `Auto` policy and preservation through batch request creation:

```csharp
[Fact]
public void Render_request_defaults_to_auto_processing()
{
    var request = TestPlans.WithInput(@"C:\media\1.mp4");
    Assert.Equal(VideoProcessingMode.Auto, request.ProcessingMode);
}

[Fact]
public void Processing_mode_is_copied_to_every_batch_request()
{
    var requests = RenderRequestFactory.CreateForPlans(
        plans,
        outputDirectory,
        "成片",
        RenderProfile.Balanced,
        OutputAspect.InheritFirst,
        overlayLayersPerPlan: null,
        sharedOverlayLayers: [],
        processingMode: VideoProcessingMode.Gpu);

    Assert.All(requests, request => Assert.Equal(VideoProcessingMode.Gpu, request.ProcessingMode));
}
```

- [ ] **Step 2: Run the domain and application tests and verify RED**

Run:

```powershell
dotnet test .\tests\JingXu.Workbench.Domain.Tests\JingXu.Workbench.Domain.Tests.csproj --no-restore --filter "FullyQualifiedName~Render_request_defaults_to_auto_processing"
dotnet test .\tests\JingXu.Workbench.Application.Tests\JingXu.Workbench.Application.Tests.csproj --no-restore --filter "FullyQualifiedName~Processing_mode_is_copied"
```

Expected: compilation fails because `VideoProcessingMode` and `RenderRequest.ProcessingMode` do not exist.

- [ ] **Step 3: Add the processor policy and request snapshot**

Create:

```csharp
namespace JingXu.Workbench.Domain.Rendering;

public enum VideoProcessingMode
{
    Auto,
    Cpu,
    Gpu
}
```

Append to the `RenderRequest` primary constructor:

```csharp
VideoProcessingMode ProcessingMode = VideoProcessingMode.Auto
```

Add a final optional parameter to `RenderRequestFactory.CreateForPlans` and pass it into every `RenderRequest`:

```csharp
VideoProcessingMode processingMode = VideoProcessingMode.Auto
```

Remove `PreferHardwareEncoder` from `RenderProfile` and update its static instances to use only quality, CRF, audio bitrate, and x264 preset.

- [ ] **Step 4: Run the domain and application tests and verify GREEN**

Run the two commands from Step 2.

Expected: both targeted tests pass.

- [ ] **Step 5: Write failing presentation tests**

Add:

```csharp
[Theory]
[InlineData(VideoProcessingMode.Auto)]
[InlineData(VideoProcessingMode.Cpu)]
[InlineData(VideoProcessingMode.Gpu)]
public async Task Enqueue_snapshots_selected_processing_mode(VideoProcessingMode mode)
{
    var store = new InMemoryRenderQueueStore();
    var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, 1);
    var vm = CompositionViewModelTestFactory.Create(coordinator);
    await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
    vm.Mode = CompositionMode.CustomSequence;
    vm.SequenceExpression = "123456";
    vm.SelectedProcessingMode = mode;

    await vm.EnqueueCommand.ExecuteAsync(null);

    Assert.Equal(mode, Assert.Single(coordinator.Jobs).Request!.ProcessingMode);
}
```

Add a WPF tree test asserting three radio buttons with automation names `处理器自动`, `处理器CPU`, and `处理器GPU`, with Auto checked by default.

- [ ] **Step 6: Run the presentation tests and verify RED**

Run:

```powershell
dotnet test .\tests\JingXu.Workbench.Presentation.Tests\JingXu.Workbench.Presentation.Tests.csproj --no-restore --filter "FullyQualifiedName~Enqueue_snapshots_selected_processing_mode|FullyQualifiedName~Processor_selector"
```

Expected: compilation or assertion failure because the property and controls do not exist.

- [ ] **Step 7: Implement the view-model and XAML controls**

Add to `CompositionViewModel`:

```csharp
[ObservableProperty]
[NotifyPropertyChangedFor(nameof(QualityHint))]
private VideoProcessingMode _selectedProcessingMode = VideoProcessingMode.Auto;
```

Pass `SelectedProcessingMode` to `RenderRequestFactory.CreateForPlans`, and add the selection to enqueue hints:

```csharp
hints.Add(SelectedProcessingMode switch
{
    VideoProcessingMode.Auto => "处理器：自动",
    VideoProcessingMode.Cpu => "处理器：CPU",
    VideoProcessingMode.Gpu => "处理器：GPU",
    _ => "处理器：自动"
});
```

Add a segmented processor selector directly below output quality:

```xml
<TextBlock Text="处理器" Style="{DynamicResource Text.SectionHeader}" Margin="0,14,0,8" />
<Border Style="{DynamicResource Segmented.Container}" HorizontalAlignment="Left">
    <WrapPanel>
        <RadioButton Style="{DynamicResource Segmented.Item}"
                     GroupName="processingMode"
                     Content="自动（推荐）"
                     IsChecked="{Binding SelectedProcessingMode, Converter={StaticResource EnumToBool}, ConverterParameter=Auto}"
                     AutomationProperties.Name="处理器自动" />
        <RadioButton Style="{DynamicResource Segmented.Item}"
                     GroupName="processingMode"
                     Content="CPU（兼容稳定）"
                     IsChecked="{Binding SelectedProcessingMode, Converter={StaticResource EnumToBool}, ConverterParameter=Cpu}"
                     AutomationProperties.Name="处理器CPU" />
        <RadioButton Style="{DynamicResource Segmented.Item}"
                     GroupName="processingMode"
                     Content="GPU（硬件加速）"
                     IsChecked="{Binding SelectedProcessingMode, Converter={StaticResource EnumToBool}, ConverterParameter=Gpu}"
                     AutomationProperties.Name="处理器GPU" />
    </WrapPanel>
</Border>
```

Extend `RefreshQualityHint` with: `GPU 只加速最终编码；蒙版、羽化和贴纸仍由 CPU 计算。`

- [ ] **Step 8: Run presentation tests and verify GREEN**

Run the command from Step 6.

Expected: all targeted tests pass.

### Task 2: Explicit Encoder Arguments

**Files:**
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/VideoEncoderSelection.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/VideoEncoderArguments.cs`
- Modify: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegCommandCompiler.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/FfmpegCommandCompilerTests.cs`

- [ ] **Step 1: Write failing compiler tests for four encoders**

Add a theory:

```csharp
[Theory]
[InlineData(VideoEncoderKind.Libx264, "libx264", "-crf", "22")]
[InlineData(VideoEncoderKind.H264Nvenc, "h264_nvenc", "-cq", "22")]
[InlineData(VideoEncoderKind.H264Qsv, "h264_qsv", "-global_quality", "22")]
[InlineData(VideoEncoderKind.H264Amf, "h264_amf", "-qp_i", "22")]
public void Balanced_profile_compiles_selected_encoder(
    VideoEncoderKind encoder,
    string codec,
    string qualitySwitch,
    string qualityValue)
{
    var result = FfmpegCommandCompiler.Compile(
        @"C:\ffmpeg.exe",
        CompilerTestPlans.TranscodeTwoClip(),
        @"C:\out\temp.mp4",
        encoder);

    AssertArgumentPair(result.Command.Arguments, "-c:v", codec);
    AssertArgumentPair(result.Command.Arguments, qualitySwitch, qualityValue);
    Assert.DoesNotContain("-hwaccel", result.Command.Arguments);
}
```

Add separate assertions for NVENC preset `p5`, QSV preset `medium`, and AMF quality `balanced`.

- [ ] **Step 2: Run the compiler tests and verify RED**

Run:

```powershell
dotnet test .\tests\JingXu.Workbench.Infrastructure.Tests\JingXu.Workbench.Infrastructure.Tests.csproj --no-restore --filter "FullyQualifiedName~Balanced_profile_compiles_selected_encoder"
```

Expected: compilation fails because `VideoEncoderKind` and the compiler overload do not exist.

- [ ] **Step 3: Implement centralized encoder argument mapping**

Create:

```csharp
public enum VideoEncoderKind
{
    Libx264,
    H264Nvenc,
    H264Qsv,
    H264Amf
}

public sealed record VideoEncoderSelection(
    VideoEncoderKind Kind,
    string DisplayName,
    string? Notice = null,
    bool IsFallback = false)
{
    public static VideoEncoderSelection Cpu(string? notice = null, bool isFallback = false) =>
        new(VideoEncoderKind.Libx264, "CPU（libx264）", notice, isFallback);
}
```

Create a helper with:

```csharp
public static IReadOnlyList<string> Build(VideoEncoderKind encoder, RenderProfile profile)
```

Return:

```csharp
VideoEncoderKind.Libx264 =>
[
    "-c:v", "libx264",
    "-preset", profile.EncodePreset,
    "-threads", "0",
    "-crf", quality.ToString(CultureInfo.InvariantCulture)
],
VideoEncoderKind.H264Nvenc =>
[
    "-c:v", "h264_nvenc",
    "-preset", NvencPreset(profile.Quality),
    "-tune", "hq",
    "-rc", "vbr",
    "-b:v", "0",
    "-cq", qualityText
],
VideoEncoderKind.H264Qsv =>
[
    "-c:v", "h264_qsv",
    "-preset", QsvPreset(profile.Quality),
    "-global_quality", qualityText
],
VideoEncoderKind.H264Amf =>
[
    "-c:v", "h264_amf",
    "-quality", AmfQuality(profile.Quality),
    "-rc", "cqp",
    "-qp_i", qualityText,
    "-qp_p", qualityText,
    "-qp_b", qualityText
]
```

Keep `-pix_fmt yuv420p` and audio arguments in the existing compiler.

- [ ] **Step 4: Modify the compiler to accept the selected encoder**

Use:

```csharp
public static FfmpegCompileResult Compile(
    string ffmpegExecutable,
    RenderRequest request,
    string tempOutputPath,
    VideoEncoderKind encoder = VideoEncoderKind.Libx264)
```

Replace the hard-coded CPU block with:

```csharp
arguments.AddRange(VideoEncoderArguments.Build(encoder, profile));
```

- [ ] **Step 5: Run compiler tests and verify GREEN**

Run the command from Step 2.

Expected: all four rows pass and none contains `-hwaccel`.

### Task 3: Cached Hardware Encoder Probe

**Files:**
- Modify: `src/JingXu.Workbench.Infrastructure/Rendering/VideoEncoderSelection.cs`
- Create: `src/JingXu.Workbench.Infrastructure/Rendering/HardwareVideoEncoderSelector.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/HardwareVideoEncoderSelectorTests.cs`

- [ ] **Step 1: Write failing priority, fallback, and cache tests**

Define a recording fake `IExternalProcessRunner` that returns exit codes by codec name. Add:

```csharp
[Fact]
public async Task Auto_prefers_nvenc_then_qsv_then_amf()
{
    var runner = new ProbeRunner(new()
    {
        ["h264_nvenc"] = 0,
        ["h264_qsv"] = 0,
        ["h264_amf"] = 0
    });
    var selector = new HardwareVideoEncoderSelector(runner);

    var result = await selector.SelectAsync(
        @"C:\ffmpeg.exe",
        VideoProcessingMode.Auto,
        default);

    Assert.Equal(VideoEncoderKind.H264Nvenc, result.Kind);
}

[Fact]
public async Task Gpu_without_available_encoder_returns_cpu_fallback_notice()
{
    var selector = new HardwareVideoEncoderSelector(ProbeRunner.AllFailing());
    var result = await selector.SelectAsync(
        @"C:\ffmpeg.exe",
        VideoProcessingMode.Gpu,
        default);

    Assert.Equal(VideoEncoderKind.Libx264, result.Kind);
    Assert.True(result.IsFallback);
    Assert.Contains("已改用 CPU", result.Notice);
}

[Fact]
public async Task Probe_results_are_cached_by_normalized_ffmpeg_path()
{
    var runner = ProbeRunner.OnlyQsv();
    var selector = new HardwareVideoEncoderSelector(runner);

    await selector.SelectAsync(@"C:\tools\ffmpeg.exe", VideoProcessingMode.Auto, default);
    await selector.SelectAsync(@"c:\tools\FFMPEG.exe", VideoProcessingMode.Gpu, default);

    Assert.Equal(2, runner.TotalCalls); // NVENC fail + QSV success, once only
}
```

- [ ] **Step 2: Run selector tests and verify RED**

Run:

```powershell
dotnet test .\tests\JingXu.Workbench.Infrastructure.Tests\JingXu.Workbench.Infrastructure.Tests.csproj --no-restore --filter "FullyQualifiedName~HardwareVideoEncoderSelectorTests"
```

Expected: compilation fails because the selector does not exist.

- [ ] **Step 3: Define the selector interface**

Add:

```csharp
public interface IVideoEncoderSelector
{
    Task<VideoEncoderSelection> SelectAsync(
        string ffmpegExecutable,
        VideoProcessingMode mode,
        CancellationToken cancellationToken);
}
```

- [ ] **Step 4: Implement probe and per-path cache**

Use a `ConcurrentDictionary<string, Lazy<Task<IReadOnlyList<VideoEncoderKind>>>>` with `StringComparer.OrdinalIgnoreCase`.

Probe each codec sequentially using:

```csharp
ProcessRequest.Create(ffmpegExecutable,
[
    "-hide_banner",
    "-loglevel", "error",
    "-f", "lavfi",
    "-i", "color=c=black:s=64x64:d=0.1",
    "-frames:v", "1",
    "-an",
    "-c:v", codecName,
    "-f", "null",
    "-"
])
```

Wrap each call with a linked two-second timeout. Treat timeout and nonzero exit as unavailable, while propagating the caller's explicit cancellation.

Return CPU immediately for `VideoProcessingMode.Cpu`, without probing.

- [ ] **Step 5: Run selector tests and verify GREEN**

Run the command from Step 2.

Expected: priority, fallback, CPU no-probe, cancellation, and cache tests pass.

### Task 4: Executor Selection, One-Time CPU Fallback, and Structured Logs

**Files:**
- Modify: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegRenderExecutor.cs`
- Modify: `src/JingXu.Workbench.Infrastructure/Bootstrap/RenderInfrastructure.cs`
- Modify: `src/JingXu.Workbench.Application/Abstractions/IRenderExecutor.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/FfmpegRenderExecutorTests.cs`

- [ ] **Step 1: Write failing executor tests**

Add a fake selector and queued process results. Cover:

```csharp
[Fact]
public async Task Hardware_initialization_failure_retries_once_with_cpu()
{
    var selector = new FixedSelector(
        new VideoEncoderSelection(VideoEncoderKind.H264Qsv, "Intel GPU（QSV）"));
    var runner = new SequencedRunner(
        Failed("[h264_qsv] Error initializing an internal MFX session"),
        Succeeded());
    var executor = CreateExecutor(runner, selector);

    var result = await executor.ExecuteAsync(GpuJob(), null, default);

    Assert.True(result.IsSuccess);
    Assert.Equal(2, runner.Requests.Count);
    Assert.Contains("h264_qsv", runner.Requests[0].Arguments);
    Assert.Contains("libx264", runner.Requests[1].Arguments);
    Assert.Contains("已自动改用 CPU", result.Notice);
}

[Fact]
public async Task Filter_failure_does_not_retry_cpu()
{
    var runner = new SequencedRunner(Failed("Error reinitializing filters!"));
    var executor = CreateExecutor(runner, QsvSelector());

    var result = await executor.ExecuteAsync(GpuJob(), null, default);

    Assert.False(result.IsSuccess);
    Assert.Single(runner.Requests);
}

[Fact]
public async Task Cancellation_does_not_retry_cpu()
{
    var runner = new CancellingRunner();
    var executor = CreateExecutor(runner, QsvSelector());

    var result = await executor.ExecuteAsync(GpuJob(), null, new CancellationToken(true));

    Assert.True(result.IsCancelled);
    Assert.Single(runner.Requests);
}
```

- [ ] **Step 2: Run executor tests and verify RED**

Run:

```powershell
dotnet test .\tests\JingXu.Workbench.Infrastructure.Tests\JingXu.Workbench.Infrastructure.Tests.csproj --no-restore --filter "FullyQualifiedName~Hardware_initialization_failure|FullyQualifiedName~Filter_failure_does_not_retry|FullyQualifiedName~Cancellation_does_not_retry"
```

Expected: compilation fails because executor selection injection and `Notice` do not exist.

- [ ] **Step 3: Add successful execution notices**

Change:

```csharp
public sealed record RenderExecutionResult(
    bool IsSuccess,
    RenderFailure? FailureInfo,
    bool IsCancelled,
    string? Notice = null)
```

Use:

```csharp
public static RenderExecutionResult Success(string? notice = null) =>
    new(true, null, false, notice);
```

- [ ] **Step 4: Inject and use the encoder selector**

Add an `IVideoEncoderSelector` constructor dependency. Before compiling a transcode request:

```csharp
var selection = RenderDecision.For(request).CanStreamCopy
    ? VideoEncoderSelection.Cpu()
    : await _encoderSelector.SelectAsync(
        ffmpeg.Path,
        request.ProcessingMode,
        cancellationToken).ConfigureAwait(false);
```

Compile with `selection.Kind`.

- [ ] **Step 5: Extract a single process-attempt method**

Create a private method that materializes input aliases, writes auxiliary files, runs FFmpeg, captures progress, and returns `IProcessResult`. It must accept the chosen `VideoEncoderKind` and rewrite the filter script on retry.

Before CPU retry:

```csharp
if (File.Exists(tempOutputPath))
{
    File.Delete(tempOutputPath);
}
```

- [ ] **Step 6: Add strict hardware failure classification**

Add:

```csharp
internal static bool IsHardwareEncoderFailure(string stderr)
```

Match case-insensitively only messages containing the selected hardware family plus one of:

```text
no capable devices found
cannot load nvcuda
error initializing output stream
failed to initialise
failed to initialize
device setup failed
device lost
unsupported device
initializing an internal mfx session
failed to create mfx session
amf failed to initialise
encoder initialization failed
```

Do not match generic filter errors alone.

- [ ] **Step 7: Retry CPU once and write both attempts to the log**

Build log sections:

```text
=== 编码器选择 ===
Intel GPU（QSV）

=== GPU 尝试 ===
...

=== 自动回退 CPU ===
GPU 编码初始化失败，已改用 libx264。

=== CPU 尝试 ===
...
```

Return:

```csharp
RenderExecutionResult.Success("GPU 编码不可用，已自动改用 CPU 完成。")
```

when the CPU attempt succeeds.

- [ ] **Step 8: Wire production selector**

In `RenderInfrastructure.CreateFfmpegRenderExecutor`, construct one `ExternalProcessRunner`, pass it both to `HardwareVideoEncoderSelector` and the executor, and preserve all current resolver/probe dependencies.

- [ ] **Step 9: Run executor tests and verify GREEN**

Run the command from Step 2.

Expected: the hardware failure retries exactly once, ordinary filter failure does not retry, and cancellation does not retry.
This proves ordinary filter errors and user cancellation do not trigger CPU fallback.

### Task 5: Queue Notice Propagation

**Files:**
- Modify: `src/JingXu.Workbench.Domain/Rendering/RenderJob.cs`
- Modify: `src/JingXu.Workbench.Application/Rendering/RenderCoordinator.cs`
- Modify: `src/JingXu.Workbench/Features/Queue/RenderJobRowViewModel.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Rendering/RenderCoordinatorTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Queue/RenderQueueViewModelTests.cs`

- [ ] **Step 1: Write failing notice propagation tests**

Add an executor that returns `RenderExecutionResult.Success("使用 Intel GPU（QSV）完成。")`.

Assert:

```csharp
var completed = await WaitForStateAsync(coordinator, job.Id, JobState.Completed);
Assert.Equal("使用 Intel GPU（QSV）完成。", completed.Notice);
```

For the queue row:

```csharp
var completed = RenderJobs.Completed() with
{
    Notice = "GPU 编码不可用，已自动改用 CPU 完成。"
};
var row = new RenderJobRowViewModel(completed, "成片");
Assert.Equal(completed.Notice, row.ProgressText);
```

- [ ] **Step 2: Run application and presentation tests and verify RED**

Run:

```powershell
dotnet test .\tests\JingXu.Workbench.Application.Tests\JingXu.Workbench.Application.Tests.csproj --no-restore --filter "FullyQualifiedName~Successful_executor_notice"
dotnet test .\tests\JingXu.Workbench.Presentation.Tests\JingXu.Workbench.Presentation.Tests.csproj --no-restore --filter "FullyQualifiedName~Completed_job_displays_notice"
```

Expected: compilation fails because `RenderJob.Notice` does not exist.

- [ ] **Step 3: Add notice state and legal completion transition**

Add:

```csharp
public string? Notice { get; init; }
```

Change completion to:

```csharp
public RenderJob Complete(string? notice = null) =>
    State is JobState.Finalizing
        ? this with
        {
            State = JobState.Completed,
            CompletedAt = DateTimeOffset.UtcNow,
            Notice = notice
        }
        : throw new InvalidOperationException(...);
```

Clear stale notices in `Fail`, `Cancel`, and `Retry`.

- [ ] **Step 4: Propagate and display the notice**

In `RenderCoordinator`:

```csharp
await TransitionJobAsync(
    finalizing,
    current => current.Complete(result.Notice),
    CancellationToken.None);
```

In `RenderJobRowViewModel.ProgressText`, return `Notice` for completed jobs before the generic `已完成`.

- [ ] **Step 5: Run notice tests and verify GREEN**

Run the commands from Step 2.

Expected: both tests pass.

### Task 6: Real CPU/GPU Integration Validation

**Files:**
- Create: `tests/JingXu.Workbench.IntegrationTests/Media/HardwareEncoderRenderTests.cs`
- Modify: `tests/JingXu.Workbench.IntegrationTests/Media/MediaIntegrationHarness.cs`

- [ ] **Step 1: Write the CPU integration test**

Render a one-second generated clip with `ProcessingMode = Cpu`, then assert output exists, duration is valid, and the compile/run log contains `libx264`.

- [ ] **Step 2: Write the conditional GPU integration test**

Use `HardwareVideoEncoderSelector.SelectAsync` against the installed FFmpeg. If it returns CPU, call `Assert.Skip("本机没有可用硬件 H.264 编码器。")`. Otherwise render one second with the selected hardware encoder and assert output validation succeeds.

- [ ] **Step 3: Run integration tests**

Run:

```powershell
dotnet test .\tests\JingXu.Workbench.IntegrationTests\JingXu.Workbench.IntegrationTests.csproj --no-restore --filter "FullyQualifiedName~HardwareEncoderRenderTests"
```

Expected on the current Intel machine: CPU test passes and QSV GPU test passes. On machines without a usable GPU encoder: CPU passes and GPU test skips with the explicit reason.

### Task 7: Full Regression, Publish, and Direct `dist` Replacement

**Files:**
- Verify all modified source and test files.
- Replace: `dist/**`

- [ ] **Step 1: Run the full solution tests**

Run:

```powershell
dotnet test .\JingXu.Workbench.sln --no-restore --verbosity minimal
```

Expected: zero failed tests; environment-dependent tests may be explicitly skipped.

- [ ] **Step 2: Run formatting/diff validation**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 3: Build the portable release**

Run:

```powershell
.\scripts\Build-Portable.ps1 -AllowPlaceholderHash -BootstrapFromPath
```

Expected: exit code 0 and a complete `artifacts\staging\portable` directory.

- [ ] **Step 4: Verify destination and mirror directly into `dist`**

Resolve and verify that the destination equals:

```text
C:\Users\dengkaile\OneDrive\Desktop\project2026071001\dist
```

Then run `robocopy <portable> <dist> /MIR`, accepting exit codes below 8.

- [ ] **Step 5: Compare manifests and hashes**

Compare every relative file path and byte length between the staging portable directory and `dist`. Verify SHA-256 equality for:

```text
炳恒快速混剪.exe
炳恒快速混剪.dll
runtime\ffmpeg\ffmpeg.exe
runtime\ffmpeg\ffprobe.exe
```

- [ ] **Step 6: Run published smoke and encoder probes**

Run the published executable with `--import-smoke` against the supplied customer video and require exit code 0. Run the bundled FFmpeg 64×64 probe for QSV on the current machine and require exit code 0; report other unavailable vendors as normal.

- [ ] **Step 7: Report the direct executable path**

Return:

```text
C:\Users\dengkaile\OneDrive\Desktop\project2026071001\dist\炳恒快速混剪.exe
```

Include the full test pass count, GPU selected on the current machine, whether any CPU fallback occurred, and the `dist` manifest result.
