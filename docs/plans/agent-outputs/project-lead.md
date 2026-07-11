# Project Lead / Synthesizer — Final Analysis

> Generated from live codebase inspection, test run, and goal-analysis review.

---

## 1. Assessment — Current State

### Test Status (verified live)

| Test Project | Passed | Failed | Status |
|---|---|---|---|
| Domain.Tests | 85 | 0 | ✅ GREEN |
| Application.Tests | 53 | 0 | ✅ GREEN |
| Infrastructure.Tests | 94 | 0 | ✅ GREEN |
| IntegrationTests | 17 | 1 | ⚠️ 1 expected M4 gate failure |
| Presentation.Tests | 41 | 41 | 🔴 WPF Dispatcher deadlock |

**Root cause of all 41 Presentation failures:** `CompositionViewModel.RunOnUi()` (line 423–434) and `GateMonitorViewModel.RunOnUi()` use `Application.Current.Dispatcher.Invoke()`. When the full test suite runs, a WPF `Application` instance is created by the first test class that touches WPF types. Subsequent test classes share this `Application` and its `Dispatcher`. Because xUnit runs tests concurrently across classes but the `Dispatcher` message pump is not active on the test thread, `Dispatcher.Invoke()` deadlocks. **Every failing test passes when run individually.** This is a test-infrastructure bug, not a production code bug.

The 1 IntegrationTests failure (`Staged_runtime_contains_every_manifest_file_with_matching_hash`) is expected — it requires M4 staging artifacts that don't exist yet.

### Git State

- **3 commits** on branch: Tasks 1–3 (scaffold, sequence parser, composition planner).
- **Massive uncommitted changeset** covering Tasks 4–18: all Application/Infrastructure/Presentation layers, all remaining tests, scripts, docs, XAML themes, ViewModels, and integration harnesses.
- The uncommitted code is functionally complete for M1–M3 domain/application/infrastructure layers.

### Implementation Coverage

All 24 files in Domain, all 24 files in Application, all 34 files in Infrastructure, and all 57 files in WPF Presentation exist and compile. The file structure matches the implementation plan exactly.

---

## 2. Approach — Sequencing Logic

The work divides into **three stabilization phases** followed by **four finishing phases**:

### Phase A: Fix the test infrastructure deadlock (BLOCKS EVERYTHING)
The 41 Presentation test failures must be resolved before any further work, because:
- They prevent `dotnet test` from producing a clean baseline.
- New Presentation tests added in later tasks will inherit the same deadlock.
- No agent can verify their work if half the test suite is broken.

### Phase B: Commit the accumulated work
The entire Tasks 4–18 implementation is uncommitted. This must be committed in coherent slices to establish a recoverable baseline. Without commits, any regression is unrecoverable.

### Phase C: Close the remaining M2/M3/M4 tasks
After green tests and committed code, finish the remaining plan tasks (Tasks 14, 19–22) in dependency order.

---

## 3. Steps — Concrete Execution Plan

### Step 1: Extract `IUiDispatcher` abstraction to fix WPF test deadlock

**Problem:** `CompositionViewModel`, `GateMonitorViewModel`, `OverlayEditorViewModel`, and `RenderQueueViewModel` all contain a private `RunOnUi(Action)` method that calls `Application.Current.Dispatcher.Invoke()`. This creates a deadlock when tests run without an active Dispatcher message pump.

**Fix pattern:**

1. Create `src/JingXu.Workbench/Bootstrap/IUiDispatcher.cs`:
   ```csharp
   public interface IUiDispatcher
   {
       void Invoke(Action action);
   }
   ```

2. Create `src/JingXu.Workbench/Bootstrap/WpfUiDispatcher.cs`:
   ```csharp
   public sealed class WpfUiDispatcher : IUiDispatcher
   {
       public void Invoke(Action action)
       {
           var dispatcher = Application.Current?.Dispatcher;
           if (dispatcher is null || dispatcher.CheckAccess())
           {
               action();
               return;
           }
           dispatcher.Invoke(action, DispatcherPriority.DataBind);
       }
   }
   ```

