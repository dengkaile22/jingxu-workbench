using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Tests.Rendering;

public sealed class RenderRequestFactoryTests
{
    [Fact]
    public void Single_plan_uses_prefix_without_sequence_suffix()
    {
        var plan = TestPlan();
        var requests = RenderRequestFactory.CreateForPlans(
            [plan],
            @"C:\输出",
            "测试成片",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst);

        var request = Assert.Single(requests);
        Assert.Equal(@"C:\输出\测试成片.mp4", request.OutputPath);
        Assert.Same(plan, request.Plan);
    }

    [Fact]
    public void Batch_plans_receive_numbered_output_paths()
    {
        var plans = new[] { TestPlan(), TestPlan() };
        var requests = RenderRequestFactory.CreateForPlans(
            plans,
            @"C:\输出",
            "混剪",
            RenderProfile.High,
            OutputAspect.InheritFirst);

        Assert.Equal(2, requests.Count);
        Assert.Equal(@"C:\输出\混剪_001.mp4", requests[0].OutputPath);
        Assert.Equal(@"C:\输出\混剪_002.mp4", requests[1].OutputPath);
    }

    [Fact]
    public void Empty_prefix_falls_back_to_default_name()
    {
        var requests = RenderRequestFactory.CreateForPlans(
            [TestPlan()],
            @"C:\输出",
            "   ",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst);

        Assert.Equal(@"C:\输出\混剪成片.mp4", Assert.Single(requests).OutputPath);
    }

    [Fact]
    public void Effect_template_materializes_per_plan_seed()
    {
        var plans = new[] { TestPlan(seed: 1), TestPlan(seed: 2) };
        var requests = RenderRequestFactory.CreateForPlans(
            plans,
            @"C:\输出",
            "成片",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            effectTemplate: EffectTemplates.StandardVariation());

        Assert.Equal(2, requests.Count);
        Assert.True(requests[0].HasEffects);
        Assert.NotNull(requests[0].Effect);
        Assert.NotEqual(requests[0].Effect, requests[1].Effect);
        Assert.Equal(
            EffectTemplates.StandardVariation().Materialize(1),
            requests[0].Effect);
    }

    [Fact]
    public void Bgm_plan_sets_has_bgm_flag()
    {
        var bgm = BgmMixPlan.Create(@"C:\音频\配乐.mp3").Value!;
        var request = Assert.Single(RenderRequestFactory.CreateForPlans(
            [TestPlan()],
            @"C:\输出",
            "成片",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            bgm: bgm));

        Assert.True(request.HasBgm);
        Assert.Equal(@"C:\音频\配乐.mp3", request.Bgm!.Path);
    }

    [Fact]
    public void Sticker_sets_has_effects_without_variation_template()
    {
        var sticker = ImageSticker.Create(
            @"C:\贴纸.png",
            x: 0.1,
            y: 0.2,
            width: 0.3,
            height: 0.25).Value!;
        var request = Assert.Single(RenderRequestFactory.CreateForPlans(
            [TestPlan()],
            @"C:\输出",
            "成片",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            stickers: [sticker]));

        Assert.True(request.HasEffects);
        Assert.Null(request.Effect);
        Assert.Same(sticker, request.Stickers[0]);
    }

    [Fact]
    public void Per_plan_overlay_layers_set_has_overlays_independently()
    {
        var plans = new[] { TestPlan(seed: 1), TestPlan(seed: 2) };
        var layerA = OverlayLayer.CreateScreenshotPreset(@"C:\mask-a.mp4", TimeSpan.FromSeconds(2));
        var layerB = OverlayLayer.CreateFullFramePreset(@"C:\mask-b.mp4", TimeSpan.FromSeconds(2));

        var requests = RenderRequestFactory.CreateForPlans(
            plans,
            @"C:\输出",
            "成片",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            overlayLayersPerPlan: [[layerA], [layerB]],
            sharedOverlayLayers: null);

        Assert.Equal(2, requests.Count);
        Assert.True(requests[0].HasOverlays);
        Assert.True(requests[1].HasOverlays);
        Assert.Equal(@"C:\mask-a.mp4", requests[0].OverlayLayers[0].SourcePath);
        Assert.Equal(@"C:\mask-b.mp4", requests[1].OverlayLayers[0].SourcePath);
    }

    [Fact]
    public void Empty_per_plan_overlay_layers_clear_has_overlays_flag()
    {
        var plan = TestPlan();
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2));
        var requests = RenderRequestFactory.CreateForPlans(
            [plan],
            @"C:\输出",
            "成片",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            overlayLayersPerPlan: [[]],
            sharedOverlayLayers: null);

        var request = Assert.Single(requests);
        Assert.False(request.HasOverlays);
        Assert.Empty(request.OverlayLayers);
    }

    [Fact]
    public void Processing_mode_is_copied_to_every_batch_request()
    {
        var requests = RenderRequestFactory.CreateForPlans(
            [TestPlan(seed: 1), TestPlan(seed: 2)],
            @"C:\输出",
            "成片",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            overlayLayersPerPlan: null,
            sharedOverlayLayers: [],
            processingMode: VideoProcessingMode.Gpu);

        Assert.All(requests, request => Assert.Equal(VideoProcessingMode.Gpu, request.ProcessingMode));
    }

    private static CompositionPlan TestPlan(int seed = 0)
    {
        var asset = new MediaAsset(
            Guid.NewGuid(),
            @"C:\素材\1.mp4",
            1,
            new MediaInfo(TimeSpan.FromSeconds(2), 1080, 1920, 30m, "h264", "aac", true, 0));

        return new CompositionPlan(
            [new PlannedClip(asset, TimeSpan.Zero, asset.Info.Duration)],
            asset.Info.Duration,
            Seed: seed,
            TimeSpan.Zero);
    }
}
