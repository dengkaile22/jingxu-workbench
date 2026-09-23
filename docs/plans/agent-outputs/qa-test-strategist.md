# QA Test Strategist Analysis

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（`src/JingXu.Workbench.Py`），文中路径仅作历史记录。

> Generated from codebase review of `tests/` across all five test projects.
> Current status: Presentation.Tests 52 passed / 30 failed; IntegrationTests 17 passed / 1 failed.

---

## 1. Assessment

### What the Failure Counts Indicate

**Presentation.Tests (30 failures):** The 30 failures cluster around two root causes:

1. **WPF Application initialization dependency.** `ShellLayoutTests`, `ThemeContractTests`, and `AppIconTests` depend on `WpfAppFixture`, which creates a `JingXu.Workbench.App` instance on an STA thread and calls `InitializeComponent()`. If the merged resource dictionaries (Colors.xaml, Typography.xaml, Controls.xaml) are incomplete, misnamed, or reference missing Geometry/Brush keys, every `[Collection(WpfAppScope.Name)]` test fails in the fixture constructor. This single failure cascades to all theme contract tests (18+ assertions across 6 tests), layout tests (2 theories × 8 regions), and icon tests.

2. **Async ViewModel tests with blocking `.GetAwaiter().GetResult()` on dispatcher-adjacent code.** `CompositionViewModelTestFactory.LoadedComposition()` calls `vm.ImportFilesCommand.ExecuteAsync(...).GetAwaiter().GetResult()`. If the ViewModel's import path touches `Dispatcher.Invoke` or any `SynchronizationContext`-aware code, this deadlocks intermittently. The `RenderQueueViewModelTests.Completed_jobs_appear_in_finished_scope` and `Failed_job_increments_failed_count` tests use `WaitUntilAsync` polling loops that depend on the `RenderCoordinator` scheduler completing within 5 seconds — a race under load.

**IntegrationTests (1 failure):** Most likely a `PortableArtifactTests` or `RuntimePackageTests` failure caused by missing build artifacts (portable directory, staged runtime, WiX sources). These tests assert on filesystem paths that only exist after `Build-Portable.ps1` or `Build-Installer.ps1` runs. If the test runner executes before the build pipeline completes, they fail with path-not-found.

### What the 52 Passing Tests Tell Us

Domain, Application, and Infrastructure test projects are largely healthy. The core domain logic (FileSequenceParser, CompositionPlanner, RenderProfile, OverlayTimeline, EffectTemplate), application services (RenderCoordinator, RenderPreflight, CompositionOrchestrator, OverlayEnqueueResolver), and infrastructure (FfmpegCommandCompiler, FfmpegProgressParser, FfmpegRenderExecutor, AtomicJsonStore, ExternalProcessRunner, parsers) are stable and production-ready. The failures are concentrated in the Presentation layer and build-pipeline-dependent integration tests.

---

## 2. Approach

### Phase 1: Stabilize the WPF Test Host (Presentation.Tests)

Fix the `WpfAppFixture` initialization chain. This is the single highest-leverage fix — it unblocks 20+ tests.

### Phase 2: Fix Async Patterns in ViewModel Tests

Replace blocking `.GetAwaiter().GetResult()` with proper async test flows. Eliminate polling-based assertions in favor of deterministic event-driven waits.

### Phase 3: Fix or Gate the Single Integration Failure

Identify the exact failing integration test and either fix the test's precondition check or gate it on build artifacts.

### Phase 4: Harden Test Infrastructure

Ensure all test doubles are correctly scoped, temp file cleanup is reliable, and no test has implicit dependencies on external state.

---

## 3. Steps

### Step 1: Diagnose WpfAppFixture Initialization Failures

**File:** `tests/JingXu.Workbench.Presentation.Tests/Infrastructure/WpfAppFixture.cs`

Run the Presentation.Tests in isolation with verbose output to capture the `_startupError` exception. The fixture stores it and throws in the constructor, but the error message ("WPF 测试宿主初始化失败") wraps the original. Add temporary logging or run with `dotnet test --logger "console;verbosity=detailed"` to surface the inner exception.

**Likely fixes:**

- If `App.InitializeComponent()` throws `XamlParseException`: the merged resource dictionaries in `App.xaml` reference a key or assembly that doesn't exist. Verify all `MergedDictionaries` entries point to existing XAML files and that referenced `Geometry`/`Brush`/`Style` keys are defined.
- If `new JingXu.Workbench.App()` throws because `Application.Current` is already set: xUnit may have already initialized a WPF Application in a prior test run. The fix is to guard with `WpfApplication.Current ?? new App()` (already done in the fixture) but also ensure the test assembly doesn't have a competing `[assembly: ...]` attribute or `App.xaml` entry point.
- If the STA thread never signals `_ready`: the dispatcher initialization hangs. This typically means `Dispatcher.Run()` is never reached because `InitializeComponent()` blocks. Check for synchronous I/O or dialog creation in the App constructor.

