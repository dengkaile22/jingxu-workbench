using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Application.Tests.Composition;

public sealed class CompositionOrchestratorTests
{
    [Fact]
    public async Task Import_returns_probe_error_instead_of_throwing_when_ffprobe_missing()
    {
        var appRoot = Path.Combine(Path.GetTempPath(), "jingxu-import-" + Guid.NewGuid().ToString("N"), "app");
        Directory.CreateDirectory(appRoot);
        try
        {
            var probe = new FfprobeMediaProbe(
                new FakeRunner(exitCode: 0, stdout: "{}"),
                new RuntimeResolver(appRoot, _ => null));

            var outcomes = await CompositionOrchestrator.ImportAsync(
                probe,
                [@"C:\素材\片段_1.mp4"],
                CancellationToken.None);

            var outcome = Assert.Single(outcomes);
            Assert.Null(outcome.Asset);
            Assert.Contains("FFprobe", outcome.ProbeError);
        }
        finally
        {
            try { Directory.Delete(Path.GetDirectoryName(appRoot)!, recursive: true); }
            catch (IOException) { }
        }
    }

    [Fact]
    public async Task Import_returns_probe_error_when_probe_throws_media_probe_exception()
    {
        var probe = new ThrowingMediaProbe(new MediaProbeException(
            @"C:\素材\损坏.mp4",
            "媒体探测失败：FFprobe 退出码 1。"));

        var outcomes = await CompositionOrchestrator.ImportAsync(
            probe,
            [@"C:\素材\损坏.mp4"],
            CancellationToken.None);

        var outcome = Assert.Single(outcomes);
        Assert.Null(outcome.Asset);
        Assert.Contains("探测失败", outcome.ProbeError);
    }

    [Fact]
    public async Task Import_wechat_hash_filename_succeeds_without_sequence_and_does_not_throw()
    {
        var probe = new FixedMediaProbe(new MediaInfo(
            TimeSpan.FromSeconds(15.533),
            720,
            960,
            29.87m,
            "hevc",
            "aac",
            true,
            0));

        var path = @"C:\Users\demo\xwechat\msg\video\11e6dfdbde17e0e9f0a4bbefc95f4e1d.mp4";
        var outcomes = await CompositionOrchestrator.ImportAsync(probe, [path], CancellationToken.None);

        var outcome = Assert.Single(outcomes);
        Assert.NotNull(outcome.Asset);
        Assert.Null(outcome.Asset!.SequenceIndex);
        Assert.Contains("未找到数字序号", outcome.SequenceWarning);
        Assert.Null(outcome.ProbeError);

        var preview = CompositionOrchestrator.BuildPreview(
            [outcome.Asset],
            CompositionMode.Random,
            string.Empty,
            batchCount: 1,
            randomSeed: 1);
        Assert.True(preview.CanEnqueue);
    }

    [Fact]
    public async Task Import_swallows_unexpected_probe_exceptions_as_outcome()
    {
        var probe = new ThrowingMediaProbe(new InvalidOperationException("模拟原生互操作失败"));

        var outcomes = await CompositionOrchestrator.ImportAsync(
            probe,
            [@"C:\素材\任意.mp4"],
            CancellationToken.None);

        var outcome = Assert.Single(outcomes);
        Assert.Null(outcome.Asset);
        Assert.Contains("媒体探测失败", outcome.ProbeError);
        Assert.Contains("原生互操作", outcome.ProbeError);
    }

    private sealed class FakeRunner(int exitCode, string stdout) : IExternalProcessRunner
    {
        public Task<IProcessResult> RunAsync(
            IProcessRequest request,
            IProgress<string>? progress,
            CancellationToken cancellationToken) =>
            Task.FromResult<IProcessResult>(new ProcessResult(exitCode, stdout, string.Empty));
    }

    private sealed class ThrowingMediaProbe(Exception exception) : IMediaProbe
    {
        public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
            Task.FromException<MediaInfo>(exception);
    }

    private sealed class FixedMediaProbe(MediaInfo info) : IMediaProbe
    {
        public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
            Task.FromResult(info);
    }
}
