using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Infrastructure.Subtitles;

/// <summary>SRT 字幕编解码。</summary>
public sealed partial class SrtSubtitleCodec : ISubtitleDocumentCodec
{
    public SubtitleFileFormat Format => SubtitleFileFormat.Srt;

    public IReadOnlyList<SubtitleCue> Read(string content, string sourcePath)
    {
        ArgumentNullException.ThrowIfNull(content);
        var normalized = content.TrimStart('\uFEFF').Replace("\r\n", "\n");
        var blocks = normalized.Split("\n\n", StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var cues = new List<SubtitleCue>();

        foreach (var block in blocks)
        {
            var lines = block.Split('\n');
            if (lines.Length < 2)
            {
                continue;
            }

            var indexLine = 0;
            if (int.TryParse(lines[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out var index))
            {
                indexLine = 1;
            }

            if (indexLine >= lines.Length)
            {
                continue;
            }

            var timingMatch = TimingLine().Match(lines[indexLine]);
            if (!timingMatch.Success)
            {
                throw new InvalidOperationException($"无法解析 SRT 时间行：{lines[indexLine]}（来源：{sourcePath}）");
            }

            var start = ParseTimestamp(timingMatch.Groups[1].Value);
            var end = ParseTimestamp(timingMatch.Groups[2].Value);
            var text = string.Join('\n', lines.Skip(indexLine + 1));
            cues.Add(new SubtitleCue(start, end, text, index));
        }

        return cues;
    }

    public string Write(IReadOnlyList<SubtitleCue> cues, SubtitleStyle? style = null)
    {
        ArgumentNullException.ThrowIfNull(cues);
        var builder = new StringBuilder();
        for (var i = 0; i < cues.Count; i++)
        {
            var cue = cues[i];
            if (i > 0)
            {
                builder.AppendLine();
            }

            builder.AppendLine((cue.Index ?? i + 1).ToString(CultureInfo.InvariantCulture));
            builder.Append(FormatTimestamp(cue.Start));
            builder.Append(" --> ");
            builder.AppendLine(FormatTimestamp(cue.End));
            builder.AppendLine(cue.Text);
        }

        return builder.ToString();
    }

    private static TimeSpan ParseTimestamp(string value)
    {
        var parts = value.Split(':', ':', ',');
        if (parts.Length != 4)
        {
            throw new FormatException($"无效 SRT 时间戳：{value}");
        }

        var hours = int.Parse(parts[0], CultureInfo.InvariantCulture);
        var minutes = int.Parse(parts[1], CultureInfo.InvariantCulture);
        var seconds = int.Parse(parts[2], CultureInfo.InvariantCulture);
        var millis = int.Parse(parts[3], CultureInfo.InvariantCulture);
        return new TimeSpan(0, hours, minutes, seconds, millis);
    }

    private static string FormatTimestamp(TimeSpan value) =>
        $"{(int)value.TotalHours:D2}:{value.Minutes:D2}:{value.Seconds:D2},{value.Milliseconds:D3}";

    [GeneratedRegex(@"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})", RegexOptions.CultureInvariant)]
    private static partial Regex TimingLine();
}
