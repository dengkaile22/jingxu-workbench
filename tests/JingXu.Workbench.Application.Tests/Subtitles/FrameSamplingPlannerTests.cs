using JingXu.Workbench.Application.Subtitles;

namespace JingXu.Workbench.Application.Tests.Subtitles;

public sealed class FrameSamplingPlannerTests
{
    [Fact]
    public void Short_video_samples_every_half_second_using_pts()
    {
        var samples = FrameSamplingPlanner.Plan(TimeSpan.FromSeconds(2), maxFrames: 3600);
        Assert.Equal([0, .5, 1, 1.5], samples.Select(x => x.TotalSeconds));
    }

    [Fact]
    public void Long_video_produces_exactly_3600_evenly_spaced_samples() =>
        Assert.Equal(3600, FrameSamplingPlanner.Plan(TimeSpan.FromHours(2), 3600).Count);
}
