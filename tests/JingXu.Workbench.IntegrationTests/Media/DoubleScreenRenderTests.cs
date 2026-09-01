using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class DoubleScreenRenderTests
{
    [Fact]
    public async Task Random_double_screen_renders_a_six_clip_batch_with_bundled_ffmpeg()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);

        var fixtureDir = Path.Combine(workspace.Root, "fixtures-double-screen");
        var assets = await MediaIntegrationHarness.GenerateFixtureClipsAsync(
            ffmpegPath,
            workspace.AppRoot,
            fixtureDir,
            TimeSpan.FromSeconds(1));

        var auxiliaryPath = Path.Combine(fixtureDir, "random-auxiliary.mp4");
        await LavfiMediaFactory.GenerateColorClipAsync(
            ffmpegPath,
            auxiliaryPath,
            "orange",
            TimeSpan.FromSeconds(1));
        var auxiliaryInfo = await RenderInfrastructure.CreateMediaProbe(workspace.AppRoot)
            .ProbeAsync(auxiliaryPath, default);
        var auxiliary = new MediaAsset(Guid.NewGuid(), auxiliaryPath, 99, auxiliaryInfo);
        var sourceAssets = assets.Append(auxiliary).ToArray();

        var plan = MediaIntegrationHarness.BuildCustomPlan(assets, [1, 2, 3, 4, 5, 6]);
        var doubleScreen = new DoubleScreenEffectPlan(
            StartClipIndex: 2,
            SourceMode: DoubleScreenSourceMode.RandomCurrentFolder,
            PlacementMode: DoubleScreenPlacementMode.Bottom,
            FeatherEnabled: true,
            FeatherPixels: 64);
        var outputDirectory = Path.Combine(workspace.Root, "output");
        Directory.CreateDirectory(outputDirectory);
        var outputPath = Path.Combine(outputDirectory, "double-screen-batch.mp4");
        var request = RenderRequestFactory.CreateForPlans(
            [plan],
            outputDirectory,
            "double-screen-batch",
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            doubleScreen: doubleScreen,
            doubleScreenSourceAssets: sourceAssets)[0] with
        {
            OutputPath = outputPath
        };

        var job = RenderJob.CreateQueued(request);
        var result = await MediaIntegrationHarness.CreateExecutor(workspace)
            .ExecuteAsync(job, progress: null, default);
        var logPath = Path.Combine(
            outputDirectory,
            ".jingxu-tmp",
            job.Id.ToString("N"),
            "render.log");

        Assert.True(
            result.IsSuccess,
            result.FailureInfo?.Message + Environment.NewLine +
            (File.Exists(logPath) ? File.ReadAllText(logPath) : "未找到 render.log"));
        Assert.True(File.Exists(outputPath));
        var outputInfo = await RenderInfrastructure.CreateMediaProbe(workspace.AppRoot)
            .ProbeAsync(outputPath, default);
        Assert.Equal(320, outputInfo.Width);
        Assert.Equal(240, outputInfo.Height);
        Assert.InRange(outputInfo.Duration.TotalSeconds, 5.5, 6.5);
    }
}
