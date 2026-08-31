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
        // 主剪辑 i0/i1，蒙版随后为 i2（路径已别名）。
        var mainAlias0 = args.IndexOf("i0.mp4");
        var mainAlias1 = args.IndexOf("i1.mp4");
        var overlayAlias = args.IndexOf("i2.mp4");
        Assert.True(mainAlias0 > 0 && args[mainAlias0 - 1] == "-i");
        Assert.True(mainAlias1 > mainAlias0 && args[mainAlias1 - 1] == "-i");
        Assert.True(overlayAlias > mainAlias1 && args[overlayAlias - 1] == "-i");
        Assert.Contains(compile.InputAliases, a => a.RelativePath == "i2.mp4" && a.AbsolutePath.Contains("overlay.mp4", StringComparison.OrdinalIgnoreCase));

        var filter = compile.TryGetFilterComplex();
        Assert.NotNull(filter);
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
    public void Feather_transform_uses_one_alpha_plane_pass_with_bounded_edge_blur()
    {
        var layer = OverlayTestSupport.LayerWithFit(OverlayFitMode.FillCrop) with
        {
            Feather = 1,
            TopFade = 1
        };
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("alphaextract,geq=lum=", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("Y/(H*1)", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("(H-Y)/(H*1+0.000001)", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("gblur=sigma=8", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("alphamerge", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Equal(1, CountOccurrences(result.FilterSuffix, "geq="));
        Assert.DoesNotContain(
            "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*",
            result.FilterSuffix,
            StringComparison.Ordinal);
    }

    [Fact]
    public void Imported_mask_preset_emits_split_feather_by_default()
    {
        var layer = OverlayLayer.CreateImportedMaskPreset(@"C:\蒙版\人物.mp4", TimeSpan.FromSeconds(2));
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("(H-Y)/(H*", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("alphaextract,geq=lum=", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("gblur=sigma=", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Equal(1, CountOccurrences(result.FilterSuffix, "geq="));
    }

    [Fact]
    public void Ellipse_shape_mask_emits_rgba_alpha_geq_not_luma()
    {
        var layer = OverlayLayer.CreateShapeMask(
            @"C:\overlay.mp4",
            TimeSpan.FromSeconds(2),
            NormalizedRect.Create(0.25, 0.25, 0.5, 0.5).Value!,
            ShapeKind.Ellipse);
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("geq=r=", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains(":a='if(lt(pow(X-", result.FilterSuffix, StringComparison.Ordinal);
        Assert.DoesNotContain("geq=lum=", result.FilterSuffix, StringComparison.Ordinal);
    }

    [Fact]
    public void Rounded_rectangle_shape_mask_preserves_existing_alpha()
    {
        var layer = OverlayLayer.CreateShapeMask(
            @"C:\overlay.mp4",
            TimeSpan.FromSeconds(2),
            NormalizedRect.Create(0.1, 0.1, 0.8, 0.8).Value!,
            ShapeKind.RoundedRectangle);
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("alpha(X,Y)", result.FilterSuffix, StringComparison.Ordinal);
        Assert.DoesNotContain("geq=lum=", result.FilterSuffix, StringComparison.Ordinal);
    }

    [Fact]
    public void Imported_png_shape_mask_emits_movie_alphamerge()
    {
        var layer = OverlayLayer.CreateShapeMask(
            @"C:\overlay.mp4",
            TimeSpan.FromSeconds(2),
            NormalizedRect.Create(0, 0, 1, 1).Value!,
            ShapeKind.ImportedPng) with
        {
            AlphaPngPath = @"C:\masks\alpha.png"
        };
        var resolved = OverlayTestSupport.ResolveSingle(layer, [4]);
        var result = OverlayFilterCompiler.Compile(resolved, 1, 1080, 1920).Value!;

        Assert.Contains("movie=", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("alphamerge", result.FilterSuffix, StringComparison.Ordinal);
        Assert.Contains("C\\:/masks/alpha.png", result.FilterSuffix, StringComparison.Ordinal);
    }

    [Fact]
    public void Overlay_audio_mix_emits_adelay_and_amix()
    {
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\overlay.mp4", TimeSpan.FromSeconds(2)) with
        {
            AudioMode = OverlayAudioMode.Mix
        };
        var request = OverlayTestSupport.RequestWithOverlay(layer, clipCount: 2);
        var compile = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", request, @"C:\out\temp.mp4");
        var filter = compile.TryGetFilterComplex();
        Assert.NotNull(filter);

        Assert.Contains("adelay=", filter, StringComparison.Ordinal);
        Assert.Contains("amix=duration=first:inputs=2", filter, StringComparison.Ordinal);
        Assert.Contains("[a_base]", filter, StringComparison.Ordinal);
    }

    private static int CountOccurrences(string value, string token)
    {
        var count = 0;
        var start = 0;
        while ((start = value.IndexOf(token, start, StringComparison.Ordinal)) >= 0)
        {
            count++;
            start += token.Length;
        }

        return count;
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
