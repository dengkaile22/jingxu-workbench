using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Stickers;
using JingXu.Workbench.Features.Stickers;
using JingXu.Workbench.Infrastructure.Persistence;
using JingXu.Workbench.Presentation.Tests.Composition;
using JingXu.Workbench.Presentation.Tests.Infrastructure;

namespace JingXu.Workbench.Presentation.Tests.Stickers;

public sealed class StickerEditorViewModelTests
{
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
            var paths = Enumerable.Range(1, 5)
                .Select(index => Path.Combine(root, $"{index}.png"))
                .ToArray();
            foreach (var path in paths)
            {
                await File.WriteAllBytesAsync(path, [0x89, 0x50, 0x4E, 0x47]);
                await service.RegisterAsync(path);
            }

            var tracksService = new StickerTracksService(
                new AtomicJsonStore<StickerTracksDocument>(StickerTracksDocument.CurrentSchemaVersion),
                Path.Combine(root, "sticker-tracks.json"));
            var vm = new StickerEditorViewModel(
                service,
                tracksService,
                new RecordingMediaFilePicker(),
                new DirectUiDispatcher())
            {
                UseRandomStickerLibrary = true
            };
            await vm.EnsureLibraryLoadedAsync();
            vm.AddStickerCommand.Execute(vm.LibraryEntries[0]);
            vm.SelectedTrack!.Name = "保留参数轨道";
            vm.SelectedTrack.X = 12;
            vm.SelectedTrack.Y = 23;
            vm.SelectedTrack.Width = 31;
            vm.SelectedTrack.Height = 17;
            vm.SelectedTrack.StickerOpacity = 72;
            vm.SelectedTrack.RotationDegrees = 19;
            vm.SelectedTrack.FixedAspectRatio = FixedAspectRatio.Ratio1x1;
            var baselineResult = vm.TryBuildTracks(enabledOnly: true);
            Assert.True(baselineResult.IsSuccess, baselineResult.Error);
            var baseline = Assert.Single(baselineResult.Value!);

            var tracks = Enumerable.Range(0, 15)
                .Select(ordinal =>
                {
                    var result = vm.TryBuildEnabledTracksForPlan(264513, ordinal);
                    Assert.True(result.IsSuccess, result.Error);
                    return Assert.Single(result.Value!);
                })
                .ToArray();
            var cycles = tracks
                .Select(track => track.SourcePath)
                .Chunk(5)
                .Select(chunk => chunk.ToArray())
                .ToArray();

