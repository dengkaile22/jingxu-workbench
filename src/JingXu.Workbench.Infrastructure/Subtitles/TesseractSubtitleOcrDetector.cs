using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Subtitles;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Subtitles;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Subtitles;

/// <summary>FFmpeg 抽帧 + Tesseract OCR 硬字幕检测。</summary>
public sealed class TesseractSubtitleOcrDetector : ISubtitleOcrDetector
{
    private const string TesseractExecutableRelative = "tesseract/tesseract.exe";

    private readonly IExternalProcessRunner _runner;
    private readonly RuntimeResolver _runtimeResolver;
    private readonly IMediaProbe _mediaProbe;
    private readonly string? _userRuntimeDirectory;

    public TesseractSubtitleOcrDetector(
        IExternalProcessRunner runner,
        RuntimeResolver runtimeResolver,
        IMediaProbe mediaProbe,
        string? userRuntimeDirectory = null)
    {
        _runner = runner;
        _runtimeResolver = runtimeResolver;
        _mediaProbe = mediaProbe;
        _userRuntimeDirectory = userRuntimeDirectory;
    }

    public async Task<Result<IReadOnlyList<DetectedSubtitleSegment>>> DetectAsync(
        string videoPath,
        NormalizedRect scanRegion,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(videoPath);
        if (!File.Exists(videoPath))
        {
            return Result<IReadOnlyList<DetectedSubtitleSegment>>.Failure("输入视频不存在。");
        }

        RuntimeResolution tesseract;
        try
        {
            tesseract = _runtimeResolver.ResolveRelative(TesseractExecutableRelative, "tesseract", _userRuntimeDirectory);
        }
        catch (RuntimeToolNotFoundException)
        {
            return Result<IReadOnlyList<DetectedSubtitleSegment>>.Failure(
                "未找到 Tesseract OCR。请将 Tesseract 放入 runtime/tesseract/，在设置中指定路径，或加入系统 PATH。");
        }

        RuntimeResolution ffmpeg;
        try
        {
            ffmpeg = _runtimeResolver.Resolve("ffmpeg", _userRuntimeDirectory);
        }
        catch (RuntimeToolNotFoundException)
        {
            return Result<IReadOnlyList<DetectedSubtitleSegment>>.Failure(
                "未找到 FFmpeg，无法抽帧进行 OCR。");
        }

        var info = await _mediaProbe.ProbeAsync(videoPath, cancellationToken).ConfigureAwait(false);
        var samples = FrameSamplingPlanner.Plan(info.Duration);
        if (samples.Count == 0)
        {
            return Result<IReadOnlyList<DetectedSubtitleSegment>>.Success([]);
        }

        var tempRoot = Path.Combine(Path.GetTempPath(), "jingxu-ocr", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempRoot);

        try
        {
            progress?.Report("正在抽帧…");
            var framePaths = new List<string>();
            for (var i = 0; i < samples.Count; i++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var framePath = Path.Combine(tempRoot, $"frame_{i:D4}.png");
                var seconds = samples[i].TotalSeconds.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture);
                var extractArgs = new[]
                {
                    "-y", "-ss", seconds, "-i", videoPath,
                    "-frames:v", "1", framePath
                };
                var extract = await _runner.RunAsync(
                    ProcessRequest.Create(ffmpeg.Path, extractArgs),
                    null,
                    cancellationToken).ConfigureAwait(false);
                if (extract.ExitCode == 0 && File.Exists(framePath))
                {
                    framePaths.Add(framePath);
                }
            }

            if (framePaths.Count == 0)
            {
                return Result<IReadOnlyList<DetectedSubtitleSegment>>.Failure("抽帧失败，无法继续 OCR。");
            }

            progress?.Report("正在 OCR 识别…");
            var listFile = Path.Combine(tempRoot, "frames.txt");
            await File.WriteAllLinesAsync(listFile, framePaths, cancellationToken).ConfigureAwait(false);

            var ocrArgs = new List<string> { listFile, "stdout", "-l", "chi_sim+eng", "tsv" };
            var ocrResult = await _runner.RunAsync(
                ProcessRequest.Create(tesseract.Path, ocrArgs, workingDirectory: tempRoot),
                null,
                cancellationToken).ConfigureAwait(false);
            if (ocrResult.ExitCode != 0)
            {
                return Result<IReadOnlyList<DetectedSubtitleSegment>>.Failure("Tesseract OCR 运行失败。");
            }

            var lines = TesseractTsvParser.Parse(ocrResult.StandardOutput, info.Width, info.Height);
            var observations = lines
                .Select((line, index) =>
                {
                    var pageIndex = Math.Clamp(line.PageNumber - 1, 0, framePaths.Count - 1);
                    var timestamp = pageIndex < samples.Count ? samples[pageIndex] : TimeSpan.Zero;
                    var mappedRegion = MapToScanRegion(line.Bounds, scanRegion);
                    return new OcrFrameObservation(timestamp, mappedRegion, line.Confidence);
                })
                .ToArray();

            var segments = SubtitleRegionClusterer.Cluster(observations);
            progress?.Report($"检测完成，共 {segments.Count} 个区域。");
            return Result<IReadOnlyList<DetectedSubtitleSegment>>.Success(segments);
        }
        catch (OperationCanceledException)
        {
            return Result<IReadOnlyList<DetectedSubtitleSegment>>.Failure("OCR 检测已取消。");
        }
        finally
        {
            TryDeleteDirectory(tempRoot);
        }
    }

    private static NormalizedRect MapToScanRegion(NormalizedRect boundsInScanCrop, NormalizedRect scanRegion) =>
        new(
            scanRegion.X + boundsInScanCrop.X * scanRegion.Width,
            scanRegion.Y + boundsInScanCrop.Y * scanRegion.Height,
            boundsInScanCrop.Width * scanRegion.Width,
            boundsInScanCrop.Height * scanRegion.Height);

    private static void TryDeleteDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
