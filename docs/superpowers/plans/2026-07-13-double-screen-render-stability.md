# Double Screen and Render Stability Implementation Plan

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（`src/JingXu.Workbench.Py`），文中 `.cs`/`.xaml` 路径仅作历史记录。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a start-indexed top/bottom duplicate-screen effect and resolve the screenshot's render failure/slow-render causes without changing the current UI style.

**Architecture:** Store double-screen settings as a typed immutable rendering plan on `RenderRequest`. Compile it per final-sequence clip before concat so only clips at or after the selected one receive `split`, half-height scale/crop, and `vstack`; keep the existing XAML control style. Stabilize the software filter graph by removing automatic hardware decode, leave denoise available but off by default, and surface the meaningful FFmpeg error line.

**Tech Stack:** .NET 8, C# records, WPF/CommunityToolkit.Mvvm, FFmpeg filter graphs, xUnit.

---

### Task 1: Typed double-screen render snapshot

**Files:**
- Create: `src/JingXu.Workbench.Domain/Effects/DoubleScreenEffectPlan.cs`
- Modify: `src/JingXu.Workbench.Domain/Rendering/RenderRequest.cs`
- Test: `tests/JingXu.Workbench.Domain.Tests/Effects/DoubleScreenEffectPlanTests.cs`

- [ ] **Step 1: Write the failing validation test**

```csharp
[Theory]
[InlineData(0)]
[InlineData(-1)]
public void Start_clip_index_must_be_one_based(int value)
{
    var result = DoubleScreenEffectPlan.Create(value);
    Assert.False(result.IsSuccess);
}
```

- [ ] **Step 2: Run the test and verify RED**

Run: `dotnet test tests/JingXu.Workbench.Domain.Tests/JingXu.Workbench.Domain.Tests.csproj -c Release --filter DoubleScreenEffectPlanTests`

Expected: FAIL because `DoubleScreenEffectPlan` does not exist.

- [ ] **Step 3: Implement the typed plan and request snapshot**

```csharp
public sealed record DoubleScreenEffectPlan(int StartClipIndex)
{
    public static Result<DoubleScreenEffectPlan> Create(int startClipIndex) =>
        startClipIndex < 1
            ? Result<DoubleScreenEffectPlan>.Failure("双屏起始视频必须从 1 开始。")
            : Result<DoubleScreenEffectPlan>.Success(new(startClipIndex));

    public bool AppliesTo(int zeroBasedClipIndex) => zeroBasedClipIndex + 1 >= StartClipIndex;
}
```

Add `DoubleScreenEffectPlan? DoubleScreen = null` to `RenderRequest` and include it in `HasRenderableEffects`.

- [ ] **Step 4: Run the domain test and verify GREEN**

Run: `dotnet test tests/JingXu.Workbench.Domain.Tests/JingXu.Workbench.Domain.Tests.csproj -c Release --filter DoubleScreenEffectPlanTests`

Expected: PASS.

### Task 2: Compile double-screen only from the selected clip

**Files:**
- Modify: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegCommandCompiler.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/FfmpegCommandCompilerTests.cs`

- [ ] **Step 1: Write failing compiler tests**

```csharp
[Fact]
public void Double_screen_applies_from_selected_final_sequence_clip()
{
    var request = CompilerTestPlans.WithDoubleScreen(startClipIndex: 2);
    var result = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", request, @"C:\out\temp.mp4");
    var args = result.Command.Arguments.ToList();
    var filter = args[args.IndexOf("-filter_complex") + 1];

    Assert.DoesNotContain("[v0fit]split=2", filter, StringComparison.Ordinal);
    Assert.Contains("[v1fit]split=2", filter, StringComparison.Ordinal);
    Assert.Contains("vstack=inputs=2", filter, StringComparison.Ordinal);
}
```

- [ ] **Step 2: Run the test and verify RED**

Run: `dotnet test tests/JingXu.Workbench.Infrastructure.Tests/JingXu.Workbench.Infrastructure.Tests.csproj -c Release --filter Double_screen`

Expected: FAIL because no double-screen graph is emitted.

- [ ] **Step 3: Add the per-clip graph**

For applicable clips, append a graph equivalent to:

```text
[vNfit]split=2[vNtop_src][vNbottom_src];
[vNtop_src]scale=W:H/2:force_original_aspect_ratio=increase,crop=W:H/2[vNtop];
[vNbottom_src]scale=W:H/2:force_original_aspect_ratio=increase,crop=W:H/2[vNbottom];
[vNtop][vNbottom]vstack=inputs=2[vN]
```

Feed `[vN]` into the existing concat input; retain the original label for unaffected clips.

- [ ] **Step 4: Run infrastructure compiler tests and verify GREEN**

Run: `dotnet test tests/JingXu.Workbench.Infrastructure.Tests/JingXu.Workbench.Infrastructure.Tests.csproj -c Release --filter FfmpegCommandCompilerTests`

Expected: PASS.

### Task 3: Capture settings from the unchanged composition UI style

**Files:**
- Modify: `src/JingXu.Workbench.Application/Rendering/RenderRequestFactory.cs`
- Modify: `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs`
- Modify: `src/JingXu.Workbench/Features/Composition/CompositionView.xaml`
- Test: `tests/JingXu.Workbench.Application.Tests/Rendering/RenderRequestFactoryTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTests.cs`

- [ ] **Step 1: Write failing snapshot tests**

```csharp
[Fact]
public async Task Enqueue_with_double_screen_captures_start_clip()
{
    var vm = CompositionViewModelTestFactory.CreateWithRecordingQueue();
    await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
    vm.EnableDoubleScreen = true;
    vm.DoubleScreenStartClipIndex = 3;
    await vm.EnqueueCommand.ExecuteAsync(null);
    Assert.Equal(3, vm.RecordedRequest.DoubleScreen!.StartClipIndex);
}
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `dotnet test tests/JingXu.Workbench.Presentation.Tests/JingXu.Workbench.Presentation.Tests.csproj -c Release --filter Double_screen`

