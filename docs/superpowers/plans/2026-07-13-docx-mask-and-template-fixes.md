# 文档截图问题修正 Implementation Plan

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（`src/JingXu.Workbench.Py`），文中 `.cs`/`.xaml` 路径仅作历史记录。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正文档截图中列出的序号/效果模板、差异化强度、蒙版库批量参数、真实预览、源裁切和羽化行为。

**Architecture:** 序号模板使用独立 JSON 文档，绝不与效果模板共用存储。蒙版可复用参数收敛为 `OverlayAppearance` 并持久化到素材库条目；任务层仍保存名称、时长、起始片段、层级和音频。源裁切与输出放置分别由 `SourceCrop` 与 `Bounds` 表达，预览请求携带完整层参数并复用生产滤镜编译器。

**Tech Stack:** .NET 10、WPF、CommunityToolkit.Mvvm、xUnit、FFmpeg、AtomicJsonStore。

---

### Task 1: 序号模板的独立持久化与效果模板生命周期

**Files:**

- Create: `src/JingXu.Workbench.Application/Projects/SequenceTemplateService.cs`
- Modify: `src/JingXu.Workbench.Application/Projects/TemplateService.cs`
- Modify: `src/JingXu.Workbench/Bootstrap/AppCompositionRoot.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Projects/SequenceTemplateServiceTests.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Projects/TemplateServiceTests.cs`

- [ ] **Step 1: Write failing tests** for sequence save/reload/rename/delete and for effect-template deletion removing its linked sticker while leaving sequence storage unchanged.

```csharp
var template = new SequenceTemplate(Guid.NewGuid(), "倒序", "6,5,4,3,2,1");
await service.UpsertAsync(template, path);
Assert.Equal("倒序", (await service.LoadAsync(path)).Templates.Single().DisplayName);
```

- [ ] **Step 2: Verify red.**

```powershell
dotnet test tests/JingXu.Workbench.Application.Tests/JingXu.Workbench.Application.Tests.csproj -c Release --no-restore --filter "FullyQualifiedName~SequenceTemplateServiceTests|FullyQualifiedName~TemplateServiceTests"
```

- [ ] **Step 3: Implement the minimal APIs.** Add `SequenceTemplate(Guid Id, string DisplayName, string Expression)`, `SequenceTemplateDocument`, and `SequenceTemplateService` with a separate default path `%LocalAppData%\JingXu\sequence-templates.json`. Upsert/delete do one load, one replacement, one atomic save. Add `TemplateService.RenameUserTemplateAsync` and `DeleteUserTemplateAsync`; protect `none` and `standard-variation`, preserve sticker IDs on rename, and remove the matching sticker entry on delete.

- [ ] **Step 4: Wire a dedicated `AtomicJsonStore<SequenceTemplateDocument>` and service in `AppCompositionRoot`; do not change `effect-templates.json`.**

- [ ] **Step 5: Verify green** by rerunning the filtered application tests.

### Task 2: 合成页模板操作与 1% 强度下限

**Files:**

- Create: `src/JingXu.Workbench/Features/Composition/CompositionViewModel.Templates.cs`
- Modify: `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs`
- Modify: `src/JingXu.Workbench/Features/Composition/CompositionView.xaml`
- Modify: `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTestFactory.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTests.cs`

- [ ] **Step 1: Write failing presentation tests** proving apply selects `CompositionMode.CustomSequence` and writes the expression, sequence rename/delete work, effect deletion leaves sequence storage unchanged, and assigning intensity 0 normalizes to 1.

- [ ] **Step 2: Verify red.**

```powershell
dotnet test tests/JingXu.Workbench.Presentation.Tests/JingXu.Workbench.Presentation.Tests.csproj -c Release --no-restore --filter "FullyQualifiedName~CompositionViewModelTests"
```

