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
