using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Application.Tests.Overlays;

public sealed class OverlayEnqueueResolverTests
{
    [Fact]
    public void Disabled_switch_returns_empty_layers()
    {
        var state = ConfiguredState(enabled: false);
        var plan = TestPlan(seed: 42);

        var layers = OverlayEnqueueResolver.ResolveForPlan(state, TestLibrary(), plan);

        Assert.Empty(layers);
    }

    [Fact]
    public void Enabled_switch_uses_configured_layers_without_random()
    {
        var state = ConfiguredState(enabled: true, useRandom: false);
        var plan = TestPlan(seed: 42);

        var layers = OverlayEnqueueResolver.ResolveForPlan(state, TestLibrary(), plan);

        Assert.Single(layers);
        Assert.Equal(@"C:\masks\manual.mp4", layers[0].SourcePath);
        Assert.Equal(OverlayMode.FreeCover, layers[0].Mode);
    }

    [Fact]
    public void Random_library_replaces_source_path_per_plan_seed()
    {
        var state = ConfiguredState(enabled: true, useRandom: true);
        var library = TestLibrary();
        var planA = TestPlan(seed: 100);
        var planB = TestPlan(seed: 200);

        var layersA = OverlayEnqueueResolver.ResolveForPlan(state, library, planA);
        var layersB = OverlayEnqueueResolver.ResolveForPlan(state, library, planB);

        Assert.Single(layersA);
        Assert.Single(layersB);
        Assert.NotEqual(layersA[0].SourcePath, layersB[0].SourcePath);
        Assert.Equal(OverlayMode.FreeCover, layersA[0].Mode);
    }

    [Fact]
    public void Random_replacement_cycles_library_between_batch_outputs()
    {
        var state = ConfiguredState(enabled: true, useRandom: true);
        var library = TestLibrary();
        var plan = TestPlan(seed: 264513);

        var first = OverlayEnqueueResolver.ResolveForPlan(state, library, plan, planOrdinal: 0);
        var second = OverlayEnqueueResolver.ResolveForPlan(state, library, plan, planOrdinal: 1);

        Assert.Single(first);
        Assert.Single(second);
        Assert.NotEqual(first[0].SourcePath, second[0].SourcePath);
    }

