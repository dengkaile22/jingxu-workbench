using CommunityToolkit.Mvvm.ComponentModel;

namespace JingXu.Workbench.Features.Composition;

/// <summary>素材列表中的一行：探测元信息与序号诊断。</summary>
public sealed partial class MaterialRowViewModel : ObservableObject
{
    public MaterialRowViewModel(
        string fileName,
        string sourcePath,
        string? sequenceLabel,
        TimeSpan duration,
        string resolutionText,
        string? diagnostic,
        bool hasValidAsset,
        string? videoCodec = null)
    {
        FileName = fileName;
        SourcePath = sourcePath;
        SequenceLabel = sequenceLabel ?? "—";
        Duration = duration;
        ResolutionText = resolutionText;
        Diagnostic = diagnostic;
        HasValidAsset = hasValidAsset;
        VideoCodec = videoCodec;
    }

    public string FileName { get; }

    public string SourcePath { get; }

    public string? SequenceLabel { get; }

    public TimeSpan Duration { get; }

    public string DurationText => FormatDuration(Duration);

    public string ResolutionText { get; }

    public string? Diagnostic { get; }

    public bool HasDiagnostic => !string.IsNullOrWhiteSpace(Diagnostic);

    public bool HasValidAsset { get; }

    public string? VideoCodec { get; }

    public string StatusText => HasDiagnostic ? "需关注" : "正常";

    [ObservableProperty]
    private bool _isSelected;

    private static string FormatDuration(TimeSpan duration) =>
        duration.TotalHours >= 1
            ? $"{(int)duration.TotalHours}:{duration.Minutes:D2}:{duration.Seconds:D2}"
            : $"{duration.Minutes:D2}:{duration.Seconds:D2}";
}
