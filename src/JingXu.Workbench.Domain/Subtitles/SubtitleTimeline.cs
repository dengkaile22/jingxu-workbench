namespace JingXu.Workbench.Domain.Subtitles;

/// <summary>字幕时间轴校验与重叠修正。</summary>
public static class SubtitleTimeline
{
    /// <summary>
    /// 校验字幕条目：报告空文本、结束早于开始、重叠等问题；不静默删除任何 cue。
    /// </summary>
    public static IReadOnlyList<SubtitleTimelineIssue> Validate(IReadOnlyList<SubtitleCue> cues)
    {
        ArgumentNullException.ThrowIfNull(cues);
        var issues = new List<SubtitleTimelineIssue>();

        for (var i = 0; i < cues.Count; i++)
        {
            var cue = cues[i];
            if (cue.End <= cue.Start)
            {
                issues.Add(new SubtitleTimelineIssue(i, "结束时间必须晚于开始时间。"));
            }

            if (string.IsNullOrWhiteSpace(cue.Text))
            {
                issues.Add(new SubtitleTimelineIssue(i, "字幕文本不能为空。"));
            }

            if (i > 0 && cues[i - 1].End > cue.Start && cues[i - 1].End > cues[i - 1].Start && cue.End > cue.Start)
            {
                issues.Add(new SubtitleTimelineIssue(i, $"与第 {i} 条字幕时间重叠。"));
            }
        }

        return issues;
    }

    /// <summary>
    /// 修正重叠：将较早 cue 的结束时间截断至下一条开始；不删除任何 cue。
    /// </summary>
    public static IReadOnlyList<SubtitleCue> ResolveOverlaps(IReadOnlyList<SubtitleCue> cues)
    {
        ArgumentNullException.ThrowIfNull(cues);
        if (cues.Count == 0)
        {
            return [];
        }

        var resolved = new List<SubtitleCue>(cues.Count) { cues[0] };
        for (var i = 1; i < cues.Count; i++)
        {
            var previous = resolved[^1];
            var current = cues[i];
            if (previous.End > current.Start && current.Start > previous.Start)
            {
                resolved[^1] = previous with { End = current.Start };
            }

            resolved.Add(current);
        }

        return resolved;
    }

    /// <summary>是否存在未确认且需审阅的检测区域。</summary>
    public static bool HasBlockingUnreviewedSegments(IReadOnlyList<DetectedSubtitleSegment> segments) =>
        segments.Any(x => x.RequiresReview && x.State == SubtitleReviewState.Unreviewed);
}