Expected: FAIL because the bindings do not exist.

- [ ] **Step 3: Implement ViewModel and factory plumbing**

Add `EnableDoubleScreen`, `DoubleScreenStartClipIndex`, and one-based available clip choices derived from the active output plan. Pass `DoubleScreenEffectPlan` through `RenderRequestFactory.CreateForPlans` so every queued request owns an immutable snapshot.

- [ ] **Step 4: Add controls without changing style**

Use the same existing effect-row `CheckBox` style for “双屏”, followed by the existing compact label/ComboBox style for “从第 N 个视频开始（至结尾）”. Do not change surrounding margins, colors, typography, or layout containers.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `dotnet test tests/JingXu.Workbench.Presentation.Tests/JingXu.Workbench.Presentation.Tests.csproj -c Release --filter Double_screen`

Expected: PASS.

### Task 4: Resolve render failure, slow default, and unhelpful error text

**Files:**
- Modify: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegCommandCompiler.cs`
- Modify: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegRenderExecutor.cs`
- Modify: `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/FfmpegCommandCompilerTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/FfmpegRenderExecutorTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTests.cs`

- [ ] **Step 1: Write failing regression tests**

```csharp
[Fact]
public void Software_filter_transcode_does_not_force_hardware_decode()
{
    var result = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", CompilerTestPlans.TranscodeTwoClip(), @"C:\out\temp.mp4");
    Assert.DoesNotContain("-hwaccel", result.Command.Arguments);
}
```

Also assert a new ViewModel starts with `VariationEnableDenoise == false` and stderr summarization prefers the last line containing an actual FFmpeg error over generic trailer text.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `dotnet test tests/JingXu.Workbench.Infrastructure.Tests/JingXu.Workbench.Infrastructure.Tests.csproj -c Release --filter "Hardware|Error_summary"`

Expected: FAIL against the current behavior.

- [ ] **Step 3: Implement the minimal stability fixes**

Remove `-hwaccel auto` from the software `filter_complex` path, set the default denoise selection to false without removing the existing switch, and summarize stderr by scanning backward while skipping generic trailer lines such as `Conversion failed!`.

- [ ] **Step 4: Run regression tests and verify GREEN**

Run the focused infrastructure and presentation test filters.

Expected: PASS.

### Task 5: Verify and publish

**Files:**
- Output: `dist/**`

- [ ] **Step 1: Run relevant project tests**

Run Domain, Application, Infrastructure, and focused Presentation tests in Release mode.

Expected: all new and relevant tests pass; any unrelated pre-existing environment-path failures are reported separately.

- [ ] **Step 2: Build Release**

Run: `dotnet build JingXu.Workbench.sln -c Release --no-restore`

Expected: 0 compilation errors.

- [ ] **Step 3: Publish self-contained Windows build**

Run: `dotnet publish src/JingXu.Workbench/JingXu.Workbench.csproj -c Release -r win-x64 --self-contained true -p:PublishTrimmed=false -p:PublishSingleFile=false -p:DebugType=None -p:DebugSymbols=false -o dist`

Expected: publish succeeds and updates `dist`.

- [ ] **Step 4: Execute packaged self-test**

Run: `dist/JingXu.Workbench.exe --self-test`

Expected: exit code 0.

Implementation will be performed inline in the current task. Git commit steps are intentionally omitted because the user requested a local build, not repository history changes.
