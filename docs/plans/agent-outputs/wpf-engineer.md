# WPF/Presentation Layer Engineering Analysis

## 1. Assessment — Current Presentation-Layer Health

### Test Status: 42 passed, 40 failed (of 82 total)

**Every failure is the same root exception:** `System.Threading.Tasks.TaskCanceledException` thrown from `System.Windows.Threading.Dispatcher.Invoke` inside the `RunOnUi` helper method.

### Failing Test Categories

| Category | Count | Trigger Pattern |
|---|---|---|
| CompositionViewModelTests | 24 | All tests calling `LoadedComposition()` or `ImportFilesCommand.ExecuteAsync()` |
| OverlayEditorViewModelTests | 10 | All tests calling `AddFreeCoverCommand.ExecuteAsync()` / `AddShapeMaskCommand.ExecuteAsync()` |
| ShellViewModelTests | 3 | Tests calling `vm.ImportFilesCommand.ExecuteAsync()` via shell |
| GateMonitorViewModelTests | 3 | Tests calling `LoadFromMaterialAsync()` which invokes `RunOnUi` |

### Passing Test Categories

| Category | Count | Why They Pass |
|---|---|---|
| ThemeContractTests | 7 | Use `WpfAppFixture` with proper STA dispatcher loop |
| ShellLayoutTests | 2 | Use `WpfAppFixture` with proper STA dispatcher loop |
| ShellViewModelTests (sync) | 9 | Never trigger `RunOnUi` |
| RenderQueueViewModelTests | 4 | Never trigger `RunOnUi` |
| SubtitleLabViewModelTests | 2 | Never trigger `RunOnUi` |
| SettingsViewModelTests | 2 | `ConfigureAwait(true)` returns to test thread; no `RunOnUi` in async path |
| GateMonitorViewModelTests | 4 | First run or `Application.Current` is null → synchronous fallback |
| Other sync tests | 12 | No async dispatcher interaction |

---

## 2. Root Cause Analysis

### The `RunOnUi` Anti-Pattern

Three ViewModels contain an identical `RunOnUi` helper:

```csharp
// CompositionViewModel.cs:423, OverlayEditorViewModel.cs:463, GateMonitorViewModel.cs:194
private static void RunOnUi(Action action)
{
    var dispatcher = System.Windows.Application.Current?.Dispatcher;
    if (dispatcher is null || dispatcher.CheckAccess())
    {
        action();       // fast path: no app or already on UI thread
        return;
    }
    dispatcher.Invoke(action, DispatcherPriority.DataBind);  // ← BLOCKS HERE
}
```

**The problem:** `Dispatcher.Invoke` is a **synchronous blocking call** that requires an active message pump. In the xUnit test runner:

1. `WpfAppFixture` creates `Application.Current` on a dedicated STA thread and starts `Dispatcher.Run()`.
2. xUnit v3 runs tests on thread-pool threads **concurrently with fixture initialization**.
3. Tests that execute **after** `Application.Current` is set but **before** `Dispatcher.Run()` begins pumping will find `Application.Current != null` and `dispatcher.CheckAccess() == false`, so they call `dispatcher.Invoke(...)` — which blocks forever because nobody is pumping messages, eventually throwing `TaskCanceledException`.

### Why Some Tests Pass

- Tests that run when `Application.Current` is still `null` → the `dispatcher is null` guard fires → action runs synchronously → PASS.
- Tests that use `WpfAppFixture.Invoke()` (ThemeContractTests, ShellLayoutTests) → proper STA dispatcher → PASS.
- Purely synchronous tests that never call `RunOnUi` → no dispatcher interaction → PASS.

### The Three Affected ViewModels

1. **`CompositionViewModel.cs`** — `RunOnUi` at line 423-434; called from `ImportFilesAsync`, `PickImportFilesAsync`, `ApplyImportOutcomes`
2. **`OverlayEditorViewModel.cs`** — `RunOnUi` at lines 463-486; called from `AddLayerAsync`, `RegisterToLibraryAsync`, `OnWorkbenchStateChanged`
3. **`GateMonitorViewModel.cs`** — `RunOnUi` at line 194-205; called from `LoadFromMaterialAsync`, `LoadStaticFrameAsync`, `ResetIdle`, `ReportPlaybackFailedAsync`

### Secondary Issue: `LoadedComposition` Blocking Pattern

`CompositionViewModelTestFactory.LoadedComposition()` (line 40) uses:

