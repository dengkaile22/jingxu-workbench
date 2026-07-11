using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;
using JingXu.Workbench.Infrastructure.Subtitles;

namespace JingXu.Workbench.Infrastructure.Tests.Subtitles;

public sealed class WhisperRunnerTests
{
    [Fact]
    public async Task Missing_model_fails_before_process_start()
    {
        using var dir = new TemporaryDirectory();
        var process = new RecordingProcessRunner();
        var runner = new WhisperRunner(
            process,
            new RuntimeResolver(dir.Path, _ => null),
            dir.Path,
            modelRelativePath: "whisper/models/missing.bin");

        Directory.CreateDirectory(Path.Combine(dir.Path, "runtime", "whisper"));
        File.WriteAllBytes(Path.Combine(dir.Path, "runtime", "whisper", "whisper-cli.exe"), [1]);
        var videoPath = Path.Combine(dir.Path, "audio.mp4");
        File.WriteAllBytes(videoPath, [1]);

        var result = await runner.RecognizeAsync(videoPath, null, default);
        Assert.False(result.IsSuccess);
        Assert.Empty(process.Requests);
        Assert.Contains("模型", result.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Missing_whisper_binary_returns_chinese_error()
    {
        using var dir = new TemporaryDirectory();
        var process = new RecordingProcessRunner();
        var runner = new WhisperRunner(process, new RuntimeResolver(dir.Path, _ => null), dir.Path);
        Directory.CreateDirectory(Path.Combine(dir.Path, "runtime", "whisper", "models"));
        File.WriteAllBytes(Path.Combine(dir.Path, "runtime", "whisper", "models", "ggml-base.bin"), [1]);
        var videoPath = Path.Combine(dir.Path, "audio.mp4");
        File.WriteAllBytes(videoPath, [1]);

        var result = await runner.RecognizeAsync(videoPath, null, default);
        Assert.False(result.IsSuccess);
        Assert.Contains("whisper-cli", result.Error!, StringComparison.OrdinalIgnoreCase);
    }
}

public sealed class TesseractRunnerTests
{
    [Fact]
    public async Task Missing_tesseract_returns_chinese_error()
    {
        using var dir = new TemporaryDirectory();
        var detector = new TesseractSubtitleOcrDetector(
            new RecordingProcessRunner(),
            new RuntimeResolver(dir.Path, _ => null),
            new FakeProbe());

        var videoPath = Path.Combine(dir.Path, "video.mp4");
        File.WriteAllBytes(videoPath, [1]);

        var result = await detector.DetectAsync(
            videoPath,
            new Domain.Common.NormalizedRect(0, 0.55, 1, 0.45),
            null,
            default);
        Assert.False(result.IsSuccess);
        Assert.Contains("Tesseract", result.Error!, StringComparison.OrdinalIgnoreCase);
    }

    private sealed class FakeProbe : IMediaProbe
    {
        public Task<Domain.Media.MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
            Task.FromResult(new Domain.Media.MediaInfo(
                TimeSpan.FromSeconds(1),
                1920,
                1080,
                30,
                "h264",
                null,
                false,
                0));
    }
}

public sealed class RecordingProcessRunner : IExternalProcessRunner
{
    public List<IProcessRequest> Requests { get; } = [];

    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        Requests.Add(request);
        return Task.FromResult<IProcessResult>(new ProcessResult(0, string.Empty, string.Empty));
    }
}

internal sealed class TemporaryDirectory : IDisposable
{
    public TemporaryDirectory()
    {
        Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "jingxu-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path);
    }

    public string Path { get; }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(Path))
            {
                Directory.Delete(Path, recursive: true);
            }
        }
        catch (IOException)
        {
        }
    }
}
