using System.Collections.Concurrent;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>
/// 通过最小编码探针选择 NVENC、QSV 或 AMF，并按 FFmpeg 路径缓存结果。
/// 探针必须达到硬件编码器常见最小分辨率，并输出 yuv420p，避免 64×64/RGB 造成「假失败」后整场都走 CPU。
/// </summary>
public sealed class HardwareVideoEncoderSelector : IVideoEncoderSelector
{
    /// <summary>
    /// 首次加载 NVIDIA 驱动可能超过 2 秒；8 秒仍远短于渲染超时，避免把可用 GPU 判死。
    /// </summary>
    private static readonly TimeSpan ProbeTimeout = TimeSpan.FromSeconds(8);

    /// <summary>
    /// NVENC/AMF 在部分世代要求宽高 ≥128；256 仍是一帧黑场，成本可忽略。
    /// </summary>
    internal const string ProbeFrameSize = "256x256";

    private static readonly (VideoEncoderKind Kind, string Codec)[] Candidates =
    [
        (VideoEncoderKind.H264Nvenc, "h264_nvenc"),
        (VideoEncoderKind.H264Qsv, "h264_qsv"),
        (VideoEncoderKind.H264Amf, "h264_amf")
    ];

    private readonly IExternalProcessRunner _runner;
    private readonly ConcurrentDictionary<string, Lazy<Task<VideoEncoderKind?>>> _cache =
        new(StringComparer.OrdinalIgnoreCase);
    private readonly ConcurrentDictionary<string, ConcurrentDictionary<VideoEncoderKind, byte>> _skipped =
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
            key => new Lazy<Task<VideoEncoderKind?>>(
                () => ProbeFirstAvailableAsync(ffmpegExecutable, key),
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

    /// <inheritdoc />
    public void RememberHardwareFailure(string ffmpegExecutable, VideoEncoderKind kind)
    {
        if (kind == VideoEncoderKind.Libx264 || string.IsNullOrWhiteSpace(ffmpegExecutable))
        {
            return;
        }

        var key = NormalizeExecutablePath(ffmpegExecutable);
        _skipped
            .GetOrAdd(key, static _ => new ConcurrentDictionary<VideoEncoderKind, byte>())
            .TryAdd(kind, 0);
        // 丢掉「首选 NVENC」缓存，下次改探 QSV/AMF，避免每个任务都先失败再回退 CPU。
        _cache.TryRemove(key, out _);
    }

    /// <inheritdoc />
    public void ResetProbe(string ffmpegExecutable)
    {
        if (string.IsNullOrWhiteSpace(ffmpegExecutable))
        {
            return;
        }

        var key = NormalizeExecutablePath(ffmpegExecutable);
        _cache.TryRemove(key, out _);
        _skipped.TryRemove(key, out _);
    }

    private async Task<VideoEncoderKind?> ProbeFirstAvailableAsync(string ffmpegExecutable, string cacheKey)
    {
        _skipped.TryGetValue(cacheKey, out var skipped);
        foreach (var (kind, codec) in Candidates)
        {
            if (skipped is not null && skipped.ContainsKey(kind))
            {
                continue;
            }

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
                // format=yuv420p：lavfi color 默认 RGB，直接喂给 NVENC/QSV/AMF 常会报不支持的像素格式。
                "-i", $"color=c=black:s={ProbeFrameSize}:d=0.04:r=25,format=yuv420p",
                "-frames:v", "1",
                "-an",
                "-c:v", codec,
                "-pix_fmt", "yuv420p",
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
        catch (Exception)
        {
            // 探测失败只表示该编码器不可用，不得让正式渲染任务变红。
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
