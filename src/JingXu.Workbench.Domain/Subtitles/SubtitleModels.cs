using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Domain.Subtitles;

/// <summary>字幕条目审阅状态。</summary>
public enum SubtitleReviewState
{
    Unreviewed,
    Confirmed,
    Rejected
}

/// <summary>硬字幕去除方式。</summary>
public enum SubtitleRemovalMode
{
    Blur,
    Delogo,
    CropAndReframe
}

/// <summary>字幕文件格式。</summary>
public enum SubtitleFileFormat
{
    Srt,
    Ass
}

/// <summary>单条字幕 cue。</summary>
public sealed record SubtitleCue(TimeSpan Start, TimeSpan End, string Text, int? Index = null)
{
    public static SubtitleCue Create(TimeSpan start, TimeSpan end, string text) =>
        new(start, end, text);

    public TimeSpan Duration => End - Start;
}

/// <summary>字幕样式（烧录 ASS 时使用）。</summary>
public sealed record SubtitleStyle(
    string FontName = "Microsoft YaHei",
    int FontSize = 48,
    string PrimaryColor = "&H00FFFFFF",
    int Alignment = 2,
    int MarginV = 40);

/// <summary>自动检测到的字幕区域片段。</summary>
public sealed record DetectedSubtitleSegment(
    NormalizedRect Region,
    TimeSpan Start,
    TimeSpan End,
    double Confidence,
    SubtitleReviewState State,
    bool RequiresReview);

/// <summary>手动或自动去字幕计划。</summary>
public sealed record SubtitleRemovalPlan(
    SubtitleRemovalMode Mode,
    NormalizedRect Region,
    int FrameWidth,
    int FrameHeight);

/// <summary>字幕实验室项目快照。</summary>
public sealed record SubtitleProject(
    string VideoPath,
    IReadOnlyList<SubtitleCue> Cues,
    IReadOnlyList<DetectedSubtitleSegment> Segments,
    SubtitleRemovalPlan? RemovalPlan,
    SubtitleStyle Style)
{
    public static SubtitleProject Empty(string videoPath) =>
        new(videoPath, [], [], null, new SubtitleStyle());
}

/// <summary>字幕烧录请求（入队快照）。</summary>
public sealed record SubtitleBurnInPlan(
    string InputVideoPath,
    string OutputPath,
    string SubtitleFilePath,
    SubtitleFileFormat SubtitleFormat,
    int FrameWidth,
    int FrameHeight,
    SubtitleRemovalPlan? Removal = null);

/// <summary>字幕时间轴校验问题。</summary>
public sealed record SubtitleTimelineIssue(int CueIndex, string Message);