```csharp
vm.ImportFilesCommand.ExecuteAsync(paths).GetAwaiter().GetResult();
```

This synchronously blocks the test thread waiting for an async operation that internally calls `RunOnUi`. Even if `RunOnUi` were fixed, this `.GetResult()` pattern is fragile — it can deadlock if any `ConfigureAwait(true)` continuation needs the blocked thread.

---

## 3. Recommended Approach

### Strategy: Eliminate Unnecessary `RunOnUi` + Make Remaining `RunOnUi` Test-Safe

**Phase A — Remove `RunOnUi` from async methods that already use `ConfigureAwait(true)`**

In every async method (returning `Task`) that uses `.ConfigureAwait(true)`, the continuation already marshals back to the calling thread. If the calling thread is the UI thread (which it is for all `[RelayCommand]` methods), `RunOnUi` is unnecessary. Remove it.

**Phase B — Replace `RunOnUi` with injectable `IDispatcherService` for genuinely cross-thread callbacks**

Some code paths (event handlers like `OnOverlayStateChanged`, `OnWorkbenchStateChanged`) are invoked from background threads and genuinely need dispatcher marshaling. Make this an injectable abstraction so tests can provide a synchronous implementation.

**Phase C — Fix `LoadedComposition` to be async**

Replace `.GetAwaiter().GetResult()` with proper async test methods.

---

## 4. Detailed Execution Steps

### Step 1: Create `IDispatcherService` Abstraction

**File:** `src/JingXu.Workbench/Bootstrap/IDispatcherService.cs`

```csharp
namespace JingXu.Workbench.Bootstrap;

public interface IDispatcherService
{
    void Invoke(Action action);
    T Invoke<T>(Func<T> func);
}
```

**File:** `src/JingXu.Workbench/Bootstrap/WpfDispatcherService.cs`

```csharp
using System.Windows;
using System.Windows.Threading;

namespace JingXu.Workbench.Bootstrap;

public sealed class WpfDispatcherService : IDispatcherService
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

    public T Invoke<T>(Func<T> func)
    {
        var dispatcher = Application.Current?.Dispatcher;
        if (dispatcher is null || dispatcher.CheckAccess())
        {
            return func();
        }
        return dispatcher.Invoke(func, DispatcherPriority.DataBind);
    }
}
```

**File:** `src/JingXu.Workbench/Bootstrap/SynchronousDispatcherService.cs` (for tests)

```csharp
namespace JingXu.Workbench.Bootstrap;

public sealed class SynchronousDispatcherService : IDispatcherService
{
    public void Invoke(Action action) => action();
    public T Invoke<T>(Func<T> func) => func();
}
```

### Step 2: Remove `RunOnUi` from `CompositionViewModel`

In `CompositionViewModel.cs`:

1. **Delete** the private `RunOnUi` method (lines 423-434).

2. **`ImportFilesAsync`** (line 344): Remove all `RunOnUi` wrappers. Since this is a `[RelayCommand]` async method using `ConfigureAwait(true)`, the continuation returns to the UI thread. Replace:
   ```csharp
   RunOnUi(() => { IsImporting = true; StatusMessage = "正在探测素材…"; });
   ```
   With direct assignment:
   ```csharp
   IsImporting = true;
   StatusMessage = "正在探测素材…";
   ```
   Apply the same pattern to the `try/catch/finally` blocks.

3. **`PickImportFilesAsync`** (line 324): The `catch` block calls `RunOnUi`. Since this is a `[RelayCommand]` async method, the catch runs on the UI thread. Remove `RunOnUi`.

4. **`OnOverlayStateChanged`** (line 282): This is an event callback that may fire from a background thread. Add `IDispatcherService` as a constructor parameter and use it here, or check `SynchronizationContext.Current` instead.

5. **Constructor:** The constructor calls `RefreshOverlayStatus()` and `RefreshPreview()` which are synchronous. These are safe since the constructor runs on the UI thread. No change needed.

### Step 3: Remove `RunOnUi` from `OverlayEditorViewModel`

In `OverlayEditorViewModel.cs`:

1. **Delete** both `RunOnUi` overloads (lines 463-486).

2. **`AddLayerAsync`** (line 314): Remove all `RunOnUi` wrappers. The method uses `ConfigureAwait(true)` (implicitly, since no `ConfigureAwait` is specified). After `await _mediaProbe.ProbeAsync(...)`, the continuation returns to the UI thread. Replace `RunOnUi(() => _filePicker.PickVideoFiles())` with direct call `_filePicker.PickVideoFiles()`.

