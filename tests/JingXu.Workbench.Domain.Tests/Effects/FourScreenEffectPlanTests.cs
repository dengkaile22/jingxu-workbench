using System.Text.Json;
using System.Text.Json.Nodes;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Domain.Tests.Effects;

public sealed class FourScreenEffectPlanTests
{
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void Screen_snapshot_prevents_stream_copy_when_legacy_effect_flag_is_missing(bool fourScreen)
    {
        var plan = Plan(Assets(@"C:\素材", 1));
        var request = new RenderRequest(plan, @"C:\output.mp4", RenderProfile.Lossless,
            OutputAspect.InheritFirst, [],
            FourScreen: fourScreen ? new FourScreenEffectPlan(1) : null,
            DoubleScreen: fourScreen ? null : new DoubleScreenEffectPlan(1));

        Assert.False(RenderDecision.For(request).CanStreamCopy);
    }

    [Theory]
    [InlineData(0, FourScreenSourceMode.CurrentClip, 48)]
    [InlineData(1, (FourScreenSourceMode)99, 48)]
    [InlineData(1, FourScreenSourceMode.CurrentClip, -1)]
    [InlineData(1, FourScreenSourceMode.CurrentClip, 257)]
    public void Invalid_settings_are_rejected(int start, FourScreenSourceMode mode, int feather)
    {
        Assert.False(FourScreenEffectPlan.Create(start, mode, featherPixels: feather).IsSuccess);
    }

    [Fact]
    public void Damaged_snapshot_with_null_clip_selection_is_rejected()
    {
        var plan = Plan(Assets(@"C:\素材", 1));
        var effect = new FourScreenEffectPlan(1, ClipSelections: [null!]);

        Assert.False(effect.ValidateForPlan(plan).IsSuccess);
    }

    [Fact]
    public void Snapshot_main_cell_must_match_main_file_even_when_asset_id_is_reused()
    {
        var plan = Plan(Assets(@"C:\素材", 1));
        var effect = new FourScreenEffectPlan(1).MaterializeForPlan(plan, [], 0).Value!;
        var selection = effect.ClipSelections[0];
        var cells = selection.Cells.Select(cell => cell.IsMain
            ? cell with { SourceAsset = cell.SourceAsset with { Path = @"C:\素材\wrong.mp4" } }
            : cell).ToArray();
        var damaged = effect with { ClipSelections = [selection with { Cells = cells }] };

        Assert.False(damaged.ValidateForPlan(plan).IsSuccess);
    }

    [Fact]
    public void Current_clip_mode_materializes_four_synchronized_cells_from_selected_start()
    {
        var assets = Assets(@"C:\素材", 3);
        var setting = new FourScreenEffectPlan(2);

        var actual = setting.MaterializeForPlan(Plan(assets), [], 0).Value!;

        Assert.Null(actual.SelectionFor(0));
        Assert.Equal(2, actual.ClipSelections.Count);
        Assert.All(actual.ClipSelections, selection =>
        {
            Assert.Equal(4, selection.Cells.Count);
            Assert.Equal(4, selection.Cells.Select(cell => cell.Position).Distinct().Count());
            Assert.Single(selection.Cells, cell => cell.IsMain);
            Assert.All(selection.Cells, cell => Assert.Equal(assets[selection.ClipIndex], cell.SourceAsset));
        });
        Assert.Empty(setting.ClipSelections);
    }

