namespace JingXu.Workbench.Domain.Media;

/// <summary>
/// 媒体文件的探测元信息。
/// </summary>
public sealed record MediaInfo(
    TimeSpan Duration,
    int Width,
    int Height,
    decimal FrameRate,
    string VideoCodec,
    string? AudioCodec,
    bool HasAudio,
    int RotationDegrees);
