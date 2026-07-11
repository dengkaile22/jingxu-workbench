using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class OverlayFilterCompilerTests
{
    [Fact]
    public void Free_cover_compiles_overlay_with_trim_and_enable()
    {
        var resolved = OverlayTestSupport.ResolveSingle(
            OverlayLayer.CreateScreenshotPreset(@"C:\蒙版\顶部.mp4", TimeSpan.FromSeconds(2.5)),
            clipSeconds: [2, 3, 4]);

        var result = OverlayFilterCompiler.Compile(resolved, mainInputCount: 3, 1080, 1920).Value!;

        Assert.Contains("-stream_loop", result.PreInputArguments);
        Assert.Contains(@"C:\蒙版\顶部.mp4", result.PreInputArguments);
        Assert.Contains("trim=duration=", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("overlay=", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("between(t,", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Equal("vov0", result.FinalVideoLabel);
    }

    [Fact]
    public void Full_frame_mode_uses_default_low_opacity()
    {
        var layer = OverlayLayer.CreateFullFramePreset(@"C:\overlay.mp4", TimeSpan.FromSeconds(3));
        var resolved = OverlayTestSupport.ResolveSingle(layer, [5]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("colorchannelmixer=aa=0.2", result.FilterSuffix, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(OverlayFitMode.FillCrop, "force_original_aspect_ratio=increase,crop=")]
    [InlineData(OverlayFitMode.Contain, "force_original_aspect_ratio=decrease,pad=")]
    [InlineData(OverlayFitMode.Stretch, "scale=540:576")]
    public void Fit_modes_emit_expected_scale_tokens(OverlayFitMode fit, string token)
    {
        var layer = OverlayTestSupport.LayerWithFit(fit);
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;
        Assert.Contains(token, result.FilterSuffix, StringComparison.Ordinal);
    }

    [Fact]
    public void Ffmpeg_compiler_maps_overlay_inputs_after_main_clips()
    {
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\overlay.mp4", TimeSpan.FromSeconds(2));
        var request = OverlayTestSupport.RequestWithOverlay(layer, clipCount: 2);
        var compile = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", request, @"C:\out\temp.mp4");

        var args = compile.Command.Arguments.ToList();
        var firstOverlayInput = args.IndexOf(@"C:\overlay.mp4");
        var lastMainInput = args.LastIndexOf(@"C:\media\2.mp4");
        Assert.True(firstOverlayInput > lastMainInput);

        var filter = args[args.IndexOf("-filter_complex") + 1];
        Assert.Contains("[vbase]", filter, StringComparison.Ordinal);
        Assert.Contains("overlay=", filter, StringComparison.Ordinal);
        Assert.Equal("[vov0]", args[args.IndexOf("-map") + 1]);
    }

    [Fact]
    public void Overlay_request_disables_stream_copy()
    {
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\overlay.mp4", TimeSpan.FromSeconds(2));
        var request = OverlayTestSupport.RequestWithOverlay(layer, clipCount: 2);
        Assert.False(RenderDecision.For(request).CanStreamCopy);
    }

    [Fact]
    public void Empty_overlay_list_fails_compile()
    {
        var result = OverlayFilterCompiler.Compile([], 1, 1080, 1920);
        Assert.False(result.IsSuccess);
    }

    [Fact]
    public void Scale_transform_emits_relative_scale_and_center_pad()
    {
        var layer = OverlayTestSupport.LayerWithFit(OverlayFitMode.FillCrop) with { Scale = 0.5 };
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("scale=iw*0.5:ih*0.5", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("pad=540:576:", result.FilterSuffix, StringComparison.Ordinal);
    }

    [Fact]
    public void Offset_transform_adjusts_overlay_anchor_expression()
    {
        var layer = OverlayTestSupport.LayerWithFit(OverlayFitMode.FillCrop) with
        {
            OffsetX = 0.1,
            OffsetY = -0.05
        };
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("overlay=x=108-(overlay_w-540)/2:y=-96-(overlay_h-576)/2", result.FilterSuffix, StringComparison.Ordinal);
    }

    [Fact]
    public void Rotation_transform_emits_rotate_filter()
    {
        var layer = OverlayTestSupport.LayerWithFit(OverlayFitMode.FillCrop) with { RotationDegrees = 45 };
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("rotate=", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains(":c=none", result.FilterSuffix, StringComparison.Ordinal);
    }

    [Fact]
    public void Feather_transform_emits_alpha_gblur_chain()
    {
        var layer = OverlayTestSupport.LayerWithFit(OverlayFitMode.FillCrop) with { Feather = 0.5 };
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("alphaextract", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("gblur=sigma=", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("alphamerge", result.FilterSuffix, StringComparison.Ordinal);
    }
}

internal static class OverlayTestSupport
{
    public static IReadOnlyList<ResolvedOverlay> ResolveSingle(OverlayLayer layer, int[] clipSeconds)
    {
        var plan = BuildPlan(clipSeconds);
        return [OverlayTimelineResolver.Resolve(plan, layer).Value!];
    }

    public static OverlayLayer LayerWithFit(OverlayFitMode fit) =>
        new(
            "适配测试",
            @"C:\overlay.mp4",
            TimeSpan.FromSeconds(2),
            OverlayMode.FreeCover,
            new NormalizedRect(0, 0, 0.5, 0.3),
            1,
            1,
            0,
            fit);

    public static RenderRequest RequestWithOverlay(OverlayLayer layer, int clipCount)
    {
        var seconds = Enumerable.Repeat(2, clipCount).ToArray();
        var plan = BuildPlan(seconds);
        return new RenderRequest(
            plan,
            @"C:\out\成片.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            [layer],
            HasOverlays: true);
    }

    private static CompositionPlan BuildPlan(int[] seconds)
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
