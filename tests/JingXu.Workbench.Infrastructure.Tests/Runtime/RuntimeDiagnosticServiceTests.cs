using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Tests.Runtime;

public sealed class RuntimeDiagnosticServiceTests
{
    [Fact]
    public async Task Missing_ffmpeg_reports_chinese_actionable_status()
    {
        using var layout = RuntimeLayout.Create();
        var service = CreateService(layout);

        var statuses = await service.DiagnoseAsync();

        var ffmpeg = Assert.Single(statuses, x => x.Kind == RuntimeKind.Ffmpeg);
        Assert.False(ffmpeg.IsAvailable);
        Assert.Contains("未找到 FFmpeg", ffmpeg.Message, StringComparison.Ordinal);
        Assert.Contains("runtime\\ffmpeg", ffmpeg.SuggestedAction, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Bundled_ffprobe_reports_bundled_source()
    {
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffprobe.exe");
        var service = CreateService(layout);

        var statuses = await service.DiagnoseAsync();

        var ffprobe = Assert.Single(statuses, x => x.Kind == RuntimeKind.Ffprobe);
        Assert.True(ffprobe.IsAvailable);
        Assert.Equal(RuntimeSource.Bundled, ffprobe.Source);
        Assert.Equal(layout.BundledFfprobe, ffprobe.ResolvedPath);
    }

    [Fact]
    public async Task Missing_tesseract_reports_chinese_message()
    {
        using var layout = RuntimeLayout.Create();
        var service = CreateService(layout);

        var statuses = await service.DiagnoseAsync();

        var tesseract = Assert.Single(statuses, x => x.Kind == RuntimeKind.Tesseract);
        Assert.False(tesseract.IsAvailable);
        Assert.Contains("未找到 Tesseract", tesseract.Message, StringComparison.Ordinal);
    }

    private static RuntimeDiagnosticService CreateService(RuntimeLayout layout) =>
        new(
            layout.AppRoot,
            new RuntimeResolver(layout.AppRoot, layout.PathLookup),
            new NoOpRunner(),
            RuntimeManifest.Default);
}

internal sealed class NoOpRunner : IExternalProcessRunner
{
    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken) =>
        Task.FromResult<IProcessResult>(new ProcessResult(0, "ffmpeg version test", string.Empty));
}
