# Sticker Randomness and Library Clear Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase sticker source variation across batch tasks and add a confirmed one-click sticker-library clear action without affecting masks, source files, or active sticker tracks.

**Architecture:** Add a new deterministic reshuffled-cycle selector beside the legacy selector, and call it only from the sticker module so mask behavior remains unchanged. Add an atomic `ClearAllAsync` operation to the sticker library, expose it through a testable confirmation abstraction and view-model command, then bind a new button in the sticker view.

**Tech Stack:** C# 13 / .NET 10, WPF, CommunityToolkit.Mvvm, xUnit, atomic JSON persistence, FFmpeg portable release scripts.

---

## File map

- Modify `src/JingXu.Workbench.Domain/Composition/DeterministicShuffleCycle.cs`: add sticker-specific reshuffled-cycle selection while preserving `SelectIndex`.
- Create `tests/JingXu.Workbench.Domain.Tests/Composition/DeterministicShuffleCycleTests.cs`: verify permutations, cycle variation, reproducibility, and legacy behavior.
- Modify `src/JingXu.Workbench/Features/Stickers/StickerEditorViewModel.cs`: use the new selector and add the clear command.
- Modify `src/JingXu.Workbench.Application/Projects/StickerLibraryService.cs`: atomically clear all library records.
- Create `src/JingXu.Workbench/Features/Stickers/StickerLibraryClearConfirmation.cs`: isolate the WPF confirmation dialog behind an interface.
- Modify `src/JingXu.Workbench/Features/Stickers/StickerEditorView.xaml`: add the one-click clear button.
- Modify `tests/JingXu.Workbench.Presentation.Tests/Stickers/StickerEditorViewModelTests.cs`: verify stronger randomization, confirmation, persistence, source-file retention, and active-track retention.
- Modify `tests/JingXu.Workbench.Presentation.Tests/Stickers/StickerEditorViewTests.cs`: verify the clear button exists and is bound to the command.

### Task 1: Add a sticker-only reshuffled-cycle selector

**Files:**
- Create: `tests/JingXu.Workbench.Domain.Tests/Composition/DeterministicShuffleCycleTests.cs`
- Modify: `src/JingXu.Workbench.Domain/Composition/DeterministicShuffleCycle.cs`

- [ ] **Step 1: Write failing domain tests**

```csharp
using JingXu.Workbench.Domain.Composition;

namespace JingXu.Workbench.Domain.Tests.Composition;

public sealed class DeterministicShuffleCycleTests
{
    [Fact]
    public void Reshuffled_cycles_are_complete_different_reproducible_and_have_no_boundary_repeat()
    {
        const int itemCount = 5;
        var sequence = Enumerable.Range(0, itemCount * 3)
            .Select(i => DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
                itemCount, seed: 264513, selectionOrdinal: i, branchIndex: 1))
            .ToArray();

        var cycles = sequence.Chunk(itemCount).Select(chunk => chunk.ToArray()).ToArray();
        Assert.All(cycles, cycle => Assert.Equal(
            Enumerable.Range(0, itemCount), cycle.OrderBy(index => index)));
        Assert.False(cycles[0].SequenceEqual(cycles[1]));
        Assert.False(cycles[1].SequenceEqual(cycles[2]));
        Assert.All(sequence.Zip(sequence.Skip(1)), pair => Assert.NotEqual(pair.First, pair.Second));

        var replay = Enumerable.Range(0, sequence.Length)
            .Select(i => DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
                itemCount, seed: 264513, selectionOrdinal: i, branchIndex: 1))
            .ToArray();
        Assert.Equal(sequence, replay);
    }

    [Fact]
    public void Legacy_selector_keeps_its_existing_repeating_cycle_for_mask_callers()
    {
        const int itemCount = 5;
        var first = Enumerable.Range(0, itemCount)
            .Select(i => DeterministicShuffleCycle.SelectIndex(itemCount, 264513, i, 0))
            .ToArray();
        var second = Enumerable.Range(itemCount, itemCount)
            .Select(i => DeterministicShuffleCycle.SelectIndex(itemCount, 264513, i, 0))
            .ToArray();

        Assert.Equal(first, second);
    }
}
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
dotnet test tests/JingXu.Workbench.Domain.Tests/JingXu.Workbench.Domain.Tests.csproj --no-restore --filter "FullyQualifiedName~DeterministicShuffleCycleTests" --verbosity minimal
```