3. Create test double in Presentation.Tests:
   ```csharp
   public sealed class DirectUiDispatcher : IUiDispatcher
   {
       public void Invoke(Action action) => action();
   }
   ```

4. Inject `IUiDispatcher` into every ViewModel constructor that currently has a private `RunOnUi` method. Replace all `RunOnUi(action)` calls with `_uiDispatcher.Invoke(action)`.

5. Register `WpfUiDispatcher` in `AppCompositionRoot`; pass `DirectUiDispatcher` in all test factories.

**Files to modify:**
- `src/JingXu.Workbench/Bootstrap/IUiDispatcher.cs` (new)
- `src/JingXu.Workbench/Bootstrap/WpfUiDispatcher.cs` (new)
- `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs` — inject `IUiDispatcher`, remove private `RunOnUi`
- `src/JingXu.Workbench/Features/Shell/GateMonitorViewModel.cs` — inject `IUiDispatcher`, remove private `RunOnUi`
- `src/JingXu.Workbench/Features/Overlays/OverlayEditorViewModel.cs` — inject `IUiDispatcher`, remove private `RunOnUi`
- `src/JingXu.Workbench/Features/Queue/RenderQueueViewModel.cs` — inject `IUiDispatcher`, remove private `RunOnUi`
- `src/JingXu.Workbench/Bootstrap/AppCompositionRoot.cs` — register `WpfUiDispatcher`
- `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTestFactory.cs` — pass `DirectUiDispatcher`
- `tests/JingXu.Workbench.Presentation.Tests/Shell/ShellViewModelTestFactory.cs` — pass `DirectUiDispatcher`
- `tests/JingXu.Workbench.Presentation.Tests/Overlays/OverlayEditorViewModelTests.cs` — pass `DirectUiDispatcher`
- `tests/JingXu.Workbench.Presentation.Tests/Infrastructure/DirectUiDispatcher.cs` (new)

**Verification:** `dotnet test JingXu.Workbench.sln` must show 0 failures across all 5 test projects (except the 1 expected IntegrationTests M4 gate).

### Step 2: Commit in coherent slices

Use the following commit sequence to match the plan's discipline:

1. **Commit Tasks 4–5:** `feat: persist projects and render queue atomically` + `feat: run media sidecars safely`
   - Domain/Rendering, Application/Abstractions, Application/Projects, Infrastructure/Persistence, Infrastructure/Processes, Infrastructure/Runtime, Infrastructure/Rendering/FfmpegProgressParser
   - Related tests

2. **Commit Tasks 6–7:** `feat: probe imported media metadata` + `feat: coordinate persistent render jobs`
   - Infrastructure/Media, Application/Rendering
   - Related tests

3. **Commit Task 8:** `feat: build professional WPF workbench shell`
   - WPF Bootstrap, Themes, ShellWindow, Features/Shell
   - Presentation tests

4. **Commit Tasks 9–12:** `feat: compile core ffmpeg render commands` through `feat: execute and finalize safe video renders`
   - Domain/Rendering (RenderProfile, TranscodeReason, RenderDecision, OutputAspect, CoverMode, RenderRequest, UnifiedAspectPolicy)
   - Infrastructure/Rendering (FfmpegCommand, FfmpegCommandCompiler, FfmpegRenderExecutor, OutputNamePolicy, EffectFilterCompiler, AudioFilterCompiler, OverlayFilterCompiler, CoverGenerator, SubtitleRemovalFilterCompiler, FfmpegFilterPathEscaper)
   - Domain/Overlays, Domain/Effects, Application/Overlays, Application/Composition
   - Related tests

5. **Commit Task 13:** `feat: complete batch composition workbench`
   - All remaining WPF Features (Composition, Overlays, Queue, Settings, Subtitles)
   - All Presentation tests

