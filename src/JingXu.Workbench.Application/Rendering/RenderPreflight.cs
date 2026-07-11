using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Rendering;

/// <summary>渲染前预检：磁盘、输入、命令预算等。</summary>
public static class RenderPreflight
{
    private const double DiskSafetyFactor = 1.25;

    /// <summary>Windows 命令行保守字符预算。</summary>
    public const int MaxCommandLineLength = 30_000;

    /// <summary>检查磁盘余量是否满足输出加临时空间的 1.25 倍要求。</summary>
    public static Result<Unit> CheckDisk(long requiredBytes, long availableBytes)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(requiredBytes);
        ArgumentOutOfRangeException.ThrowIfNegative(availableBytes);

        var needed = (long)Math.Ceiling(requiredBytes * DiskSafetyFactor);
        if (availableBytes < needed)
        {
            return Result<Unit>.Failure(
                $"磁盘空间不足：需要约 {FormatBytes(needed)}（含临时文件），当前可用 {FormatBytes(availableBytes)}。");
        }

        return Result<Unit>.Success(default);
    }

    /// <summary>检查所有输入文件是否存在。</summary>
    public static Result<Unit> CheckInputs(RenderRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        foreach (var clip in request.Plan.Clips)
        {
            if (!File.Exists(clip.Asset.Path))
            {
                return Result<Unit>.Failure($"找不到输入素材：{clip.Asset.Path}");
            }
        }

        return Result<Unit>.Success(default);
    }

    /// <summary>检查输出目录是否可写。</summary>
    public static Result<Unit> CheckOutputDirectory(string outputPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);

        var directory = Path.GetDirectoryName(outputPath);
        if (string.IsNullOrWhiteSpace(directory))
        {
            return Result<Unit>.Failure("输出路径无效。");
        }

        if (!Directory.Exists(directory))
        {
            try
            {
                Directory.CreateDirectory(directory);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                return Result<Unit>.Failure($"无法创建输出目录：{directory}。");
            }
        }

        var probe = Path.Combine(directory, $".jingxu-write-probe-{Guid.NewGuid():N}.tmp");
        try
        {
            File.WriteAllText(probe, string.Empty);
            File.Delete(probe);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Result<Unit>.Failure($"输出目录不可写：{directory}。");
        }

        return Result<Unit>.Success(default);
    }

    /// <summary>检查 FFmpeg 命令长度预算。</summary>
    public static Result<Unit> CheckCommandBudget(int estimatedCommandLineLength)
    {
        if (estimatedCommandLineLength > MaxCommandLineLength)
        {
            return Result<Unit>.Failure(
                $"FFmpeg 命令过长（约 {estimatedCommandLineLength} 字符），超过 {MaxCommandLineLength} 字符的安全上限。请减少素材数量或拆分任务。");
        }

        return Result<Unit>.Success(default);
    }

    /// <summary>估算输出字节数（保守：按 1 MB/秒视频 + 音频码率）。</summary>
    public static long EstimateRequiredBytes(RenderRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        var durationSeconds = request.Plan.Duration.TotalSeconds;
        const long videoBytesPerSecond = 1_000_000;
        var audioBytesPerSecond = request.Profile.AudioKbps * 1000 / 8;
        var payload = (long)((videoBytesPerSecond + audioBytesPerSecond) * durationSeconds);
        return Math.Max(payload, 1_048_576);
    }

    private static string FormatBytes(long bytes)
    {
        if (bytes >= 1_073_741_824)
        {
            return $"{bytes / 1_073_741_824.0:0.##} GB";
        }

        if (bytes >= 1_048_576)
        {
            return $"{bytes / 1_048_576.0:0.##} MB";
        }

        return $"{bytes / 1024.0:0.##} KB";
    }
}
