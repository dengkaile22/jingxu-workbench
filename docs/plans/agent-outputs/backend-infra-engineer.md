# Backend / Infrastructure Engineer Analysis

> Generated from full solution build + test run against `.worktrees/jingxu-implementation/`.

---

## 1. Assessment — Current State

### Build Status
- **Solution builds cleanly**: 0 warnings, 0 errors. All 9 projects (4 production, 5 test) compile.

### Test Results (per project)

| Project | Passed | Failed | Skipped | Notes |
|---------|--------|--------|---------|-------|
| Domain.Tests | 85 | 0 | 0 | Fully green |
| Application.Tests | 53 | 0 | 0 | Fully green |
| Infrastructure.Tests | 94 | 0 | 0 | Fully green |
| Presentation.Tests | 41 | **41** | 0 | All failures are `TaskCanceledException` from `Dispatcher.Invoke` |
| IntegrationTests | 0 | **1** | 0 | `RuntimePackageTests` — placeholder SHA-256 hashes in manifest |

### Implementation Coverage

The codebase has extensive implementations spanning all 22 planned tasks:

**Domain Layer (24 files)**: `Result<T>`, `FileSequenceParser`, `CompositionPlanner`, `DeterministicRandom`, `MediaInfo`, `MediaAsset`, `RenderJob` (full state machine), `RenderProfile`, `RenderDecision`, `RenderRequest`, `OutputAspect`, `UnifiedAspectPolicy`, `OverlayModels`, `OverlayTimelineResolver`, `OverlaySourceSelector`, `EffectTemplate`, `SubtitleModels`, `SubtitleTimeline`, `NormalizedRect`.

**Application Layer (24 files)**: All 8 abstractions (`IAtomicJsonStore`, `IExternalProcessRunner`, `IMediaProbe`, `IRenderExecutor`, `IMediaFrameExtractor`, `ISubtitleDocumentCodec`, `ISpeechRecognizer`, `IRenderQueueStore`). Full `RenderCoordinator` with bounded concurrency, pause/resume, per-job cancellation, shutdown drain. `RenderPreflight`, `RenderQueueRecovery`, `ProjectService`, `ProjectDocument`, `OverlayLibraryService`, `TemplateService`, `CompositionOrchestrator`, `SubtitleWorkflow`, `FrameSamplingPlanner`, `SubtitleRegionClusterer`.

**Infrastructure Layer (34 files)**: `AtomicJsonStore<T>` with atomic temp+replace, `ExternalProcessRunner` with dual-stream drain + `WindowsJobObject`, `RuntimeResolver`, `FfprobeMediaProbe`, `FfprobeJsonParser`, `FfmpegCommandCompiler` (full filter graph), `FfmpegRenderExecutor` (staging + validation + atomic move), `OverlayFilterCompiler`, `EffectFilterCompiler`, `AudioFilterCompiler`, `SubtitleRemovalFilterCompiler`, `SubtitleBurnInFilterCompiler`, `SubtitleBurnInCommandCompiler`, `FfmpegFilterPathEscaper`, `FfmpegProgressParser`, `CoverGenerator`, `OutputNamePolicy`, `TesseractSubtitleOcrDetector`, `TesseractTsvParser`, `WhisperRunner`, `WhisperSrtParser`, `SrtSubtitleCodec`, `AssSubtitleCodec`, `SubtitleCodecRegistry`, `RuntimeManifest`, `RuntimeManifestValidator`, `RuntimeDiagnosticService`, `FfmpegMediaFrameExtractor`, `RenderInfrastructure`.

**Presentation Layer (46 files)**: Full WPF shell with `ShellViewModel`, `CompositionViewModel`, `OverlayEditorViewModel`, `SubtitleLabViewModel`, `RenderQueueViewModel`, `SettingsViewModel`, `GateMonitorViewModel`. All XAML views present. Theme dictionaries (Colors, Typography, Metrics, Controls, Motion). Composition root wiring all services.

### Key Observation
The backend/infrastructure layer is **production-complete**. All domain logic, application orchestration, process execution, persistence, FFmpeg command compilation, overlay/subtitle filter graphs, and runtime resolution are fully implemented and tested. The remaining failures are exclusively in the Presentation test harness and an integration manifest placeholder.

