using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;
using JingXu.Workbench.Infrastructure.Media;

namespace JingXu.Workbench.IntegrationTests.Media;

/// <summary>客户素材（桌面风扇 + 赵雨蒙版）真机短渲染验收。</summary>
public sealed class CustomerAssetAcceptanceTests
{
    [Fact]
    [Trait("Category", "Acceptance")]
    public async Task Fan_clips_with_zhaoyu_mask_unified_aspect_short_render()
    {
        var (ffmpegPath, ffprobePath) = MediaIntegrationHarness.RequireFfmpeg();
        var assetsRoot = ResolveCustomerAssetsRoot();
        if (assetsRoot is null)
        {
            Assert.Skip("未找到 test-assets 客户素材目录，跳过真机验收。");
        }

        var clipPaths = ResolveFanClips(assetsRoot, count: 3);
        var maskPath = ResolveMaskClip(assetsRoot);
        if (clipPaths.Count < 3 || maskPath is null)
        {
            Assert.Skip("未找到风扇 1-3 或赵雨蒙版素材，跳过真机验收。");
        }

        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpegPath, ffprobePath);
        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);

        var assets = new List<MediaAsset>(clipPaths.Count);
        foreach (var path in clipPaths)
        {
            var info = await probe.ProbeAsync(path, default);
            var index = FileSequenceParser.ExtractIndex(Path.GetFileName(path)).Value;
            assets.Add(new MediaAsset(Guid.NewGuid(), path, index, info));
        }

        var plan = MediaIntegrationHarness.BuildCustomPlan(assets, [1, 2, 3]);
        var maskInfo = await probe.ProbeAsync(maskPath, default);
        var maskLayer = OverlayLayer.CreateScreenshotPreset(maskPath, maskInfo.Duration) with
        {
            Name = "赵雨蒙版",
            Scale = 0.95,
            OffsetY = 0.02,
            RotationDegrees = 5,
            Feather = 0.15,
            Fit = OverlayFitMode.Contain
        };

        var aspect = OutputAspect.Custom(1080, 1920, AspectFitMode.CenterCrop);
        var outputPath = await MediaIntegrationHarness.RenderPlanAsync(
            workspace,
            plan,
            "acceptance-fan-zhaoyu.mp4",
            RenderProfile.Balanced,
            aspect,
            overlays: [maskLayer]);

        var outputInfo = await probe.ProbeAsync(outputPath, default);
        Assert.Equal(1080, outputInfo.Width);
        Assert.Equal(1920, outputInfo.Height);
        Assert.True(outputInfo.Duration > TimeSpan.Zero);
        Assert.True(new FileInfo(outputPath).Length > 100_000);
    }

    private static string? ResolveCustomerAssetsRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "test-assets");
            if (Directory.Exists(candidate))
            {
                return candidate;
            }

            dir = dir.Parent;
        }

        return null;
    }

    private static List<string> ResolveFanClips(string assetsRoot, int count)
    {
        var clips = new List<string>(count);
        for (var i = 1; i <= count; i++)
        {
            var match = Directory.EnumerateFiles(assetsRoot, $"{i}.mp4", SearchOption.AllDirectories)
                .OrderBy(p => p.Length)
                .FirstOrDefault();
            if (match is not null)
            {
                clips.Add(match);
            }
        }

        return clips;
    }

    private static string? ResolveMaskClip(string assetsRoot) =>
        Directory.EnumerateFiles(assetsRoot, "*.mp4", SearchOption.AllDirectories)
            .Where(p => !p.EndsWith("\\1.mp4", StringComparison.OrdinalIgnoreCase)
                        && !p.EndsWith("\\2.mp4", StringComparison.OrdinalIgnoreCase)
                        && !p.EndsWith("\\3.mp4", StringComparison.OrdinalIgnoreCase)
                        && !p.EndsWith("\\4.mp4", StringComparison.OrdinalIgnoreCase)
                        && !p.EndsWith("\\5.mp4", StringComparison.OrdinalIgnoreCase)
                        && !p.EndsWith("\\6.mp4", StringComparison.OrdinalIgnoreCase)
                        && !p.EndsWith("\\7.mp4", StringComparison.OrdinalIgnoreCase)
                        && !p.EndsWith("\\8.mp4", StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(p => new FileInfo(p).Length)
            .FirstOrDefault();
}
