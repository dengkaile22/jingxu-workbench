using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Domain.Tests.Effects;

public sealed class DoubleScreenEffectPlanTests
{
    [Fact]
    public void Double_screen_plan_exposes_random_source_and_feather_configuration()
    {
        var planType = typeof(DoubleScreenEffectPlan);

        Assert.NotNull(planType.GetProperty("SourceMode"));
        Assert.NotNull(planType.GetProperty("PlacementMode"));
        Assert.NotNull(planType.GetProperty("FeatherEnabled"));
        Assert.NotNull(planType.GetProperty("FeatherPixels"));
        Assert.NotNull(planType.GetProperty("ClipSelections"));
    }

    [Fact]
    public void Random_materialization_is_deterministic_and_respects_selected_start_clip()
    {
        var assets = Enumerable.Range(1, 4)
            .Select(index => Asset($@"C:\素材\{index}.mp4", index))
            .ToArray();
        var plan = new CompositionPlan(
            assets.Take(3)
                .Select((asset, index) => new PlannedClip(
                    asset,
                    TimeSpan.FromSeconds(index * 2),
                    TimeSpan.FromSeconds(2)))
                .ToArray(),
            TimeSpan.FromSeconds(6),
            Seed: 20260901,
            TimeSpan.Zero);
        var setting = DoubleScreenEffectPlan.Create(
            startClipIndex: 2,
            sourceMode: DoubleScreenSourceMode.RandomCurrentFolder,
            placementMode: DoubleScreenPlacementMode.Random,
            featherEnabled: true,
            featherPixels: 64).Value!;

        var first = setting.MaterializeForPlan(plan, assets, planIndex: 0).Value!;
        var second = setting.MaterializeForPlan(plan, assets, planIndex: 0).Value!;

        Assert.Null(first.SelectionFor(0));
        Assert.Equal(2, first.ClipSelections.Count);
        Assert.Equal(
            first.ClipSelections.Select(selection => selection.SourceAsset.Path),
            second.ClipSelections.Select(selection => selection.SourceAsset.Path));
        Assert.Equal(
            first.ClipSelections.Select(selection => selection.Placement),
            second.ClipSelections.Select(selection => selection.Placement));
        Assert.All(first.ClipSelections, selection =>
            Assert.DoesNotContain(
                selection.SourceAsset.Path,
                plan.Clips[selection.ClipIndex].Asset.Path,
                StringComparison.OrdinalIgnoreCase));
        Assert.Equal(64, first.FeatherPixels);
    }

    private static MediaAsset Asset(string path, int index) =>
        new(
            Guid.Parse($"00000000-0000-0000-0000-{index:000000000000}"),
            path,
            index,
            new MediaInfo(TimeSpan.FromSeconds(2), 1080, 1920, 30m, "h264", "aac", true, 0));
}
