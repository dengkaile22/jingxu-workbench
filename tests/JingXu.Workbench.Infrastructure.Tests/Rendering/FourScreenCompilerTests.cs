using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class FourScreenCompilerTests
{
    [Fact]
    public void Repeated_auxiliary_cells_share_the_decoded_label_without_eager_nullsink_branches()
    {
        var filter = Compile(Request(FourScreenSourceMode.RandomCurrentFolder, 2)).TryGetFilterComplex()!;

        Assert.DoesNotContain("nullsink", filter, StringComparison.Ordinal);
        Assert.Single(filter.Split(';'), chain => chain.Contains("split=3", StringComparison.Ordinal));
    }

    [Fact]
    public void Looped_auxiliary_input_keeps_software_decode_when_main_uses_qsv()
    {
        var request = Request(FourScreenSourceMode.RandomCurrentFolder, 2) with { ProcessingMode = VideoProcessingMode.Gpu };
        var compiled = FfmpegCommandCompiler.Compile("ffmpeg", request, "out.mp4", VideoEncoderKind.H264Qsv,
            new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.Qsv, true));

        Assert.Equal(1, compiled.HardwareDecodedInputs);
        Assert.DoesNotContain("[1:v]hwdownload", compiled.TryGetFilterComplex(), StringComparison.Ordinal);
        var inputOptions = new List<string>();
        foreach (var argument in compiled.Command.Arguments)
        {
            inputOptions.Add(argument);
            if (argument != "-i") { continue; }
            if (inputOptions.Contains("-stream_loop")) { Assert.DoesNotContain("-hwaccel", inputOptions); }
            inputOptions.Clear();
        }
    }

    [Fact]
    public void Shared_auxiliary_file_is_opened_once_per_clip_and_decoder_threads_are_bounded()
    {
        var original = Request(FourScreenSourceMode.RandomCurrentFolder, 2);
        var plan = original.Plan with
        {
            Clips = [original.Plan.Clips[0], original.Plan.Clips[0] with { Start = TimeSpan.FromSeconds(2) }],
            Duration = TimeSpan.FromSeconds(4)
        };
        var assets = original.FourScreen!.ClipSelections[0].Cells.Select(cell => cell.SourceAsset).DistinctBy(asset => asset.Path).ToArray();
        var four = new FourScreenEffectPlan(1, FourScreenSourceMode.RandomCurrentFolder).MaterializeForPlan(plan, assets, 0).Value!;
        var compiled = Compile(original with { Plan = plan, FourScreen = four });

        Assert.Equal(4, compiled.Command.Arguments.Count(argument => argument == "-i"));
        Assert.Equal(4, compiled.Command.Arguments.TakeWhile(argument => argument != "-filter_complex_script").Count(argument => argument == "-threads"));
        Assert.Equal(2, compiled.Command.Arguments.Count(argument => argument == "-stream_loop"));
        Assert.DoesNotContain("split=6", compiled.TryGetFilterComplex(), StringComparison.Ordinal);
    }

    [Fact]
    public void Current_clip_is_decoded_once_and_split_into_four_cells()
    {
        var result = Compile(Request(FourScreenSourceMode.CurrentClip, 1));

        Assert.Single(result.Command.Arguments, argument => argument == "-i");
        Assert.Contains("split=4", result.TryGetFilterComplex(), StringComparison.Ordinal);
        Assert.Contains("xstack=inputs=4", result.TryGetFilterComplex(), StringComparison.Ordinal);
    }

    [Fact]
    public void Random_sources_are_looped_deduplicated_and_auxiliary_audio_is_unused()
    {
        var request = Request(FourScreenSourceMode.RandomCurrentFolder, 4);
        var result = Compile(request);
        var filter = result.TryGetFilterComplex()!;

        Assert.Equal(4, result.Command.Arguments.Count(argument => argument == "-i"));
        Assert.Equal(3, result.Command.Arguments.Count(argument => argument == "-stream_loop"));
        Assert.Contains("[0:a]", filter, StringComparison.Ordinal);
        for (var input = 1; input <= 3; input++)
        {
            Assert.Contains($"[{input}:v]", filter, StringComparison.Ordinal);
            Assert.DoesNotContain($"[{input}:a]", filter, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void Repeated_auxiliary_source_is_one_input_split_to_three_consumers()
    {
        var result = Compile(Request(FourScreenSourceMode.RandomCurrentFolder, 2));

        Assert.Equal(2, result.Command.Arguments.Count(argument => argument == "-i"));
        Assert.Contains("split=3", result.TryGetFilterComplex(), StringComparison.Ordinal);
    }

    [Fact]
    public void Feathering_blends_both_axes_and_keeps_target_canvas()
    {
        var result = Compile(Request(FourScreenSourceMode.RandomCurrentFolder, 4, feather: true));
        var filter = result.TryGetFilterComplex()!;

        Assert.Contains("geq=", filter, StringComparison.Ordinal);
        Assert.Contains("clip((", filter, StringComparison.Ordinal);
        Assert.Contains("-X)", filter, StringComparison.Ordinal);
        Assert.Contains("-Y)", filter, StringComparison.Ordinal);
        Assert.Contains("pad=320:240", filter, StringComparison.Ordinal);
    }

    [Fact]
    public void Feathering_calculates_each_gray_mask_once_and_reuses_it_until_the_video_ends()
    {
        var filter = Compile(Request(FourScreenSourceMode.CurrentClip, 1, feather: true)).TryGetFilterComplex()!;
        var maskChains = filter.Split(';').Where(chain => chain.Contains("geq=", StringComparison.Ordinal)).ToArray();

        Assert.NotEmpty(maskChains);
        Assert.DoesNotContain("geq=r=", filter, StringComparison.Ordinal);
        Assert.All(maskChains, chain =>
        {
            Assert.Contains("format=gray", chain, StringComparison.Ordinal);
            var trimIndex = chain.IndexOf("trim=end_frame=1", StringComparison.Ordinal);
            Assert.True(trimIndex >= 0 && trimIndex < chain.IndexOf("geq=", StringComparison.Ordinal), chain);
        });
        Assert.Equal(3, filter.Split("alphamerge=eof_action=repeat:repeatlast=1", StringSplitOptions.None).Length - 1);
    }

    [Theory]
    [InlineData(FourScreenSourceMode.CurrentClip, 1)]
    [InlineData(FourScreenSourceMode.RandomCurrentFolder, 2)]
    [InlineData(FourScreenSourceMode.RandomCurrentFolder, 4)]
    public void Equal_sized_cells_resize_each_source_only_once(FourScreenSourceMode mode, int sourceCount)
    {
        var filter = Compile(Request(mode, sourceCount, feather: true)).TryGetFilterComplex()!;

        Assert.Equal(sourceCount, filter.Split("format=rgba,scale=", StringSplitOptions.None).Length - 1);
    }

    [Fact]
    public void Compiler_rejects_unmaterialized_four_screen_and_conflicting_layouts()
    {
        var request = Request(FourScreenSourceMode.CurrentClip, 1);
        Assert.Throws<InvalidOperationException>(() => Compile(request with { FourScreen = new FourScreenEffectPlan(1) }));
        Assert.Throws<InvalidOperationException>(() => Compile(request with { DoubleScreen = new DoubleScreenEffectPlan(1) }));
    }

    [Fact]
    public void Bgm_input_follows_all_four_screen_auxiliary_inputs()
    {
        var request = Request(FourScreenSourceMode.RandomCurrentFolder, 4) with
        {
            HasBgm = true,
            Bgm = new BgmMixPlan(@"C:\素材\bgm.mp3", 1, 0.2, 0)
        };
        var compiled = Compile(request);
        Assert.Equal(5, compiled.Command.Arguments.Count(argument => argument == "-i"));
        Assert.Contains("[4:a]", compiled.TryGetFilterComplex(), StringComparison.Ordinal);
    }

    [Fact]
    public void Four_screen_starts_at_selected_clip_and_preserves_odd_cell_dimensions()
    {
        var original = Request(FourScreenSourceMode.CurrentClip, 1);
        var plan = original.Plan with
        {
            Clips = [original.Plan.Clips[0], original.Plan.Clips[0] with { Start = TimeSpan.FromSeconds(2) }],
            Duration = TimeSpan.FromSeconds(4)
        };
        var request = original with
        {
            Plan = plan,
            Aspect = OutputAspect.Custom(318, 238),
            FourScreen = new FourScreenEffectPlan(2, FeatherEnabled: false).MaterializeForPlan(plan, [], 0).Value!
        };
        var filter = Compile(request).TryGetFilterComplex();
        Assert.DoesNotContain("fs0", filter, StringComparison.Ordinal);
        Assert.Contains("layout=0_0|159_0|0_119|159_119", filter, StringComparison.Ordinal);
    }

    private static FfmpegCompileResult Compile(RenderRequest request) =>
        FfmpegCommandCompiler.Compile(@"C:\ffmpeg.exe", request, @"C:\out\output.mp4");

    private static RenderRequest Request(FourScreenSourceMode mode, int sourceCount, bool feather = false)
    {
        var assets = Enumerable.Range(1, sourceCount).Select(index => new MediaAsset(
            Guid.NewGuid(), $@"C:\素材\{index}.mp4", index,
            new MediaInfo(TimeSpan.FromSeconds(index == 1 ? 2 : 1), 320, 240, 30m, "h264", "aac", true, 0, "yuv420p"))).ToArray();
        var plan = new CompositionPlan([new PlannedClip(assets[0], TimeSpan.Zero, TimeSpan.FromSeconds(2))],
            TimeSpan.FromSeconds(2), 42, TimeSpan.Zero);
        var effect = new FourScreenEffectPlan(1, mode, feather, 256).MaterializeForPlan(plan, assets, 0).Value!;
        return new RenderRequest(plan, @"C:\out\output.mp4", RenderProfile.Balanced,
            OutputAspect.InheritFirst, [], HasEffects: true, FourScreen: effect);
    }
}
