using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;
using JingXu.Workbench.Infrastructure.Runtime;
using JingXu.Workbench.Infrastructure.Tests.Runtime;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class HardwareVideoProcessingExecutorTests
{
    [Fact]
    public async Task Auto_same_size_skips_device_probe_and_reports_cpu_decode_with_gpu_encoding()
    {
        using var directory = new TemporaryDirectory();
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var request = KnownRequest(directory) with { ProcessingMode = VideoProcessingMode.Auto };
        var runner = new SequencedRenderRunner(new ProcessResult(0, "progress=end\n", string.Empty));
        var selector = new FixedProcessingSelector();
        var executor = new FfmpegRenderExecutor(runner, new KnownFormatProbe(),
            new RuntimeResolver(layout.AppRoot, layout.PathLookup), availableDiskBytes: _ => long.MaxValue,
            encoderSelector: FixedEncoderSelector.Qsv(), processingSelector: selector);
        var result = await executor.ExecuteAsync(RenderJob.CreateQueued(request), null, default);

        Assert.True(result.IsSuccess, result.FailureInfo?.Message);
        Assert.Equal(0, selector.Calls);
        Assert.DoesNotContain("-hwaccel", Assert.Single(runner.Requests).Arguments);
        Assert.Contains("CPU 解码与缩放", result.Notice, StringComparison.Ordinal);
        Assert.Contains("QSV", result.Notice, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Legacy_snapshot_gets_fresh_pixel_format_for_this_attempt_without_mutating_the_snapshot()
    {
        using var directory = new TemporaryDirectory();
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var request = TestJobs.RequestFor([directory.File("clip.mp4", "clip")], directory.Root) with { ProcessingMode = VideoProcessingMode.Gpu };
        var runner = new SequencedRenderRunner(new ProcessResult(0, "progress=end\n", string.Empty));
        var executor = new FfmpegRenderExecutor(runner, new KnownFormatProbe(),
            new RuntimeResolver(layout.AppRoot, layout.PathLookup), availableDiskBytes: _ => long.MaxValue,
            encoderSelector: FixedEncoderSelector.Qsv(), processingSelector: new FixedProcessingSelector());
        var result = await executor.ExecuteAsync(RenderJob.CreateQueued(request), null, default);

        Assert.True(result.IsSuccess, result.FailureInfo?.Message);
        Assert.Contains("-hwaccel", Assert.Single(runner.Requests).Arguments);
        Assert.Null(request.Plan.Clips[0].Asset.Info.PixelFormat);
    }

    [Theory]
    [InlineData("Device creation failed: -1313558101.")]
    [InlineData("[h264_qsv @ 0] Error initializing the MFX video decoder: unsupported (-3)")]
    [InlineData("[h264_qsv @ 0] Error during QSV decoding.")]
    [InlineData("[h264_qsv @ 0] Error initializing a QSV frame pool")]
    [InlineData("[h264_qsv @ 0] Error querying IO surface: unsupported (-3)")]
    [InlineData("[h264 @ 0] Failed to begin frame: 0x8007000e")]
    [InlineData("[h264 @ 0] Failed to execute: 0x80004005")]
    [InlineData("[h264 @ 0] Failed to end frame: 0x80004005")]
    [InlineData("Reconfiguring filter graph because hwaccel changed")]
    [InlineData("[Parsed_scale_qsv_0 @ 123] Failed to create processing session")]
    [InlineData("[Parsed_hwdownload_1 @ 123] Failed to download frame: -5")]
    public async Task Hardware_processing_failure_retries_software_decode_and_keeps_gpu_encoder(string error)
    {
        using var directory = new TemporaryDirectory();
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var request = KnownRequest(directory);
        var runner = new SequencedRenderRunner(new ProcessResult(1, string.Empty, error), new ProcessResult(0, "progress=end\n", string.Empty));
        var encoder = new RecordingEncoderSelector(new(VideoEncoderKind.H264Qsv, "Intel QSV", "QSV 完成"));
        var executor = new FfmpegRenderExecutor(runner, new FixedProbe(TimeSpan.FromSeconds(2)),
            new RuntimeResolver(layout.AppRoot, layout.PathLookup), availableDiskBytes: _ => long.MaxValue,
            encoderSelector: encoder, processingSelector: new FixedProcessingSelector());

        var result = await executor.ExecuteAsync(RenderJob.CreateQueued(request), null, default);

        Assert.True(result.IsSuccess, result.FailureInfo?.Message);
        Assert.Equal(2, runner.Requests.Count);
        Assert.Contains("-hwaccel", runner.Requests[0].Arguments);
        Assert.DoesNotContain("-hwaccel", runner.Requests[1].Arguments);
        Assert.All(runner.Requests, item => Assert.Contains("h264_qsv", item.Arguments));
        Assert.Empty(encoder.RememberedFailures);
        Assert.Contains("CPU 解码", result.Notice, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Decoder_then_encoder_failure_falls_back_in_two_distinct_steps()
    {
        using var directory = new TemporaryDirectory();
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new SequencedRenderRunner(
            new ProcessResult(1, string.Empty, "Device creation failed: -1."),
            new ProcessResult(1, string.Empty, "[h264_qsv] Error initializing an internal MFX session"),
            new ProcessResult(0, "progress=end\n", string.Empty));
        var encoder = new RecordingEncoderSelector(new(VideoEncoderKind.H264Qsv, "QSV", "QSV 完成"));
        var executor = new FfmpegRenderExecutor(runner, new FixedProbe(TimeSpan.FromSeconds(2)),
            new RuntimeResolver(layout.AppRoot, layout.PathLookup), availableDiskBytes: _ => long.MaxValue,
            encoderSelector: encoder, processingSelector: new FixedProcessingSelector());

        var result = await executor.ExecuteAsync(RenderJob.CreateQueued(KnownRequest(directory)), null, default);

        Assert.True(result.IsSuccess, result.FailureInfo?.Message);
        Assert.Equal(3, runner.Requests.Count);
        Assert.Contains("-hwaccel", runner.Requests[0].Arguments);
        Assert.Contains("h264_qsv", runner.Requests[1].Arguments);
        Assert.DoesNotContain("-hwaccel", runner.Requests[1].Arguments);
        Assert.Contains("libx264", runner.Requests[2].Arguments);
        Assert.Equal([VideoEncoderKind.H264Qsv], encoder.RememberedFailures);
    }

    [Fact]
    public async Task Generic_filter_error_with_hardware_input_is_not_retried()
    {
        using var directory = new TemporaryDirectory();
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new SequencedRenderRunner(new ProcessResult(1, string.Empty,
            "[h264_qsv @ 0] encoder ready\n[Parsed_overlay_0] Error reinitializing filters!"));
        var executor = new FfmpegRenderExecutor(runner, new FixedProbe(TimeSpan.FromSeconds(2)),
            new RuntimeResolver(layout.AppRoot, layout.PathLookup), availableDiskBytes: _ => long.MaxValue,
            encoderSelector: FixedEncoderSelector.Qsv(), processingSelector: new FixedProcessingSelector());

        var result = await executor.ExecuteAsync(RenderJob.CreateQueued(KnownRequest(directory)), null, default);

        Assert.False(result.IsSuccess);
        Assert.Contains("-hwaccel", Assert.Single(runner.Requests).Arguments);
    }

    private static RenderRequest KnownRequest(TemporaryDirectory directory)
    {
        var request = TestJobs.RequestFor([directory.File("clip.mp4", "clip")], directory.Root);
        var clip = request.Plan.Clips[0];
        return request with
        {
            ProcessingMode = VideoProcessingMode.Gpu,
            Plan = request.Plan with { Clips = [clip with { Asset = clip.Asset with { Info = clip.Asset.Info with { PixelFormat = "yuv420p" } } }] }
        };
    }
}

internal sealed class FixedProcessingSelector : IVideoProcessingSelector
{
    public int Calls { get; private set; }
    public Task<HardwareVideoProcessingPlan> SelectAsync(string ffmpegExecutable, VideoProcessingMode mode, VideoEncoderKind encoder, CancellationToken cancellationToken)
    {
        Calls++;
        return Task.FromResult(new HardwareVideoProcessingPlan(HardwareVideoProcessingKind.Qsv, true));
    }
    public void ResetProbe(string ffmpegExecutable) { }
}

internal sealed class KnownFormatProbe : IMediaProbe
{
    public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken)
        => Task.FromResult(new MediaInfo(TimeSpan.FromSeconds(2), 1080, 1920, 30m, "h264", "aac", true, 0, "yuv420p"));
}
