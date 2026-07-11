using System.Globalization;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>FFmpeg 进度状态。</summary>
public enum FfmpegProgressStatus
{
    /// <summary>进度继续。</summary>
    Continue,

    /// <summary>已到达结尾。</summary>
    End
}

/// <summary>解析后的 FFmpeg 进度快照。</summary>
public sealed record FfmpegProgress(
    TimeSpan Position,
    double Speed,
    FfmpegProgressStatus Status,
    long? Frame,
    double? Fps,
    long? TotalSizeBytes);

/// <summary>
/// 解析 FFmpeg <c>-progress</c> 输出的机器可读键值块
/// （<c>out_time_us</c>、<c>speed</c>、<c>progress</c> 等）。
/// 未知字段与 <c>N/A</c> 值都会被安全忽略。
/// </summary>
public static class FfmpegProgressParser
{
    /// <summary>解析一个进度块。</summary>
    public static FfmpegProgress Parse(string block)
    {
        ArgumentNullException.ThrowIfNull(block);

        var position = TimeSpan.Zero;
        var speed = 0d;
        var status = FfmpegProgressStatus.Continue;
        long? frame = null;
        double? fps = null;
        long? totalSize = null;

        foreach (var rawLine in block.Split('\n'))
        {
            var line = rawLine.Trim().TrimEnd('\r');
            if (line.Length == 0)
            {
                continue;
            }

            var separator = line.IndexOf('=');
            if (separator <= 0)
            {
                continue;
            }

            var key = line[..separator].Trim();
            var value = line[(separator + 1)..].Trim();

            switch (key)
            {
                case "out_time_us":
                    if (TryParseLong(value, out var microseconds))
                    {
                        position = TimeSpan.FromMicroseconds(microseconds);
                    }

                    break;
                case "speed":
                    speed = ParseSpeed(value);
                    break;
                case "progress":
                    status = string.Equals(value, "end", StringComparison.OrdinalIgnoreCase)
                        ? FfmpegProgressStatus.End
                        : FfmpegProgressStatus.Continue;
                    break;
                case "frame":
                    if (TryParseLong(value, out var frameValue))
                    {
                        frame = frameValue;
                    }

                    break;
                case "fps":
                    if (TryParseDouble(value, out var fpsValue))
                    {
                        fps = fpsValue;
                    }

                    break;
                case "total_size":
                    if (TryParseLong(value, out var totalSizeValue))
                    {
                        totalSize = totalSizeValue;
                    }

                    break;
                default:
                    break;
            }
        }

        return new FfmpegProgress(position, speed, status, frame, fps, totalSize);
    }

    private static double ParseSpeed(string value)
    {
        var trimmed = value.EndsWith('x') ? value[..^1] : value;
        return TryParseDouble(trimmed, out var parsed) ? parsed : 0d;
    }

    private static bool TryParseLong(string value, out long result) =>
        long.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out result);

    private static bool TryParseDouble(string value, out double result) =>
        double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out result);
}
