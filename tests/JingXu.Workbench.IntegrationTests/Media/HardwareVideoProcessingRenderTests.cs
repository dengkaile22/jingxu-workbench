using System.Diagnostics;
using System.Drawing;
using System.Text.Json;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class HardwareVideoProcessingRenderTests
{
    [Fact]
    public async Task Real_hardware_scale_preserves_fit_color_duration_and_recovers_from_device_setup_failure()
    {
        var (ffmpeg, ffprobe) = MediaIntegrationHarness.RequireFfmpeg();
        var process = new ExternalProcessRunner();
        var encoder = await new HardwareVideoEncoderSelector(process).SelectAsync(ffmpeg, VideoProcessingMode.Gpu, default);
        var processing = await new HardwareVideoProcessingSelector(process).SelectAsync(ffmpeg, VideoProcessingMode.Gpu, encoder.Kind, default);
        if (!processing.CanScale)
        {
            Assert.Skip("本机没有通过真实解码/缩放探针的 QSV 或 CUDA 设备。");
            return;
        }

        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpeg, ffprobe);
        var source = Path.Combine(workspace.Root, "red-blue.mp4");
        var generated = await process.RunAsync(ProcessRequest.Create(ffmpeg,
            ["-y", "-f", "lavfi", "-i", "color=c=red:s=960x720:r=30:d=1,drawbox=x=480:y=0:w=480:h=720:color=blue:t=fill",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", source]), null, default);
        Assert.True(generated.ExitCode == 0, generated.StandardError);
        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var info = await probe.ProbeAsync(source, default);
        Assert.Equal("yuv420p", info.PixelFormat);
        var asset = new MediaAsset(Guid.NewGuid(), source, 1, info);
        var plan = new CompositionPlan([new PlannedClip(asset, TimeSpan.Zero, info.Duration)], info.Duration, 0, TimeSpan.Zero);
        var evidence = Path.Combine(Packaging.BuildPaths.RepoRoot, "artifacts", "gpu-validation");
        Directory.CreateDirectory(evidence);
        var report = new List<object>();

        foreach (var fit in new[] { AspectFitMode.CenterCrop, AspectFitMode.Letterbox, AspectFitMode.Stretch, AspectFitMode.BlurBackground })
        {
            var frames = new List<string>();
            foreach (var hardware in new[] { false, true })
            {
                var output = Path.Combine(workspace.Root, $"{fit}-{hardware}.mp4");
                var request = new RenderRequest(plan, output, RenderProfile.Balanced, OutputAspect.Custom(720, 480, fit), [],
                    ProcessingMode: VideoProcessingMode.Gpu);
                var runner = new HardwareProcessingRecordingRunner();
                var executor = RenderInfrastructure.CreateFfmpegRenderExecutor(workspace.AppRoot, runner: runner,
                    encoderSelector: new SpecifiedEncoderSelector(encoder),
                    processingSelector: new SpecifiedProcessingSelector(hardware ? processing : HardwareVideoProcessingPlan.Software));
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
                var watch = Stopwatch.StartNew();
                var result = await executor.ExecuteAsync(RenderJob.CreateQueued(request), null, timeout.Token);
                watch.Stop();
                Assert.True(result.IsSuccess, result.FailureInfo?.Message);
                var actual = await probe.ProbeAsync(output, default);
                Assert.Equal((720, 480), (actual.Width, actual.Height));
                Assert.InRange(actual.Duration.TotalSeconds, .9, 1.2);
                Assert.Equal(30m, actual.FrameRate);
                Assert.Single(runner.RenderRequests);
                Assert.Equal(hardware, runner.RenderRequests[0].Arguments.Contains("-hwaccel"));
                var hardwareScale = runner.Filter.Contains("scale_qsv=", StringComparison.Ordinal) || runner.Filter.Contains("scale_cuda=", StringComparison.Ordinal);
                Assert.Equal(hardware && fit != AspectFitMode.BlurBackground, hardwareScale);
                var png = Path.Combine(workspace.Root, $"{fit}-{hardware}.png");
                var extracted = await process.RunAsync(ProcessRequest.Create(ffmpeg,
                    ["-y", "-ss", "0.5", "-i", output, "-frames:v", "1", png]), null, default);
                Assert.True(extracted.ExitCode == 0, extracted.StandardError);
                frames.Add(png);
                report.Add(new { Fit = fit.ToString(), Hardware = hardware, Seconds = watch.Elapsed.TotalSeconds, HardwareScale = hardwareScale, result.Notice });
                if (hardware)
                {
                    await File.WriteAllTextAsync(Path.Combine(evidence, $"scale-{fit}.filter.txt"), runner.Filter);
                    await File.WriteAllTextAsync(Path.Combine(evidence, $"scale-{fit}.log"), runner.Log);
                }
            }
            using var softwareFrame = new Bitmap(frames[0]);
            using var hardwareFrame = new Bitmap(frames[1]);
            foreach (var x in new[] { 5, 60, 200, 500, 660, 715 })
            foreach (var y in new[] { 5, 120, 240, 360, 475 })
            {
                var reference = softwareFrame.GetPixel(x, y);
                var actual = hardwareFrame.GetPixel(x, y);
                Assert.InRange(Math.Abs(reference.R - actual.R), 0, 16);
                Assert.InRange(Math.Abs(reference.G - actual.G), 0, 16);
                Assert.InRange(Math.Abs(reference.B - actual.B), 0, 16);
            }
        }

        // 让真实 FFmpeg 拒绝首轮设备参数，验证第二轮回退仍成功调用原硬件编码器。
        var failingRunner = new HardwareProcessingRecordingRunner { FailFirstHardwareDevice = true };
        var fallbackExecutor = RenderInfrastructure.CreateFfmpegRenderExecutor(workspace.AppRoot, runner: failingRunner,
            encoderSelector: new SpecifiedEncoderSelector(encoder), processingSelector: new SpecifiedProcessingSelector(processing));
        var fallbackRequest = new RenderRequest(plan, Path.Combine(workspace.Root, "device-fallback.mp4"), RenderProfile.Balanced,
            OutputAspect.Custom(720, 480), [], ProcessingMode: VideoProcessingMode.Gpu);
        var fallback = await fallbackExecutor.ExecuteAsync(RenderJob.CreateQueued(fallbackRequest), null, default);
        Assert.True(fallback.IsSuccess, fallback.FailureInfo?.Message);
        Assert.Equal(2, failingRunner.RenderRequests.Count);
        Assert.Contains("-hwaccel", failingRunner.RenderRequests[0].Arguments);
        Assert.DoesNotContain("-hwaccel", failingRunner.RenderRequests[1].Arguments);
        Assert.Contains("CPU 解码", fallback.Notice, StringComparison.Ordinal);
        Assert.DoesNotContain("libx264", failingRunner.RenderRequests[1].Arguments);
        await File.WriteAllTextAsync(Path.Combine(evidence, "real-device-fallback.log"), failingRunner.Log);
        await File.WriteAllTextAsync(Path.Combine(evidence, "scaling-comparison.json"), JsonSerializer.Serialize(report));
    }
}

internal sealed class SpecifiedEncoderSelector(VideoEncoderSelection selection) : IVideoEncoderSelector
{
    public Task<VideoEncoderSelection> SelectAsync(string ffmpegExecutable, VideoProcessingMode mode, CancellationToken cancellationToken) => Task.FromResult(selection);
}

internal sealed class SpecifiedProcessingSelector(HardwareVideoProcessingPlan plan) : IVideoProcessingSelector
{
    public Task<HardwareVideoProcessingPlan> SelectAsync(string ffmpegExecutable, VideoProcessingMode mode, VideoEncoderKind encoder, CancellationToken cancellationToken) => Task.FromResult(plan);
    public void ResetProbe(string ffmpegExecutable) { }
}

internal sealed class HardwareProcessingRecordingRunner : IExternalProcessRunner
{
    private readonly ExternalProcessRunner _runner = new();
    public List<IProcessRequest> RenderRequests { get; } = [];
    public string Filter { get; private set; } = string.Empty;
    public string Log { get; private set; } = string.Empty;
    public bool FailFirstHardwareDevice { get; init; }

    public async Task<IProcessResult> RunAsync(IProcessRequest request, IProgress<string>? progress, CancellationToken cancellationToken)
    {
        var rendering = request.Arguments.Contains("-progress");
        if (rendering)
        {
            var arguments = request.Arguments.ToList();
            if (FailFirstHardwareDevice && RenderRequests.Count == 0 && arguments.Contains("-hwaccel"))
            {
                arguments[arguments.IndexOf("-init_hw_device") + 1] = "jingxu_invalid_test_device";
                request = ProcessRequest.Create(request.Executable, arguments, request.WorkingDirectory, request.EnvironmentOverrides, request.Priority);
            }
            RenderRequests.Add(request);
            Filter = await File.ReadAllTextAsync(Path.Combine(request.WorkingDirectory!, "filter_complex.txt"), cancellationToken);
        }
        var result = await _runner.RunAsync(request, progress, cancellationToken);
        if (rendering) { Log += result.StandardError + Environment.NewLine; }
        return result;
    }
}
