using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Domain.Tests.Subtitles;

public sealed class SubtitleTimelineTests
{
    [Fact]
    public void Invalid_cues_are_reported_and_never_silently_deleted()
    {
        var cues = new[]
        {
            SubtitleCue.Create(TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(1), "倒序"),
            SubtitleCue.Create(TimeSpan.Zero, TimeSpan.FromSeconds(1), "")
        };
        var issues = SubtitleTimeline.Validate(cues);
        Assert.Equal(2, issues.Count);
        Assert.Equal(2, cues.Length);
    }

    [Fact]
    public void ResolveOverlaps_trims_earlier_cue_without_dropping()
    {
        var cues = new[]
        {
            SubtitleCue.Create(TimeSpan.Zero, TimeSpan.FromSeconds(3), "A"),
            SubtitleCue.Create(TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(5), "B")
        };
        var resolved = SubtitleTimeline.ResolveOverlaps(cues);
        Assert.Equal(2, resolved.Count);
        Assert.Equal(TimeSpan.FromSeconds(2), resolved[0].End);
        Assert.Equal(TimeSpan.FromSeconds(2), resolved[1].Start);
    }
}
