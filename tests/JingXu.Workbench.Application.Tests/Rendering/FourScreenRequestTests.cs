using System.Text.Json;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Tests.Rendering;

public sealed class FourScreenRequestTests
{
    [Theory]
    [InlineData(FourScreenSourceMode.CurrentClip)]
    [InlineData(FourScreenSourceMode.RandomCurrentFolder)]
    public void Factory_materializes_all_four_cells_before_enqueue(FourScreenSourceMode mode)
    {
        var asset = Asset(Path.Combine(Path.GetTempPath(), "four-screen-main.mp4"));
        var plan = Plan(asset);

        var request = Assert.Single(RenderRequestFactory.CreateForPlans(
            [plan], Path.GetTempPath(), "four-screen-" + Guid.NewGuid().ToString("N"),
            RenderProfile.Balanced, OutputAspect.InheritFirst,
            fourScreen: new FourScreenEffectPlan(1, mode), fourScreenSourceAssets: [asset]));

        Assert.True(request.HasRenderableEffects);
        Assert.Equal(4, Assert.Single(Assert.IsType<FourScreenEffectPlan>(request.FourScreen).ClipSelections).Cells.Count);
    }

    [Fact]
    public void Factory_rejects_simultaneous_double_and_four_screen()
    {
        Assert.Throws<ArgumentException>(() => RenderRequestFactory.CreateForPlans(
            [Plan(Asset(Path.Combine(Path.GetTempPath(), "four-main.mp4")))],
            Path.GetTempPath(), "four-" + Guid.NewGuid().ToString("N"),
            RenderProfile.Balanced, OutputAspect.InheritFirst,
            doubleScreen: new DoubleScreenEffectPlan(1), fourScreen: new FourScreenEffectPlan(1)));
    }

    [Fact]
    public void Preflight_rejects_missing_or_duplicate_four_screen_cells()
    {
        using var files = new FourScreenFiles();
        var plan = Plan(Asset(files.Main));
        var effect = new FourScreenEffectPlan(1).MaterializeForPlan(plan, [], 0).Value!;
        var request = Request(plan, effect);
        Assert.True(RenderPreflight.CheckInputs(request).IsSuccess);

        Assert.False(RenderPreflight.CheckInputs(request with { FourScreen = effect with { ClipSelections = [] } }).IsSuccess);
        var selection = effect.ClipSelections[0];
        var duplicate = selection with { Cells = [selection.Cells[0], selection.Cells[0], selection.Cells[2], selection.Cells[3]] };
        Assert.False(RenderPreflight.CheckInputs(request with { FourScreen = effect with { ClipSelections = [duplicate] } }).IsSuccess);
    }

    [Fact]
    public void Preflight_reports_missing_auxiliary_file()
    {
        using var files = new FourScreenFiles();
        var main = Asset(files.Main);
        var missing = Asset(Path.Combine(files.Root, "missing.mp4"));
        var plan = Plan(main);
        var effect = new FourScreenEffectPlan(1, FourScreenSourceMode.RandomCurrentFolder)
            .MaterializeForPlan(plan, [main, missing], 0).Value!;

        var result = RenderPreflight.CheckInputs(Request(plan, effect));

        Assert.False(result.IsSuccess);
        Assert.Contains("四屏", result.Error, StringComparison.Ordinal);
        Assert.Contains("missing.mp4", result.Error, StringComparison.Ordinal);
    }

    [Fact]
    public void Template_round_trip_preserves_four_screen_and_old_json_keeps_it_disabled()
    {
        const string json = """
            {"variationIntensityPercent":90,"fourScreen":{"enabled":true,"startClipIndex":2,"useRandomCurrentFolder":true,"featherEnabled":false,"featherPixels":32}}
            """;
        var document = JsonSerializer.SerializeToNode(JsonSerializer.Deserialize<EffectTemplateSettingsDto>(json));
        Assert.Equal(true, document!["fourScreen"]?["enabled"]?.GetValue<bool>());
        var legacy = JsonSerializer.SerializeToNode(JsonSerializer.Deserialize<EffectTemplateSettingsDto>("{}"));
        Assert.NotEqual(true, legacy!["fourScreen"]?["enabled"]?.GetValue<bool>());
        Assert.Equal(1, EffectTemplateDocument.CurrentSchemaVersion);
    }

    private static RenderRequest Request(CompositionPlan plan, FourScreenEffectPlan effect) =>
        new(plan, Path.Combine(Path.GetTempPath(), "out.mp4"), RenderProfile.Balanced,
            OutputAspect.InheritFirst, [], HasEffects: true, FourScreen: effect);

    private static MediaAsset Asset(string path) => new(Guid.NewGuid(), path, 1,
        new MediaInfo(TimeSpan.FromSeconds(1), 320, 240, 30m, "h264", "aac", true, 0));

    private static CompositionPlan Plan(MediaAsset asset) => new(
        [new PlannedClip(asset, TimeSpan.Zero, TimeSpan.FromSeconds(1))], TimeSpan.FromSeconds(1), 42, TimeSpan.Zero);

    private sealed class FourScreenFiles : IDisposable
    {
        public string Root { get; } = Path.Combine(Path.GetTempPath(), "jingxu-four-inputs-" + Guid.NewGuid().ToString("N"));
        public string Main => Path.Combine(Root, "main.mp4");

        public FourScreenFiles()
        {
            Directory.CreateDirectory(Root);
            File.WriteAllText(Main, "fixture");
        }

        public void Dispose() => Directory.Delete(Root, recursive: true);
    }
}