    [Fact]
    public void Random_replacement_uses_only_one_mask_track_instead_of_stacking_all_tracks()
    {
        var firstBounds = new NormalizedRect(0.1, 0.2, 0.7, 0.35);
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\masks\first.mp4", TimeSpan.FromSeconds(2)) with
        {
            Bounds = firstBounds,
            Opacity = 0.55,
            Feather = 0.4
        });
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\masks\second.mp4", TimeSpan.FromSeconds(2)) with
        {
            ZIndex = 2
        });
        state.SetEnabled(true);
        state.SetUseRandomLibrarySource(true);

        var layers = OverlayEnqueueResolver.ResolveForPlan(
            state,
            TestLibrary(),
            TestPlan(seed: 42),
            planOrdinal: 0);

        var layer = Assert.Single(layers);
        Assert.Contains(@"C:\library\", layer.SourcePath);
        Assert.Equal(firstBounds, layer.Bounds);
        Assert.Equal(0.55, layer.Opacity);
        Assert.Equal(0.4, layer.Feather);
    }

    [Fact]
    public void Additive_random_keeps_track_placement_when_library_has_visual_settings()
    {
        var trackBounds = new NormalizedRect(0.1, 0.2, 0.7, 0.35);
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\masks\manual.mp4", TimeSpan.FromSeconds(2)) with
        {
            Bounds = trackBounds,
            Opacity = 0.55,
            Feather = 0.4
        });
        state.SetEnabled(true);
        state.SetUseRandomLibrarySource(true);

        var libraryBounds = new NormalizedRect(0, 0, 1, 1);
        var library = new[]
        {
            new OverlayLibraryEntry(
                Guid.Parse("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                @"C:\library\a.mp4",
                [],
                null,
                null,
                new OverlayVisualSettings(libraryBounds, 0.1, OverlayFitMode.Stretch, Feather: 0)),
            new OverlayLibraryEntry(
                Guid.Parse("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                @"C:\library\b.mp4",
                [],
                null,
                null,
                new OverlayVisualSettings(libraryBounds, 0.1, OverlayFitMode.Stretch, Feather: 0)),
        };

        var layers = OverlayEnqueueResolver.ResolveForPlan(state, library, TestPlan(seed: 42));

        Assert.Single(layers);
        Assert.Contains(@"C:\library\", layers[0].SourcePath);
        Assert.Equal(trackBounds, layers[0].Bounds);
        Assert.Equal(0.55, layers[0].Opacity);
        Assert.Equal(0.4, layers[0].Feather);
        Assert.Equal(OverlayFitMode.FillCrop, layers[0].Fit);
    }

    [Fact]
    public void Random_library_without_layers_creates_full_frame_preset()
    {
        var state = new OverlayWorkbenchState();
        state.SetEnabled(true);
        state.SetUseRandomLibrarySource(true);

        var layers = OverlayEnqueueResolver.ResolveForPlan(state, TestLibrary(), TestPlan(seed: 7));

        Assert.Single(layers);
        Assert.Equal(OverlayMode.FreeCover, layers[0].Mode);
        Assert.Contains(@"C:\library\", layers[0].SourcePath);
    }

    [Fact]
    public void Validate_blocks_enabled_without_layers_or_random_library()
    {
        var state = new OverlayWorkbenchState();
        state.SetEnabled(true);

        var message = OverlayEnqueueResolver.ValidateForEnqueue(state, libraryEntryCount: 0);

        Assert.Contains("未配置蒙版层", message);
    }

    [Fact]
    public void Validate_blocks_random_library_when_library_empty()
    {
        var state = new OverlayWorkbenchState();
        state.SetEnabled(true);
        state.SetUseRandomLibrarySource(true);

        var message = OverlayEnqueueResolver.ValidateForEnqueue(state, libraryEntryCount: 0);

        Assert.Contains("素材库为空", message);
    }

    [Fact]
    public async Task Probe_source_durations_updates_random_library_layers()
    {
        var state = new OverlayWorkbenchState();
        state.SetEnabled(true);
        state.SetUseRandomLibrarySource(true);

        var layers = OverlayEnqueueResolver.ResolveForPlan(state, TestLibrary(), TestPlan(seed: 7));
        Assert.Equal(TimeSpan.FromSeconds(3), layers[0].SourceDuration);

        var probe = new RecordingProbe(TimeSpan.FromSeconds(12.5));
        var probed = await OverlayEnqueueResolver.ProbeSourceDurationsAsync(layers, probe);

        Assert.Equal(TimeSpan.FromSeconds(12.5), probed[0].SourceDuration);
        Assert.Equal(layers[0].SourcePath, probe.LastPath);
    }

    private sealed class RecordingProbe(TimeSpan duration) : JingXu.Workbench.Application.Abstractions.IMediaProbe
    {
        public string? LastPath { get; private set; }

        public Task<JingXu.Workbench.Domain.Media.MediaInfo> ProbeAsync(string path, CancellationToken cancellationToken)
        {
            LastPath = path;
            return Task.FromResult(new JingXu.Workbench.Domain.Media.MediaInfo(
                duration, 1080, 1920, 30m, "h264", "aac", true, 0));
        }
    }

    private static OverlayWorkbenchState ConfiguredState(bool enabled, bool useRandom = false)
    {
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\masks\manual.mp4", TimeSpan.FromSeconds(2)));
        state.SetEnabled(enabled);
        state.SetUseRandomLibrarySource(useRandom);
        return state;
    }

    private static IReadOnlyList<OverlayLibraryEntry> TestLibrary() =>
    [
        new OverlayLibraryEntry(Guid.Parse("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), @"C:\library\a.mp4", [], null, null),
        new OverlayLibraryEntry(Guid.Parse("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), @"C:\library\b.mp4", [], null, null),
        new OverlayLibraryEntry(Guid.Parse("cccccccc-cccc-cccc-cccc-cccccccccccc"), @"C:\library\c.mp4", [], null, null),
    ];

    private static CompositionPlan TestPlan(int seed)
    {
        var asset = new MediaAsset(
            Guid.NewGuid(),
            @"C:\素材\1.mp4",
            1,
            new MediaInfo(TimeSpan.FromSeconds(2), 1080, 1920, 30m, "h264", "aac", true, 0));

        return new CompositionPlan(
            [new PlannedClip(asset, TimeSpan.Zero, asset.Info.Duration)],
            asset.Info.Duration,
            Seed: seed,
            TimeSpan.Zero);
    }
}