Expected: compilation fails because `SelectIndexWithReshuffledCycles` does not exist; the legacy test compiles once the new API reference is present and protects mask behavior.

- [ ] **Step 3: Implement the minimal new selector without changing `SelectIndex`**

Add to `DeterministicShuffleCycle`:

```csharp
public static int SelectIndexWithReshuffledCycles(
    int itemCount,
    int seed,
    long selectionOrdinal,
    int branchIndex = 0)
{
    if (itemCount <= 0)
    {
        throw new ArgumentOutOfRangeException(nameof(itemCount), "素材数量必须大于零。");
    }

    ArgumentOutOfRangeException.ThrowIfNegative(selectionOrdinal);
    if (itemCount <= 2)
    {
        // 两项时连续不重复已经是最大差异，只能保持交替。
        return SelectIndex(itemCount, seed, selectionOrdinal, branchIndex);
    }

    var cycleOrdinal = selectionOrdinal / itemCount;
    var offset = (int)(selectionOrdinal % itemCount);
    var order = BuildCycleOrder(itemCount, seed, cycleOrdinal, branchIndex);
    if (cycleOrdinal > 0)
    {
        var previous = BuildCycleOrder(itemCount, seed, cycleOrdinal - 1, branchIndex);
        if (order[0] == previous[^1])
        {
            (order[0], order[1]) = (order[1], order[0]);
        }
    }

    return order[offset];
}

private static int[] BuildCycleOrder(int itemCount, int seed, long cycleOrdinal, int branchIndex)
{
    var cycleBits = unchecked((long)((ulong)cycleOrdinal * 0x9E3779B97F4A7C15UL));
    var mixedSeed = unchecked(((long)seed << 32) ^ cycleBits ^ (uint)branchIndex);
    var random = new DeterministicRandom(mixedSeed);
    var order = Enumerable.Range(0, itemCount).ToArray();
    for (var index = order.Length - 1; index > 0; index--)
    {
        var target = random.Next(index + 1);
        (order[index], order[target]) = (order[target], order[index]);
    }

    return order;
}
```

- [ ] **Step 4: Run the domain tests and verify GREEN**

Run the Step 2 command. Expected: 2 passed, 0 failed.

- [ ] **Step 5: Commit only the selector and its tests**

```powershell
git add -- src/JingXu.Workbench.Domain/Composition/DeterministicShuffleCycle.cs tests/JingXu.Workbench.Domain.Tests/Composition/DeterministicShuffleCycleTests.cs
git commit -m "feat: diversify sticker shuffle cycles"
```

### Task 2: Use reshuffled cycles only for sticker sources

**Files:**
- Modify: `tests/JingXu.Workbench.Presentation.Tests/Stickers/StickerEditorViewModelTests.cs`
- Modify: `src/JingXu.Workbench/Features/Stickers/StickerEditorViewModel.cs`

- [ ] **Step 1: Add a failing sticker-level multi-cycle test**

Create five real temporary PNG paths, register them, add one enabled template track, and collect fifteen plans:

```csharp
[Fact]
public async Task Random_replacement_reshuffles_each_completed_library_cycle_without_changing_track_parameters()
{
    var root = Path.Combine(Path.GetTempPath(), $"jingxu-sticker-cycles-{Guid.NewGuid():N}");
    Directory.CreateDirectory(root);
    try
    {
        var service = new StickerLibraryService(
            new AtomicJsonStore<StickerLibraryDocument>(StickerLibraryDocument.CurrentSchemaVersion),
            Path.Combine(root, "sticker-library.json"));
        var paths = Enumerable.Range(1, 5).Select(index => Path.Combine(root, $"{index}.png")).ToArray();
        foreach (var path in paths)
        {
            await File.WriteAllBytesAsync(path, [0x89, 0x50, 0x4E, 0x47]);
            await service.RegisterAsync(path);
        }

        var vm = new StickerEditorViewModel(service, new RecordingMediaFilePicker(), new DirectUiDispatcher())
        {
            UseRandomStickerLibrary = true
        };
        await vm.EnsureLibraryLoadedAsync();
        vm.AddStickerCommand.Execute(vm.LibraryEntries[0]);
        vm.SelectedTrack!.X = 12;
        vm.SelectedTrack.Y = 23;
        vm.SelectedTrack.Width = 31;
        vm.SelectedTrack.Height = 17;
        vm.SelectedTrack.StickerOpacity = 72;
        vm.SelectedTrack.RotationDegrees = 19;

        var tracks = Enumerable.Range(0, 15)
            .Select(ordinal => Assert.Single(vm.TryBuildEnabledTracksForPlan(264513, ordinal).Value!))
            .ToArray();
        var cycles = tracks.Select(track => track.SourcePath).Chunk(5).Select(x => x.ToArray()).ToArray();

        Assert.All(cycles, cycle => Assert.Equal(paths.OrderBy(x => x), cycle.OrderBy(x => x)));
        Assert.False(cycles[0].SequenceEqual(cycles[1]));
        Assert.All(tracks, track =>
        {
            Assert.Equal(0.12, track.Bounds.X, 3);
            Assert.Equal(0.23, track.Bounds.Y, 3);
            Assert.Equal(0.31, track.Bounds.Width, 3);
            Assert.Equal(0.17, track.Bounds.Height, 3);
            Assert.Equal(0.72, track.Opacity, 3);
            Assert.Equal(19, track.RotationDegrees, 3);
        });
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
dotnet test tests/JingXu.Workbench.Presentation.Tests/JingXu.Workbench.Presentation.Tests.csproj --no-restore --filter "FullyQualifiedName~Random_replacement_reshuffles_each_completed_library_cycle" --verbosity minimal
```

Expected: FAIL because current cycles repeat the same source order.

- [ ] **Step 3: Switch only the sticker call site**

In `TryBuildEnabledTracksForPlan`, replace the selector call with:

```csharp
var sourceIndex = DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
    sources.Length,
    seed,
    selectionOrdinal,
    branchIndex: 1);
```

Do not modify `OverlaySourceSelector` or any mask call site.

- [ ] **Step 4: Run sticker and mask random tests**

```powershell
dotnet test tests/JingXu.Workbench.Presentation.Tests/JingXu.Workbench.Presentation.Tests.csproj --no-restore --filter "FullyQualifiedName~StickerEditorViewModelTests" --verbosity minimal
dotnet test tests/JingXu.Workbench.Application.Tests/JingXu.Workbench.Application.Tests.csproj --no-restore --filter "FullyQualifiedName~OverlaySourceSelector|FullyQualifiedName~OverlayEnqueueResolver" --verbosity minimal
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit only the sticker call site and test**

```powershell
git add -- src/JingXu.Workbench/Features/Stickers/StickerEditorViewModel.cs tests/JingXu.Workbench.Presentation.Tests/Stickers/StickerEditorViewModelTests.cs
git commit -m "feat: reshuffle sticker sources between batches"
```

### Task 3: Add confirmed one-click sticker-library clearing

**Files:**
- Modify: `src/JingXu.Workbench.Application/Projects/StickerLibraryService.cs`
- Create: `src/JingXu.Workbench/Features/Stickers/StickerLibraryClearConfirmation.cs`
- Modify: `src/JingXu.Workbench/Features/Stickers/StickerEditorViewModel.cs`
- Modify: `src/JingXu.Workbench/Features/Stickers/StickerEditorView.xaml`
- Modify: `tests/JingXu.Workbench.Presentation.Tests/Stickers/StickerEditorViewModelTests.cs`
- Modify: `tests/JingXu.Workbench.Presentation.Tests/Stickers/StickerEditorViewTests.cs`

- [ ] **Step 1: Write failing clear and cancellation tests**

Add a confirmation stub in `StickerEditorViewModelTests.cs`:

```csharp
private sealed class StubStickerLibraryClearConfirmation(bool result) : IStickerLibraryClearConfirmation
{
    public int CallCount { get; private set; }
    public int LastEntryCount { get; private set; }