3. **`RegisterToLibraryAsync`** (line 230): Remove `RunOnUi` wrappers. Direct assignment.

4. **`RefreshLibraryCountAsync`** (line 432): Remove `RunOnUi`. Direct assignment.

5. **`OnWorkbenchStateChanged`** (line 393): This event handler fires from the `OverlayWorkbenchState.Changed` event, which may be raised from a background thread. Inject `IDispatcherService` and use it here.

### Step 4: Remove `RunOnUi` from `GateMonitorViewModel`

In `GateMonitorViewModel.cs`:

1. **Delete** the private `RunOnUi` method (lines 194-205).

2. **`LoadFromMaterialAsync`** (line 56): This method is `async Task` and uses no `ConfigureAwait` (defaults to `ConfigureAwait(true)`). Remove all `RunOnUi` wrappers and assign properties directly.

3. **`LoadStaticFrameAsync`** (line 125): Same — remove `RunOnUi`, assign directly after `await`.

4. **`ResetIdle`** (line 162): This is a synchronous method called from `LoadFromMaterialAsync`. Since the caller is async and returns to the UI thread, `ResetIdle` runs on the UI thread. Remove `RunOnUi`.

5. **`ReportPlaybackFailedAsync`** (line 104): `[RelayCommand]` async method. Remove `RunOnUi`.

### Step 5: Fix `CompositionViewModelTestFactory.LoadedComposition`

In `CompositionViewModelTestFactory.cs`:

1. Make `LoadedComposition` async:
   ```csharp
   public static async Task<CompositionViewModel> LoadedCompositionAsync(
       OverlayWorkbenchState? overlayState = null,
       OverlayLibraryService? overlayLibraryService = null)
   {
       var vm = Create(
           probe: FakeMediaProbe.ForSixClips(),
           overlayState: overlayState,
           overlayLibraryService: overlayLibraryService);
       await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
       return vm;
   }
   ```

2. Keep the sync `LoadedComposition` for tests that don't need async, but have it call the async version:
   ```csharp
   public static CompositionViewModel LoadedComposition(
       OverlayWorkbenchState? overlayState = null,
       OverlayLibraryService? overlayLibraryService = null) =>
       LoadedCompositionAsync(overlayState, overlayLibraryService).GetAwaiter().GetResult();
   ```
   This is safe once `RunOnUi` is removed from `ImportFilesAsync` because the async method will no longer block on the dispatcher.

3. **Update all test methods** that call `LoadedComposition()` to be `async Task` and use `await LoadedCompositionAsync()`. Affected tests:
   - `Invalid_custom_expression_disables_enqueue_with_specific_message`
   - `Custom_expression_shows_expanded_preview_and_duration`
   - `Random_batch_preview_shows_multiple_plans`
   - `Multi_expression_custom_mode_shows_multiple_preview_plans`
   - `Empty_output_settings_disable_enqueue`
   - `Overlay_switch_on_shows_enabled_status_label`
   - `Unified_aspect_preview_updates_when_preset_changes`
   - `Custom_aspect_with_invalid_dimensions_disables_enqueue`

### Step 6: Wire `IDispatcherService` Through Composition Root

In `AppCompositionRoot.cs`:

1. Add `IDispatcherService` parameter (defaulting to `WpfDispatcherService`).
2. Pass it to `OverlayEditorViewModel` constructor (for `OnWorkbenchStateChanged`).
3. For tests, `ShellViewModelTestFactory` and `CompositionViewModelTestFactory` pass `SynchronousDispatcherService`.

### Step 7: Verify All Tests Pass

Run:
```powershell
dotnet test tests/JingXu.Workbench.Presentation.Tests --no-restore
```

Expected: 82 passed, 0 failed.

---

## 5. Dependencies

### Presentation Layer Depends On

| Dependency | Status | Impact |
|---|---|---|
| `CompositionOrchestrator` (Application) | Implemented | Composition import/preview works |
| `RenderCoordinator` (Application) | Implemented | Queue binding works |
| `SubtitleWorkflow` (Application) | Implemented | Subtitle lab works |
| `OverlayLibraryService` (Application) | Implemented | Overlay library works |
| `OverlayWorkbenchState` (Application) | Implemented | Overlay state sharing works |
| `RuntimeDiagnosticService` (Infrastructure) | Implemented | Settings diagnostics works |
| `IMediaProbe` (Application) | Implemented | All ViewModels use it |
| `IRenderExecutor` (Application) | Implemented | Queue coordination works |
| Domain models (all) | Implemented | All domain types exist |

