namespace JingXu.Workbench.Application.Subtitles;

/// <summary>按 PTS 均匀抽帧采样计划。</summary>
public static class FrameSamplingPlanner
{
    private static readonly TimeSpan DefaultInterval = TimeSpan.FromMilliseconds(500);

    /// <summary>
    /// 规划抽帧时间点。短视频按 0.5 秒间隔；超过 <paramref name="maxFrames"/> 时改为等距采样。
    /// </summary>
    public static IReadOnlyList<TimeSpan> Plan(TimeSpan duration, int maxFrames = 3600)
    {
        if (duration <= TimeSpan.Zero)
        {
            return [];
        }

        var intervalSamples = new List<TimeSpan>();
        for (var t = TimeSpan.Zero; t < duration; t += DefaultInterval)
        {
            intervalSamples.Add(t);
        }

        if (intervalSamples.Count <= maxFrames)
        {
            return intervalSamples;
        }

        var evenlySpaced = new List<TimeSpan>(maxFrames);
        var totalSeconds = duration.TotalSeconds;
        for (var i = 0; i < maxFrames; i++)
        {
            var seconds = totalSeconds * i / maxFrames;
            evenlySpaced.Add(TimeSpan.FromSeconds(seconds));
        }

        return evenlySpaced;
    }
}
