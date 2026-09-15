using System.Globalization;
using System.Reflection;
using JingXu.Workbench.Application.Rendering;
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
    public void Double_screen_compiler_exposes_external_material_filter_overload()
    {
        var overload = typeof(FfmpegCommandCompiler)
            .GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
            .FirstOrDefault(method =>
                method.Name == "BuildDoubleScreenFilter"
                && method.GetParameters().Any(parameter => parameter.Name == "sourceInputIndex"));

        Assert.NotNull(overload);
    }

    [Fact]
    public void Random_double_screen_adds_looped_auxiliary_input_and_uses_hard_cut_when_disabled()
    {
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            CompilerTestPlans.WithRandomDoubleScreen(featherEnabled: false),
            @"C:\out\temp.mp4");

        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.Contains("-stream_loop", result.Command.Arguments);
        Assert.Contains("i3.mp4", result.Command.Arguments);
        Assert.Equal(4, result.Command.Arguments.Count(argument => argument == "-i"));
        Assert.Contains(result.InputAliases, alias =>
            alias.AbsolutePath.Contains("随机辅助.mp4", StringComparison.Ordinal));
        Assert.Contains("[3:v]fps=30,trim=duration=2", filter, StringComparison.Ordinal);
        Assert.Contains("vstack=inputs=2", filter, StringComparison.Ordinal);
        Assert.DoesNotContain("geq=", filter, StringComparison.Ordinal);
    }

    [Fact]
    public void Random_double_screen_places_auxiliary_material_in_requested_half_with_feather()
    {
        var filter = FfmpegCommandCompiler.BuildDoubleScreenFilter(
            clipIndex: 1,
            sourceInputIndex: 3,
            targetWidth: 1080,
            targetHeight: 1920,
            placement: DoubleScreenPlacement.Top,
            featherEnabled: true,
            featherPixels: 64,
            durationSeconds: "2",
            fpsText: "30");

        Assert.Contains("[3:v]fps=30,trim=duration=2", filter, StringComparison.Ordinal);
        Assert.Contains("[ds1aux_src]scale=1080:1024", filter, StringComparison.Ordinal);
        Assert.Contains("[v1fit]scale=1080:1024", filter, StringComparison.Ordinal);
        Assert.Contains("geq=", filter, StringComparison.Ordinal);
        Assert.Contains("/64))'[ds1top]", filter, StringComparison.Ordinal);
        Assert.Contains("overlay=0:0", filter, StringComparison.Ordinal);
    }

    [Fact]
    public void Chinese_path_is_aliased_without_shell_quotes()
    {
        var result = FfmpegCommandCompiler.Compile(
            @"C:\runtime\ffmpeg.exe",
            CompilerTestPlans.WithInput(@"C:\素材 文件\1.mp4"),
            @"C:\out\.jingxu-tmp\output.mp4");

        Assert.Contains("i0.mp4", result.Command.Arguments);
        Assert.DoesNotContain(result.Command.Arguments, x => x.Contains(@"C:\素材", StringComparison.Ordinal));
        Assert.Contains(result.InputAliases, a => a.RelativePath == "i0.mp4" && a.AbsolutePath.Contains("素材", StringComparison.Ordinal));
        Assert.DoesNotContain(result.Command.Arguments, x => x.Contains("cmd.exe", StringComparison.OrdinalIgnoreCase));
        Assert.Equal("output.mp4", result.Command.Arguments[^1]);
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
        Assert.Contains("不进行解码", result.ProcessingDescription, StringComparison.Ordinal);
        Assert.Empty(result.InputAliases);
        Assert.Equal("temp.mp4", result.Command.Arguments[^1]);
    }

    [Fact]
    public void Transcode_path_uses_filter_complex_script_and_libx264()
    {
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            CompilerTestPlans.TranscodeTwoClip(),
            @"C:\out\temp.mp4");

        Assert.Contains("-filter_complex_script", result.Command.Arguments);
        Assert.Contains(FfmpegCommandCompiler.FilterComplexScriptFileName, result.Command.Arguments);
        Assert.DoesNotContain("-filter_complex", result.Command.Arguments);
        Assert.Contains(FfmpegCommandCompiler.FilterComplexScriptFileName, result.AuxiliaryFiles.Select(x => x.FileName));
        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.Contains("libx264", result.Command.Arguments);
        Assert.Contains("concat=n=2:v=1:a=1", filter, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(VideoEncoderKind.Libx264, "libx264", "-crf", "22")]
    [InlineData(VideoEncoderKind.H264Nvenc, "h264_nvenc", "-cq", "22")]
    [InlineData(VideoEncoderKind.H264Qsv, "h264_qsv", "-global_quality", "22")]
    [InlineData(VideoEncoderKind.H264Amf, "h264_amf", "-qp_i", "22")]
    public void Balanced_profile_compiles_selected_encoder(
        VideoEncoderKind encoder,
        string codec,
        string qualitySwitch,
        string qualityValue)
    {
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            CompilerTestPlans.TranscodeTwoClip(),
            @"C:\out\temp.mp4",
            encoder);

        AssertArgumentPair(result.Command.Arguments, "-c:v", codec);
        AssertArgumentPair(result.Command.Arguments, qualitySwitch, qualityValue);
        AssertArgumentPair(result.Command.Arguments, "-pix_fmt", "yuv420p");
        Assert.DoesNotContain("-hwaccel", result.Command.Arguments);
    }

    [Fact]
    public void Balanced_hardware_encoders_use_expected_vendor_presets()
    {
        var request = CompilerTestPlans.TranscodeTwoClip();
        var nvenc = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\nvenc.mp4",
            VideoEncoderKind.H264Nvenc);
        var qsv = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\qsv.mp4",
            VideoEncoderKind.H264Qsv);
        var amf = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\amf.mp4",
            VideoEncoderKind.H264Amf);

        AssertArgumentPair(nvenc.Command.Arguments, "-preset", "p5");
        AssertArgumentPair(qsv.Command.Arguments, "-preset", "medium");
        AssertArgumentPair(amf.Command.Arguments, "-quality", "balanced");
    }

    [Fact]
    public void Fast_and_high_profiles_keep_vendor_speed_quality_presets()
    {
        var fast = CompilerTestPlans.TranscodeTwoClip() with { Profile = RenderProfile.Fast };
        var high = CompilerTestPlans.TranscodeTwoClip() with { Profile = RenderProfile.High };

        var nvencFast = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", fast, @"C:\out\fast.mp4", VideoEncoderKind.H264Nvenc);
        var nvencHigh = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", high, @"C:\out\high.mp4", VideoEncoderKind.H264Nvenc);

        AssertArgumentPair(nvencFast.Command.Arguments, "-preset", "p2");
        AssertArgumentPair(nvencFast.Command.Arguments, "-cq", "26");
        AssertArgumentPair(nvencHigh.Command.Arguments, "-preset", "p6");
        AssertArgumentPair(nvencHigh.Command.Arguments, "-cq", "18");
        Assert.DoesNotContain("-hwaccel", nvencFast.Command.Arguments);
        Assert.DoesNotContain("-hwaccel", nvencHigh.Command.Arguments);
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

            var filter = result.TryGetFilterComplex();
            Assert.NotNull(filter);
            Assert.Contains("fps=29.97", filter, StringComparison.Ordinal);
            Assert.DoesNotContain("fps=29,97", filter, StringComparison.Ordinal);
        }
        finally
        {
            CultureInfo.CurrentCulture = previous;
        }
    }

    [Fact]
    public void Extremely_long_input_paths_are_aliased_under_command_budget()
    {
        var longPath = @"C:\media\" + new string('x', 40_000) + ".mp4";
        var request = CompilerTestPlans.WithInput(longPath);
        var result = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", request, @"C:\out\temp.mp4");

        Assert.DoesNotContain(result.Command.Arguments, x => x.Contains(new string('x', 100), StringComparison.Ordinal));
        Assert.Contains("i0.mp4", result.Command.Arguments);
        Assert.True(
            result.Command.EstimatedCommandLineLength < RenderPreflight.MaxCommandLineLength,
            $"argv length {result.Command.EstimatedCommandLineLength} should stay under budget after aliasing");
        Assert.True(FfmpegCommandCompiler.ValidateCommandBudget(result.Command).IsSuccess);
        Assert.Single(result.InputAliases);
        Assert.Contains("x", result.InputAliases[0].AbsolutePath, StringComparison.Ordinal);
    }

    [Fact]
    public void Many_deep_path_inputs_stay_under_command_budget_via_aliases()
    {
        var deep = @"C:\Users\Administrator\OneDrive\Desktop\" + new string('深', 80) + @"\归档";
        var paths = Enumerable.Range(1, 40)
            .Select(i => Path.Combine(deep, $"素材_{i:000}_超长文件名商品展示视频片段.mp4"))
            .ToArray();
        var request = CompilerTestPlans.ManyInputs(paths);
        var result = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", request, @"C:\out\temp.mp4");

        Assert.Equal(40, result.InputAliases.Count);
        Assert.All(result.Command.Arguments.Where((_, i) => i > 0 && result.Command.Arguments[i - 1] == "-i"),
            arg => Assert.True(arg.StartsWith('i'), arg));
        Assert.DoesNotContain(result.Command.Arguments, a => a.Contains(deep, StringComparison.OrdinalIgnoreCase));
        Assert.True(
            result.Command.EstimatedCommandLineLength < RenderPreflight.MaxCommandLineLength,
            $"argv length {result.Command.EstimatedCommandLineLength}");
        Assert.True(FfmpegCommandCompiler.ValidateCommandBudget(result.Command).IsSuccess);
    }

    [Fact]
    public void Command_budget_still_rejects_extreme_argv_after_aliasing()
    {
        // 短别名后仍可能因输入数量过多撑爆 argv；错误文案保持中文。
        var arguments = new List<string> { "-y" };
        for (var index = 0; index < 5_000; index++)
        {
            arguments.Add("-i");
            arguments.Add($"i{index}.mp4");
        }

        arguments.Add("-filter_complex_script");
        arguments.Add(FfmpegCommandCompiler.FilterComplexScriptFileName);
        arguments.Add("output.mp4");

        var command = new FfmpegCommand(@"C:\ffmpeg.exe", arguments);
        var budget = FfmpegCommandCompiler.ValidateCommandBudget(command);
        Assert.False(budget.IsSuccess);
        Assert.Contains("命令过长", budget.Error, StringComparison.Ordinal);
        Assert.Contains("staging 相对路径", budget.Error, StringComparison.Ordinal);
    }

    [Fact]
    public void Rich_six_clip_job_stays_under_command_budget_via_filter_script()
    {
        var request = CompilerTestPlans.RichSixClipJob();
        var result = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", request, @"C:\out\temp.mp4");
        var filter = result.TryGetFilterComplex();

        Assert.NotNull(filter);
        Assert.True(filter.Length > 2_000, $"expected a large filter graph, got {filter.Length}");
        Assert.True(
            result.Command.EstimatedCommandLineLength < RenderPreflight.MaxCommandLineLength,
            $"argv length {result.Command.EstimatedCommandLineLength} should stay under {RenderPreflight.MaxCommandLineLength} when filter is scripted");
        Assert.True(FfmpegCommandCompiler.ValidateCommandBudget(result.Command).IsSuccess);
        Assert.Contains("-filter_complex_script", result.Command.Arguments);
        Assert.DoesNotContain(result.Command.Arguments, a => a.Contains("炳恒混剪素材库", StringComparison.Ordinal));
        Assert.True(result.InputAliases.Count >= 6);
    }

    [Fact]
    public void Effects_and_bgm_compile_into_filter_graph()
    {
        var request = CompilerTestPlans.WithEffectsAndBgm();
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.Contains("eq=", filter, StringComparison.Ordinal);
        Assert.Contains("aloop", filter, StringComparison.Ordinal);
        Assert.Contains("amix=duration=first", filter, StringComparison.Ordinal);
        Assert.Contains(result.InputAliases, a => a.AbsolutePath.Contains("bgm.mp3", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(result.Command.Arguments, a => a.StartsWith('i') && a.EndsWith(".mp3", StringComparison.Ordinal));
    }

    [Fact]
    public void Crop_effect_restores_the_requested_output_canvas()
    {
        var request = CompilerTestPlans.WithEffectsAndBgm() with
        {
            Aspect = OutputAspect.Custom(1080, 1440),
            OutputVideoSettings = new(OutputResolutionPreset.P1080),
            Effect = new MaterializedEffect(
                MirrorMode.None,
                CropPercent: 0.1,
                Brightness: 0,
                Contrast: 1,
                Saturation: 1,
                DenoiseStrength: 0,
                ClearMetadata: false)
        };

        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.Contains(
            "crop=iw*0.999:ih*0.999:(iw-ow)/2:(ih-oh)/2,scale=1080:1440,setsar=1[vfx]",
            filter,
            StringComparison.Ordinal);
    }

    [Fact]
    public void Sticker_compiles_overlay_with_extra_input()
    {
        var request = CompilerTestPlans.WithSticker();
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.Contains(result.InputAliases, a => a.AbsolutePath.Contains("贴纸.png", StringComparison.Ordinal));
        Assert.Contains("-loop", result.Command.Arguments);
        Assert.Contains("overlay=", filter, StringComparison.Ordinal);
        Assert.Contains("shortest=1", filter, StringComparison.Ordinal);
        Assert.Contains("[1:v]", filter, StringComparison.Ordinal);
    }

    [Fact]
    public void Sticker_is_composited_after_mask_and_mapped_as_topmost_video()
    {
        var mask = OverlayLayer.CreateImportedMaskPreset(
            @"C:\蒙版.mp4",
            TimeSpan.FromSeconds(3));
        var request = CompilerTestPlans.WithSticker() with
        {
            HasOverlays = true,
            OverlayLayers = [mask]
        };

        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.Contains("[vbase][ovenvelope0]overlay=", filter, StringComparison.Ordinal);
        Assert.Contains("[vov0][vstkalpha]overlay=", filter, StringComparison.Ordinal);

        var arguments = result.Command.Arguments.ToList();
        Assert.Equal("[vstk]", arguments[arguments.IndexOf("-map") + 1]);
        Assert.True(
            filter.IndexOf("[vbase][ovenvelope0]overlay=", StringComparison.Ordinal)
            < filter.IndexOf("[vov0][vstkalpha]overlay=", StringComparison.Ordinal));
    }

    [Fact]
    public void Animated_sticker_uses_stream_loop_to_cover_full_duration()
    {
        var sticker = ImageSticker.Create(
            @"C:\动画.gif",
            x: 0.1,
            y: 0.1,
            width: 0.2,
            height: 0.2).Value!;
        var request = CompilerTestPlans.WithSticker() with { Stickers = [sticker] };
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        Assert.Contains("-stream_loop", result.Command.Arguments);
        Assert.Contains("i1.gif", result.Command.Arguments);
        Assert.Contains(result.InputAliases, a => a.AbsolutePath.Contains("动画.gif", StringComparison.Ordinal));
        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.Contains("shortest=1", filter, StringComparison.Ordinal);
    }

    [Fact]
    public void Metadata_clearing_does_not_change_timeline_duration()
    {
        var request = CompilerTestPlans.WithMetadataClearing();
        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.Contains("-map_metadata", result.Command.Arguments);
        Assert.Contains("-1", result.Command.Arguments);
        Assert.DoesNotContain("]setpts=", filter, StringComparison.Ordinal);
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

        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
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

        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.Contains("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920", filter, StringComparison.Ordinal);
        Assert.Contains("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920", filter, StringComparison.Ordinal);
        Assert.Contains("overlay=", filter, StringComparison.Ordinal);
    }

    [Fact]
    public void Double_screen_uses_midline_alpha_blend_instead_of_hard_vstack()
    {
        var filter = FfmpegCommandCompiler.BuildDoubleScreenFilter(1, targetWidth: 1080, targetHeight: 1920);

        Assert.Contains("[v1fit]split=2", filter, StringComparison.Ordinal);
        Assert.Contains("format=rgba", filter, StringComparison.Ordinal);
        Assert.Contains("geq=", filter, StringComparison.Ordinal);
        Assert.Contains("overlay=0:0", filter, StringComparison.Ordinal);
        Assert.Contains("format=yuv420p[v1]", filter, StringComparison.Ordinal);
        Assert.DoesNotContain("vstack=inputs=2", filter, StringComparison.Ordinal);

        // 奇数高度：上 960、下 961；羽化后仍输出原画布高度。
        var odd = FfmpegCommandCompiler.BuildDoubleScreenFilter(0, 1080, 1921);
        Assert.Contains("pad=1080:1921:", odd, StringComparison.Ordinal);
        Assert.Contains("format=yuv420p[v0]", odd, StringComparison.Ordinal);
    }

    [Fact]
    public void Double_screen_applies_from_selected_final_sequence_clip()
    {
        var request = CompilerTestPlans.WithDoubleScreen(startClipIndex: 2);
        var result = FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", request, @"C:\out\temp.mp4");
        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);

        Assert.DoesNotContain("[v0fit]split=2", filter, StringComparison.Ordinal);
        Assert.Contains("[v1fit]split=2", filter, StringComparison.Ordinal);
        Assert.Contains("overlay=0:0", filter, StringComparison.Ordinal);
        Assert.DoesNotContain("vstack=inputs=2", filter, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(2, 2, 0)]
    [InlineData(960, 960, 48)]
    [InlineData(100, 100, 32)]
    public void Double_screen_blend_pixels_respect_half_height(int top, int bottom, int expected)
    {
        Assert.Equal(expected, FfmpegCommandCompiler.ResolveDoubleScreenBlendPixels(top, bottom));
    }

    private static void AssertArgumentPair(
        IReadOnlyList<string> arguments,
        string option,
        string expectedValue)
    {
        var index = arguments.ToList().IndexOf(option);
        Assert.True(index >= 0, $"Missing FFmpeg option {option}.");
        Assert.True(index + 1 < arguments.Count, $"FFmpeg option {option} has no value.");
        Assert.Equal(expectedValue, arguments[index + 1]);
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
            Stickers: [sticker]);
    }

    public static RenderRequest WithDoubleScreen(int startClipIndex)
    {
        var assets = new[]
        {
            Asset(@"C:\media\1.mp4", 1),
            Asset(@"C:\media\2.mp4", 2),
            Asset(@"C:\media\3.mp4", 3)
        };
        var clips = new List<PlannedClip>();
        var offset = TimeSpan.Zero;
        foreach (var asset in assets)
        {
            clips.Add(new PlannedClip(asset, offset, asset.Info.Duration));
            offset += asset.Info.Duration;
        }

        var plan = new CompositionPlan(clips, offset, Seed: 42, TimeSpan.Zero);
        return new RenderRequest(
            plan,
            @"C:\out\成片.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            [],
            HasEffects: true,
            DoubleScreen: new DoubleScreenEffectPlan(StartClipIndex: startClipIndex));
    }

    public static RenderRequest WithRandomDoubleScreen(bool featherEnabled)
    {
        var assets = new[]
        {
            Asset(@"C:\media\1.mp4", 1),
            Asset(@"C:\media\2.mp4", 2),
            Asset(@"C:\media\3.mp4", 3)
        };
        var clips = assets
            .Select((asset, index) => new PlannedClip(
                asset,
                TimeSpan.FromSeconds(index * 2),
                asset.Info.Duration))
            .ToArray();
        var plan = new CompositionPlan(clips, TimeSpan.FromSeconds(6), Seed: 42, TimeSpan.Zero);
        var auxiliary = Asset(@"C:\媒体库\随机辅助.mp4", 99);
        var doubleScreen = new DoubleScreenEffectPlan(
            StartClipIndex: 2,
            SourceMode: DoubleScreenSourceMode.RandomCurrentFolder,
            PlacementMode: DoubleScreenPlacementMode.Bottom,
            FeatherEnabled: featherEnabled,
            FeatherPixels: 64,
            ClipSelections:
            [
                new DoubleScreenClipSelection(1, auxiliary, DoubleScreenPlacement.Bottom),
                new DoubleScreenClipSelection(2, auxiliary, DoubleScreenPlacement.Bottom)
            ]);

        return new RenderRequest(
            plan,
            @"C:\out\成片.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            [],
            HasEffects: true,
            DoubleScreen: doubleScreen);
    }

    /// <summary>
    /// 复现用户场景：深路径 + 6 段素材 + 蒙版/贴纸/特效/双屏/增益，
    /// 滤镜图本身很长，但 argv 应通过脚本外置保持在预算内。
    /// </summary>
    public static RenderRequest RichSixClipJob()
    {
        const string deep =
            @"C:\Users\Administrator\OneDrive\Desktop\炳恒混剪素材库\客户项目\商品短视频\2026年07月批次\竖屏3x4成片\原始素材归档";
        var clips = new List<PlannedClip>();
        var offset = TimeSpan.Zero;
        for (var i = 1; i <= 6; i++)
        {
            var path = Path.Combine(deep, $"素材_{i:00}_竖屏商品展示视频.mp4");
            var info = new MediaInfo(TimeSpan.FromSeconds(8), 1080, 1440, 30m, "h264", "aac", true, 0);
            clips.Add(new PlannedClip(new MediaAsset(Guid.NewGuid(), path, i, info), offset, info.Duration));
            offset += info.Duration;
        }

        var plan = new CompositionPlan(clips, offset, Seed: 1, TimeSpan.Zero);
        var layers = new List<OverlayLayer>
        {
            OverlayLayer.CreateSelfGhostPreset(TimeSpan.FromSeconds(3)),
            OverlayLayer.CreateScreenshotPreset(Path.Combine(deep, "蒙版层_0_顶部覆盖素材.mp4"), TimeSpan.FromSeconds(3)) with
            {
                TopFade = 1,
                Feather = 0.4,
                Scale = 1.15
            }
        };
        var stickers = new List<ImageSticker>();
        for (var i = 0; i < 3; i++)
        {
            stickers.Add(ImageSticker.Create(
                Path.Combine(deep, $"贴纸_{i}_logo.png"),
                0.1 + i * 0.05,
                0.2,
                0.2,
                0.15).Value!);
        }

        var boost = MainMaterialBoostPlan.Create(
            enableVolume: true,
            volumeMode: MainMaterialBoostMode.Fixed,
            volumeMinPercent: 105,
            volumeMaxPercent: 105,
            enableScale: true,
            scaleMode: MainMaterialBoostMode.Fixed,
            scaleMinPercent: 108,
            scaleMaxPercent: 108).Value!;

        return new RenderRequest(
            plan,
            Path.Combine(deep, "分镜输出", "成片_001.mp4"),
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            layers,
            HasEffects: true,
            HasOverlays: true,
            HasBgm: true,
            HasMainMaterialBoost: true,
            Effect: EffectTemplates.StandardVariation().Materialize(1),
            Bgm: BgmMixPlan.Create(Path.Combine(deep, "bgm_track.mp3")).Value!,
            Stickers: stickers,
            MainMaterialBoost: boost.Materialize(1, 6),
            DoubleScreen: new DoubleScreenEffectPlan(StartClipIndex: 2));
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

    public static RenderRequest ManyInputs(IReadOnlyList<string> paths, RenderProfile? profile = null)
    {
        ArgumentNullException.ThrowIfNull(paths);
        var assets = paths.Select((path, index) => Asset(path, index + 1)).ToArray();
        return MultiClip(assets, profile ?? RenderProfile.Balanced);
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