### Step 2: Fix Blocking Async in CompositionViewModelTestFactory

**File:** `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTestFactory.cs:40`

```csharp
// CURRENT (deadlock-prone):
vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips).GetAwaiter().GetResult();

// FIX: make LoadedComposition async
public static async Task<CompositionViewModel> LoadedCompositionAsync(...)
{
    var vm = Create(probe: ..., overlayState: ..., overlayLibraryService: ...);
    await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips).ConfigureAwait(false);
    return vm;
}
```

Update all call sites in `CompositionViewModelTests.cs` to use `await CompositionViewModelTestFactory.LoadedCompositionAsync(...)`. Tests that call `LoadedComposition()` synchronously (like `Invalid_custom_expression_disables_enqueue_with_specific_message`) must become `async Task` methods.

### Step 3: Fix RenderQueueViewModelTests Polling Races

**File:** `tests/JingXu.Workbench.Presentation.Tests/Queue/RenderQueueViewModelTests.cs`

The `WaitUntilAsync` helper polls every 25ms with a 5-second deadline. Under CI load or parallel execution, this can time out. Replace with:

- Subscribe to `RenderCoordinator.JobsChanged` (or equivalent observable) and `await` a `TaskCompletionSource` that resolves when the expected state is reached.
- Alternatively, increase timeout to 15 seconds and add `ConfigureAwait(false)` on the delay to avoid dispatcher affinity.

### Step 4: Fix Duplicate FakeMediaProbe Class Names

**Files:**
- `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTestFactory.cs` — defines `public sealed class FakeMediaProbe`
- `tests/JingXu.Workbench.Presentation.Tests/Overlays/OverlayEditorViewModelTests.cs` — defines `internal sealed class FakeMediaProbe`

Both are in the same assembly. The `internal` one in OverlayEditorViewModelTests shadows the `public` one. This causes `CS0104` ambiguity errors when both namespaces are imported. Fix: rename the overlay test's fake to `OverlayFakeMediaProbe` or move it into a nested class.

### Step 5: Fix OverlayEditorViewModelTests Temp File Cleanup

**File:** `tests/JingXu.Workbench.Presentation.Tests/Overlays/OverlayEditorViewModelTests.cs:307-312`

`CreateTempMediaPath()` writes a zero-byte file to `%TEMP%` but never deletes it. The `Chinese_path_mask_imports_successfully` test uses `ResolveZhaoyuMaskPath()` which depends on a specific path (`C:\Users\dengkaile\OneDrive\Desktop\project2026071001\test-assets\赵雨蒙版\赵雨 (8).mp4`). If this path doesn't exist, the test skips — which is correct. But `Assert.Skip` in xUnit v3 needs to be verified as the correct API (it is in v3, but confirm the project uses v3 and not v2).

### Step 6: Gate Integration Tests on Build Artifacts

**File:** `tests/JingXu.Workbench.IntegrationTests/Packaging/PortableArtifactTests.cs`

The `Portable_artifact_is_self_contained_and_has_required_runtime_layout` test asserts on `BuildPaths.PortableDirectory`. If this directory doesn't exist, the test fails with a directory-not-found error rather than a meaningful assertion failure. Add a precondition check:

```csharp
if (!Directory.Exists(BuildPaths.PortableDirectory))
{
    Assert.Skip("便携版构建产物不存在，跳过布局验证。");
}
```

Apply the same pattern to `RuntimePackageTests` and `WixSourceTests`.

### Step 7: Verify WPF Resource Dictionary Completeness

**File:** `tests/JingXu.Workbench.Presentation.Tests/Themes/ThemeContractTests.cs`

This test checks 18 palette keys, 3 typography keys, 13 control style keys, 4 metric keys, and per-status icon/fill/text keys. If ANY of these are missing from the XAML resource dictionaries, the `TryFindResource` returns `null` and the test fails. Run these tests first in isolation after fixing the WpfAppFixture to get a precise list of missing resource keys.

### Step 8: Ensure Presentation.Tests Project Targets net10.0-windows

**File:** `tests/JingXu.Workbench.Presentation.Tests/*.csproj`

