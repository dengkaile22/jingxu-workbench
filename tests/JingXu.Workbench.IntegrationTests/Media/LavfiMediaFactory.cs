using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.IntegrationTests.Media;

/// <summary>使用 FFmpeg lavfi 生成可探测的测试短视频。</summary>
internal static class LavfiMediaFactory
{
    private const int DefaultWidth = 320;
    private const int DefaultHeight = 240;
    private const int DefaultFps = 24;

    public static async Task GenerateColorClipAsync(
        string ffmpegPath,
        string outputPath,
        string color,
        TimeSpan duration,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(color);

        var seconds = FormatSeconds(duration);
        var request = ProcessRequest.Create(
            ffmpegPath,
            [
                "-y",
                "-f", "lavfi",
                "-i", $"color=c={color}:size={DefaultWidth}x{DefaultHeight}:rate={DefaultFps}:duration={seconds}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                outputPath
            ]);

        await RunOrThrowAsync(request, "生成 lavfi 纯色片段", cancellationToken);
    }

    public static async Task GenerateToneClipAsync(
        string ffmpegPath,
        string outputPath,
        int sequenceIndex,
        string color,
        int frequencyHz,
        TimeSpan duration,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(color);

        if (sequenceIndex <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(sequenceIndex), "序号必须为正整数。");
        }

        if (frequencyHz <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(frequencyHz), "音频频率必须为正整数。");
        }

        var seconds = FormatSeconds(duration);
        var request = ProcessRequest.Create(
            ffmpegPath,
            [
                "-y",
                "-f", "lavfi",
                "-i", $"color=c={color}:size={DefaultWidth}x{DefaultHeight}:rate={DefaultFps}:duration={seconds}",
                "-f", "lavfi",
                "-i", $"sine=frequency={frequencyHz}:sample_rate=48000:duration={seconds}",
                "-shortest",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "128k",
                "-metadata", $"title=seq-{sequenceIndex}",
                outputPath
            ]);

        await RunOrThrowAsync(request, $"生成序号 {sequenceIndex} lavfi 测试片段", cancellationToken);
    }

    public static async Task GenerateSilentClipAsync(
        string ffmpegPath,
        string outputPath,
        string color,
        TimeSpan duration,
        CancellationToken cancellationToken = default) =>
        await GenerateColorClipAsync(ffmpegPath, outputPath, color, duration, cancellationToken);

    public static async Task GenerateBgmToneAsync(
        string ffmpegPath,
        string outputPath,
        int frequencyHz,
        TimeSpan duration,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);

        var seconds = FormatSeconds(duration);
        var request = ProcessRequest.Create(
            ffmpegPath,
            [
                "-y",
                "-f", "lavfi",
                "-i", $"sine=frequency={frequencyHz}:sample_rate=48000:duration={seconds}",
                "-c:a", "aac",
                "-b:a", "128k",
                outputPath
            ]);

        await RunOrThrowAsync(request, "生成 BGM 测试音轨", cancellationToken);
    }

    public static async Task ConcatHardCutAsync(
        string ffmpegPath,
        IReadOnlyList<string> inputPaths,
        string outputPath,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegPath);
        ArgumentNullException.ThrowIfNull(inputPaths);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);

        if (inputPaths.Count == 0)
        {
            throw new ArgumentException("至少需要一个输入片段。", nameof(inputPaths));
        }

        var listPath = outputPath + ".txt";
        var lines = inputPaths.Select(path => $"file '{ToConcatPath(path)}'");
        await File.WriteAllLinesAsync(listPath, lines, cancellationToken);

        try
        {
            var request = ProcessRequest.Create(
                ffmpegPath,
                [
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", listPath,
                    "-c", "copy",
                    outputPath
                ]);

            await RunOrThrowAsync(request, "硬切拼接", cancellationToken);
        }
        finally
        {
            try { File.Delete(listPath); }
            catch (IOException) { }
        }
    }

    private static async Task RunOrThrowAsync(
        IProcessRequest request,
        string action,
        CancellationToken cancellationToken)
    {
        var result = await new ExternalProcessRunner().RunAsync(request, progress: null, cancellationToken);

        if (result.ExitCode != 0)
        {
            throw new InvalidOperationException($"{action}失败：{result.StandardError.Trim()}");
        }
    }

    private static string FormatSeconds(TimeSpan duration) =>
        duration.TotalSeconds.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture);

    private static string ToConcatPath(string path) =>
        path.Replace('\\', '/').Replace("'", "''");
}
