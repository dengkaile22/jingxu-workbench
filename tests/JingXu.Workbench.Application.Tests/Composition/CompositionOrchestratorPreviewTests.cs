using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Application.Tests.Composition;

public sealed class CompositionOrchestratorPreviewTests
{
    [Fact]
    public void Custom_mode_supports_multiple_expressions_separated_by_semicolon()
    {
        var assets = TestAssets.SixClips();

        var result = CompositionOrchestrator.BuildPreview(
            assets,
            CompositionMode.CustomSequence,
            "123456; 654321",
            batchCount: 1,
            randomSeed: 0);

        Assert.True(result.CanEnqueue);
        Assert.Equal(2, result.Plans.Count);
        Assert.Equal(2, result.ExecutablePlans.Count);
        Assert.Equal([1, 2, 3, 4, 5, 6], result.Plans[0].Sequence);
        Assert.Equal([6, 5, 4, 3, 2, 1], result.Plans[1].Sequence);
    }

    [Fact]
    public void Custom_mode_supports_multiple_expressions_on_separate_lines()
    {
        var assets = TestAssets.SixClips();

        var result = CompositionOrchestrator.BuildPreview(
            assets,
            CompositionMode.CustomSequence,
            "264513\n351246",
            batchCount: 1,
            randomSeed: 0);

        Assert.True(result.CanEnqueue);
        Assert.Equal(2, result.Plans.Count);
        Assert.Equal([2, 6, 4, 5, 1, 3], result.Plans[0].Sequence);
        Assert.Equal([3, 5, 1, 2, 4, 6], result.Plans[1].Sequence);
    }

    [Fact]
    public void Custom_mode_reports_expression_specific_validation_error()
    {
        var assets = TestAssets.SixClips();

        var result = CompositionOrchestrator.BuildPreview(
            assets,
            CompositionMode.CustomSequence,
            "123456; 2,a,3",
            batchCount: 1,
            randomSeed: 0);

        Assert.False(result.CanEnqueue);
        Assert.Contains("2,a,3", result.ValidationMessage);
    }
}

internal static class TestAssets
{
    public static IReadOnlyList<MediaAsset> SixClips()
    {
        var clips = new List<MediaAsset>();
        for (var i = 1; i <= 6; i++)
        {
            clips.Add(new MediaAsset(
                Guid.NewGuid(),
                $@"C:\素材\片段_{i}.mp4",
                i,
                new MediaInfo(TimeSpan.FromSeconds(30), 1080, 1920, 30m, "h264", "aac", true, 0)));
        }

        return clips;
    }
}