6. **Commit Tasks 15–18:** `feat: complete offline subtitle laboratory`
   - Domain/Subtitles, Application/Subtitles, Infrastructure/Subtitles, Infrastructure/Rendering (subtitle compilers)
   - Related tests

7. **Commit infrastructure/docs/scripts:** `docs: add architecture, testing, and release documentation`
   - README.md, THIRD_PARTY_NOTICES.md, docs/, scripts/

8. **Commit the IUiDispatcher fix:** `fix: extract IUiDispatcher to resolve WPF test deadlock`

### Step 3: Verify M2 integration (Task 14)

After all commits, run the M2 e2e integration tests:
```powershell
dotnet test tests/JingXu.Workbench.IntegrationTests --filter "CompositionRenderTests|OverlayRenderTests|AudioAndCoverTests"
```
These tests require FFmpeg on PATH. If FFprobe/FFmpeg are not available on the CI machine, these tests will skip. Ensure `FfmpegRuntimeProbe` correctly detects availability.

Fix any integration failures exposed by real FFmpeg execution. These are the tests that validate actual video output — duration, pixel sampling, audio frequency, overlay positioning.

### Step 4: Complete remaining M4 tasks (Tasks 19–22)

Execute in this order:

1. **Task 19: Settings, runtime manifest, first-run diagnostics**
   - `RuntimeManifest.cs`, `RuntimeManifestValidator.cs`, `SettingsViewModel.cs`, `SelfTestRunner.cs`
   - `build/runtime-manifest.json`
   - Tests

2. **Task 20: Runtime staging, licensing, docs**
   - `scripts/Resolve-Runtimes.ps1`
   - `runtime/README.md`, `README.md`, `THIRD_PARTY_NOTICES.md`, `docs/*`
   - Runtime package tests

3. **Task 21: Portable build and WiX installer**
   - `scripts/Build-Portable.ps1`, `scripts/Build-Installer.ps1`
   - `build/Installer/*.wxs`, `build/Installer/*.wixproj`
   - Portable/installer artifact tests

4. **Task 22: Final acceptance**
   - `scripts/Verify-Release.ps1`
   - `docs/acceptance-report.md`
   - Full clean build + test + format verification

---

## 4. Dependencies — What Must Happen Before What

```
Step 1 (IUiDispatcher fix)
  └── MUST complete before ANY new Presentation test work
  └── MUST complete before Step 2 (commits) to ensure committed code is green

Step 2 (commits)
  └── MUST complete before Step 3 (M2 e2e) to have a recoverable baseline
  └── MUST complete before Step 4 (M4 tasks) for the same reason

Step 3 (M2 e2e verification)
  └── Depends on Steps 1+2
  └── May expose bugs in FfmpegCommandCompiler/FfmpegRenderExecutor/OverlayFilterCompiler
  └── Any fixes here must be committed before Step 4

Step 4, Task 19 (Settings/manifest)
  └── Depends on Steps 1+2
  └── RuntimeManifest must exist before Task 20 (staging tests reference it)

Step 4, Task 20 (Runtime staging/docs)
  └── Depends on Task 19 (RuntimeManifest)
  └── Must complete before Task 21 (Build scripts reference staged runtimes)

Step 4, Task 21 (Portable/Installer)
  └── Depends on Task 20 (staged runtimes, docs)
  └── Must complete before Task 22 (Verify-Release references artifacts)

Step 4, Task 22 (Final acceptance)
  └── Depends on ALL previous steps
```

**Critical cross-cutting dependency:** The `OverlayLibraryService` constructor signature in tests uses `AtomicJsonStore<OverlayLibraryDocument>` with a schema version parameter. Ensure the `OverlayLibraryDocument.CurrentSchemaVersion` is consistent across all test factories and the production `OverlayEditorViewModel`.

---

## 5. Risks & Mitigations