- [ ] **Step 3: Implement a partial VM and bindings.** Validate expressions with `FileSequenceParser`; apply sets `Mode = CompositionMode.CustomSequence` and `SequenceExpression = selected.Expression`. XAML gets separate named sequence-template selection/apply/save/rename/delete and effect rename/delete controls. The intensity slider becomes `Minimum="1"`, `TickFrequency="1"`, snap enabled; the VM clamps `[1, 200]`, while domain-level `ScaleIntensity(0)` remains a valid generic operation.

- [ ] **Step 4: Verify green** with the affected presentation class and WPF build.

### Task 3: 导出分辨率与帧率兼容选项

**Files:**

- Create: `src/JingXu.Workbench.Domain/Rendering/OutputVideoSettings.cs`
- Modify: `src/JingXu.Workbench.Domain/Rendering/RenderRequest.cs`
- Modify: `src/JingXu.Workbench.Domain/Rendering/RenderDecision.cs`
- Modify: `src/JingXu.Workbench.Domain/Rendering/TranscodeReason.cs`
- Modify: `src/JingXu.Workbench.Application/Rendering/RenderRequestFactory.cs`
- Modify: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegCommandCompiler.cs`
- Modify: `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs`
- Modify: `src/JingXu.Workbench/Features/Composition/CompositionView.xaml`
- Test: `tests/JingXu.Workbench.Domain.Tests/Rendering/OutputVideoSettingsTests.cs`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/FfmpegCommandCompilerTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTests.cs`

- [ ] **Step 1: Write failing tests** proving that the default settings preserve the original first-clip resolution and frame rate, that 1080P/720P use an even pixel size while retaining the selected canvas aspect, and that 30 fps/60 fps become explicit FFmpeg filters.

- [ ] **Step 2: Verify red.**

- [ ] **Step 3: Add an immutable output-video policy.** The default is `原画（跟随源）` for both resolution and fps. A selected resolution limits the output's short edge (1080P, 720P, 480P), retaining the configured canvas aspect and never introducing odd YUV420 dimensions. A selected fps (30/60) replaces the first clip's frame rate. Keep these settings independent from `OutputAspect`, which remains responsible only for canvas/cropping.

- [ ] **Step 4: Force transcode when a non-default resolution or fps is selected.** This must work even when the user has chosen “无损直拷”; otherwise FFmpeg concat copy would silently ignore the requested export setting. Continue to encode as the existing H.264/AAC/yuv420p path, and leave the all-default route byte-for-byte behaviorally unchanged.

- [ ] **Step 5: Bind the controls under output quality.** Provide `原画（跟随源）`, 1080P, 720P, and 480P for resolution, and `原画（跟随源）`, 30 fps, and 60 fps for frame rate. Explain that “原画” preserves the existing result and 30 fps is the compatibility option for phone import failures. Include selected settings in the queued-job summary and lossless eligibility hint.

- [ ] **Step 6: Verify green** with the domain, infrastructure, application, and affected presentation tests.

### Task 4: 蒙版外观模型、库内批量套用与随机入队

**Files:**

- Modify: `src/JingXu.Workbench.Domain/Overlays/OverlayModels.cs`
- Modify: `src/JingXu.Workbench.Application/Projects/OverlayLibraryService.cs`
- Modify: `src/JingXu.Workbench.Application/Overlays/OverlayEnqueueResolver.cs`
- Test: `tests/JingXu.Workbench.Domain.Tests/Overlays/OverlayLayerTransformTests.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Projects/OverlayLibraryServiceTests.cs`
- Test: `tests/JingXu.Workbench.Application.Tests/Overlays/OverlayEnqueueResolverTests.cs`

- [ ] **Step 1: Write failing tests** for legacy JSON compatibility, atomic multi-ID appearance updates, and random enqueue applying the chosen library entry's saved appearance.

- [ ] **Step 2: Verify red.**