            Assert.All(cycles, cycle => Assert.Equal(
                paths.OrderBy(path => path),
                cycle.OrderBy(path => path)));
            Assert.False(cycles[0].SequenceEqual(cycles[1]));
            Assert.False(cycles[1].SequenceEqual(cycles[2]));
            Assert.All(tracks, track =>
            {
                Assert.Equal(baseline.Name, track.Name);
                Assert.Equal(baseline.Bounds, track.Bounds);
                Assert.Equal(baseline.Opacity, track.Opacity);
                Assert.Equal(baseline.RotationDegrees, track.RotationDegrees);
                Assert.Equal(baseline.IsEnabled, track.IsEnabled);
                Assert.Equal(baseline.FixedAspectRatio, track.FixedAspectRatio);
            });
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task Random_replacement_loads_persistent_library_and_changes_source_between_outputs()
    {
        var root = Path.Combine(Path.GetTempPath(), $"jingxu-sticker-random-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var libraryPath = Path.Combine(root, "sticker-library.json");
            var templatePath = Path.Combine(root, "template.png");
            var firstPath = Path.Combine(root, "first.png");
            var secondPath = Path.Combine(root, "second.png");
            await File.WriteAllBytesAsync(templatePath, [0x89, 0x50, 0x4E, 0x47]);
            await File.WriteAllBytesAsync(firstPath, [0x89, 0x50, 0x4E, 0x47]);
            await File.WriteAllBytesAsync(secondPath, [0x89, 0x50, 0x4E, 0x47]);

            var service = new StickerLibraryService(
                new AtomicJsonStore<StickerLibraryDocument>(StickerLibraryDocument.CurrentSchemaVersion),
                libraryPath);
            await service.RegisterAsync(firstPath);
            await service.RegisterAsync(secondPath);

            var tracksService2 = new StickerTracksService(
                new AtomicJsonStore<StickerTracksDocument>(StickerTracksDocument.CurrentSchemaVersion),
                Path.Combine(root, "sticker-tracks.json"));
            var vm = new StickerEditorViewModel(
                service,
                tracksService2,
                new RecordingMediaFilePicker(),
                new DirectUiDispatcher())
            {
                UseRandomStickerLibrary = true
            };
            vm.AddStickerCommand.Execute(new StickerLibraryEntryRowViewModel(
                new StickerLibraryEntry(Guid.NewGuid(), templatePath, null, null)));

            Assert.Empty(vm.LibraryEntries);
            await vm.EnsureLibraryLoadedAsync();

            var first = vm.TryBuildEnabledTracksForPlan(seed: 264513, planOrdinal: 0);
            var second = vm.TryBuildEnabledTracksForPlan(seed: 264513, planOrdinal: 1);

            Assert.True(first.IsSuccess, first.Error);
            Assert.True(second.IsSuccess, second.Error);
            var firstTrack = Assert.Single(first.Value!);
            var secondTrack = Assert.Single(second.Value!);
            Assert.NotEqual(templatePath, firstTrack.SourcePath);
            Assert.NotEqual(firstTrack.SourcePath, secondTrack.SourcePath);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task Remove_library_sticker_removes_entry_from_view_and_persistent_library()
    {
        var root = Path.Combine(Path.GetTempPath(), $"jingxu-sticker-remove-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var libraryPath = Path.Combine(root, "sticker-library.json");
            var firstPath = Path.Combine(root, "first.png");
            var secondPath = Path.Combine(root, "second.gif");
            await File.WriteAllBytesAsync(firstPath, [0x89, 0x50, 0x4E, 0x47]);
            await File.WriteAllBytesAsync(secondPath, [0x47, 0x49, 0x46]);

            var service = new StickerLibraryService(
                new AtomicJsonStore<StickerLibraryDocument>(StickerLibraryDocument.CurrentSchemaVersion),
                libraryPath);
            await service.RegisterAsync(firstPath);
            await service.RegisterAsync(secondPath);

            var tracksService3 = new StickerTracksService(
                new AtomicJsonStore<StickerTracksDocument>(StickerTracksDocument.CurrentSchemaVersion),
                Path.Combine(root, "sticker-tracks.json"));
            var vm = new StickerEditorViewModel(
                service,
                tracksService3,
                new RecordingMediaFilePicker(),
                new DirectUiDispatcher());
            await vm.LoadLibraryCommand.ExecuteAsync(null);
            var entryToRemove = vm.LibraryEntries.Single(entry => entry.FilePath == firstPath);
            var remainingEntry = vm.LibraryEntries.Single(entry => entry.FilePath == secondPath);

            var commandProperty = typeof(StickerEditorViewModel).GetProperty("RemoveLibraryStickerCommand");
            Assert.NotNull(commandProperty);
            var command = Assert.IsAssignableFrom<IAsyncRelayCommand>(commandProperty!.GetValue(vm));
            await command.ExecuteAsync(entryToRemove);

            Assert.DoesNotContain(vm.LibraryEntries, entry => entry.Id == entryToRemove.Id);
            Assert.Single(vm.LibraryEntries);
            Assert.Same(remainingEntry, vm.LibraryEntries[0]);
            Assert.Contains("已从贴纸素材库移除", vm.StatusMessage, StringComparison.Ordinal);

            var reloaded = await service.LoadAsync();
            Assert.DoesNotContain(reloaded.Entries, entry => entry.Id == entryToRemove.Id);
            Assert.Single(reloaded.Entries);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

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
            var tracksService4 = new StickerTracksService(
                new AtomicJsonStore<StickerTracksDocument>(StickerTracksDocument.CurrentSchemaVersion),
                Path.Combine(root, "sticker-tracks.json"));
            var vm = new StickerEditorViewModel(
                service,
                tracksService4,
                new RecordingMediaFilePicker(),
                new DirectUiDispatcher(),
                confirmation);
            await vm.EnsureLibraryLoadedAsync();
            vm.AddStickerCommand.Execute(vm.LibraryEntries.Single(entry => entry.FilePath == firstPath));
            Assert.True(vm.ClearStickerLibraryCommand.CanExecute(null));

            await vm.ClearStickerLibraryCommand.ExecuteAsync(null);

            Assert.Empty(vm.LibraryEntries);
            Assert.False(vm.ClearStickerLibraryCommand.CanExecute(null));
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
            var tracksService5 = new StickerTracksService(
                new AtomicJsonStore<StickerTracksDocument>(StickerTracksDocument.CurrentSchemaVersion),
                Path.Combine(root, "sticker-tracks.json"));
            var vm = new StickerEditorViewModel(
                service,
                tracksService5,
                new RecordingMediaFilePicker(),
                new DirectUiDispatcher(),
                confirmation);
            await vm.EnsureLibraryLoadedAsync();

            await vm.ClearStickerLibraryCommand.ExecuteAsync(null);

            Assert.Equal(2, vm.LibraryEntries.Count);
            Assert.Equal(2, (await service.LoadAsync()).Entries.Count);
            Assert.Equal(1, confirmation.CallCount);
            Assert.Equal(2, confirmation.LastEntryCount);
            Assert.Contains("已取消", vm.StatusMessage, StringComparison.Ordinal);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

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
}
