using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Domain.Tests.Composition;

public sealed class CompositionPlannerTests
{
    private static MediaAsset Asset(int index, int seconds) =>
        new(Guid.NewGuid(), $"C:\\media\\{index}.mp4", index,
            new MediaInfo(TimeSpan.FromSeconds(seconds), 1080, 1920, 30m, "h264", "aac", true, 0));

    // --- Custom sequence ---

    [Fact]
    public void Custom_264513_preserves_requested_order_and_full_duration()
    {
        var assets = Enumerable.Range(1, 6).Select(i => Asset(i, 30)).ToArray();
        var plan = CompositionPlanner.PlanCustom(assets, [2, 6, 4, 5, 1, 3], TimeSpan.Zero).Value!;
        Assert.Equal([2, 6, 4, 5, 1, 3], plan.Clips.Select(x => x.Asset.SequenceIndex));
        Assert.Equal(TimeSpan.FromSeconds(180), plan.Duration);
        Assert.Equal(TimeSpan.FromSeconds(60), plan.Clips[2].Start);
    }

    [Fact]
    public void Custom_allows_duplicate_indices()
    {
        var assets = Enumerable.Range(1, 3).Select(i => Asset(i, 10)).ToArray();
        var plan = CompositionPlanner.PlanCustom(assets, [1, 2, 1], TimeSpan.Zero).Value!;
        Assert.Equal([1, 2, 1], plan.Clips.Select(x => x.Asset.SequenceIndex));
        Assert.Equal(TimeSpan.FromSeconds(30), plan.Duration);
    }

    [Fact]
    public void Custom_rejects_missing_index()
    {
        var assets = Enumerable.Range(1, 3).Select(i => Asset(i, 10)).ToArray();
        var result = CompositionPlanner.PlanCustom(assets, [1, 99, 3], TimeSpan.Zero);
        Assert.False(result.IsSuccess);
        Assert.Contains("99", result.Error!);
        Assert.Contains("第 2 项", result.Error!);
    }

    [Fact]
    public void Custom_with_single_clip()
    {
        var assets = new[] { Asset(1, 15) };
        var plan = CompositionPlanner.PlanCustom(assets, [1], TimeSpan.Zero).Value!;
        Assert.Single(plan.Clips);
        Assert.Equal(TimeSpan.FromSeconds(15), plan.Duration);
    }

    [Fact]
    public void Custom_rejects_empty_indices()
    {
        var assets = new[] { Asset(1, 10) };
        var result = CompositionPlanner.PlanCustom(assets, [], TimeSpan.Zero);
        Assert.False(result.IsSuccess);
    }

    [Fact]
    public void Custom_rejects_empty_assets()
    {
        var result = CompositionPlanner.PlanCustom([], [1, 2], TimeSpan.Zero);
        Assert.False(result.IsSuccess);
    }

    // --- Random batch ---

    [Fact]
    public void Random_batch_is_reproducible_and_unique_until_space_exhausts()
    {
        var assets = Enumerable.Range(1, 4).Select(i => Asset(i, 1)).ToArray();
        var first = CompositionPlanner.PlanRandomBatch(assets, 8, seed: 264513).Value!;
        var second = CompositionPlanner.PlanRandomBatch(assets, 8, seed: 264513).Value!;
        Assert.Equal(first.Select(Key), second.Select(Key));
        // 4! = 24, requesting 8 should give 8 unique permutations
        Assert.Equal(8, first.Select(Key).Distinct().Count());
    }

    [Fact]
    public void Random_different_seeds_produce_different_orders()
    {
        var assets = Enumerable.Range(1, 6).Select(i => Asset(i, 1)).ToArray();
        var first = CompositionPlanner.PlanRandomBatch(assets, 1, seed: 1).Value!;
        var second = CompositionPlanner.PlanRandomBatch(assets, 1, seed: 999).Value!;
        // With 720 permutations, different seeds almost certainly produce different orders
        Assert.NotEqual(Key(first[0]), Key(second[0]));
    }

    [Fact]
    public void Random_preserves_full_duration()
    {
        var assets = Enumerable.Range(1, 6).Select(i => Asset(i, 30)).ToArray();
        var plan = CompositionPlanner.PlanRandomBatch(assets, 1, seed: 42).Value![0];
        Assert.Equal(TimeSpan.FromSeconds(180), plan.Duration);
    }

    [Fact]
    public void Random_rejects_zero_count()
    {
        var assets = new[] { Asset(1, 10) };
        var result = CompositionPlanner.PlanRandomBatch(assets, 0, seed: 1);
        Assert.False(result.IsSuccess);
    }

    // --- Transitions ---

    [Fact]
    public void Transition_reduces_total_duration()
    {
        var assets = Enumerable.Range(1, 3).Select(i => Asset(i, 10)).ToArray();
        var transition = TimeSpan.FromSeconds(1);
        var plan = CompositionPlanner.PlanCustom(assets, [1, 2, 3], transition).Value!;
        // 3×10 - 2×1 = 28
        Assert.Equal(TimeSpan.FromSeconds(28), plan.Duration);
    }

    [Fact]
    public void Transition_longer_than_clip_is_rejected()
    {
        var assets = new[] { Asset(1, 2), Asset(2, 1) };
        var result = CompositionPlanner.PlanCustom(assets, [1, 2], TimeSpan.FromSeconds(1.5));
        Assert.False(result.IsSuccess);
        Assert.Contains("转场时长", result.Error!);
    }

    // --- Cumulative timeline ---

    [Fact]
    public void Cumulative_start_times_are_correct()
    {
        var assets = new[] { Asset(1, 5), Asset(2, 10), Asset(3, 15) };
        var plan = CompositionPlanner.PlanCustom(assets, [1, 2, 3], TimeSpan.Zero).Value!;
        Assert.Equal(TimeSpan.Zero, plan.Clips[0].Start);
        Assert.Equal(TimeSpan.FromSeconds(5), plan.Clips[1].Start);
        Assert.Equal(TimeSpan.FromSeconds(15), plan.Clips[2].Start);
    }

    private static string Key(CompositionPlan p) =>
        string.Join(',', p.Clips.Select(x => x.Asset.SequenceIndex));
}
