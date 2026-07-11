using System.Globalization;
using System.Text.RegularExpressions;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Infrastructure.Subtitles;

/// <summary>解析 whisper.cpp 输出的 SRT。</summary>
public static partial class WhisperSrtParser
{
    public static IReadOnlyList<SubtitleCue> Parse(string content)
    {
        ArgumentNullException.ThrowIfNull(content);
        var codec = new SrtSubtitleCodec();
        return codec.Read(content, "whisper.srt");
    }
}