The Presentation.Tests project MUST target `net10.0-windows` (not plain `net10.0`) to access WPF types. If the TFM is wrong, all WPF-dependent tests fail with `TypeLoadException`. Verify:

```xml
<TargetFramework>net10.0-windows</TargetFramework>
<UseWPF>true</UseWPF>
```

---

## 4. Dependencies

### Implementation Stabilization Before Tests Can Be Reliable

| Dependency | Blocks | Reason |
|---|---|---|
| WPF resource dictionaries (Colors.xaml, Typography.xaml, Controls.xaml) must define all keys referenced in ThemeContractTests | ShellLayoutTests, ThemeContractTests, AppIconTests | Tests assert on resource existence |
| `AppCompositionRoot.CreateShell()` must succeed without throwing | All ShellViewModel-dependent tests | Test factory calls this |
| `RenderCoordinator` scheduler loop must complete async work deterministically | RenderQueueViewModelTests, CompositionViewModelTests (enqueue tests) | Tests poll for state changes |
| `OverlayWorkbenchState` must be thread-safe for cross-thread test access | OverlayEditorViewModelTests, CompositionViewModelTests (overlay tests) | Tests create state on test thread, use on dispatcher thread |
| FFmpeg/FFprobe binaries must be on PATH or in `runtime/ffmpeg/` for integration tests | All IntegrationTests.Media | Tests call `FfmpegRuntimeProbe.FindFfmpeg()` |
| Build artifacts (portable dir, staged runtime, WiX output) must exist for packaging tests | PortableArtifactTests, RuntimePackageTests, WixSourceTests | Tests assert on file existence |

---

## 5. Risks & Mitigations

### Risk 1: WPF Dispatcher Thread Starvation in Parallel Test Execution

**Impact:** High. xUnit runs tests in parallel by default. Multiple `[Collection(WpfAppScope.Name)]` test classes share a single `WpfAppFixture` dispatcher. If one test blocks the dispatcher (e.g., `window.Show()` + `UpdateLayout()`), other tests queue behind it.

**Mitigation:** The `[Collection]` attribute already serializes these tests. Verify no other test class accidentally touches `Application.Current` or creates windows outside the collection. Run with `-maxCpuCount:1` if flaky.

### Risk 2: Temp Directory Leaks and File Locking on Windows

**Impact:** Medium. `TemporaryDirectory`, `CreateTempMediaPath()`, and integration test workspaces create files in `%TEMP%`. On Windows, file handles from `File.WriteAllText` or FFmpeg processes may not be released immediately, causing `Directory.Delete` to throw `IOException`.

**Mitigation:** All cleanup blocks already catch `IOException`. Ensure every test that creates temp files uses `IDisposable` and that `using` declarations are present. Consider adding a `RetryOnIOException` wrapper for cleanup.

### Risk 3: FFmpeg Version Differences Across Environments

**Impact:** Medium. Integration tests use lavfi filters and codec features. If the CI machine has a different FFmpeg version than the developer machine, filter syntax or codec availability may differ.

**Mitigation:** Tests already skip when FFmpeg is not found. Pin the FFmpeg version in the test fixture generation script (`New-MediaFixtures.ps1`). Log the FFmpeg version at test startup.

### Risk 4: Chinese Path Handling on Non-UTF-8 Systems

