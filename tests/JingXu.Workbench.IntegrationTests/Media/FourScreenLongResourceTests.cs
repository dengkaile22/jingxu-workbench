using System.Diagnostics;
using System.Drawing;
using System.Text.Json;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class FourScreenLongResourceTests
{
    [Theory]
    [InlineData(VideoProcessingMode.Cpu, false)]
    [InlineData(VideoProcessingMode.Gpu, false)]
    [InlineData(VideoProcessingMode.Gpu, true)]
    public async Task Portrait_multiclip_four_screen_with_looped_auxiliary_and_avatar_reaches_last_frame(VideoProcessingMode mode, bool softwareDecode)
    {
        var (ffmpeg, ffprobe) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpeg, ffprobe);
        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var runner = new ExternalProcessRunner();
        var assets = new List<MediaAsset>();
        foreach (var item in new[] { (Name: "main", Filter: "color=c=red:size=1080x1440:rate=30:duration=5"),
                                    (Name: "aux", Filter: "color=c=blue:size=720x960:rate=17:duration=0.5"),
                                    (Name: "avatar", Filter: "color=c=lime:size=320x480:rate=30:duration=2") })
        {
            var path = Path.Combine(workspace.Root, item.Name + ".mp4");
            var generated = await runner.RunAsync(ProcessRequest.Create(ffmpeg,
                ["-y", "-f", "lavfi", "-i", item.Filter, "-c:v", "libx264", "-preset", "ultrafast",
                 "-pix_fmt", "yuv420p", path]), null, default);
            Assert.True(generated.ExitCode == 0, generated.StandardError);
            assets.Add(new MediaAsset(Guid.NewGuid(), path, assets.Count + 1, await probe.ProbeAsync(path, default)));
        }

        var plan = new CompositionPlan(
            [new PlannedClip(assets[0], TimeSpan.Zero, TimeSpan.FromSeconds(5)),
             new PlannedClip(assets[0], TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(5))],
            TimeSpan.FromSeconds(10), 42, TimeSpan.Zero);
        var avatar = OverlayLayer.CreateFullFramePreset(assets[2].Path, plan.Duration) with
        {
            Bounds = new NormalizedRect(.78, .62, .18, .30), Opacity = .95, TopFade = .1, Feather = .05
        };
        var request = RenderRequestFactory.CreateForPlans([plan], workspace.Root, "long-" + mode,
            RenderProfile.Balanced, OutputAspect.InheritFirst,
            fourScreen: new FourScreenEffectPlan(1, FourScreenSourceMode.RandomCurrentFolder),
            fourScreenSourceAssets: assets.Take(2).ToArray())[0] with
        {
            ProcessingMode = mode, HasOverlays = true, OverlayLayers = [avatar]
        };
        var measurement = new MeasuredRenderProcessRunner();
        var executor = RenderInfrastructure.CreateFfmpegRenderExecutor(workspace.AppRoot, runner: measurement,
            processingSelector: softwareDecode ? new SpecifiedProcessingSelector(HardwareVideoProcessingPlan.Software) : null);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var watch = Stopwatch.StartNew();
        var result = await executor.ExecuteAsync(RenderJob.CreateQueued(request), null, timeout.Token);
        watch.Stop();

        var evidence = Path.Combine(Packaging.BuildPaths.RepoRoot, "artifacts", "resource-validation");
        Directory.CreateDirectory(evidence);
        var caseName = mode + (softwareDecode ? "SoftwareDecode" : string.Empty);
        await File.WriteAllTextAsync(Path.Combine(evidence, $"long-{caseName}.log"), measurement.RenderLog);
        Assert.True(result.IsSuccess, result.FailureInfo?.Message ?? "长片段渲染超时或取消");
        var info = await probe.ProbeAsync(request.OutputPath, default);
        Assert.Equal(1080, info.Width);
        Assert.Equal(1440, info.Height);
        Assert.InRange(info.Duration.TotalSeconds, 9.9, 10.15);
        // 合成测试给出宽松的回归上限，用于捕获跨片段无限堆积，不作为真实素材的内存承诺。
        Assert.InRange(measurement.PeakWorkingSetKiB, 1, 2_500L * 1024);
        foreach (var (clipIndex, time) in new[] { (0, "4.8"), (1, "9.8") })
        {
            var path = Path.Combine(workspace.Root, $"tail-{clipIndex}.png");
            var frame = await runner.RunAsync(ProcessRequest.Create(ffmpeg,
                ["-y", "-ss", time, "-i", request.OutputPath, "-frames:v", "1", path]), null, default);
            Assert.True(frame.ExitCode == 0, frame.StandardError);
            using var image = new Bitmap(path);
            foreach (var cell in request.FourScreen!.SelectionFor(clipIndex)!.Cells)
            {
                var position = (int)cell.Position;
                var pixel = image.GetPixel(position % 2 == 0 ? 270 : 700, position < 2 ? 360 : 1080);
                var expected = cell.SourceAsset.Path == assets[0].Path ? new Rgb24(255, 0, 0) : new Rgb24(0, 0, 255);
                Assert.True(new Rgb24(pixel.R, pixel.G, pixel.B).IsCloseTo(expected, 20), $"{mode} 片段 {clipIndex} 四格尾帧颜色错误");
            }

            var avatarPixel = image.GetPixel(940, 1120);
            Assert.True(avatarPixel.G > 200 && avatarPixel.R < 35 && avatarPixel.B < 35, "数字人视频应持续循环至末帧。");
        }

        await File.WriteAllTextAsync(Path.Combine(evidence, $"long-{caseName}.json"), JsonSerializer.Serialize(new
        {
            Mode = caseName, Seconds = watch.Elapsed.TotalSeconds,
            PeakWorkingSetMiB = measurement.PeakWorkingSetKiB / 1024d, result.Notice
        }));
    }
}