    [Fact]
    public void Random_cells_are_deterministic_distinct_and_limited_to_each_main_folder()
    {
        var firstFolder = Assets(@"C:\素材甲", 4);
        var secondFolder = Assets(@"C:\素材乙", 4, 10);
        var assets = firstFolder.Concat(secondFolder).ToArray();
        var plan = Plan([firstFolder[0], secondFolder[0]]);
        var setting = new FourScreenEffectPlan(1, FourScreenSourceMode.RandomCurrentFolder);

        var first = setting.MaterializeForPlan(plan, assets, 3).Value!;
        var replay = setting.MaterializeForPlan(plan, assets.Reverse().ToArray(), 3).Value!;

        Assert.Equal(2, first.ClipSelections.Count);
        Assert.Equal(JsonSerializer.Serialize(first), JsonSerializer.Serialize(replay));
        Assert.All(first.ClipSelections, selection =>
        {
            Assert.Equal(4, selection.Cells.Select(cell => cell.SourceAsset.Path).Distinct().Count());
            Assert.Equal(plan.Clips[selection.ClipIndex].Asset, Assert.Single(selection.Cells, cell => cell.IsMain).SourceAsset);
            Assert.All(selection.Cells, cell => Assert.Equal(
                Path.GetDirectoryName(plan.Clips[selection.ClipIndex].Asset.Path),
                Path.GetDirectoryName(cell.SourceAsset.Path)));
        });
    }

    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    public void Small_imported_pools_repeat_available_sources_without_losing_the_main_cell(int count)
    {
        var assets = Assets(@"C:\素材", count);
        var setting = new FourScreenEffectPlan(1, FourScreenSourceMode.RandomCurrentFolder);

        var actual = setting.MaterializeForPlan(Plan([assets[0]]), assets, 0).Value!;

        var selection = Assert.Single(actual.ClipSelections);
        Assert.Equal(4, selection.Cells.Count);
        Assert.Single(selection.Cells, cell => cell.IsMain);
        Assert.Equal(count, selection.Cells.Select(cell => cell.SourceAsset.Path).Distinct().Count());
    }

    [Fact]
    public void Duplicate_import_entries_cannot_repeat_a_source_when_four_unique_sources_exist()
    {
        var assets = Assets(@"C:\素材", 4);
        var pool = assets.Concat([assets[1] with { Id = Guid.NewGuid() }]).ToArray();
        var setting = new FourScreenEffectPlan(1, FourScreenSourceMode.RandomCurrentFolder);

        var actual = setting.MaterializeForPlan(Plan([assets[0]]), pool, 0).Value!;

        Assert.Equal(4, Assert.Single(actual.ClipSelections).Cells.Select(cell => cell.SourceAsset.Path).Distinct().Count());
    }

    [Fact]
    public void Queued_four_screen_snapshot_requires_effect_rendering_after_json_round_trip()
    {
        var asset = new MediaAsset(Guid.NewGuid(), @"C:\素材\1.mp4", 1,
            new MediaInfo(TimeSpan.FromSeconds(2), 320, 240, 30m, "h264", "aac", true, 0));
        var plan = new CompositionPlan([new PlannedClip(asset, TimeSpan.Zero, TimeSpan.FromSeconds(2))],
            TimeSpan.FromSeconds(2), 42, TimeSpan.Zero);
        var request = new RenderRequest(plan, @"C:\output.mp4", RenderProfile.Balanced,
            OutputAspect.InheritFirst, [], HasEffects: true);
        var document = JsonSerializer.SerializeToNode(request)!.AsObject();
        document["FourScreen"] = JsonNode.Parse("""
            {"StartClipIndex":1,"SourceMode":0,"FeatherEnabled":true,"FeatherPixels":48,"ClipSelections":[]}
            """);

        var restored = document.Deserialize<RenderRequest>()!;

        Assert.True(restored.HasRenderableEffects);
        Assert.NotNull(JsonSerializer.SerializeToNode(restored)!["FourScreen"]);
    }

    private static MediaAsset[] Assets(string folder, int count, int start = 0) =>
        Enumerable.Range(start + 1, count).Select(index => new MediaAsset(
            Guid.Parse($"00000000-0000-0000-0000-{index:000000000000}"),
            Path.Combine(folder, $"{index}.mp4"), index,
            new MediaInfo(TimeSpan.FromSeconds(2), 320, 240, 30m, "h264", "aac", true, 0))).ToArray();

    private static CompositionPlan Plan(MediaAsset[] assets) => new(
        assets.Select((asset, index) => new PlannedClip(asset, TimeSpan.FromSeconds(index * 2), TimeSpan.FromSeconds(2))).ToArray(),
        TimeSpan.FromSeconds(assets.Length * 2), 42, TimeSpan.Zero);
}