**Impact:** Low-Medium. Several tests use Chinese characters in paths (`C:\素材\`, `成片.mp4`, `分镜输出`). On Windows systems with non-Chinese locale, path encoding could cause issues with FFmpeg's argument parsing.

**Mitigation:** `ExternalProcessRunner` uses `ProcessStartInfo.ArgumentList` (not shell strings), which handles Unicode correctly. Integration tests should verify Chinese path round-trips explicitly — `OverlayRenderTests.Unicode_and_space_paths_render_successfully` already does this.

### Risk 5: xUnit v3 API Differences

**Impact:** Low. The project uses `xunit.v3` (version 3.2.2). `Assert.Skip` is a v3 API. If any test runner or SDK version mismatch causes v2 to load, `Assert.Skip` throws `MissingMethodException`.

**Mitigation:** Verify `Directory.Packages.props` pins `xunit.v3` and that no test project references `xunit` (v2) directly. The `xunit.runner.visualstudio` version must be compatible with v3.

---

## 6. Quality Standards

### What Good Looks Like for This Repo's Tests

1. **Deterministic:** Every test produces the same result regardless of machine, time of day, or parallel execution order. No `Thread.Sleep` without timeout guards. No dependency on filesystem state outside test-owned temp directories.

2. **Production-asserting:** Tests assert on observable behavior (state transitions, output values, error messages), not internal implementation details. The test names describe business scenarios, not method signatures.

3. **Fast-failing:** Domain and Application unit tests complete in < 100ms each. Infrastructure tests with fake process runners complete in < 500ms. Integration tests with real FFmpeg complete in < 30 seconds per test. Packaging tests complete in < 5 seconds.

4. **Isolated:** No test modifies global state (environment variables, current directory, `Application.Current`). Test doubles are scoped per-test, not shared across tests. Temp files are created in unique directories and cleaned up in `finally`/`Dispose`.

5. **Readable:** Test names follow the pattern `Action_condition_expected_result`. Test bodies follow Arrange-Act-Assert. Fake implementations are named to reveal their behavior (`FailingMediaProbe`, `GateRenderExecutor`, `ScriptedRenderExecutor`).

6. **Skip-aware:** Tests that depend on external resources (FFmpeg, customer assets, build artifacts) call `Assert.Skip` with a Chinese message explaining what's missing. Release verification must not skip — these tests gate the release.

---

## 7. Critical Details

### Test Design Pitfalls

1. **`.GetAwaiter().GetResult()` in test factories.** `CompositionViewModelTestFactory.LoadedComposition()` blocks the calling thread. If the ViewModel's `ImportFilesCommand` internally posts to a `SynchronizationContext` or `Dispatcher`, this deadlocks. Every synchronous factory that calls async code must be converted to async or use `Task.Run(() => ...).GetAwaiter().GetResult()` to escape the synchronization context.

2. **Shared mutable state in `OverlayWorkbenchState`.** Multiple tests in `CompositionViewModelTests` and `OverlayEditorViewModelTests` create `OverlayWorkbenchState` instances and mutate them. If tests run in parallel and accidentally share an instance (through a static factory), state leaks between tests. Each test must create its own instance.

3. **`FakeMediaProbe` naming collision.** Two classes with the same name in different namespaces within the same assembly. The `public` one in `CompositionViewModelTestFactory` and the `internal` one in `OverlayEditorViewModelTests`. This causes `CS0104` when both namespaces are imported. Rename the overlay version.

4. **`RenderJob.CreateDraft().Enqueue()` chain in test data.** This assumes the `RenderJob` state machine allows Draft → Queued in one step. If the implementation adds validation (e.g., "cannot enqueue without a Request"), these test data factories break. Keep test data factories close to the domain model's actual constraints.

5. **Integration tests assume FFmpeg lavfi behavior.** `LavfiMediaFactory.GenerateColorClipAsync` and `GenerateToneClipAsync` use FFmpeg's `color` and `sine` sources. These are available in full GPL builds but may not be present in minimal or LGPL builds. The test skip mechanism handles this, but the skip message should name the specific missing filter.

### Verification Priorities

1. **Run Presentation.Tests first.** Fix the WpfAppFixture, then re-run. The 30 failures should drop to < 5 immediately. Remaining failures are likely ViewModel-specific.

2. **Run Domain.Tests and Application.Tests as regression baseline.** These should be 100% green. Any new failure here indicates a production code regression, not a test issue.

3. **Run Infrastructure.Tests with `--filter "FullyQualifiedName~Rendering"` to validate the FFmpeg command compiler pipeline.** This is the most complex infrastructure component and the one most likely to have subtle bugs (decimal formatting, argument escaping, filter graph ordering).

4. **Run IntegrationTests with `--filter "Category!=Acceptance"` to exclude customer-asset-dependent tests.** The remaining tests use auto-generated lavfi fixtures and should pass on any machine with FFmpeg.

5. **Run Packaging tests last.** These are the most environment-dependent and should only be verified after the build pipeline produces artifacts.

### Specific Fixes for the 30 Presentation.Test Failures

| Category | Estimated Count | Root Cause | Fix |
|---|---|---|---|
| WpfAppFixture initialization | ~12 tests | Resource dictionary missing keys or XAML parse error | Fix App.xaml merged dictionaries; add missing resource keys |
| Blocking async in factory | ~6 tests | `.GetAwaiter().GetResult()` deadlock | Convert `LoadedComposition()` to async |
| Polling timeout races | ~4 tests | `WaitUntilAsync` 5s deadline too short | Increase timeout or use event-driven wait |
| FakeMediaProbe collision | ~2 tests | `CS0104` ambiguous type reference | Rename overlay fake |
| Temp file / environment | ~4 tests | Missing test assets or path assumptions | Add `Assert.Skip` guards |
| Other | ~2 tests | Various | Diagnose individually after top fixes |
