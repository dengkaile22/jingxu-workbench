using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class HardwareVideoEncoderSelectorTests
{
    [Fact]
    public async Task Auto_prefers_nvenc_then_qsv_then_amf()
    {
        var runner = new ProbeRunner(new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["h264_nvenc"] = 0,
            ["h264_qsv"] = 0,
            ["h264_amf"] = 0
        });
        var selector = new HardwareVideoEncoderSelector(runner);

        var result = await selector.SelectAsync(
            @"C:\ffmpeg.exe",
            VideoProcessingMode.Auto,
            default);

        Assert.Equal(VideoEncoderKind.H264Nvenc, result.Kind);
        Assert.Equal(1, runner.TotalCalls);
        AssertProbeUsesSafeFrames(Assert.Single(runner.Requests));
    }

    [Fact]
    public async Task Auto_without_available_encoder_selects_cpu_without_fallback_flag()
    {
        var runner = ProbeRunner.AllFailing();
        var selector = new HardwareVideoEncoderSelector(runner);

        var result = await selector.SelectAsync(
            @"C:\ffmpeg.exe",
            VideoProcessingMode.Auto,
            default);

        Assert.Equal(VideoEncoderKind.Libx264, result.Kind);
        Assert.False(result.IsFallback);
        Assert.Contains("自动使用 CPU", result.Notice, StringComparison.Ordinal);
        Assert.Equal(3, runner.TotalCalls);
    }

    [Fact]
    public async Task Gpu_without_available_encoder_returns_cpu_fallback_notice()
    {
        var runner = ProbeRunner.AllFailing();
        var selector = new HardwareVideoEncoderSelector(runner);

        var result = await selector.SelectAsync(
            @"C:\ffmpeg.exe",
            VideoProcessingMode.Gpu,
            default);

        Assert.Equal(VideoEncoderKind.Libx264, result.Kind);
        Assert.True(result.IsFallback);
        Assert.Contains("已改用 CPU", result.Notice, StringComparison.Ordinal);
        Assert.Equal(3, runner.TotalCalls);
    }

    [Fact]
    public async Task Probe_results_are_cached_by_normalized_ffmpeg_path()
    {
        var runner = ProbeRunner.OnlyQsv();
        var selector = new HardwareVideoEncoderSelector(runner);

        await selector.SelectAsync(@"C:\tools\ffmpeg.exe", VideoProcessingMode.Auto, default);
        await selector.SelectAsync(@"c:\tools\FFMPEG.exe", VideoProcessingMode.Gpu, default);

        Assert.Equal(2, runner.TotalCalls);
    }

    [Fact]
    public async Task Remembered_hardware_failure_skips_that_encoder_on_next_select()
    {
        var runner = new ProbeRunner(new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["h264_nvenc"] = 0,
            ["h264_qsv"] = 0,
            ["h264_amf"] = 0
        });
        var selector = new HardwareVideoEncoderSelector(runner);

        var first = await selector.SelectAsync(@"C:\ffmpeg.exe", VideoProcessingMode.Auto, default);
        Assert.Equal(VideoEncoderKind.H264Nvenc, first.Kind);

        selector.RememberHardwareFailure(@"C:\ffmpeg.exe", VideoEncoderKind.H264Nvenc);
        var second = await selector.SelectAsync(@"C:\ffmpeg.exe", VideoProcessingMode.Auto, default);

        Assert.Equal(VideoEncoderKind.H264Qsv, second.Kind);
        Assert.Equal(2, runner.TotalCalls);
        Assert.Equal("h264_qsv", CodecOf(runner.Requests[1]));
    }

    [Fact]
    public async Task Reset_probe_clears_skipped_encoders()
    {
        var runner = new ProbeRunner(new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["h264_nvenc"] = 0,
            ["h264_qsv"] = 0
        });
        var selector = new HardwareVideoEncoderSelector(runner);

        await selector.SelectAsync(@"C:\ffmpeg.exe", VideoProcessingMode.Auto, default);
        selector.RememberHardwareFailure(@"C:\ffmpeg.exe", VideoEncoderKind.H264Nvenc);
        selector.ResetProbe(@"C:\ffmpeg.exe");
        var again = await selector.SelectAsync(@"C:\ffmpeg.exe", VideoProcessingMode.Auto, default);

        Assert.Equal(VideoEncoderKind.H264Nvenc, again.Kind);
    }

    [Fact]
    public async Task Cpu_mode_returns_immediately_without_probe()
    {
        var runner = ProbeRunner.AllFailing();
        var selector = new HardwareVideoEncoderSelector(runner);

        var result = await selector.SelectAsync(
            @"C:\ffmpeg.exe",
            VideoProcessingMode.Cpu,
            default);

        Assert.Equal(VideoEncoderKind.Libx264, result.Kind);
        Assert.False(result.IsFallback);
        Assert.Equal(0, runner.TotalCalls);
    }

    [Fact]
    public async Task Caller_cancellation_is_propagated()
    {
        var runner = ProbeRunner.AllFailing();
        var selector = new HardwareVideoEncoderSelector(runner);
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            selector.SelectAsync(
                @"C:\ffmpeg.exe",
                VideoProcessingMode.Auto,
                cancellation.Token));

        Assert.Equal(0, runner.TotalCalls);
    }

    [Fact]
    public async Task Probe_failure_exceptions_are_treated_as_unavailable()
    {
        var runner = new ThrowingProbeRunner();
        var selector = new HardwareVideoEncoderSelector(runner);

        var result = await selector.SelectAsync(
            @"C:\ffmpeg.exe",
            VideoProcessingMode.Auto,
            default);

        Assert.Equal(VideoEncoderKind.Libx264, result.Kind);
        Assert.False(result.IsFallback);
    }

    private static void AssertProbeUsesSafeFrames(IProcessRequest request)
    {
        Assert.Contains(request.Arguments, argument =>
            argument.Contains(HardwareVideoEncoderSelector.ProbeFrameSize, StringComparison.Ordinal)
            && argument.Contains("format=yuv420p", StringComparison.Ordinal));
        AssertArgumentPair(request.Arguments, "-c:v", "h264_nvenc");
        AssertArgumentPair(request.Arguments, "-pix_fmt", "yuv420p");
        Assert.DoesNotContain("-hwaccel", request.Arguments);
    }

    private static string CodecOf(IProcessRequest request)
    {
        var index = request.Arguments.ToList().IndexOf("-c:v");
        return index >= 0 && index + 1 < request.Arguments.Count
            ? request.Arguments[index + 1]
            : string.Empty;
    }

    private static void AssertArgumentPair(IReadOnlyList<string> arguments, string option, string expected)
    {
        var index = arguments.ToList().IndexOf(option);
        Assert.True(index >= 0, $"Missing {option}");
        Assert.Equal(expected, arguments[index + 1]);
    }
}

internal sealed class ProbeRunner(
    IReadOnlyDictionary<string, int> exitCodes) : IExternalProcessRunner
{
    public int TotalCalls { get; private set; }

    public List<IProcessRequest> Requests { get; } = [];

    public static ProbeRunner AllFailing() =>
        new(new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase));

    public static ProbeRunner OnlyQsv() =>
        new(new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["h264_qsv"] = 0
        });

    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        TotalCalls++;
        Requests.Add(request);

        var codecIndex = request.Arguments.ToList().IndexOf("-c:v");
        var codec = codecIndex >= 0 && codecIndex + 1 < request.Arguments.Count
            ? request.Arguments[codecIndex + 1]
            : string.Empty;
        var exitCode = exitCodes.TryGetValue(codec, out var configured) ? configured : 1;
        return Task.FromResult<IProcessResult>(
            new ProcessResult(exitCode, string.Empty, exitCode == 0 ? string.Empty : "encoder unavailable"));
    }
}

internal sealed class ThrowingProbeRunner : IExternalProcessRunner
{
    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken) =>
        throw new InvalidOperationException("无法启动外部进程：ffmpeg");
}
