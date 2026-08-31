using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Media;

/// <summary>使用 FFmpeg 抽取视频首帧 JPEG，以及主片+蒙版叠层静帧预览。</summary>
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
            EnsureParentDirectory(outputJpegPath);
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
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (RuntimeToolNotFoundException ex)
        {
            return Result<string>.Failure(ex.Message);
        }
        catch (Exception ex)
        {
            return Result<string>.Failure($"首帧抽取失败：{ex.GetBaseException().Message}");
        }
    }

    /// <inheritdoc />
    public async Task<Result<string>> ExtractOverlayCompositePreviewAsync(
        OverlayCompositePreviewRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.BaseVideoPath);
        ArgumentNullException.ThrowIfNull(request.Layer);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.OutputJpegPath);

        if (!File.Exists(request.BaseVideoPath))
        {
            return Result<string>.Failure("主片素材不存在，无法生成叠层预览。");
        }

        if (!request.Layer.IsSelfSource && !File.Exists(request.Layer.SourcePath))
        {
            return Result<string>.Failure("蒙版素材不存在，无法生成叠层预览。");
        }

        try
        {
            var ffmpeg = _resolver.Resolve("ffmpeg", _userRuntimeDirectory);
            EnsureParentDirectory(request.OutputJpegPath);

            var w = Math.Max(64, request.OutputWidth);
            var h = Math.Max(64, request.OutputHeight);
            var previewOverlay = new ResolvedOverlay(
                request.Layer,
                TimeSpan.Zero,
                TimeSpan.FromSeconds(1),
                LoopCount: 1,
                LastLoopDuration: TimeSpan.FromSeconds(1));
            var overlayCompile = OverlayFilterCompiler.Compile(
                [previewOverlay],
                mainInputCount: 1,
                targetWidth: w,
                targetHeight: h);
            if (!overlayCompile.IsSuccess)
            {
                return Result<string>.Failure($"叠层预览滤镜编译失败：{overlayCompile.Error}");
            }

            var compiledOverlay = overlayCompile.Value!;

            var filter =
                $"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease," +
                $"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=rgba[vbase];" +
                $"{compiledOverlay.FilterSuffix};" +
                $"[{compiledOverlay.FinalVideoLabel}]format=yuv420p[vout]";

            var arguments = new List<string>
            {
                "-y",
                "-ss", "0",
                "-i", request.BaseVideoPath
            };
            arguments.AddRange(compiledOverlay.PreInputArguments);
            arguments.AddRange(
            [
                "-filter_complex", filter,
                "-map", "[vout]",
                "-frames:v", "1",
                "-q:v", "3",
                request.OutputJpegPath
            ]);

            var processRequest = ProcessRequest.Create(ffmpeg.Path, arguments);
            var result = await _runner.RunAsync(processRequest, progress: null, cancellationToken)
                .ConfigureAwait(false);
            if (result.ExitCode != 0)
            {
                var stderr = string.IsNullOrWhiteSpace(result.StandardError)
                    ? "FFmpeg 退出码非零。"
                    : result.StandardError.Trim();
                return Result<string>.Failure($"叠层预览合成失败：{stderr}");
            }

            if (!File.Exists(request.OutputJpegPath) || new FileInfo(request.OutputJpegPath).Length == 0)
            {
                return Result<string>.Failure("叠层预览文件未生成或为零字节。");
            }

            return Result<string>.Success(request.OutputJpegPath);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (RuntimeToolNotFoundException ex)
        {
            return Result<string>.Failure(ex.Message);
        }
        catch (Exception ex)
        {
            return Result<string>.Failure($"叠层预览生成失败：{ex.GetBaseException().Message}");
        }
    }

    private static void EnsureParentDirectory(string filePath)
    {
        var directory = Path.GetDirectoryName(filePath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }
    }
}
