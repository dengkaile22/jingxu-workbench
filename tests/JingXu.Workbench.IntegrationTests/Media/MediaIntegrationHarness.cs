using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;

namespace JingXu.Workbench.IntegrationTests.Media;

/// <summary>媒体集成测试的 FFmpeg 运行时与渲染执行辅助。</summary>
internal static class MediaIntegrationHarness
{
    public static (string FfmpegPath, string FfprobePath) RequireFfmpeg()
    {
        var ffmpegPath = FfmpegRuntimeProbe.FindFfmpeg();
        var ffprobePath = FfmpegRuntimeProbe.FindFfprobe();
        if (ffmpegPath is null || ffprobePath is null)
        {
            Assert.Skip("本机未找到 FFmpeg/FFprobe，跳过媒体集成测试。");
        }

        return (ffmpegPath, ffprobePath);
    }

    public static MediaWorkspace CreateWorkspace()
    {
        var root = Path.Combine(Path.GetTempPath(), "jingxu-media-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var appRoot = Path.Combine(root, "app");
        Directory.CreateDirectory(appRoot);
        return new MediaWorkspace(root, appRoot);
    }

    public static void InstallBundledRuntime(MediaWorkspace workspace, string ffmpegPath, string ffprobePath)
    {
        var runtimeDir = Path.Combine(workspace.AppRoot, "runtime", "ffmpeg");
        Directory.CreateDirectory(runtimeDir);
        File.Copy(ffmpegPath, Path.Combine(runtimeDir, "ffmpeg.exe"), overwrite: true);
        File.Copy(ffprobePath, Path.Combine(runtimeDir, "ffprobe.exe"), overwrite: true);
    }

    public static IRenderExecutor CreateExecutor(MediaWorkspace workspace) =>
        RenderInfrastructure.CreateFfmpegRenderExecutor(workspace.AppRoot);

    public static async Task<IReadOnlyList<MediaAsset>> GenerateFixtureClipsAsync(
        string ffmpegPath,
        string appRoot,
        string directory,
        TimeSpan clipDuration,
        CancellationToken cancellationToken = default)
    {
        Directory.CreateDirectory(directory);
        var assets = new List<MediaAsset>(MediaFixtureCatalog.Segments.Count);
        var probe = RenderInfrastructure.CreateMediaProbe(appRoot);

        foreach (var (sequenceIndex, segment) in MediaFixtureCatalog.Segments.OrderBy(x => x.Key))
        {
            var path = Path.Combine(directory, MediaFixtureCatalog.ClipFileName(sequenceIndex));
            await LavfiMediaFactory.GenerateToneClipAsync(
                ffmpegPath,
                path,
                sequenceIndex,
                segment.LavfiColor,
                segment.FrequencyHz,
                clipDuration,
                cancellationToken);

            var info = await probe.ProbeAsync(path, cancellationToken);
            assets.Add(new MediaAsset(Guid.NewGuid(), path, sequenceIndex, info));
        }

        return assets;
    }

    public static CompositionPlan BuildCustomPlan(
        IReadOnlyList<MediaAsset> assets,
        IReadOnlyList<int> sequenceOrder)
    {
        var planResult = CompositionPlanner.PlanCustom(assets, sequenceOrder, TimeSpan.Zero);
        Assert.True(planResult.IsSuccess, planResult.Error);
        return planResult.Value!;
    }

    public static CompositionPlan Build264513Plan(IReadOnlyList<MediaAsset> assets)
    {
        var indices = FileSequenceParser.Parse(MediaFixtureCatalog.CustomSequenceExpression);
        Assert.True(indices.IsSuccess);
        Assert.Equal(MediaFixtureCatalog.CustomSequenceOrder, indices.Value);
        return BuildCustomPlan(assets, indices.Value!);
    }

    public static async Task<string> RenderPlanAsync(
        MediaWorkspace workspace,
        CompositionPlan plan,
        string outputFileName,
        RenderProfile profile,
        OutputAspect aspect,
        IReadOnlyList<OverlayLayer>? overlays = null,
        BgmMixPlan? bgm = null,
        IReadOnlyList<ImageSticker>? stickers = null,
        CancellationToken cancellationToken = default)
    {
        var outputDir = Path.Combine(workspace.Root, "output");
        Directory.CreateDirectory(outputDir);
        var outputPath = Path.Combine(outputDir, outputFileName);

        var requests = RenderRequestFactory.CreateForPlans(
            [plan],
            outputDir,
            Path.GetFileNameWithoutExtension(outputFileName),
            profile,
            aspect,
            overlays,
            effectTemplate: null,
            bgm,
            stickers ?? []);

        var request = requests[0] with { OutputPath = outputPath };
        var executor = CreateExecutor(workspace);
        var job = RenderJob.CreateQueued(request);
        var result = await executor.ExecuteAsync(job, progress: null, cancellationToken);
        Assert.True(result.IsSuccess, result.FailureInfo?.Message ?? "渲染失败。");
        Assert.True(File.Exists(outputPath));
        return outputPath;
    }

    public static TimeSpan SegmentMidpoint(CompositionPlan plan, int segmentIndex)
    {
        var clip = plan.Clips[segmentIndex];
        return clip.Start + TimeSpan.FromTicks(clip.Duration.Ticks / 2);
    }
}

internal sealed class MediaWorkspace(string root, string appRoot) : IDisposable
{
    public string Root { get; } = root;

    public string AppRoot { get; } = appRoot;

    public void Dispose()
    {
        try { Directory.Delete(Root, recursive: true); }
        catch (IOException) { }
    }
}