- [ ] **Step 3: Implement the typed boundary.** Add `OverlayAppearance` with bounds, opacity, fit, scale, offsets, rotation, feather, top fade and nullable source crop. Add `OverlayLayer.ToAppearance()` and `OverlayAppearance.ApplyTo(OverlayLayer)`; add nullable `Appearance` to `OverlayLibraryEntry`, and implement one-shot `OverlayLibraryService.ApplyAppearanceAsync`. Do not persist source path, duration, start index, z index or audio as an appearance.

```csharp
public sealed record OverlayAppearance(
    NormalizedRect Bounds, double Opacity, OverlayFitMode Fit, double Scale,
    double OffsetX, double OffsetY, double RotationDegrees, double Feather,
    double TopFade, NormalizedRect? SourceCrop = null);
```

- [ ] **Step 4: Apply `entry.Appearance` in `OverlayEnqueueResolver` after resolving the task-specific source path; legacy entries retain current defaults.**

- [ ] **Step 5: Verify green** with domain and application tests.

### Task 5: 源裁切、真实蒙版预览和编辑器批量操作

**Files:**

- Modify: `src/JingXu.Workbench.Application/Abstractions/OverlayCompositePreviewRequest.cs`
- Modify: `src/JingXu.Workbench.Infrastructure/Media/FfmpegMediaFrameExtractor.cs`
- Modify: `src/JingXu.Workbench.Infrastructure/Rendering/OverlayFilterCompiler.cs`
- Create: `src/JingXu.Workbench/Features/Overlays/PreviewRectManipulator.cs`
- Modify: `src/JingXu.Workbench/Features/Overlays/OverlayEditorViewModel.cs`
- Modify: `src/JingXu.Workbench/Features/Overlays/OverlayEditorView.xaml`
- Test: `tests/JingXu.Workbench.Infrastructure.Tests/Rendering/OverlayFilterCompilerTests.cs`
- Test: `tests/JingXu.Workbench.Presentation.Tests/Overlays/OverlayEditorViewModelTests.cs`

- [ ] **Step 1: Write failing tests** for source crop preceding fit, preview retaining opacity/top-fade/feather/rotation/fit/source crop, batch update applying only to checked library entries, and reset clearing source crop.

- [ ] **Step 2: Verify red.**

- [ ] **Step 3: Implement source crop and preview parity.** Nullable `OverlayLayer.SourceCrop` preserves legacy `SourceCropY` when null; otherwise crop the source before the existing fit pipeline and ignore legacy vertical bias. Change preview request to include full `OverlayLayer`; create a one-second `ResolvedOverlay` and invoke `OverlayFilterCompiler.Compile` rather than duplicating filters. Preview must not clamp opacity zero to 0.05; editor image opacity must not clamp to 8%–72%.

- [ ] **Step 4: Implement UI.** Keep the blue bounds rectangle as output placement. Add independent source-crop X/Y/width/height controls, a draggable crop rectangle over the source thumbnail, and reset. Add library-card checkboxes plus “将当前参数套用到已选素材”; only the derived `OverlayAppearance` persists.

- [ ] **Step 5: Verify green** with infrastructure/presentation tests and one FFmpeg pixel-level acceptance test.

### Task 6: 回归与交付核验

- [ ] **Step 1: Confirm the diff preserves pre-existing work.**

```powershell
git diff --check
git status --short
```

- [ ] **Step 2: Run core regression suites.**

```powershell
dotnet test tests/JingXu.Workbench.Domain.Tests/JingXu.Workbench.Domain.Tests.csproj -c Release --no-restore
dotnet test tests/JingXu.Workbench.Application.Tests/JingXu.Workbench.Application.Tests.csproj -c Release --no-restore
dotnet test tests/JingXu.Workbench.Infrastructure.Tests/JingXu.Workbench.Infrastructure.Tests.csproj -c Release --no-restore
```

- [ ] **Step 3: Run affected presentation tests and build the WPF project; report existing test-isolation or executable-lock failures separately.**
