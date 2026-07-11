using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class CompositionRenderTests
{
    [Fact]
    public async Task Custom_264513_preserves_color_and_audio_segment_order()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);

        var clipDuration = TimeSpan.FromSeconds(2);
        var fixtureDir = Path.Combine(workspace.Root, "fixtures");
        var assets = await MediaIntegrationHarness.GenerateFixtureClipsAsync(
            ffmpegPath,
            workspace.AppRoot,
            fixtureDir,
            clipDuration);

        var plan = MediaIntegrationHarness.Build264513Plan(assets);
        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "264513.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst);

        for (var segmentIndex = 0; segmentIndex < plan.Clips.Count; segmentIndex++)
        {
            var sequenceIndex = plan.Clips[segmentIndex].Asset.SequenceIndex!.Value;
            var expected = MediaFixtureCatalog.SegmentFor(sequenceIndex);
            var midpoint = MediaIntegrationHarness.SegmentMidpoint(plan, segmentIndex);

            var pixel = await MediaSampleAnalyzer.SampleCenterPixelAsync(ffmpegPath, outputPath, midpoint);
            Assert.Equal(sequenceIndex, Rgb24.ClosestSegmentIndex(pixel));

            var frequency = await MediaSampleAnalyzer.SampleDominantFrequencyAsync(
                ffmpegPath,
                outputPath,
                midpoint,
                TimeSpan.FromMilliseconds(500));
            Assert.InRange(frequency, expected.FrequencyHz - 40, expected.FrequencyHz + 40);
        }
    }

    [Fact]
    [Trait("Category", "LongRunning")]
    public async Task Six_by_thirty_second_hard_cut_matches_expected_duration()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);

        var clipDuration = TimeSpan.FromSeconds(30);
        var fixtureDir = Path.Combine(workspace.Root, "fixtures-long");
        var assets = await MediaIntegrationHarness.GenerateFixtureClipsAsync(
            ffmpegPath,
            workspace.AppRoot,
            fixtureDir,
            clipDuration);

        var indices = FileSequenceParser.Parse("1,2,3,4,5,6");
        Assert.True(indices.IsSuccess);
        var planResult = CompositionPlanner.PlanCustom(assets, indices.Value!, TimeSpan.Zero);
        Assert.True(planResult.IsSuccess);
        var plan = planResult.Value!;

        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "six-by-thirty.mp4",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst);

        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var info = await probe.ProbeAsync(outputPath, default);

        var expected = TimeSpan.FromSeconds(180);
        var frameTolerance = TimeSpan.FromSeconds(1.0 / 24.0);
        var tolerance = TimeSpan.FromMilliseconds(Math.Max(frameTolerance.TotalMilliseconds, 100));
        var delta = (info.Duration - expected).Duration();
        Assert.True(
            delta <= tolerance,
            $"六段 30 秒硬切时长应为约 180 秒，实际 {info.Duration.TotalSeconds:0.###} 秒。");
    }
}