### Risk 1: WPF Dispatcher deadlock pattern is repeated in future ViewModels
**Impact:** Every new ViewModel that calls `RunOnUi` will break tests.
**Mitigation:** The `IUiDispatcher` abstraction in Step 1 eliminates this permanently. All future ViewModels MUST use the injected dispatcher, never `Application.Current.Dispatcher` directly. Add a code review rule: any direct `Dispatcher.Invoke` in a ViewModel is a blocking issue.

### Risk 2: Uncommitted changeset is too large for a single commit
**Impact:** If any file in the changeset has a bug, reverting the commit loses all work.
**Mitigation:** Step 2 splits the changeset into 8 coherent commits. Each commit should pass `dotnet build` and `dotnet test` independently. If a commit breaks the build, fix it before proceeding.

### Risk 3: Integration tests depend on FFmpeg availability
**Impact:** M2/M3 e2e tests may skip silently on machines without FFmpeg.
**Mitigation:** The `FfmpegRuntimeProbe` class already handles detection. Integration tests should use `Assert.Skip` (not `Assert.Fail`) when FFmpeg is unavailable. The `Verify-Release.ps1` script in Task 22 must NOT allow skipped required tests.

### Risk 4: `TreatWarningsAsErrors=true` may surface hidden warnings
**Impact:** The `Directory.Build.props` sets `TreatWarningsAsErrors=true`. Uncommitted code may have accumulated warnings that now block the build.
**Mitigation:** Run `dotnet build -c Release` after each commit. Fix warnings immediately; do not suppress with `#pragma` unless the warning is genuinely false-positive.

### Risk 5: xUnit v3 concurrent test execution may cause file-system races
**Impact:** Tests that write to temp directories (e.g., `AtomicJsonStoreTests`, `FfmpegRenderExecutorTests`) may conflict.
**Mitigation:** Each test must use `Guid`-based unique temp paths (many already do). Run the full suite twice to catch races: `dotnet test && dotnet test`.

### Risk 6: WiX Toolset 6 may not be installed on the build machine
**Impact:** Task 21 installer tests will fail.
**Mitigation:** The `Build-Installer.ps1` script should check for WiX and provide a Chinese error message if missing. Installer tests should skip gracefully when WiX is not available.

---

## 6. Quality Standards — Production-Ready Guarantees

A production-ready plan must guarantee:

1. **Zero test failures** across all 5 test projects (Domain, Application, Infrastructure, Presentation, Integration) at each commit.
2. **Zero build warnings** with `TreatWarningsAsErrors=true`.
3. **`dotnet format --verify-no-changes`** passes before final acceptance.
4. **No `Application.Current` access in ViewModels** — all WPF-specific operations go through injectable abstractions (`IUiDispatcher`, `IMediaFilePicker`, `IOutputFolderPicker`, `IFolderLauncher`).
5. **No shell string concatenation** — all FFmpeg/FFprobe/Whisper/Tesseract invocations use `ProcessStartInfo.ArgumentList`.
6. **No empty placeholders** — every button, menu item, and view must be functional or not present.
7. **Domain purity** — `JingXu.Workbench.Domain` has zero references to WPF, `System.IO`, or `System.Diagnostics.Process`.
8. **Immutable job snapshots** — `RenderJob` records are never mutated after enqueue.
9. **Atomic persistence** — all JSON writes go through temp-file-then-replace via `AtomicJsonStore<T>`.
10. **Chinese error messages** — every user-facing error message is in Chinese and includes a suggested action.

---

## 7. Critical Details — Easy-to-Overlook Coordination Issues

### 7.1 `CompositionViewModelTestFactory.LoadedComposition` blocks on async
Line 40: `vm.ImportFilesCommand.ExecuteAsync(...).GetAwaiter().GetResult()` — this synchronous blocking on async is only safe because the import path uses `ConfigureAwait(false)` internally and the `FakeMediaProbe` returns immediately. Once the `IUiDispatcher` fix is applied, this pattern must still work with `DirectUiDispatcher`. Do NOT change this to `await` — it's called from synchronous test setup methods.

