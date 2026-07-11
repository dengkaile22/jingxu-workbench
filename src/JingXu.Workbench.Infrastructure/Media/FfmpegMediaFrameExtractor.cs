using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Media;

/// <summary>使用 FFmpeg 抽取视频首帧 JPEG。</summary>
public sealed class FfmpegMediaFrameExtractor : IMediaFrameExtractor
{
    private readonly IExternalProcessRunner _runner;
    private readonly RuntimeResolver _resolver;
    private readonly string? _userRuntimeDirectory;

    public FfmpegMediaFrameExtractor(
        IExternalProcessRunner runner,
        RuntimeResolver resolver,
        string? userRuntimeDirectory = null)
    {
        _runner = runner;
        _resolver = resolver;
        _userRuntimeDirectory = userRuntimeDirectory;
    }

    public async Task<Result<string>> ExtractFirstFrameAsync(
        string videoPath,
        string outputJpegPath,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(videoPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputJpegPath);

        try
        {
            var ffmpeg = _resolver.Resolve("ffmpeg", _userRuntimeDirectory);
            string[] arguments =
            [
                "-y",
                "-ss", "0",
                "-i", videoPath,
                "-frames:v", "1",
                "-q:v", "2",
                outputJpegPath
            ];

            var request = ProcessRequest.Create(ffmpeg.Path, arguments);
            var result = await _runner.RunAsync(request, progress: null, cancellationToken).ConfigureAwait(false);
            if (result.ExitCode != 0)
            {
                var stderr = string.IsNullOrWhiteSpace(result.StandardError)
                    ? "FFmpeg 退出码非零。"
                    : result.StandardError.Trim();
                return Result<string>.Failure($"首帧抽取失败：{stderr}");
            }

            if (!File.Exists(outputJpegPath) || new FileInfo(outputJpegPath).Length == 0)
            {
                return Result<string>.Failure("首帧文件未生成或为零字节。");
            }

            return Result<string>.Success(outputJpegPath);
        }
        catch (RuntimeToolNotFoundException ex)
        {
            return Result<string>.Failure(ex.Message);
        }
    }
}
