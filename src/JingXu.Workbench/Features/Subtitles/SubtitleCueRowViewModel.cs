using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Features.Subtitles;

/// <summary>字幕表格行。</summary>
public sealed partial class SubtitleCueRowViewModel : ObservableObject
{
    public SubtitleCueRowViewModel(int index, SubtitleCue cue)
    {
        Index = index;
        StartText = FormatTime(cue.Start);
        EndText = FormatTime(cue.End);
        Text = cue.Text;
    }

    public int Index { get; }

    [ObservableProperty]
    private string _startText;

    [ObservableProperty]
    private string _endText;

    [ObservableProperty]
    private string _text;

    public SubtitleCue ToCue() =>
        new(ParseTime(StartText), ParseTime(EndText), Text, Index);

    private static string FormatTime(TimeSpan value) =>
        $"{(int)value.TotalHours:D2}:{value.Minutes:D2}:{value.Seconds:D2},{value.Milliseconds:D3}";

    private static TimeSpan ParseTime(string value)
    {
        var normalized = value.Trim().Replace('.', ',');
        var parts = normalized.Split(':', ',');
        if (parts.Length != 4)
        {
            return TimeSpan.Zero;
        }

        return new TimeSpan(
            0,
            int.Parse(parts[0], CultureInfo.InvariantCulture),
            int.Parse(parts[1], CultureInfo.InvariantCulture),
            int.Parse(parts[2], CultureInfo.InvariantCulture),
            int.Parse(parts[3], CultureInfo.InvariantCulture));
    }
}
