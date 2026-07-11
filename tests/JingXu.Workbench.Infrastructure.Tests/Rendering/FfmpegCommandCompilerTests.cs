using System.Globalization;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class FfmpegCommandCompilerTests
{
    [Fact]
    public void Chinese_path_is_one_argument_without_shell_quotes()
    {
        var command = FfmpegCommandCompiler.Compile(
            @"C:\runtime\ffmpeg.exe",
            CompilerTestPlans.WithInput(@"C:\素材 文件\1.mp4"),
            @"C:\out\.jingxu-tmp\output.mp4").Command;

        Assert.Contains(@"C:\素材 文件\1.mp4", command.Arguments);
        Assert.DoesNotContain(command.Arguments, x => x.Contains("cmd.exe", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Compatible_hard_cut_uses_stream_copy_concat()
    {
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            CompilerTestPlans.CompatibleTwoClipHardCut(),
            @"C:\out\temp.mp4");

        Assert.Contains("-c", result.Command.Arguments);
        Assert.Contains("copy", result.Command.Arguments);
        Assert.Contains("concat.txt", result.AuxiliaryFiles.Select(x => x.FileName));
    }

    [Fact]
    public void Transcode_path_uses_filter_complex_and_libx264()
    {
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            CompilerTestPlans.TranscodeTwoClip(),
            @"C:\out\temp.mp4");

        var args = result.Command.Arguments.ToList();
        var filter = args[args.IndexOf("-filter_complex") + 1];
        Assert.Contains("libx264", result.Command.Arguments);
        Assert.Contains("concat=n=2:v=1:a=1", filter, StringComparison.Ordinal);
    }

    [Fact]
    public void Decimal_tokens_use_invariant_format_under_de_de()
    {
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = new CultureInfo("de-DE");
            var result = FfmpegCommandCompiler.Compile(
                @"C:\ffmpeg.exe",
                CompilerTestPlans.TranscodeTwoClip(frameRate: 29.97m),
                @"C:\out\temp.mp4");

            var args = result.Command.Arguments.ToList();
            var filter = args[args.IndexOf("-filter_complex") + 1];
            Assert.Contains("fps=29.97", filter, StringComparison.Ordinal);
            Assert.DoesNotContain("fps=29,97", filter, StringComparison.Ordinal);
        }
        finally
        {
            CultureInfo.CurrentCulture = previous;
        }
    }

    [Fact]
    public void Command_budget_rejects_overlong_commands()
    {
        var longPath = @"C:\media\" + new string('x', 40_000) + ".mp4";
        var request = CompilerTestPlans.WithInput(longPath);
        var command = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", request, @"C:\out\temp.mp4").Command;
        var budget = FfmpegCommandCompiler.ValidateCommandBudget(command);
        Assert.False(budget.IsSuccess);
        Assert.Contains("命令过长", budget.Error, StringComparison.Ordinal);
    }

    [Fact]
    public void Effects_and_bgm_compile_into_filter_graph()
    {
        var request = CompilerTestPlans.WithEffectsAndBgm();
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var args = result.Command.Arguments.ToList();
        var filter = args[args.IndexOf("-filter_complex") + 1];
        Assert.Contains("eq=", filter, StringComparison.Ordinal);
        Assert.Contains("aloop", filter, StringComparison.Ordinal);
        Assert.Contains("amix=duration=first", filter, StringComparison.Ordinal);
        Assert.Contains(@"C:\bgm.mp3", result.Command.Arguments);
    }

    [Fact]
    public void Sticker_compiles_overlay_with_extra_input()
    {
        var request = CompilerTestPlans.WithSticker();
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var args = result.Command.Arguments.ToList();
        var filter = args[args.IndexOf("-filter_complex") + 1];
        Assert.Contains(@"C:\贴纸.png", result.Command.Arguments);
        Assert.Contains("overlay=", filter, StringComparison.Ordinal);
        Assert.Contains("[1:v]", filter, StringComparison.Ordinal);
    }

    [Fact]
    public void Metadata_clearing_does_not_change_timeline_duration()
    {
        var request = CompilerTestPlans.WithMetadataClearing();
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var args = result.Command.Arguments.ToList();
        var filter = args[args.IndexOf("-filter_complex") + 1];
        Assert.Contains("-map_metadata", result.Command.Arguments);
        Assert.Contains("-1", result.Command.Arguments);
        Assert.DoesNotContain("setpts", filter, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(AspectFitMode.CenterCrop, "force_original_aspect_ratio=increase,crop=1080:1920")]
    [InlineData(AspectFitMode.Letterbox, "force_original_aspect_ratio=decrease,pad=1080:1920")]
    [InlineData(AspectFitMode.Stretch, "scale=1080:1920,")]
    [InlineData(AspectFitMode.BlurBackground, "boxblur=20:1")]
    public void Custom_aspect_applies_fit_filter_to_each_clip(AspectFitMode fitMode, string token)
    {
        var request = CompilerTestPlans.MixedResolutionWithCustomAspect(1080, 1920, fitMode);
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var args = result.Command.Arguments.ToList();
        var filter = args[args.IndexOf("-filter_complex") + 1];
        Assert.Contains(token, filter, StringComparison.Ordinal);
        Assert.Contains("concat=n=2:v=1:a=1", filter, StringComparison.Ordinal);
    }

    [Fact]
    public void Unified_aspect_with_overlay_uses_target_canvas_for_overlay_fit()
    {
        var layer = OverlayLayer.CreateFullFramePreset(@"C:\蒙版\赵雨.mp4", TimeSpan.FromSeconds(3)) with
        {
            Fit = OverlayFitMode.Contain
        };
        var request = CompilerTestPlans.MixedResolutionWithCustomAspect(
            1080,
            1920,
            AspectFitMode.CenterCrop,
            overlay: layer);
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var args = result.Command.Arguments.ToList();
        var filter = args[args.IndexOf("-filter_complex") + 1];
        Assert.Contains("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920", filter, StringComparison.Ordinal);
        Assert.Contains("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920", filter, StringComparison.Ordinal);
        Assert.Contains("overlay=", filter, StringComparison.Ordinal);
    }
}

internal static class CompilerTestPlans
{
    public static RenderRequest WithInput(string path) =>
        MultiClip([Asset(path, 1)], RenderProfile.Balanced);

    public static RenderRequest CompatibleHardCut(string path = @"C:\media\1.mp4") =>
        MultiClip(
            [Asset(path, 1), Asset(@"C:\media\2.mp4", 2)],
            RenderProfile.Lossless);

    public static RenderRequest CompatibleTwoClipHardCut() => CompatibleHardCut();

    public static RenderRequest TranscodeTwoClip(decimal frameRate = 30m) =>
        MultiClip(
            [Asset(@"C:\media\1.mp4", 1, frameRate), Asset(@"C:\media\2.mp4", 2, frameRate)],
            RenderProfile.Balanced);

    public static RenderRequest WithEffectsAndBgm()
    {
        var assets = new[] { Asset(@"C:\media\1.mp4", 1), Asset(@"C:\media\2.mp4", 2) };
        var clips = new List<PlannedClip>();
        var offset = TimeSpan.Zero;
        foreach (var asset in assets)
        {
            clips.Add(new PlannedClip(asset, offset, asset.Info.Duration));
            offset += asset.Info.Duration;
        }

        var plan = new CompositionPlan(clips, offset, Seed: 264513, TimeSpan.Zero);
        var effect = EffectTemplates.StandardVariation().Materialize(plan.Seed);
        var bgm = BgmMixPlan.Create(@"C:\bgm.mp3").Value!;
        return new RenderRequest(
            plan,
            @"C:\out\成片.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            [],
            HasEffects: true,
            HasBgm: true,
            Effect: effect,
            Bgm: bgm);
    }

    public static RenderRequest WithSticker()
    {
        var sticker = ImageSticker.Create(
            @"C:\贴纸.png",
            x: 0.1,
            y: 0.2,
            width: 0.3,
            height: 0.25).Value!;
        var plan = SingleClipPlan();
        return new RenderRequest(
            plan,
            @"C:\out\成片.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            [],
            HasEffects: true,
            Sticker: sticker);
    }

    public static RenderRequest WithMetadataClearing()
    {
        var effect = EffectTemplates.StandardVariation().Materialize(42) with { ClearMetadata = true };
        var plan = SingleClipPlan();
        return new RenderRequest(
            plan,
            @"C:\out\成片.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            [],
            HasEffects: true,
            Effect: effect);
    }

    public static RenderRequest MixedResolutionWithCustomAspect(
        int width,
        int height,
        AspectFitMode fitMode,
        OverlayLayer? overlay = null)
    {
        var clipA = Asset(@"C:\media\1.mp4", 1, frameRate: 30m, width: 1080, height: 1920);
        var clipB = Asset(@"C:\media\2.mp4", 2, frameRate: 30m, width: 2160, height: 3840);
        var clips = new List<PlannedClip>
        {
            new(clipA, TimeSpan.Zero, clipA.Info.Duration),
            new(clipB, clipA.Info.Duration, clipB.Info.Duration)
        };
        var plan = new CompositionPlan(clips, clipA.Info.Duration + clipB.Info.Duration, Seed: 0, TimeSpan.Zero);
        var aspect = OutputAspect.Custom(width, height, fitMode);
        var layers = overlay is null ? Array.Empty<OverlayLayer>() : new[] { overlay };
        return new RenderRequest(
            plan,
            @"C:\out\成片.mp4",
            RenderProfile.Balanced,
            aspect,
            layers,
            HasOverlays: overlay is not null);
    }

    private static CompositionPlan SingleClipPlan()
    {
        var asset = Asset(@"C:\media\1.mp4", 1);
        return new CompositionPlan(
            [new PlannedClip(asset, TimeSpan.Zero, asset.Info.Duration)],
            asset.Info.Duration,
            Seed: 42,
            TimeSpan.Zero);
    }

    private static RenderRequest MultiClip(IReadOnlyList<MediaAsset> assets, RenderProfile profile)
    {
        var clips = new List<PlannedClip>();
        var offset = TimeSpan.Zero;
        foreach (var asset in assets)
        {
            clips.Add(new PlannedClip(asset, offset, asset.Info.Duration));
            offset += asset.Info.Duration;
        }

        var plan = new CompositionPlan(clips, offset, Seed: 0, TimeSpan.Zero);
        return new RenderRequest(plan, @"C:\out\成片.mp4", profile, OutputAspect.InheritFirst, []);
    }

    private static MediaAsset Asset(
        string path,
        int index,
        decimal frameRate = 30m,
        int width = 1080,
        int height = 1920) =>
        new(Guid.NewGuid(), path, index,
            new MediaInfo(TimeSpan.FromSeconds(2), width, height, frameRate, "h264", "aac", true, 0));
}