### 7.2 `OverlayEditorViewModel` constructor creates a default `OverlayLibraryService`
Line 37–38: If no `libraryService` is injected, a new `AtomicJsonStore` is created with a default temp path. Test factories must inject a controlled instance to avoid file-system side effects.

### 7.3 `RenderCoordinator.Create` vs `new RenderCoordinator`
The factory method `RenderCoordinator.Create()` is used everywhere. Ensure it matches the constructor signature. If the constructor changes (e.g., adding `IUiDispatcher`), the factory must be updated.

### 7.4 `InMemoryRenderQueueStore` is used in Presentation tests
This test double must implement the same interface as `AtomicJsonStore<QueueDocument>`. Any new method on the store interface requires updating `InMemoryRenderQueueStore`.

### 7.5 `WpfAppFixture` creates a real `Application`
The `WpfAppFixture` in `tests/JingXu.Workbench.Presentation.Tests/Infrastructure/WpfAppFixture.cs` creates a real `JingXu.Workbench.App()` and calls `InitializeComponent()`. This loads the merged resource dictionaries. Tests that use `[Collection("WpfApp")]` run on the STA thread with a Dispatcher. Tests that do NOT use this collection run on regular threads. After the `IUiDispatcher` fix, the `WpfAppFixture` is only needed for theme/layout tests, not for ViewModel tests.

### 7.6 `packages.lock.json` must be committed
`Directory.Build.props` sets `RestorePackagesWithLockFile=true`. Every project's `packages.lock.json` must be committed. The uncommitted changeset includes lock file modifications — these must be part of the commits.

### 7.7 IntegrationTests target `net10.0-windows`
The `JingXu.Workbench.IntegrationTests.csproj` targets `net10.0-windows` (not `net10.0`). This is correct because it references the WPF project. But it means these tests can only run on Windows with the Windows Desktop runtime.

### 7.8 The `RuntimePackageTests` failure is a future-gate, not a bug
`Staged_runtime_contains_every_manifest_file_with_matching_hash` reads from `artifacts/staging/runtime/` which doesn't exist yet. This test will fail until Task 20/21 are complete. Do NOT attempt to fix this test before Task 20.

### 7.9 `OverlayLayer.CreateScreenshotPreset` signature
The test code calls `OverlayLayer.CreateScreenshotPreset(path, duration)` with two arguments, but the plan spec shows it taking only one argument. The implementation has been adapted. Ensure consistency across all call sites.

### 7.10 `FfmpegCommandCompiler` culture sensitivity
The plan requires invariant-culture decimal formatting. The existing implementation uses `CultureInfo.InvariantCulture` in format strings. Any new code that formats frame rates, durations, or opacity must also use invariant culture.

---

## Summary: Execution Order for Agents

| Order | Action | Gate |
|---|---|---|
| 1 | Extract `IUiDispatcher`, fix all 4 ViewModels, update test factories | `dotnet test` = 0 Presentation failures |
| 2 | Commit Tasks 4–5 | `dotnet build && dotnet test` = green |
| 3 | Commit Tasks 6–7 | `dotnet build && dotnet test` = green |
| 4 | Commit Task 8 | `dotnet build && dotnet test` = green |
| 5 | Commit Tasks 9–12 | `dotnet build && dotnet test` = green |
| 6 | Commit Task 13 | `dotnet build && dotnet test` = green |
| 7 | Commit Tasks 15–18 | `dotnet build && dotnet test` = green |
| 8 | Commit docs/scripts | `dotnet build && dotnet test` = green |
| 9 | Run M2 e2e integration tests | All Composition/Overlay/Audio tests pass |
| 10 | Implement Task 19 (Settings/Manifest) | Tests pass |
| 11 | Implement Task 20 (Staging/Docs) | Runtime package tests pass |
| 12 | Implement Task 21 (Portable/Installer) | Artifact tests pass |
| 13 | Implement Task 22 (Final Acceptance) | Full clean build + test + format = green |