**No blocking dependencies from other layers.** All types referenced by ViewModels exist and compile. The presentation layer failures are entirely self-contained dispatcher issues.

---

## 6. Risks & Mitigations

### Risk 1: Removing `RunOnUi` Breaks Genuine Cross-Thread Calls

**Scenario:** `OverlayWorkbenchState.Changed` fires from a `RenderCoordinator` background thread, calling `OnWorkbenchStateChanged` → `RefreshFromState` → `Layers.Clear()` (ObservableCollection must be modified on UI thread).

**Mitigation:** `OnWorkbenchStateChanged` is the **only** callback that genuinely needs dispatcher marshaling. All other `RunOnUi` callers are in async `[RelayCommand]` methods that already return to the UI thread. Inject `IDispatcherService` specifically for this callback.

### Risk 2: `ConfigureAwait(true)` Continuation Lost Under xUnit

**Scenario:** xUnit v3 may use a custom `SynchronizationContext` that doesn't propagate back to the UI thread.

**Mitigation:** xUnit v3 does **not** install a `SynchronizationContext` by default. `ConfigureAwait(true)` captures the calling thread's `SynchronizationContext`, which for `[RelayCommand]` methods is the WPF dispatcher context. For tests, there is no SynchronizationContext, so `ConfigureAwait(true)` falls back to the thread pool — which is fine because there's no UI to update. Properties can be set from any thread in tests (no binding validation).

### Risk 3: Constructor `RunOnUi` in `CompositionViewModel`

**Scenario:** The constructor calls `RefreshOverlayStatus()` and `RefreshPreview()`, which modify observable properties. If the constructor runs on a non-UI thread...

**Mitigation:** The constructor doesn't use `RunOnUi` — it calls the methods directly. This is correct because constructors are always called on the creating thread (UI thread in production, test thread in tests). No change needed.

### Risk 4: Test Flakiness from Async Timing

**Scenario:** `RenderQueueViewModelTests.Completed_jobs_appear_in_finished_scope` uses `WaitUntilAsync` with a 5-second timeout.

**Mitigation:** This test already passes and doesn't involve `RunOnUi`. The `RenderCoordinator` processes jobs on its own scheduler thread. No change needed.

---

## 7. Quality Standards for Production-Ready Presentation

### Must-Have

1. **No `Dispatcher.Invoke` in async command paths.** Every `[RelayCommand]` async method must use `ConfigureAwait(true)` and access properties directly. `Dispatcher.Invoke` is only acceptable in synchronous event handlers that are provably called from background threads.

2. **No blocking `.GetResult()` on async commands in production code.** The `LoadedComposition` pattern is test-only. Production code must never block the UI thread waiting for an async operation.

3. **Every observable property change must be thread-safe.** If a property can be set from a background thread (via event callback), the setter must dispatch to the UI thread. Use `IDispatcherService` for this.

4. **Command `CanExecute` must be deterministic.** No async `CanExecute` — use synchronous property checks with `[NotifyCanExecuteChangedFor]`.

5. **Cancellation must propagate cleanly.** No `TaskCanceledException` leaking to the UI. Catch `OperationCanceledException` and set a user-visible status message.

6. **No empty catch blocks.** Every `catch (Exception)` must either log, set `StatusMessage`, or rethrow.

### Must-Not-Have

1. No `Dispatcher.Invoke` in any method that returns `Task`.
2. No `.GetAwaiter().GetResult()` in production code.
3. No `Thread.Sleep` or `Task.Wait()` in ViewModels.
4. No direct `Application.Current` access outside `WpfDispatcherService`.
5. No hardcoded UI thread assumptions in unit-testable code.

---

## 8. Critical Details Easy to Miss

### 8.1 The `RunOnUi<T>` Generic Overload

`OverlayEditorViewModel` has **two** `RunOnUi` overloads — `void` and `T`. The generic version (line 476) is used in `AddLayerAsync` to return the file picker result:

```csharp
paths = RunOnUi(() => _filePicker.PickVideoFiles());
```

When removing `RunOnUi`, replace with direct call: `paths = _filePicker.PickVideoFiles()`.

### 8.2 The `OnOverlayStateChanged` Bidirectional Sync

