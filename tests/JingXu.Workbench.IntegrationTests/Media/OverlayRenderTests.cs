using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class OverlayRenderTests
{
    [Fact]
    public async Task Three_overlay_modes_appear_from_start_clip_through_final_frame()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);

        var fixtureDir = Path.Combine(workspace.Root, "fixtures");
        var assets = await MediaIntegrationHarness.GenerateFixtureClipsAsync(
            ffmpegPath,
            workspace.AppRoot,
            fixtureDir,
            TimeSpan.FromSeconds(2));

        var plan = MediaIntegrationHarness.BuildCustomPlan(assets, [1, 2, 3]);
        var overlayClip = Path.Combine(fixtureDir, "overlay.mp4");
        await LavfiMediaFactory.GenerateColorClipAsync(
            ffmpegPath,
            overlayClip,
            "orange",
            TimeSpan.FromSeconds(1));

        var overlayInfo = await RenderInfrastructure.CreateMediaProbe(workspace.AppRoot)
            .ProbeAsync(overlayClip, default);

        await AssertFreeCoverAsync(workspace, plan, overlayClip, overlayInfo, ffmpegPath);
        await AssertFullFrameAsync(workspace, plan, overlayClip, overlayInfo, ffmpegPath);
        await AssertShapeMaskAsync(workspace, plan, overlayClip, overlayInfo, ffmpegPath);
    }

    [Fact]
    public async Task Higher_z_index_overlay_wins_at_overlap()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);

        var fixtureDir = Path.Combine(workspace.Root, "fixtures-z");
        var assets = await MediaIntegrationHarness.GenerateFixtureClipsAsync(
            ffmpegPath,
            workspace.AppRoot,
            fixtureDir,
            TimeSpan.FromSeconds(2));

        var plan = MediaIntegrationHarness.BuildCustomPlan(assets, [1]);
        var lowClip = Path.Combine(fixtureDir, "low.mp4");
        var highClip = Path.Combine(fixtureDir, "high.mp4");
        await LavfiMediaFactory.GenerateColorClipAsync(ffmpegPath, lowClip, "blue", TimeSpan.FromSeconds(1));
        await LavfiMediaFactory.GenerateColorClipAsync(ffmpegPath, highClip, "red", TimeSpan.FromSeconds(1));

        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var lowInfo = await probe.ProbeAsync(lowClip, default);
        var highInfo = await probe.ProbeAsync(highClip, default);

        var lowLayer = OverlayLayer.CreateFullFramePreset(lowClip, lowInfo.Duration) with
        {
            Name = "低层",
            ZIndex = 0,
            Opacity = 0.9
        };
        var highLayer = OverlayLayer.CreateFullFramePreset(highClip, highInfo.Duration) with
        {
            Name = "高层",
            ZIndex = 5,
            Opacity = 0.9
        };

        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "zindex.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            overlays: [lowLayer, highLayer]);

        var pixel = await MediaSampleAnalyzer.SampleCenterPixelAsync(
            ffmpegPath,
            outputPath,
            TimeSpan.FromMilliseconds(500));
        Assert.True(pixel.R > pixel.B, $"高层蒙版应覆盖低层，实际 RGB({pixel.R},{pixel.G},{pixel.B})。");
    }

    [Fact]
    public async Task Unicode_and_space_paths_render_successfully()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);

        var fixtureDir = Path.Combine(workspace.Root, "素材 目录", "分镜 01");
        Directory.CreateDirectory(fixtureDir);
        var assets = await MediaIntegrationHarness.GenerateFixtureClipsAsync(
            ffmpegPath,
            workspace.AppRoot,
            fixtureDir,
            TimeSpan.FromSeconds(1.5));

        var plan = MediaIntegrationHarness.BuildCustomPlan(assets, [2, 1]);
        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "unicode 成片.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst);

        var midpoint = MediaIntegrationHarness.SegmentMidpoint(plan, 0);
        var pixel = await MediaSampleAnalyzer.SampleCenterPixelAsync(ffmpegPath, outputPath, midpoint);
        Assert.Equal(2, Rgb24.ClosestSegmentIndex(pixel));
    }

    private static async Task AssertFreeCoverAsync(
        MediaWorkspace workspace,
        CompositionPlan plan,
        string overlayClip,
        JingXu.Workbench.Domain.Media.MediaInfo overlayInfo,
        string ffmpegPath)
    {
        var layer = OverlayLayer.CreateScreenshotPreset(overlayClip, overlayInfo.Duration) with
        {
            Name = "自由覆盖",
            StartClipIndex = 2,
            ZIndex = 0
        };

        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "overlay-free.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            overlays: [layer]);

        var beforeOverlay = MediaIntegrationHarness.SegmentMidpoint(plan, 0);
        var beforePixel = await MediaSampleAnalyzer.SampleCenterPixelAsync(ffmpegPath, outputPath, beforeOverlay);
        Assert.Equal(1, Rgb24.ClosestSegmentIndex(beforePixel));

        var duringOverlay = plan.Clips[1].Start + TimeSpan.FromMilliseconds(500);
        var duringPixel = await MediaSampleAnalyzer.SamplePixelAsync(ffmpegPath, outputPath, duringOverlay, x: 160, y: 48);
        Assert.NotEqual(2, Rgb24.ClosestSegmentIndex(duringPixel));
    }

    private static async Task AssertFullFrameAsync(
        MediaWorkspace workspace,
        CompositionPlan plan,
        string overlayClip,
        JingXu.Workbench.Domain.Media.MediaInfo overlayInfo,
        string ffmpegPath)
    {
        var layer = OverlayLayer.CreateFullFramePreset(overlayClip, overlayInfo.Duration) with
        {
            Name = "全屏低透明",
            StartClipIndex = 1,
            ZIndex = 0
        };

        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "overlay-full.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            overlays: [layer]);

        var midpoint = MediaIntegrationHarness.SegmentMidpoint(plan, 1);
        var pixel = await MediaSampleAnalyzer.SampleCenterPixelAsync(ffmpegPath, outputPath, midpoint);
        Assert.True(pixel.R > 25, "全屏低透明蒙版应使画面混入橙色（抬高红色通道）。");

        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var duration = (await probe.ProbeAsync(outputPath, default)).Duration;
        var finalPixel = await MediaSampleAnalyzer.SampleCenterPixelAsync(
            ffmpegPath,
            outputPath,
            duration - TimeSpan.FromMilliseconds(200));
        Assert.True(finalPixel.R > 25, "末帧仍应保留全屏蒙版的橙色混合。");
    }

    private static async Task AssertShapeMaskAsync(
        MediaWorkspace workspace,
        CompositionPlan plan,
        string overlayClip,
        JingXu.Workbench.Domain.Media.MediaInfo overlayInfo,
        string ffmpegPath)
    {
        var layer = OverlayLayer.CreateShapeMask(
            overlayClip,
            overlayInfo.Duration,
            NormalizedRect.Create(0.25, 0.25, 0.5, 0.5).Value!,
            ShapeKind.Rectangle) with
        {
            Name = "形状遮罩",
            StartClipIndex = 2,
            ZIndex = 0
        };

        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "overlay-shape.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            overlays: [layer]);

        var sampleTime = plan.Clips[1].Start + TimeSpan.FromMilliseconds(500);
        var centerPixel = await MediaSampleAnalyzer.SampleCenterPixelAsync(ffmpegPath, outputPath, sampleTime);
        var edgePixel = await MediaSampleAnalyzer.SamplePixelAsync(ffmpegPath, outputPath, sampleTime, x: 8, y: 8);
        Assert.NotEqual(Rgb24.ClosestSegmentIndex(centerPixel), Rgb24.ClosestSegmentIndex(edgePixel));
    }
}
