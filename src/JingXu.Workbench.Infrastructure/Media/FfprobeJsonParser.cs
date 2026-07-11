using System.Globalization;
using System.Text.Json;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Infrastructure.Media;

/// <summary>
/// 解析 FFprobe JSON 输出并映射为 <see cref="MediaInfo"/>。
/// </summary>
public static class FfprobeJsonParser
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };

    /// <summary>
    /// 将 FFprobe JSON 文本解析为领域媒体信息。
    /// </summary>
    /// <param name="json">FFprobe 标准输出 JSON。</param>
    /// <exception cref="MediaProbeException">缺少视频流或字段无法解析时抛出。</exception>
    public static MediaInfo Parse(string json)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(json);

        ProbeDocument? document;
        try
        {
            document = JsonSerializer.Deserialize<ProbeDocument>(json, SerializerOptions);
        }
        catch (JsonException ex)
        {
            throw new MediaProbeException(string.Empty, "无法解析 FFprobe 输出：JSON 格式无效。", innerException: ex);
        }

        if (document?.Streams is null || document.Streams.Count == 0)
        {
            throw new MediaProbeException(string.Empty, "无法解析 FFprobe 输出：未找到任何媒体流。");
        }

        var video = document.Streams.FirstOrDefault(s =>
            string.Equals(s.CodecType, "video", StringComparison.OrdinalIgnoreCase));
        if (video is null)
        {
            throw new MediaProbeException(string.Empty, "无法解析 FFprobe 输出：未找到视频流。");
        }

        var audio = document.Streams.FirstOrDefault(s =>
            string.Equals(s.CodecType, "audio", StringComparison.OrdinalIgnoreCase));

        var duration = ResolveDuration(video.Duration, document.Format?.Duration);
        var frameRate = ParseRationalFrameRate(video.AvgFrameRate)
            ?? ParseRationalFrameRate(video.RFrameRate)
            ?? 0m;
        var rotation = NormalizeRotation(video.Tags?.Rotate, video.SideDataList);
        var videoCodec = string.IsNullOrWhiteSpace(video.CodecName) ? "unknown" : video.CodecName;

        return new MediaInfo(
            duration,
            video.Width ?? 0,
            video.Height ?? 0,
            frameRate,
            videoCodec,
            audio?.CodecName,
            audio is not null,
            rotation);
    }

    private static TimeSpan ResolveDuration(string? streamDuration, string? formatDuration)
    {
        if (TryParseSeconds(streamDuration, out var streamSeconds))
        {
            return TimeSpan.FromTicks((long)(streamSeconds * TimeSpan.TicksPerSecond));
        }

        if (TryParseSeconds(formatDuration, out var formatSeconds))
        {
            return TimeSpan.FromTicks((long)(formatSeconds * TimeSpan.TicksPerSecond));
        }

        return TimeSpan.Zero;
    }

    private static bool TryParseSeconds(string? value, out decimal seconds)
    {
        seconds = 0m;
        if (string.IsNullOrWhiteSpace(value))
        {
            return false;
        }

        return decimal.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out seconds)
            && seconds >= 0m;
    }

    private static decimal? ParseRationalFrameRate(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        var parts = value.Split('/', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != 2)
        {
            return null;
        }

        if (!long.TryParse(parts[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out var numerator)
            || !long.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var denominator)
            || denominator == 0)
        {
            return null;
        }

        return decimal.Round((decimal)numerator / denominator, 2, MidpointRounding.AwayFromZero);
    }

    private static int NormalizeRotation(string? tagRotate, IReadOnlyList<SideData>? sideDataList)
    {
        if (!string.IsNullOrWhiteSpace(tagRotate)
            && int.TryParse(tagRotate, NumberStyles.Integer, CultureInfo.InvariantCulture, out var tagDegrees))
        {
            return NormalizeDegrees(tagDegrees);
        }

        if (sideDataList is not null)
        {
            foreach (var sideData in sideDataList)
            {
                if (sideData.Rotation is int sideDegrees)
                {
                    return NormalizeDegrees(sideDegrees);
                }
            }
        }

        return 0;
    }

    private static int NormalizeDegrees(int degrees)
    {
        var normalized = degrees % 360;
        if (normalized < 0)
        {
            normalized += 360;
        }

        return normalized switch
        {
            0 => 0,
            90 => 90,
            180 => 180,
            270 => 270,
            _ => ((normalized + 45) / 90 * 90) % 360
        };
    }

    private sealed class ProbeDocument
    {
        public List<StreamEntry>? Streams { get; init; }
        public FormatEntry? Format { get; init; }
    }

    private sealed class FormatEntry
    {
        public string? Duration { get; init; }
    }

    private sealed class StreamEntry
    {
        public string? CodecType { get; init; }
        public string? CodecName { get; init; }
        public int? Width { get; init; }
        public int? Height { get; init; }
        public string? AvgFrameRate { get; init; }
        public string? RFrameRate { get; init; }
        public string? Duration { get; init; }
        public TagEntry? Tags { get; init; }
        public List<SideData>? SideDataList { get; init; }
    }

    private sealed class TagEntry
    {
        public string? Rotate { get; init; }
    }

    private sealed class SideData
    {
        public int? Rotation { get; init; }
    }
}