    public bool ConfirmClear(int entryCount)
    {
        CallCount++;
        LastEntryCount = entryCount;
        return result;
    }
}
```

Add two tests:

```csharp
[Fact]
public async Task Clear_library_removes_all_records_but_keeps_source_files_and_active_tracks()
{
    var root = Path.Combine(Path.GetTempPath(), $"jingxu-sticker-clear-{Guid.NewGuid():N}");
    Directory.CreateDirectory(root);
    try
    {
        var firstPath = Path.Combine(root, "first.png");
        var secondPath = Path.Combine(root, "second.gif");
        await File.WriteAllBytesAsync(firstPath, [0x89, 0x50, 0x4E, 0x47]);
        await File.WriteAllBytesAsync(secondPath, [0x47, 0x49, 0x46]);
        var service = new StickerLibraryService(
            new AtomicJsonStore<StickerLibraryDocument>(StickerLibraryDocument.CurrentSchemaVersion),
            Path.Combine(root, "sticker-library.json"));
        await service.RegisterAsync(firstPath);
        await service.RegisterAsync(secondPath);
        var confirmation = new StubStickerLibraryClearConfirmation(true);
        var vm = new StickerEditorViewModel(
            service,
            new RecordingMediaFilePicker(),
            new DirectUiDispatcher(),
            confirmation);
        await vm.EnsureLibraryLoadedAsync();
        vm.AddStickerCommand.Execute(vm.LibraryEntries.Single(entry => entry.FilePath == firstPath));

        await vm.ClearStickerLibraryCommand.ExecuteAsync(null);

        Assert.Empty(vm.LibraryEntries);
        Assert.Single(vm.Tracks);
        Assert.True(File.Exists(firstPath));
        Assert.True(File.Exists(secondPath));
        Assert.Empty((await service.LoadAsync()).Entries);
        Assert.Equal(1, confirmation.CallCount);
        Assert.Equal(2, confirmation.LastEntryCount);
        Assert.Contains("原文件未删除", vm.StatusMessage, StringComparison.Ordinal);
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

[Fact]
public async Task Cancelling_clear_keeps_library_and_does_not_touch_persistence()
{
    var root = Path.Combine(Path.GetTempPath(), $"jingxu-sticker-clear-cancel-{Guid.NewGuid():N}");
    Directory.CreateDirectory(root);
    try
    {
        var firstPath = Path.Combine(root, "first.png");
        var secondPath = Path.Combine(root, "second.gif");
        await File.WriteAllBytesAsync(firstPath, [0x89, 0x50, 0x4E, 0x47]);
        await File.WriteAllBytesAsync(secondPath, [0x47, 0x49, 0x46]);
        var service = new StickerLibraryService(
            new AtomicJsonStore<StickerLibraryDocument>(StickerLibraryDocument.CurrentSchemaVersion),
            Path.Combine(root, "sticker-library.json"));
        await service.RegisterAsync(firstPath);
        await service.RegisterAsync(secondPath);
        var confirmation = new StubStickerLibraryClearConfirmation(false);
        var vm = new StickerEditorViewModel(
            service,
            new RecordingMediaFilePicker(),
            new DirectUiDispatcher(),
            confirmation);
        await vm.EnsureLibraryLoadedAsync();

        await vm.ClearStickerLibraryCommand.ExecuteAsync(null);

        Assert.Equal(2, vm.LibraryEntries.Count);
        Assert.Equal(2, (await service.LoadAsync()).Entries.Count);
        Assert.Equal(1, confirmation.CallCount);
        Assert.Contains("已取消", vm.StatusMessage, StringComparison.Ordinal);
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}
```

Add `using System.Windows.Controls;` and these assertions to the existing themed layout test:

```csharp
var clearButton = Assert.IsType<Button>(view.FindName("ClearStickerLibraryButton"));
Assert.Same(shell.StickerModule.ClearStickerLibraryCommand, clearButton.Command);
Assert.False(clearButton.IsEnabled);
```

- [ ] **Step 2: Run the tests and verify RED**

```powershell
dotnet test tests/JingXu.Workbench.Presentation.Tests/JingXu.Workbench.Presentation.Tests.csproj --no-restore --filter "FullyQualifiedName~Clear_library|FullyQualifiedName~Cancelling_clear|FullyQualifiedName~Parameter_editor_loads" --verbosity minimal
```

Expected: compilation fails because the confirmation abstraction and clear command do not exist, and the view test cannot find the button.

- [ ] **Step 3: Add atomic library clearing**

Add to `StickerLibraryService`:

```csharp
public async Task<(StickerLibraryDocument Document, int Removed)> ClearAllAsync(
    CancellationToken cancellationToken = default)
{
    var target = ResolveLibraryPath(null);
    return await MutateAsync(target, async path =>
    {
        var loaded = await LoadDocumentAsync(path, cancellationToken).ConfigureAwait(false);
        var removed = loaded.Document.Entries.Count;
        if (removed == 0)
        {
            return (loaded.Document, 0);
        }

        var empty = StickerLibraryDocument.Empty;
        await _store.SaveAsync(path, empty, DocumentAccessMode.ReadWrite, cancellationToken).ConfigureAwait(false);
        return (empty, removed);
    }, cancellationToken).ConfigureAwait(false);
}
```

- [ ] **Step 4: Add the testable WPF confirmation adapter**

Create `StickerLibraryClearConfirmation.cs`:

```csharp
using System.Windows;

namespace JingXu.Workbench.Features.Stickers;

public interface IStickerLibraryClearConfirmation
{
    bool ConfirmClear(int entryCount);
}

public sealed class WpfStickerLibraryClearConfirmation : IStickerLibraryClearConfirmation
{
    public bool ConfirmClear(int entryCount) =>
        MessageBox.Show(
            $"确定清空贴纸素材库中的 {entryCount} 条记录吗？\n\n只清空软件素材库，不会删除电脑中的 PNG/GIF 原文件，也不会删除当前贴纸轨道。",
            "确认清空贴纸素材库",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No) == MessageBoxResult.Yes;
}
```

- [ ] **Step 5: Add the view-model command and CanExecute updates**

Extend the constructor with an optional confirmation dependency so existing composition tests remain isolated:

```csharp
private readonly IStickerLibraryClearConfirmation _clearConfirmation;

public StickerEditorViewModel(
    StickerLibraryService libraryService,
    IMediaFilePicker filePicker,
    IUiDispatcher uiDispatcher,
    IStickerLibraryClearConfirmation? clearConfirmation = null)
{
    _libraryService = libraryService;
    _filePicker = filePicker;
    _uiDispatcher = uiDispatcher;
    _clearConfirmation = clearConfirmation ?? new WpfStickerLibraryClearConfirmation();

    // Keep the existing Tracks handler.
    LibraryEntries.CollectionChanged += (_, _) =>
    {
        OnPropertyChanged(nameof(HasLibraryEntries));
        ClearStickerLibraryCommand.NotifyCanExecuteChanged();
    };
}
```

Add the command:

```csharp
[RelayCommand(CanExecute = nameof(CanClearStickerLibrary))]
private async Task ClearStickerLibraryAsync()
{
    var entryCount = LibraryEntries.Count;
    if (entryCount == 0)
    {
        return;
    }

    if (!_clearConfirmation.ConfirmClear(entryCount))
    {
        StatusMessage = "已取消清空贴纸素材库。";
        return;
    }

    try
    {
        var (document, removed) = await _libraryService.ClearAllAsync().ConfigureAwait(false);
        _uiDispatcher.Invoke(() =>
        {
            ApplyLibraryDocument(document);
            StatusMessage = removed == 0
                ? "贴纸素材库已为空。"
                : $"已清空贴纸素材库（{removed} 条）；电脑中的原文件未删除，当前贴纸轨道未改动。";
        });
    }
    catch (Exception ex)
    {
        _uiDispatcher.Invoke(() =>
            StatusMessage = $"清空贴纸素材库失败：{ex.GetBaseException().Message}");
    }
}

private bool CanClearStickerLibrary() => HasLibraryEntries;
```

- [ ] **Step 6: Add the clear button**

Place before the existing import button in the header action panel:

```xml
<Button x:Name="ClearStickerLibraryButton"
        Style="{DynamicResource Button.Secondary}"
        Content="清空库"
        Command="{Binding ClearStickerLibraryCommand}"
        Margin="0,0,8,0"
        ToolTip="一次清空贴纸素材库记录；不会删除电脑中的原始图片。"
        AutomationProperties.Name="清空贴纸素材库" />
```

- [ ] **Step 7: Run sticker tests and verify GREEN**

Run the Step 2 command, then:

```powershell
dotnet test tests/JingXu.Workbench.Presentation.Tests/JingXu.Workbench.Presentation.Tests.csproj --no-restore --filter "FullyQualifiedName~StickerEditor" --verbosity minimal
```

Expected: all sticker view-model and view tests pass.

- [ ] **Step 8: Commit the clear feature only**

```powershell
git add -- src/JingXu.Workbench.Application/Projects/StickerLibraryService.cs src/JingXu.Workbench/Features/Stickers/StickerLibraryClearConfirmation.cs src/JingXu.Workbench/Features/Stickers/StickerEditorViewModel.cs src/JingXu.Workbench/Features/Stickers/StickerEditorView.xaml tests/JingXu.Workbench.Presentation.Tests/Stickers/StickerEditorViewModelTests.cs tests/JingXu.Workbench.Presentation.Tests/Stickers/StickerEditorViewTests.cs
git commit -m "feat: clear sticker library in one action"
```

### Task 4: Full verification and direct `dist` release

**Files:**
- Generated: `artifacts/staging/portable/**`
- Replace: `dist/**`

- [ ] **Step 1: Run the complete test suite**

```powershell
dotnet test JingXu.Workbench.sln --no-restore --verbosity minimal
```

Expected: 0 failed; only existing environment-dependent skips are allowed.

- [ ] **Step 2: Build the Release portable directory**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Portable.ps1 -AllowPlaceholderHash -BootstrapFromPath
```

Expected: Release publish succeeds and `artifacts/staging/portable/炳恒快速混剪.exe` exists.

- [ ] **Step 3: Verify paths and mirror the release into `dist`**

Resolve both paths and confirm they begin with the repository root, then run:

```powershell
robocopy artifacts\staging\portable dist /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP
```

Accept robocopy exit codes below 8.

- [ ] **Step 4: Compare every staged and `dist` file by SHA-256**

Build relative-path-to-hash maps for both trees and assert: same count, no missing files, no extra files, no differing hashes.

- [ ] **Step 5: Run published-customer-video smoke verification**

Run `dist/炳恒快速混剪.exe --import-smoke` against:

```text
C:\Users\dengkaile\OneDrive\Documents\xwechat_files\wxid_jutff6al2uat22_f87f\msg\video\2026-07\2b9c415f7be836c4438b27fbf3eb2da9.mp4
```

Expected JSON: `success: true`, `probeOk: true`, `importOk: true`.

- [ ] **Step 6: Run packaging tests**

```powershell
dotnet test tests/JingXu.Workbench.IntegrationTests/JingXu.Workbench.IntegrationTests.csproj --no-build --no-restore --filter "FullyQualifiedName~Packaging" --verbosity minimal
```

Expected: 0 failed.
