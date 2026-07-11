using JingXu.Workbench.Application.Subtitles;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Application.Tests.Subtitles;

public static class OcrFixtures
{
    public static IReadOnlyList<OcrFrameObservation> JitteredLowConfidence()
    {
        var baseRegion = new NormalizedRect(0.2, 0.78, 0.6, 0.12);
        return
        [
            new OcrFrameObservation(TimeSpan.Zero, baseRegion with { X = 0.21 }, 0.42),
            new OcrFrameObservation(TimeSpan.FromSeconds(0.5), baseRegion with { X = 0.19 }, 0.48),
            new OcrFrameObservation(TimeSpan.FromSeconds(1), baseRegion with { X = 0.205 }, 0.44)
        ];
    }
}

public sealed class SubtitleRegionClustererTests
{
    [Fact]
    public void Jittered_boxes_cluster_but_low_confidence_remains_reviewable()
    {
        var result = SubtitleRegionClusterer.Cluster(OcrFixtures.JitteredLowConfidence());
        Assert.Single(result);
        Assert.True(result[0].RequiresReview);
    }
}