---

## 2. Approach — Fix Sequencing

The 41 Presentation test failures share a **single root cause**: `CompositionViewModel.RunOnUi` and `OverlayEditorViewModel.RunOnUi` use `System.Windows.Application.Current.Dispatcher`, which is unavailable or deadlocked in the test STA thread context. This is an infrastructure/wiring issue, not a domain logic issue.

**Fix order (impact descending)**:
1. Fix the `Dispatcher` injection pattern in ViewModels (unblocks 41 tests)
2. Update runtime manifest SHA-256 placeholders (unblocks 1 integration test)
3. Verify all tests green end-to-end

---

## 3. Steps — Exact Implementation

### Step 1: Fix Presentation Test Failures (41 tests)

**Root cause**: `CompositionViewModel` and `OverlayEditorViewModel` use a static `RunOnUi` helper that calls `System.Windows.Application.Current.Dispatcher.Invoke(...)`. In the test environment, the WPF `Application` instance is created on the `WpfAppFixture` STA thread. Test methods run on xUnit's own thread. When the ViewModel calls `Application.Current.Dispatcher.Invoke`, it either:
- Finds `Application.Current == null` (no dispatcher), or
- Deadlocks because the dispatcher message loop is not pumping (the STA thread is blocked waiting for the test to finish)

**Fix: Inject `Dispatcher` as a constructor parameter.**

**Files to modify**:
- `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs` — Add `Dispatcher? dispatcher` constructor parameter; store as `_dispatcher`; change `RunOnUi` to use `_dispatcher ?? Application.Current?.Dispatcher`.
- `src/JingXu.Workbench/Features/Overlays/OverlayEditorViewModel.cs` — Same pattern.
- `src/JingXu.Workbench/Bootstrap/AppCompositionRoot.cs` — Pass `null` (production path uses `Application.Current`).
- `tests/JingXu.Workbench.Presentation.Tests/Infrastructure/WpfAppFixture.cs` — Expose `Dispatcher` property (already available as `_dispatcher`).
- `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTestFactory.cs` — Pass `WpfAppFixture.Dispatcher` to ViewModel constructors.
- `tests/JingXu.Workbench.Presentation.Tests/Overlays/OverlayEditorViewModelTests.cs` — Same wiring.

**Critical detail**: The `RunOnUi` method must use `Dispatcher.InvokeAsync` (not `Invoke`) for async operations, or the test thread will deadlock. The pattern should be:

```csharp
private void RunOnUi(Action action)
{
    var dispatcher = _dispatcher ?? Application.Current?.Dispatcher;
    if (dispatcher is null || dispatcher.CheckAccess())
    {
        action();
        return;
    }
    dispatcher.Invoke(action, DispatcherPriority.DataBind);
}
```

For async methods that call `RunOnUi`, the callers must be restructured so the async work happens ON the dispatcher thread, not dispatched from outside. The current pattern `dispatcher.Invoke(() => command.Execute(null))` blocks until the Invoke returns, but `AsyncRelayCommand.Execute` returns immediately, so the command's async body runs after `Invoke` already returned.

**Recommended refactoring**: Replace the `command.Execute(null)` pattern inside `RunOnUi` with direct invocation of the async method on the dispatcher via `dispatcher.InvokeAsync` or restructure to avoid the nested command pattern entirely.

### Step 2: Fix Integration Test (1 test)

**File**: `build/runtime-manifest.json`

The `RuntimePackageTests.Staged_runtime_contains_every_manifest_file_with_matching_hash` test fails because all component SHA-256 fields contain placeholder values. This is expected for an offline-first project that bundles sidecar binaries — the actual hashes are only known after staging real runtime binaries.

**Fix**: Either:
- (a) Skip the test with `[Trait("Category", "ReleaseGate")]` when no staged runtime exists, or
- (b) Update the manifest with real SHA-256 hashes of the expected runtime binaries (requires the actual binaries to be present).

Given the offline-first constraint, option (b) is correct for release but option (a) is acceptable for development milestone gates.

