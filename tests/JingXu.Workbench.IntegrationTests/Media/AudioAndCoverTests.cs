using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class AudioAndCoverTests
{
    [Fact]
    public async Task Bgm_mix_preserves_source_segment_and_adds_background_tone()
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

        var plan = MediaIntegrationHarness.BuildCustomPlan(assets, [1, 2]);
        var bgmPath = Path.Combine(fixtureDir, "bgm.m4a");
        await LavfiMediaFactory.GenerateBgmToneAsync(
            ffmpegPath,
            bgmPath,
            frequencyHz: 880,
            duration: plan.Duration + TimeSpan.FromSeconds(1));

        var bgm = BgmMixPlan.Create(bgmPath, originalVolume: 0.85, bgmVolume: 0.2).Value!;
        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "bgm-mix.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            bgm: bgm);

        var firstMid = MediaIntegrationHarness.SegmentMidpoint(plan, 0);
        var firstFrequency = await MediaSampleAnalyzer.SampleDominantFrequencyAsync(
            ffmpegPath,
            outputPath,
            firstMid,
            TimeSpan.FromMilliseconds(500));
        Assert.InRange(firstFrequency, 160, 340);

        var bgmDominant = await MediaSampleAnalyzer.SampleDominantFrequencyAsync(
            ffmpegPath,
            outputPath,
            TimeSpan.FromMilliseconds(250),
            TimeSpan.FromMilliseconds(500));
        Assert.True(bgmDominant is >= 840 and <= 920 or >= 160 and <= 340);
    }

    [Fact]
    public async Task No_audio_inputs_still_render_with_synthetic_audio()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);

        var fixtureDir = Path.Combine(workspace.Root, "fixtures-silent");
        Directory.CreateDirectory(fixtureDir);
        var silentPath = Path.Combine(fixtureDir, "1.mp4");
        await LavfiMediaFactory.GenerateSilentClipAsync(
            ffmpegPath,
            silentPath,
            "purple",
            TimeSpan.FromSeconds(2));

        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var info = await probe.ProbeAsync(silentPath, default);
        Assert.False(info.HasAudio);

        var asset = new JingXu.Workbench.Domain.Media.MediaAsset(
            Guid.NewGuid(),
            silentPath,
            1,
            info);
        var planResult = CompositionPlanner.PlanCustom([asset], [1], TimeSpan.Zero);
        Assert.True(planResult.IsSuccess);
        var plan = planResult.Value!;

        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "silent.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst);

        var outputInfo = await probe.ProbeAsync(outputPath, default);
        Assert.True(outputInfo.HasAudio);
        Assert.InRange(outputInfo.Duration.TotalMilliseconds, 1700, 2300);
    }

    [Fact]
    public async Task First_source_frame_cover_matches_opening_segment_color()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);

        var fixtureDir = Path.Combine(workspace.Root, "fixtures-cover");
        var assets = await MediaIntegrationHarness.GenerateFixtureClipsAsync(
            ffmpegPath,
            workspace.AppRoot,
            fixtureDir,
            TimeSpan.FromSeconds(2));

        var plan = MediaIntegrationHarness.BuildCustomPlan(assets, [2, 1]);
        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "cover-first.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst);

        var coverPath = Path.Combine(workspace.Root, "cover-first.jpg");
        var coverResult = await CoverGenerator.GenerateAsync(
            ffmpegPath,
            CoverMode.FirstSourceFrame,
            outputPath,
            plan.Clips[0].Asset.Path,
            coverPath);
        Assert.True(coverResult.IsSuccess, coverResult.Error);

        var coverPixel = MediaSampleAnalyzer.ReadImageCenterPixel(coverPath);
        Assert.Equal(2, Rgb24.ClosestSegmentIndex(coverPixel));
    }

    [Fact]
    public async Task Final_output_frame_cover_matches_last_segment_color()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);

        var fixtureDir = Path.Combine(workspace.Root, "fixtures-cover-final");
        var assets = await MediaIntegrationHarness.GenerateFixtureClipsAsync(
            ffmpegPath,
            workspace.AppRoot,
            fixtureDir,
            TimeSpan.FromSeconds(2));

        var plan = MediaIntegrationHarness.BuildCustomPlan(assets, [2, 1]);
        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "cover-final.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst);

        var coverPath = Path.Combine(workspace.Root, "cover-final.jpg");
        var coverResult = await CoverGenerator.GenerateAsync(
            ffmpegPath,
            CoverMode.FinalOutputFrame,
            outputPath,
            firstSourcePath: null,
            coverPath);
        Assert.True(coverResult.IsSuccess, coverResult.Error);

        var coverPixel = MediaSampleAnalyzer.ReadImageCenterPixel(coverPath);
        Assert.Equal(1, Rgb24.ClosestSegmentIndex(coverPixel));
    }
}
