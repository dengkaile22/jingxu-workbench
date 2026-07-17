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

            var vm = new StickerEditorViewModel(
                service,
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

            var vm = new StickerEditorViewModel(
                service,
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

            var vm = new StickerEditorViewModel(
                service,
                new RecordingMediaFilePicker(),
                new DirectUiDispatcher());
            await vm.LoadLibraryCommand.ExecuteAsync(null);
            var entryToRemove = vm.LibraryEntries.Single(entry => entry.FilePath == firstPath);

            var commandProperty = typeof(StickerEditorViewModel).GetProperty("RemoveLibraryStickerCommand");
            Assert.NotNull(commandProperty);
            var command = Assert.IsAssignableFrom<IAsyncRelayCommand>(commandProperty!.GetValue(vm));
            await command.ExecuteAsync(entryToRemove);

            Assert.DoesNotContain(vm.LibraryEntries, entry => entry.Id == entryToRemove.Id);
            Assert.Single(vm.LibraryEntries);
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
}
