using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Domain.Tests.Rendering;

public sealed class RenderProfileTests
{
    [Fact]
    public void Effects_or_mismatched_streams_disable_lossless_copy()
    {
        Assert.True(RenderDecision.For(TestPlans.CompatibleHardCut()).CanStreamCopy);
        Assert.False(RenderDecision.For(TestPlans.WithOverlay()).CanStreamCopy);
        Assert.Contains(TranscodeReason.Overlay, RenderDecision.For(TestPlans.WithOverlay()).Reasons);
        Assert.False(RenderDecision.For(TestPlans.WithEffects()).CanStreamCopy);
        Assert.Contains(TranscodeReason.Effects, RenderDecision.For(TestPlans.WithEffects()).Reasons);
        Assert.False(RenderDecision.For(TestPlans.WithBgm()).CanStreamCopy);
        Assert.Contains(TranscodeReason.Bgm, RenderDecision.For(TestPlans.WithBgm()).Reasons);
    }

    [Theory]
    [InlineData(QualityPreset.High, 18, 192)]
    [InlineData(QualityPreset.Balanced, 22, 160)]
    [InlineData(QualityPreset.Small, 27, 128)]
    public void Quality_presets_map_to_expected_values(QualityPreset preset, int crf, int audioKbps)
    {
        var profile = RenderProfile.For(preset);
        Assert.Equal(crf, profile.Crf);
        Assert.Equal(audioKbps, profile.AudioKbps);
    }

    [Fact]
    public void Legacy_request_with_missing_overlay_and_sticker_collections_is_safe_to_inspect()
    {
        var request = TestPlans.WithInput(@"C:\media\legacy.mp4") with
        {
            OverlayLayers = null!,
            Stickers = null!,
            HasOverlays = true,
            HasEffects = true
        };

        Assert.False(request.HasRenderableOverlays);
        Assert.False(request.HasRenderableEffects);
    }

    [Fact]
    public void Render_request_defaults_to_auto_processing()
    {
        var request = TestPlans.WithInput(@"C:\media\1.mp4");

        Assert.Equal(VideoProcessingMode.Auto, request.ProcessingMode);
    }
}

internal static class TestPlans
{
    public static RenderRequest CompatibleHardCut() =>
        WithInput(@"C:\media\1.mp4");

    public static RenderRequest WithOverlay() =>
        WithInput(@"C:\media\1.mp4", hasOverlays: true);

    public static RenderRequest WithEffects() =>
        WithInput(@"C:\media\1.mp4", hasEffects: true);

    public static RenderRequest WithBgm() =>
        WithInput(@"C:\media\1.mp4", hasBgm: true);

    public static RenderRequest WithInput(string path, bool hasOverlays = false, bool hasEffects = false, bool hasBgm = false)
    {
        var asset = Asset(path, 1);
        var clip = new PlannedClip(asset, TimeSpan.Zero, asset.Info.Duration);
        var plan = new CompositionPlan([clip], asset.Info.Duration, Seed: 0, TimeSpan.Zero);
        return new RenderRequest(
            plan,
            @"C:\out\成片.mp4",
            RenderProfile.Lossless,
            OutputAspect.InheritFirst,
            [],
            HasOverlays: hasOverlays,
            HasEffects: hasEffects,
            HasBgm: hasBgm);
    }

    public static RenderRequest MultiClipHardCut(params string[] paths)
    {
        var clips = new List<PlannedClip>();
        var offset = TimeSpan.Zero;
        foreach (var (path, index) in paths.Select((p, i) => (p, i + 1)))
        {
            var asset = Asset(path, index);
            clips.Add(new PlannedClip(asset, offset, asset.Info.Duration));
            offset += asset.Info.Duration;
        }

        var plan = new CompositionPlan(clips, offset, Seed: 0, TimeSpan.Zero);
        return new RenderRequest(
            plan,
            @"C:\out\成片.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            []);
    }

    private static MediaAsset Asset(string path, int index) =>
        new(Guid.NewGuid(), path, index,
            new MediaInfo(TimeSpan.FromSeconds(2), 1080, 1920, 30m, "h264", "aac", true, 0));
}
