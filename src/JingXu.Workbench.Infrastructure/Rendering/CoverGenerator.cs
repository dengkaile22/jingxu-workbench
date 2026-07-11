using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>使用 FFmpeg 从素材或成片生成 JPEG 封面。</summary>
public static class CoverGenerator
{
    /// <summary>生成封面 JPEG 并返回输出路径。</summary>
    public static async Task<Result<string>> GenerateAsync(
        string ffmpegPath,
        CoverMode mode,
        string outputVideoPath,
        string? firstSourcePath,
        string outputJpegPath,
        IExternalProcessRunner? runner = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputVideoPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputJpegPath);

        var processRunner = runner ?? new ExternalProcessRunner();
        string inputPath;
        switch (mode)
        {
            case CoverMode.FirstSourceFrame when !string.IsNullOrWhiteSpace(firstSourcePath):
                inputPath = firstSourcePath;
                break;
            case CoverMode.FinalOutputFrame:
                inputPath = outputVideoPath;
                break;
            case CoverMode.FirstSourceFrame:
                return Result<string>.Failure("首帧封面需要第一条素材路径。");
            default:
                throw new ArgumentOutOfRangeException(nameof(mode), mode, null);
        }

        string[] arguments;
        if (mode == CoverMode.FinalOutputFrame)
        {
            arguments =
            [
                "-y",
                "-sseof", "-0.1",
                "-i", inputPath,
                "-frames:v", "1",
                "-q:v", "2",
                outputJpegPath
            ];
        }
        else
        {
            arguments =
            [
                "-y",
                "-i", inputPath,
                "-frames:v", "1",
                "-q:v", "2",
                outputJpegPath
            ];
        }

        var request = ProcessRequest.Create(ffmpegPath, arguments);
        var result = await processRunner.RunAsync(request, progress: null, cancellationToken);

        if (result.ExitCode != 0)
        {
            return Result<string>.Failure($"封面生成失败：{result.StandardError.Trim()}");
        }

        if (!File.Exists(outputJpegPath) || new FileInfo(outputJpegPath).Length == 0)
        {
            return Result<string>.Failure("封面文件未生成或为零字节。");
        }

        return Result<string>.Success(outputJpegPath);
    }
}