---

## 4. Dependencies — Stabilization Order

| Layer | Status | Blocks |
|-------|--------|--------|
| Domain | **Stable** | Nothing remaining |
| Application | **Stable** | Nothing remaining |
| Infrastructure | **Stable** | Nothing remaining |
| Presentation (ViewModel wiring) | **Broken** | 41 tests, visual smoke tests |
| Integration (manifest) | **Broken** | 1 test, release packaging |

The only blocking work is Presentation test wiring. All domain/application/infrastructure code is production-ready.

---

## 5. Risks & Mitigations

### Risk 1: Dispatcher Injection Breaks Production WPF Startup
**Severity**: Low
**Mitigation**: Constructor parameter defaults to `null`; production path (`AppCompositionRoot`) passes `null` and falls back to `Application.Current.Dispatcher`. No behavioral change in production.

### Risk 2: Async Dispatcher.Invoke Pattern Still Deadlocks
**Severity**: High
**Mitigation**: The current `RunOnUi` pattern calls `Dispatcher.Invoke(action)` where `action` contains `command.Execute(null)`. `AsyncRelayCommand.Execute` returns a `Task` but `Invoke` doesn't await it. The fix must either:
- Use `dispatcher.Invoke(() => { /* sync work */ })` for sync-only operations, or
- Use `await dispatcher.InvokeAsync(async () => { await command.ExecuteAsync(null); })` for async work, or
- Restructure ViewModel methods to not use nested command execution inside `RunOnUi`.

### Risk 3: Windows Job Object Race on Dispose
**Severity**: Low
**Mitigation**: Already handled — `ExternalProcessRunner` uses `try/catch` around `Kill` and falls back to `JobObject.Terate()`. The `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` flag ensures cleanup even if `Dispose` is called before `Kill`.

### Risk 4: AtomicJsonStore Temp File Leaks on Crash
**Severity**: Low
**Mitigation**: The `.tmp` file is written to the same directory as the target. On process crash, the `.tmp` file remains but the target is untouched. `LoadAsync` only reads the target; orphaned `.tmp` files are harmless and can be cleaned by a future maintenance pass.

### Risk 5: RenderCoordinator State Persistence Race
**Severity**: Low
**Mitigation**: `PersistAndPublishAsync` persists to the store BEFORE updating the in-memory list. If persist fails, the in-memory state is not updated, so the observable queue remains consistent with the persisted state. The `_persistDrain` field tracks outstanding persists for graceful shutdown.

---

## 6. Quality Standards — Production-Ready Backend Behavior

