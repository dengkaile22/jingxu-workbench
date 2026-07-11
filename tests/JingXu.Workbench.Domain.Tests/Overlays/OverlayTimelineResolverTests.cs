using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Domain.Tests.Overlays;

public sealed class OverlayTimelineResolverTests
{
    [Fact]
    public void Screenshot_preset_is_top_full_width_and_adjustable()
    {
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\overlays\banner.mp4", TimeSpan.FromSeconds(3));
        Assert.Equal(new NormalizedRect(0, 0, 1, 0.48), layer.Bounds);
        Assert.Equal(OverlayMode.FreeCover, layer.Mode);
    }

    [Fact]
    public void Starts_at_requested_clip_and_loops_to_exact_end()
    {
        var plan = TestPlans.Clips(seconds: [2, 3, 4]);
        var layer = TestLayers.StartAt(2, sourceSeconds: 2.5);
        var resolved = OverlayTimelineResolver.Resolve(plan, layer).Value!;

        Assert.Equal(TimeSpan.FromSeconds(2), resolved.Start);
        Assert.Equal(TimeSpan.FromSeconds(7), resolved.ActiveDuration);
        Assert.Equal(3, resolved.LoopCount);
        Assert.Equal(TimeSpan.FromSeconds(2), resolved.LastLoopDuration);
    }

    [Fact]
    public void Layers_are_stably_ordered_by_z_index() =>
        Assert.Equal(["back", "front"], OverlayTimelineResolver.Sort(TestLayers.Unordered()).Select(x => x.Name));

    [Fact]
    public void Invalid_start_clip_returns_validation_error()
    {
        var plan = TestPlans.Clips(seconds: [2, 3]);
        var layer = TestLayers.StartAt(5, sourceSeconds: 2);
        var result = OverlayTimelineResolver.Resolve(plan, layer);
        Assert.False(result.IsSuccess);
        Assert.Contains("1 到 2", result.Error, StringComparison.Ordinal);
    }

    [Fact]
    public void Zero_area_bounds_fail_validation()
    {
        var plan = TestPlans.Clips(seconds: [2]);
        var layer = new OverlayLayer(
            "空区域",
            @"C:\overlay.mp4",
            TimeSpan.FromSeconds(2),
            OverlayMode.FreeCover,
            new NormalizedRect(0.1, 0.1, 0, 0.2),
            1,
            1,
            0);

        var result = OverlayTimelineResolver.Resolve(plan, layer);
        Assert.False(result.IsSuccess);
        Assert.Contains("面积", result.Error, StringComparison.Ordinal);
    }
}

public sealed class OverlaySourceSelectorTests
{
    [Fact]
    public void Library_random_choice_is_reproducible_from_job_seed()
    {
        var library = TestAssets.OverlayLibrary(8);
        Assert.Equal(
            OverlaySourceSelector.Select(library, 264513).Id,
            OverlaySourceSelector.Select(library, 264513).Id);
    }

    [Fact]
    public void Empty_library_throws()
    {
        Assert.Throws<InvalidOperationException>(() => OverlaySourceSelector.Select([], 1));
    }
}

internal static class TestPlans
{
    public static CompositionPlan Clips(int[] seconds)
    {
        var clips = new List<PlannedClip>();
        var offset = TimeSpan.Zero;
        for (var i = 0; i < seconds.Length; i++)
        {
            var asset = new MediaAsset(
                Guid.NewGuid(),
                $@"C:\media\{i + 1}.mp4",
                i + 1,
                new MediaInfo(TimeSpan.FromSeconds(seconds[i]), 1080, 1920, 30m, "h264", "aac", true, 0));
            clips.Add(new PlannedClip(asset, offset, asset.Info.Duration));
            offset += asset.Info.Duration;
        }

        return new CompositionPlan(clips, offset, Seed: 0, TimeSpan.Zero);
    }
}

internal static class TestLayers
{
    public static OverlayLayer StartAt(int clipIndex, double sourceSeconds) =>
        new(
            "测试蒙版",
            @"C:\overlays\loop.mp4",
            TimeSpan.FromSeconds(sourceSeconds),
            OverlayMode.FreeCover,
            new NormalizedRect(0, 0, 1, 0.3),
            1,
            clipIndex,
            0);

    public static IEnumerable<OverlayLayer> Unordered() =>
    [
        new("front", @"C:\a.mp4", TimeSpan.FromSeconds(2), OverlayMode.FreeCover, NormalizedRect.FullFrame, 1, 1, 1),
        new("back", @"C:\b.mp4", TimeSpan.FromSeconds(2), OverlayMode.FreeCover, NormalizedRect.FullFrame, 1, 1, 0)
    ];
}

internal static class TestAssets
{
    public static IReadOnlyList<OverlayLibraryEntry> OverlayLibrary(int count) =>
        Enumerable.Range(0, count)
            .Select(i => new OverlayLibraryEntry(
                Guid.Parse($"00000000-0000-0000-0000-{i:D12}"),
                $@"C:\library\{i}.mp4",
                [],
                null,
                null))
            .ToArray();
}