`CompositionViewModel.OnOverlayStateChanged` (line 282) is called when `OverlayWorkbenchState.Changed` fires. This can happen from:
- The overlay editor (UI thread) — safe
- A `RenderCoordinator` background thread during enqueue — needs dispatcher

After removing `RunOnUi`, this callback must still dispatch if called from a background thread. Use `IDispatcherService` or guard with `SynchronizationContext.Current != null`.

### 8.3 The `_loadGeneration` Stale Check in `GateMonitorViewModel`

`LoadFromMaterialAsync` uses `Interlocked.Increment(ref _loadGeneration)` to invalidate stale operations. After removing `RunOnUi`, the generation check (line 91: `if (generation != _loadGeneration) return;`) still works correctly because it runs on the UI thread (via `ConfigureAwait(true)`). No change needed to the logic.

### 8.4 The `CompositionViewModelTestFactory.LoadedComposition` Sync Wrapper

Once `RunOnUi` is removed from `ImportFilesAsync`, the sync `LoadedComposition` wrapper becomes safe (no dispatcher blocking). But it should still be replaced with an async version for test hygiene. The sync wrapper can remain as a convenience for tests that don't need to await.

### 8.5 The `ShellViewModel.OnCompositionPropertyChanged` Fire-and-Forget

`ShellViewModel.cs:78`:
```csharp
_ = Monitor.LoadFromMaterialAsync(CompositionModule.SelectedMaterial);
```

This is fire-and-forget. If `LoadFromMaterialAsync` throws, the exception is lost. After removing `RunOnUi`, this pattern is still correct (the method has internal try/catch). But consider adding a top-level `try/catch` with logging for defense-in-depth.

### 8.6 The `OverlayEditorViewModel.AddLayerAsync` File Existence Check

`AddLayerAsync` line 347: `if (!File.Exists(path))` — this is called from the async method after `await`. In tests, `FakeMediaFilePicker` returns a path to a temp file created by `CreateTempMediaPath()`. After removing `RunOnUi`, this check still runs on the UI thread (via `ConfigureAwait(true)`). But if the test file is cleaned up before the check runs, it could fail. Ensure temp files live for the duration of the test.

### 8.7 Theme/Layout Tests Are Already Correct

`ThemeContractTests` and `ShellLayoutTests` use `WpfAppFixture.Invoke()` which calls `_dispatcher.Invoke(func)` on the proper STA dispatcher. These tests are unaffected by the `RunOnUi` changes.

### 8.8 The `DispatcherPriority.DataBind` Choice

All `RunOnUi` calls use `DispatcherPriority.DataBind`. This is intentional — it ensures property changes propagate before the next layout pass. After removing `RunOnUi`, this priority is irrelevant because direct property assignment is immediate. But for the remaining `IDispatcherService.Invoke` call in `OnWorkbenchStateChanged`, keep `DispatcherPriority.DataBind`.

---

## Summary of Changes Required

| File | Change | Lines Affected |
|---|---|---|
| `Bootstrap/IDispatcherService.cs` | **Create** | New file |
| `Bootstrap/WpfDispatcherService.cs` | **Create** | New file |
| `Bootstrap/SynchronousDispatcherService.cs` | **Create** | New file |
| `Bootstrap/AppCompositionRoot.cs` | Add `IDispatcherService` param | ~5 lines |
| `Features/Composition/CompositionViewModel.cs` | Delete `RunOnUi`; unwrap all calls | ~30 lines removed/changed |
| `Features/Overlays/OverlayEditorViewModel.cs` | Delete both `RunOnUi` overloads; unwrap calls; inject `IDispatcherService` for event callback | ~40 lines removed/changed |
| `Features/Shell/GateMonitorViewModel.cs` | Delete `RunOnUi`; unwrap all calls | ~20 lines removed/changed |
| `Composition/CompositionViewModelTestFactory.cs` | Add `LoadedCompositionAsync`; update callers | ~15 lines |
| `Composition/CompositionViewModelTests.cs` | Make 8 tests `async Task`; use `await LoadedCompositionAsync()` | ~16 lines |
| `Shell/ShellViewModelTestFactory.cs` | Pass `SynchronousDispatcherService` | ~2 lines |
| `Overlays/OverlayEditorViewModelTests.cs` | No change needed (tests already async) | 0 lines |
| `Shell/GateMonitorViewModelTests.cs` | No change needed (tests already async) | 0 lines |
| `Settings/SettingsViewModelFactory.cs` | No change needed | 0 lines |

**Total estimated change:** ~130 lines across 13 files (3 new, 10 modified).
