namespace JingXu.Workbench.Features.Composition;

/// <summary>编排预览中的一条成片计划。</summary>
public sealed class PreviewPlanRowViewModel
{
    public PreviewPlanRowViewModel(
        int planNumber,
        string sequenceText,
        TimeSpan duration,
        int clipCount)
    {
        PlanNumber = planNumber;
        SequenceText = sequenceText;
        Duration = duration;
        ClipCount = clipCount;
    }

    public int PlanNumber { get; }

    public string Title => $"成片 {PlanNumber}";

    public string SequenceText { get; }

    public TimeSpan Duration { get; }

    public int ClipCount { get; }

    public string DurationText => $"{Duration.TotalSeconds:F1} 秒";
}
