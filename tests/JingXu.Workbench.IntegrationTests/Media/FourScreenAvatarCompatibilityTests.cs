using System.Diagnostics;
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

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class FourScreenAvatarCompatibilityTests
{
    private static readonly JsonSerializerOptions ReportJsonOptions = new() { WriteIndented = true };
    [Theory]
    [InlineData(VideoProcessingMode.Auto)]
    [InlineData(VideoProcessingMode.Gpu)]
    public async Task Portrait_four_screen_and_avatar_overlay_render_together(VideoProcessingMode mode)
    {
        var (ffmpeg, ffprobe) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpeg, ffprobe);
        var source = Path.Combine(workspace.Root, "main.mp4");
        var avatar = Path.Combine(workspace.Root, "avatar-simulated.mp4");
        var runner = new ExternalProcessRunner();
        foreach (var item in new[] { (Path: source, Filter: "testsrc2=size=1080x1440:rate=30:duration=2"),
                                    (Path: avatar, Filter: "color=c=red:size=320x480:rate=30:duration=2") })
        {
            var generated = await runner.RunAsync(ProcessRequest.Create(ffmpeg,
                ["-y", "-f", "lavfi", "-i", item.Filter, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", item.Path]), null, default);
            Assert.True(generated.ExitCode == 0, generated.StandardError);
        }

        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var info = await probe.ProbeAsync(source, default);
        var asset = new MediaAsset(Guid.NewGuid(), source, 1, info);
        var plan = new CompositionPlan([new PlannedClip(asset, TimeSpan.Zero, info.Duration)], info.Duration, 42, TimeSpan.Zero);
        var layer = OverlayLayer.CreateFullFramePreset(avatar, TimeSpan.FromSeconds(2)) with
        {
            Name = "模拟数字人视频叠加", Bounds = new NormalizedRect(0.62, 0.4, 0.3, 0.55),
            Opacity = 0.95, TopFade = 0.1, Feather = 0.05
        };
        var cases = new[]
        {
            (Name: "avatar_only", Four: false, Avatar: true, Feather: true),
            (Name: "four_only", Four: true, Avatar: false, Feather: true),
            (Name: "four_and_avatar", Four: true, Avatar: true, Feather: true),
            (Name: "four_and_avatar_no_feather", Four: true, Avatar: true, Feather: false)
        };
        var measurement = new MeasuredRenderProcessRunner();
        var executor = RenderInfrastructure.CreateFfmpegRenderExecutor(workspace.AppRoot, runner: measurement);
        var metrics = new List<object>();
        foreach (var item in cases)
        {
            measurement.ResetMeasurement();
            var request = RenderRequestFactory.CreateForPlans([plan], workspace.Root, item.Name,
                RenderProfile.Balanced, OutputAspect.InheritFirst,
                fourScreen: item.Four ? new FourScreenEffectPlan(1, FeatherEnabled: item.Feather) : null)[0] with
            {
                ProcessingMode = mode,
                HasOverlays = item.Avatar,
                OverlayLayers = item.Avatar ? [item.Feather ? layer : layer with { TopFade = 0, Feather = 0 }] : []
            };
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(60));
            var watch = Stopwatch.StartNew();
            var result = await executor.ExecuteAsync(RenderJob.CreateQueued(request), null, timeout.Token);
            watch.Stop();
            Assert.True(result.IsSuccess, result.FailureInfo?.Message ?? "渲染超时或取消");
            var rendered = await probe.ProbeAsync(request.OutputPath, default);
            Assert.Equal(1080, rendered.Width);
            Assert.Equal(1440, rendered.Height);
            Assert.InRange(rendered.Duration.TotalSeconds, 1.8, 2.25);
            var row = new { item.Name, Mode = mode.ToString(), Seconds = watch.Elapsed.TotalSeconds, EffectiveSpeed = 2 / watch.Elapsed.TotalSeconds,
                PeakWorkingSetMiB = measurement.PeakWorkingSetKiB / 1024d, Encoder = result.Notice };
            metrics.Add(row);
            Console.WriteLine(JsonSerializer.Serialize(row));
        }

        var report = Path.Combine(Packaging.BuildPaths.RepoRoot, "artifacts", $"avatar-compatibility-measurements-{mode}.json");
        var json = JsonSerializer.Serialize(metrics, ReportJsonOptions);
        await File.WriteAllTextAsync(report, json);
        if (mode == VideoProcessingMode.Gpu)
        {
            await File.WriteAllTextAsync(Path.Combine(Packaging.BuildPaths.RepoRoot, "artifacts", "avatar-compatibility-measurements.json"), json);
        }
    }
}