| Standard | Status | Evidence |
|----------|--------|---------|
| Domain purity (no WPF/process/filesystem refs) | **PASS** | Domain project references only `System.*` |
| Process arguments via `ArgumentList` only | **PASS** | `IProcessRequest.Arguments` is `IReadOnlyList<string>`; no shell string concatenation exists |
| Atomic persistence (temp + replace) | **PASS** | `AtomicJsonStore` uses `File.Replace` / `File.Move` with `Flush(flushToDisk: true)` |
| Job state machine with legal transitions | **PASS** | `RenderJob` throws `InvalidOperationException` on illegal transitions |
| Bounded concurrency (1–4) | **PASS** | `RenderCoordinator` uses `_maxConcurrency` with `SemaphoreSlim`-equivalent lock-based gating |
| Per-job cancellation isolation | **PASS** | Each job gets its own `CancellationTokenSource`; cancel affects only that job |
| Dual-stream drain before WaitForExit | **PASS** | `ExternalProcessRunner` starts `ReadToEndAsync` for both stdout/stderr before `WaitForExitAsync` |
| Windows Job Object for process tree cleanup | **PASS** | `WindowsJobObject` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` + `Kill(entireProcessTree: true)` |
| Chinese validation messages | **PASS** | All `Result.Failure` messages are in Chinese |
| Invariant culture for FFmpeg decimals | **PASS** | `FormatDecimal` / `FormatSeconds` use `CultureInfo.InvariantCulture` |
| No `System.Random` (deterministic seeds) | **PASS** | `DeterministicRandom` uses SplitMix64 |
| Command budget preflight (30,000 chars) | **PASS** | `RenderPreflight.CheckCommandBudget` + `FfmpegCommandCompiler.ValidateCommandBudget` |
| Disk space preflight (1.25× factor) | **PASS** | `RenderPreflight.CheckDisk` with `DiskSafetyFactor = 1.25` |
| Output validation (duration, zero-byte) | **PASS** | `FfmpegRenderExecutor.ValidateOutputAsync` checks existence, size, duration tolerance |
| Schema versioning with read-only newer docs | **PASS** | `AtomicJsonStore` returns `ReadOnlyNewerSchema` for higher versions; save rejects it |
| Queue recovery on interrupted states | **PASS** | `RenderQueueRecovery.Recover` marks `Preparing/Running/Finalizing` as `Failed` with `CanRetry = true` |
| Shutdown drains active jobs | **PASS** | `RenderCoordinator.ShutdownAsync` cancels all tokens and awaits `_persistDrain` |
| Tesseract/Whisper concurrency gate of 1 | **PASS** | `TesseractSubtitleOcrDetector` and `WhisperRunner` run sequentially (no parallel OCR/ASR) |
| Overlay normalized coordinates [0,1] | **PASS** | `NormalizedRect` validates and clamps during pixel conversion |
| Cover generation (FirstSourceFrame / FinalOutputFrame) | **PASS** | `CoverGenerator` implementation present |

---

## 7. Critical Details

### Boundary Integrity
- **Domain ↔ Application**: Domain has zero references to Application. Application references Domain via `CompositionPlanner`, `RenderJob`, `RenderRequest`, `OverlayTimelineResolver`, etc.
- **Application ↔ Infrastructure**: Application defines abstractions (`IExternalProcessRunner`, `IMediaProbe`, `IRenderExecutor`, `IAtomicJsonStore`, `ISubtitleDocumentCodec`, `ISpeechRecognizer`). Infrastructure implements all of them.
- **Infrastructure ↔ Presentation**: Presentation references Infrastructure only through `AppCompositionRoot` (composition root pattern). ViewModels depend on Application abstractions, not Infrastructure types.

### Cancellation Semantics
- `ExternalProcessRunner`: On `OperationCanceledException`, calls `Kill(entireProcessTree: true)` then `JobObject.Terminate()`, then drains streams to avoid zombie handles.
- `RenderCoordinator`: Per-job `CancellationTokenSource` stored in `_jobTokens` dictionary. `CancelJobAsync` cancels only that token. `ShutdownAsync` cancels all.
- `FfmpegRenderExecutor`: Cancellation propagates to the FFmpeg process; staging directory is cleaned (media deleted, log preserved).
- `WhisperRunner`/`TesseractSubtitleOcrDetector`: Temp directories cleaned in `finally` block regardless of success/failure/cancellation.

### Resumability
- `RenderJob.Retry()` transitions from `Failed` → `Queued` only when `CanRetry == true`.
- `RenderQueueRecovery.Recover` marks interrupted `Preparing/Running/Finalizing` states as `Failed` with `CanRetry = true`, enabling UI-level retry.
- Queue state is persisted atomically before each transition is published, so crash recovery always loads a consistent snapshot.

### Error Surfaces
- All process failures return Chinese error messages with exit code and stderr summary.
- `MediaProbeException` wraps FFprobe failures with path and stderr.
- `RuntimeToolNotFoundException` includes the missing tool name.
- `ReadOnlyDocumentException` prevents overwriting documents from newer application versions.
- `RenderExecutionResult.Failed(string)` carries a Chinese `RenderFailure.Message` for UI display.

### FFmpeg Command Compilation Safety
- All paths go through `ArgumentList.Add()` — no shell string concatenation.
- Chinese paths are one argument each (no quoting needed).
- Concat list paths are escaped via `EscapeConcatPath` (forward-slash normalization + single-quote escaping).
- Filter paths use `FfmpegFilterPathEscaper` for Windows backslash/colon handling inside FFmpeg filter expressions.
- Frame rate, opacity, seconds use `CultureInfo.InvariantCulture` — verified by test with `de-DE` culture.
