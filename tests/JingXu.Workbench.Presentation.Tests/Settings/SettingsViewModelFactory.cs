using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Features.Settings;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Presentation.Tests.Settings;

public static class SettingsViewModelFactory
{
    public static SettingsViewModel WithMissing(RuntimeKind kind)
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "jingxu-settings-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempRoot);
        var appRoot = Path.Combine(tempRoot, "app");
        Directory.CreateDirectory(appRoot);

        var diagnostics = new RuntimeDiagnosticService(
            appRoot,
            new RuntimeResolver(appRoot, _ => null),
            new NoOpProcessRunner(),
            RuntimeManifest.Default);

        return new SettingsViewModel(diagnostics);
    }

    public static SettingsViewModel WithFfmpegAndEncoder(VideoEncoderSelection selection, HardwareVideoProcessingPlan? processing = null)
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "jingxu-settings-" + Guid.NewGuid().ToString("N"));
        var appRoot = Path.Combine(tempRoot, "app");
        var ffmpegDir = Path.Combine(appRoot, "runtime", "ffmpeg");
        Directory.CreateDirectory(ffmpegDir);
        File.WriteAllText(Path.Combine(ffmpegDir, "ffmpeg.exe"), string.Empty);
        File.WriteAllText(Path.Combine(ffmpegDir, "ffprobe.exe"), string.Empty);

        var diagnostics = new RuntimeDiagnosticService(
            appRoot,
            new RuntimeResolver(appRoot, _ => null),
            new NoOpProcessRunner(),
            RuntimeManifest.Default);

        return new SettingsViewModel(
            diagnostics,
            encoderSelector: new StubEncoderSelector(selection),
            processingSelector: processing is null ? null : new StubProcessingSelector(processing));
    }
}

internal sealed class StubProcessingSelector(HardwareVideoProcessingPlan plan) : IVideoProcessingSelector
{
    public Task<HardwareVideoProcessingPlan> SelectAsync(string ffmpegExecutable, VideoProcessingMode mode, VideoEncoderKind encoder, CancellationToken cancellationToken)
        => Task.FromResult(plan);
    public void ResetProbe(string ffmpegExecutable) { }
}

internal sealed class NoOpProcessRunner : IExternalProcessRunner
{
    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken) =>
        Task.FromResult<IProcessResult>(new ProcessResult(0, "test version", string.Empty));
}

internal sealed class StubEncoderSelector(VideoEncoderSelection selection) : IVideoEncoderSelector
{
    public Task<VideoEncoderSelection> SelectAsync(
        string ffmpegExecutable,
        VideoProcessingMode mode,
        CancellationToken cancellationToken) =>
        Task.FromResult(selection);
}
