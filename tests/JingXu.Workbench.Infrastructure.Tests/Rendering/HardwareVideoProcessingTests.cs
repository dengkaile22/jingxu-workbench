using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class HardwareVideoProcessingTests
{
    [Fact]
    public void Cuda_input_explicitly_downloads_after_scaling_and_d3d11_never_uses_unsupported_scaler()
    {
        var request = Request(AspectFitMode.Stretch);
        var cuda = FfmpegCommandCompiler.Compile("ffmpeg", request, "out.mp4", VideoEncoderKind.H264Nvenc,
            new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.Cuda, true));
        var d3d11 = FfmpegCommandCompiler.Compile("ffmpeg", request, "out.mp4", VideoEncoderKind.H264Amf,
            new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.D3D11, false));
        Assert.Contains("cuda=jxgpu:0", cuda.Command.Arguments);
        Assert.Contains("scale_cuda=w=720:h=480:format=nv12:passthrough=0,hwdownload,format=nv12", cuda.TryGetFilterComplex(), StringComparison.Ordinal);
        Assert.Contains("d3d11va=jxgpu", d3d11.Command.Arguments);
        Assert.Contains("hwdownload,format=nv12", d3d11.TryGetFilterComplex(), StringComparison.Ordinal);
        Assert.DoesNotContain("scale_d3d11", d3d11.TryGetFilterComplex(), StringComparison.Ordinal);
        Assert.Equal(0, d3d11.HardwareScaledInputs);
    }

    [Theory]
    [InlineData(VideoProcessingMode.Auto, 0)]
    [InlineData(VideoProcessingMode.Cpu, 0)]
    [InlineData(VideoProcessingMode.Gpu, 1)]
    public void Processing_mode_only_enables_same_size_hardware_decode_when_explicitly_requested(VideoProcessingMode mode, int expectedInputs)
    {
        var request = Request(AspectFitMode.CenterCrop) with { Aspect = OutputAspect.InheritFirst, ProcessingMode = mode };
        var compiled = FfmpegCommandCompiler.Compile("ffmpeg", request, "out.mp4", VideoEncoderKind.H264Qsv,
            new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.Qsv, true));

        Assert.Equal(expectedInputs, compiled.HardwareDecodedInputs);
        Assert.Equal(0, compiled.HardwareScaledInputs);
    }

    [Theory]
    [InlineData(AspectFitMode.CenterCrop, 1)]
    [InlineData(AspectFitMode.Letterbox, 1)]
    [InlineData(AspectFitMode.Stretch, 1)]
    [InlineData(AspectFitMode.BlurBackground, 0)]
    public void Auto_uses_hardware_only_when_the_fit_has_an_actual_gpu_downscale(AspectFitMode fit, int expectedInputs)
    {
        var request = Request(fit) with { ProcessingMode = VideoProcessingMode.Auto };
        var compiled = FfmpegCommandCompiler.Compile("ffmpeg", request, "out.mp4", VideoEncoderKind.H264Qsv,
            new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.Qsv, true));

        Assert.Equal(expectedInputs, compiled.HardwareDecodedInputs);
        Assert.Equal(expectedInputs, compiled.HardwareScaledInputs);
    }

    [Fact]
    public void Auto_keeps_software_decode_when_only_d3d11_decode_is_available()
    {
        var request = Request(AspectFitMode.CenterCrop) with { ProcessingMode = VideoProcessingMode.Auto };
        var compiled = FfmpegCommandCompiler.Compile("ffmpeg", request, "out.mp4", VideoEncoderKind.H264Amf,
            new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.D3D11, false));
        Assert.Equal(0, compiled.HardwareDecodedInputs);
    }

    [Fact]
    public void Same_size_hardware_decode_avoids_unnecessary_gpu_scaling()
    {
        var request = Request(AspectFitMode.CenterCrop) with { Aspect = OutputAspect.InheritFirst };
        var compiled = FfmpegCommandCompiler.Compile("ffmpeg", request, "out.mp4", VideoEncoderKind.H264Qsv,
            new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.Qsv, true));

        Assert.Equal(1, compiled.HardwareDecodedInputs);
        Assert.Equal(0, compiled.HardwareScaledInputs);
        Assert.Contains("hwdownload,format=nv12", compiled.TryGetFilterComplex(), StringComparison.Ordinal);
        Assert.DoesNotContain("scale_qsv", compiled.TryGetFilterComplex(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Probe_timeout_falls_back_to_software_without_leaking_its_temporary_directory()
    {
        var runner = new BlockingProcessingProbeRunner();
        var selector = new HardwareVideoProcessingSelector(runner, TimeSpan.FromMilliseconds(40));
        var plan = await selector.SelectAsync("ffmpeg", VideoProcessingMode.Auto, VideoEncoderKind.H264Qsv, default);

        Assert.Equal(HardwareVideoProcessingKind.Software, plan.Kind);
        Assert.False(Directory.Exists(runner.Directory));
    }

    [Fact]
    public void Qsv_plan_accepts_known_eight_bit_h264_and_rejects_unsafe_inputs()
    {
        var plan = new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.Qsv, CanScale: true);
        var info = new MediaInfo(TimeSpan.FromSeconds(2), 1920, 1080, 30m, "h264", null, false, 0, "yuv420p");

        Assert.True(plan.Supports(info));
        Assert.False(plan.Supports(info with { PixelFormat = null }));
        Assert.False(plan.Supports(info with { PixelFormat = "yuv420p10le" }));
        Assert.False(plan.Supports(info with { PixelFormat = "yuva420p" }));
        Assert.False(plan.Supports(info with { RotationDegrees = 90 }));
        Assert.False(plan.Supports(info with { VideoCodec = "vp9" }));
        Assert.False(plan.Supports(info with { Width = 1919 }));
        Assert.False(plan.Supports(info with { Width = 7680 }));
    }

    [Theory]
    [InlineData(AspectFitMode.CenterCrop, "scale_qsv=w=720:h=540:format=nv12,hwdownload,format=nv12,crop=720:480,")]
    [InlineData(AspectFitMode.Letterbox, "scale_qsv=w=640:h=480:format=nv12,hwdownload,format=nv12,pad=720:480:(ow-iw)/2:(oh-ih)/2:black,")]
    [InlineData(AspectFitMode.Stretch, "scale_qsv=w=720:h=480:format=nv12,hwdownload,format=nv12,")]
    public void Compiler_uses_hardware_scale_then_download_and_preserves_crop_or_padding(AspectFitMode fit, string expected)
    {
        var request = Request(fit);
        var result = FfmpegCommandCompiler.Compile("ffmpeg", request, "output.mp4", VideoEncoderKind.H264Qsv,
            new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.Qsv, CanScale: true));

        Assert.Contains("-hwaccel", result.Command.Arguments);
        Assert.Contains("qsv=jxgpu:hw_any", result.Command.Arguments);
        Assert.Contains(expected, result.TryGetFilterComplex(), StringComparison.Ordinal);
        Assert.Contains("h264_qsv", result.Command.Arguments);
    }

    [Fact]
    public void Compiler_disables_hardware_for_cpu_mode_and_unknown_pixel_format()
    {
        var request = Request(AspectFitMode.Stretch);
        var plan = new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.Qsv, CanScale: true);
        var cpu = FfmpegCommandCompiler.Compile("ffmpeg", request with { ProcessingMode = VideoProcessingMode.Cpu }, "out.mp4", VideoEncoderKind.Libx264, plan);
        Assert.DoesNotContain("-hwaccel", cpu.Command.Arguments);
        var clip = request.Plan.Clips[0];
        var unknown = request with { Plan = request.Plan with { Clips = [clip with { Asset = clip.Asset with { Info = clip.Asset.Info with { PixelFormat = null } } }] } };
        Assert.DoesNotContain("-hwaccel", FfmpegCommandCompiler.Compile("ffmpeg", unknown, "out.mp4", VideoEncoderKind.H264Qsv, plan).Command.Arguments);
    }

    [Fact]
    public async Task Selector_probes_real_encoded_sample_and_caches_the_qsv_result()
    {
        var runner = new ProcessingProbeRunner();
        var selector = new HardwareVideoProcessingSelector(runner);
        var first = await selector.SelectAsync("ffmpeg", VideoProcessingMode.Auto, VideoEncoderKind.H264Qsv, default);
        var second = await selector.SelectAsync("ffmpeg", VideoProcessingMode.Gpu, VideoEncoderKind.H264Qsv, default);

        Assert.Equal(HardwareVideoProcessingKind.Qsv, first.Kind);
        Assert.True(first.CanScale);
        Assert.Equal(first, second);
        Assert.Equal(2, runner.Requests.Count);
        Assert.Contains("libx264", runner.Requests[0].Arguments);
        Assert.Contains("qsv", runner.Requests[1].Arguments);
        Assert.DoesNotContain("hwupload", string.Join(' ', runner.Requests[1].Arguments), StringComparison.Ordinal);
        Assert.EndsWith("sample.mp4", InputOf(runner.Requests[1]), StringComparison.Ordinal);
        Assert.False(Directory.Exists(runner.Requests[0].WorkingDirectory));
    }

    [Fact]
    public async Task Selector_falls_back_to_d3d11_decode_when_vendor_processing_fails_and_reset_reprobes()
    {
        var runner = new ProcessingProbeRunner { FailQsv = true };
        var selector = new HardwareVideoProcessingSelector(runner);
        var result = await selector.SelectAsync("ffmpeg", VideoProcessingMode.Auto, VideoEncoderKind.H264Qsv, default);
        Assert.Equal(HardwareVideoProcessingKind.D3D11, result.Kind);
        Assert.False(result.CanScale);
        Assert.DoesNotContain("scale_d3d11", string.Join(' ', runner.Requests[^1].Arguments), StringComparison.Ordinal);
        selector.ResetProbe("ffmpeg");
        runner.FailQsv = false;
        Assert.Equal(HardwareVideoProcessingKind.Qsv,
            (await selector.SelectAsync("ffmpeg", VideoProcessingMode.Auto, VideoEncoderKind.H264Qsv, default)).Kind);
    }

    [Fact]
    public async Task Cpu_mode_skips_probe_and_cancellation_is_propagated()
    {
        var runner = new ProcessingProbeRunner();
        var selector = new HardwareVideoProcessingSelector(runner);
        Assert.Equal(HardwareVideoProcessingKind.Software,
            (await selector.SelectAsync("ffmpeg", VideoProcessingMode.Cpu, VideoEncoderKind.H264Qsv, default)).Kind);
        using var cts = new CancellationTokenSource();
        cts.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => selector.SelectAsync("ffmpeg", VideoProcessingMode.Auto, VideoEncoderKind.H264Qsv, cts.Token));
        Assert.Empty(runner.Requests);
    }

    private static string InputOf(IProcessRequest request) => request.Arguments[request.Arguments.ToList().IndexOf("-i") + 1];

    internal static RenderRequest Request(AspectFitMode fit)
    {
        var asset = new MediaAsset(Guid.NewGuid(), @"C:\media\input.mp4", 1,
            new MediaInfo(TimeSpan.FromSeconds(2), 1920, 1440, 30m, "h264", null, false, 0, "yuv420p"));
        var plan = new CompositionPlan([new PlannedClip(asset, TimeSpan.Zero, asset.Info.Duration)], asset.Info.Duration, 0, TimeSpan.Zero);
        return new RenderRequest(plan, @"C:\output.mp4", RenderProfile.Balanced,
            OutputAspect.Custom(720, 480, fit), []) { ProcessingMode = VideoProcessingMode.Gpu };
    }
}

internal sealed class ProcessingProbeRunner : IExternalProcessRunner
{
    public List<IProcessRequest> Requests { get; } = [];
    public bool FailQsv { get; set; }
    public Task<IProcessResult> RunAsync(IProcessRequest request, IProgress<string>? progress, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        Requests.Add(request);
        return Task.FromResult<IProcessResult>(new ProcessResult(FailQsv && request.Arguments.Contains("qsv") ? 1 : 0, string.Empty, string.Empty));
    }
}

internal sealed class BlockingProcessingProbeRunner : IExternalProcessRunner
{
    public string? Directory { get; private set; }
    public async Task<IProcessResult> RunAsync(IProcessRequest request, IProgress<string>? progress, CancellationToken cancellationToken)
    {
        Directory = request.WorkingDirectory;
        await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
        throw new InvalidOperationException("探针未在超时后取消");
    }
}
