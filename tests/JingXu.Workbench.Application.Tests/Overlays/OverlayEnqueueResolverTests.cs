using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Application.Overlays;
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
    public void Random_library_without_layers_creates_full_frame_preset()
    {
        var state = new OverlayWorkbenchState();
        state.SetEnabled(true);
        state.SetUseRandomLibrarySource(true);

        var layers = OverlayEnqueueResolver.ResolveForPlan(state, TestLibrary(), TestPlan(seed: 7));

        Assert.Single(layers);
        Assert.Equal(OverlayMode.FullFrameLowOpacity, layers[0].Mode);
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
