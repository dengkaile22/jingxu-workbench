using System.Collections.Concurrent;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>
/// 通过最小 64×64 编码探针选择 NVENC、QSV 或 AMF，并按 FFmpeg 路径缓存结果。
/// </summary>
public sealed class HardwareVideoEncoderSelector : IVideoEncoderSelector
{
    private static readonly TimeSpan ProbeTimeout = TimeSpan.FromSeconds(2);

    private static readonly (VideoEncoderKind Kind, string Codec)[] Candidates =
    [
        (VideoEncoderKind.H264Nvenc, "h264_nvenc"),
        (VideoEncoderKind.H264Qsv, "h264_qsv"),
        (VideoEncoderKind.H264Amf, "h264_amf")
    ];

    private readonly IExternalProcessRunner _runner;
    private readonly ConcurrentDictionary<string, Lazy<Task<VideoEncoderKind?>>> _cache =
        new(StringComparer.OrdinalIgnoreCase);

    public HardwareVideoEncoderSelector(IExternalProcessRunner runner)
    {
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));
    }

    public async Task<VideoEncoderSelection> SelectAsync(
        string ffmpegExecutable,
        VideoProcessingMode mode,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegExecutable);
        cancellationToken.ThrowIfCancellationRequested();

        if (mode == VideoProcessingMode.Cpu)
        {
            return VideoEncoderSelection.Cpu("使用 CPU（libx264）完成。");
        }

        if (mode is not VideoProcessingMode.Auto and not VideoProcessingMode.Gpu)
        {
            throw new ArgumentOutOfRangeException(nameof(mode), mode, "未知的视频处理模式。");
        }

        var normalizedPath = NormalizeExecutablePath(ffmpegExecutable);
        var probe = _cache.GetOrAdd(
            normalizedPath,
            _ => new Lazy<Task<VideoEncoderKind?>>(
                () => ProbeFirstAvailableAsync(ffmpegExecutable),
                LazyThreadSafetyMode.ExecutionAndPublication));

        var selected = await probe.Value
            .WaitAsync(cancellationToken)
            .ConfigureAwait(false);

        if (selected is not null)
        {
            return CreateHardwareSelection(selected.Value);
        }

        return mode == VideoProcessingMode.Gpu
            ? VideoEncoderSelection.Cpu(
                "未检测到可用 GPU 编码器，已改用 CPU（libx264）。",
                isFallback: true)
            : VideoEncoderSelection.Cpu(
                "未检测到可用 GPU 编码器，自动使用 CPU（libx264）完成。");
    }

    private async Task<VideoEncoderKind?> ProbeFirstAvailableAsync(string ffmpegExecutable)
    {
        foreach (var (kind, codec) in Candidates)
        {
            if (await ProbeAsync(ffmpegExecutable, codec).ConfigureAwait(false))
            {
                return kind;
            }
        }

        return null;
    }

    private async Task<bool> ProbeAsync(string ffmpegExecutable, string codec)
    {
        using var timeout = new CancellationTokenSource(ProbeTimeout);
        var request = ProcessRequest.Create(
            ffmpegExecutable,
            [
                "-hide_banner",
                "-loglevel", "error",
                "-f", "lavfi",
                "-i", "color=c=black:s=64x64:d=0.1",
                "-frames:v", "1",
                "-an",
                "-c:v", codec,
                "-f", "null",
                "-"
            ]);

        try
        {
            var result = await _runner
                .RunAsync(request, progress: null, timeout.Token)
                .ConfigureAwait(false);
            return result.ExitCode == 0;
        }
        catch (OperationCanceledException) when (timeout.IsCancellationRequested)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    private static VideoEncoderSelection CreateHardwareSelection(VideoEncoderKind kind) =>
        kind switch
        {
            VideoEncoderKind.H264Nvenc =>
                new(kind, "NVIDIA GPU（NVENC）", "使用 NVIDIA GPU（NVENC）完成。"),
            VideoEncoderKind.H264Qsv =>
                new(kind, "Intel GPU（QSV）", "使用 Intel GPU（QSV）完成。"),
            VideoEncoderKind.H264Amf =>
                new(kind, "AMD GPU（AMF）", "使用 AMD GPU（AMF）完成。"),
            _ => throw new ArgumentOutOfRangeException(nameof(kind), kind, "不是硬件视频编码器。")
        };

    private static string NormalizeExecutablePath(string path)
    {
        try
        {
            return Path.GetFullPath(path.Trim());
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return path.Trim();
        }
    }
}
