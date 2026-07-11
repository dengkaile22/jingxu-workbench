using System.Globalization;
using System.Text;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Infrastructure.Subtitles;

/// <summary>ASS 字幕编解码（基础事件行）。</summary>
public sealed class AssSubtitleCodec : ISubtitleDocumentCodec
{
    public SubtitleFileFormat Format => SubtitleFileFormat.Ass;

    public IReadOnlyList<SubtitleCue> Read(string content, string sourcePath)
    {
        ArgumentNullException.ThrowIfNull(content);
        var normalized = content.TrimStart('\uFEFF');
        var formatOrder = ParseFormatOrder(normalized);
        if (formatOrder.Count == 0)
        {
            throw new InvalidOperationException($"ASS 文件缺少 Format 行（来源：{sourcePath}）");
        }

        var cues = new List<SubtitleCue>();
        foreach (var line in normalized.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (!line.StartsWith("Dialogue:", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var payload = line["Dialogue:".Length..];
            var fields = SplitAssFields(payload);
            if (fields.Count < formatOrder.Count)
            {
                continue;
            }

            var map = formatOrder
                .Select((name, index) => (name, Value: fields[index]))
                .ToDictionary(x => x.name, x => x.Value, StringComparer.OrdinalIgnoreCase);

            if (!map.TryGetValue("Start", out var startText) || !map.TryGetValue("End", out var endText))
            {
                continue;
            }

            map.TryGetValue("Text", out var text);
            cues.Add(new SubtitleCue(
                ParseAssTimestamp(startText),
                ParseAssTimestamp(endText),
                (text ?? string.Empty).Replace("\\N", "\n", StringComparison.Ordinal)));
        }

        return cues;
    }

    public string Write(IReadOnlyList<SubtitleCue> cues, SubtitleStyle? style = null)
    {
        ArgumentNullException.ThrowIfNull(cues);
        style ??= new SubtitleStyle();
        var builder = new StringBuilder();
        builder.AppendLine("[Script Info]");
        builder.AppendLine("ScriptType: v4.00+");
        builder.AppendLine("Collisions: Normal");
        builder.AppendLine("PlayResX: 1920");
        builder.AppendLine("PlayResY: 1080");
        builder.AppendLine();
        builder.AppendLine("[V4+ Styles]");
        builder.AppendLine("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding");
        builder.AppendLine(CultureInfo.InvariantCulture,
            $"Style: Default,{style.FontName},{style.FontSize},{style.PrimaryColor},&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,{style.Alignment},20,20,{style.MarginV},1");
        builder.AppendLine();
        builder.AppendLine("[Events]");
        builder.AppendLine("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text");

        foreach (var cue in cues)
        {
            var text = cue.Text.Replace("\n", "\\N", StringComparison.Ordinal);
            builder.Append("Dialogue: 0,");
            builder.Append(FormatAssTimestamp(cue.Start));
            builder.Append(',');
            builder.Append(FormatAssTimestamp(cue.End));
            builder.Append(",Default,,0,0,0,,");
            builder.AppendLine(text);
        }

        return builder.ToString().Replace("\n", "\r\n", StringComparison.Ordinal);
    }

    private static List<string> ParseFormatOrder(string content)
    {
        foreach (var line in content.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (line.StartsWith("Format:", StringComparison.OrdinalIgnoreCase)
                && line.Contains("Start", StringComparison.OrdinalIgnoreCase))
            {
                return line["Format:".Length..]
                    .Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
                    .ToList();
            }
        }

        return [];
    }

    private static List<string> SplitAssFields(string payload)
    {
        var fields = payload.Split(',');
        if (fields.Length <= 9)
        {
            return fields.ToList();
        }

        var head = fields.Take(9).ToList();
        head.Add(string.Join(',', fields.Skip(9)));
        return head;
    }

    private static TimeSpan ParseAssTimestamp(string value)
    {
        var colonIndex = value.IndexOf(':', StringComparison.Ordinal);
        var secondColonIndex = value.IndexOf(':', colonIndex + 1);
        if (colonIndex < 0 || secondColonIndex < 0)
        {
            throw new FormatException($"无效 ASS 时间戳：{value}");
        }

        var hours = int.Parse(value[..colonIndex], CultureInfo.InvariantCulture);
        var minutes = int.Parse(value[(colonIndex + 1)..secondColonIndex], CultureInfo.InvariantCulture);
        var secondsPart = value[(secondColonIndex + 1)..];
        var dotIndex = secondsPart.IndexOf('.', StringComparison.Ordinal);
        var seconds = dotIndex >= 0
            ? int.Parse(secondsPart[..dotIndex], CultureInfo.InvariantCulture)
            : int.Parse(secondsPart, CultureInfo.InvariantCulture);
        var centiseconds = dotIndex >= 0
            ? int.Parse(secondsPart[(dotIndex + 1)..], CultureInfo.InvariantCulture)
            : 0;
        return new TimeSpan(0, hours, minutes, seconds, centiseconds * 10);
    }

    private static string FormatAssTimestamp(TimeSpan value) =>
        $"{(int)value.TotalHours}:{value.Minutes:D2}:{value.Seconds:D2}.{value.Milliseconds / 10:D2}";
}
