using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class RenderCacheLifecycleTests
{
    [Theory]
    [InlineData(VideoProcessingMode.Cpu)]
    [InlineData(VideoProcessingMode.Gpu)]
    public async Task Repeated_four_screen_jobs_reclaim_staging_and_keep_all_exports(VideoProcessingMode mode)
    {
        var (ffmpeg, ffprobe) = MediaIntegrationHarness.RequireFfmpeg();
        VideoEncoderSelection? selected = null;
        if (mode == VideoProcessingMode.Gpu)
        {
            selected = await new HardwareVideoEncoderSelector(new ExternalProcessRunner()).SelectAsync(ffmpeg, mode, default);
            if (selected.Kind == VideoEncoderKind.Libx264) { Assert.Skip("本机没有可用硬件编码器。"); }
        }

        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpeg, ffprobe);
        var source = Path.Combine(workspace.Root, "source.mp4");
        await LavfiMediaFactory.GenerateToneClipAsync(ffmpeg, source, 1, "blue", 440, TimeSpan.FromSeconds(1));
        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var asset = new MediaAsset(Guid.NewGuid(), source, 1, await probe.ProbeAsync(source, default));
        var plan = new CompositionPlan([new PlannedClip(asset, TimeSpan.Zero, asset.Info.Duration)], asset.Info.Duration, 42, TimeSpan.Zero);
        var output = Path.Combine(workspace.Root, "output");
        var executor = MediaIntegrationHarness.CreateExecutor(workspace);
        for (var index = 0; index < 8; index++)
        {
            var request = RenderRequestFactory.CreateForPlans([plan], output, "batch-" + index, RenderProfile.Balanced,
                OutputAspect.InheritFirst, fourScreen: new FourScreenEffectPlan(1))[0] with { ProcessingMode = mode };
            var result = await executor.ExecuteAsync(RenderJob.CreateQueued(request), null, default);
            Assert.True(result.IsSuccess, result.FailureInfo?.Message);
            if (selected is not null) { Assert.Contains(selected.DisplayName, result.Notice, StringComparison.Ordinal); }
            Assert.True(File.Exists(request.OutputPath));
            var staging = Path.Combine(output, ".jingxu-tmp");
            Assert.True(!Directory.Exists(staging) || !Directory.EnumerateFileSystemEntries(staging).Any());
            Assert.False(TempResourceLease.IsInUse(staging));
        }

        Assert.Equal(8, Directory.GetFiles(output, "*.mp4", SearchOption.TopDirectoryOnly).Length);
        Assert.True(File.Exists(source));
    }
}
