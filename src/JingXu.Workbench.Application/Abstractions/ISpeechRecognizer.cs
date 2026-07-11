using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Application.Abstractions;

/// <summary>本地语音识别（whisper.cpp）抽象。</summary>
public interface ISpeechRecognizer
{
    Task<Result<IReadOnlyList<SubtitleCue>>> RecognizeAsync(
        string videoPath,
        IProgress<string>? progress,
        CancellationToken cancellationToken);
}

/// <summary>硬字幕 OCR 检测抽象。</summary>
public interface ISubtitleOcrDetector
{
    Task<Result<IReadOnlyList<DetectedSubtitleSegment>>> DetectAsync(
        string videoPath,
        NormalizedRect scanRegion,
        IProgress<string>? progress,
        CancellationToken cancellationToken);
}
