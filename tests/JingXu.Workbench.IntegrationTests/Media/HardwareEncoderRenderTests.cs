using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class HardwareEncoderRenderTests
{
    [Fact]
    public async Task Cpu_mode_renders_with_libx264()
    {
        var fixture = await CreateFixtureAsync();
        using var workspace = fixture.Workspace;

        var rendered = await RenderAsync(
            workspace,
            fixture.Asset,
            VideoProcessingMode.Cpu,
            "cpu.mp4");

        Assert.True(rendered.Result.IsSuccess, rendered.Result.FailureInfo?.Message);
        Assert.True(File.Exists(rendered.OutputPath));
        Assert.Contains("CPU（libx264）", rendered.Result.Notice, StringComparison.Ordinal);
        var outputInfo = await RenderInfrastructure.CreateMediaProbe(workspace.AppRoot)
            .ProbeAsync(rendered.OutputPath, default);
        Assert.True(outputInfo.Duration >= TimeSpan.FromMilliseconds(750));
    }

    [Fact]
    public async Task Gpu_mode_renders_with_detected_hardware_encoder_when_available()
    {
        var (ffmpegPath, _) = MediaIntegrationHarness.RequireFfmpeg();
        var selector = new HardwareVideoEncoderSelector(new ExternalProcessRunner());
        var selection = await selector.SelectAsync(
            ffmpegPath,
            VideoProcessingMode.Gpu,
            default);
        if (selection.Kind == VideoEncoderKind.Libx264)
        {
            Assert.Skip("本机没有可用硬件 H.264 编码器。");
            return;
        }

        var fixture = await CreateFixtureAsync();
        using var workspace = fixture.Workspace;
        var rendered = await RenderAsync(
            workspace,
            fixture.Asset,
            VideoProcessingMode.Gpu,
            "gpu.mp4");

        Assert.True(rendered.Result.IsSuccess, rendered.Result.FailureInfo?.Message);
        Assert.True(File.Exists(rendered.OutputPath));
        Assert.Contains(selection.DisplayName, rendered.Result.Notice, StringComparison.Ordinal);
        var outputInfo = await RenderInfrastructure.CreateMediaProbe(workspace.AppRoot)
            .ProbeAsync(rendered.OutputPath, default);
        Assert.True(outputInfo.Duration >= TimeSpan.FromMilliseconds(750));
    }

    private static async Task<(MediaWorkspace Workspace, MediaAsset Asset)> CreateFixtureAsync()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        var workspace = MediaIntegrationHarness.CreateWorkspace();
        try
        {
            MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);
            var inputPath = Path.Combine(workspace.Root, "input.mp4");
            await LavfiMediaFactory.GenerateToneClipAsync(
                ffmpegPath,
                inputPath,
                sequenceIndex: 1,
                color: "blue",
                frequencyHz: 440,
                duration: TimeSpan.FromSeconds(1));
            var info = await RenderInfrastructure.CreateMediaProbe(workspace.AppRoot)
                .ProbeAsync(inputPath, default);
            return (workspace, new MediaAsset(Guid.NewGuid(), inputPath, 1, info));
        }
        catch
        {
            workspace.Dispose();
            throw;
        }
    }

    private static async Task<RenderedFixture> RenderAsync(
        MediaWorkspace workspace,
        MediaAsset asset,
        VideoProcessingMode mode,
        string outputFileName)
    {
        var plan = new CompositionPlan(
            [new PlannedClip(asset, TimeSpan.Zero, asset.Info.Duration)],
            asset.Info.Duration,
            Seed: 42,
            TimeSpan.Zero);
        var outputDirectory = Path.Combine(workspace.Root, "output");
        Directory.CreateDirectory(outputDirectory);
        var outputPath = Path.Combine(outputDirectory, outputFileName);
        var request = new RenderRequest(
            plan,
            outputPath,
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            [],
            ProcessingMode: mode);
        var job = RenderJob.CreateQueued(request);
        var result = await MediaIntegrationHarness.CreateExecutor(workspace)
            .ExecuteAsync(job, progress: null, default);
        var logPath = Path.Combine(
            outputDirectory,
            ".jingxu-tmp",
            job.Id.ToString("N"),
            "render.log");
        return new RenderedFixture(outputPath, logPath, result);
    }

    private sealed record RenderedFixture(
        string OutputPath,
        string LogPath,
        JingXu.Workbench.Application.Abstractions.RenderExecutionResult Result);
}
