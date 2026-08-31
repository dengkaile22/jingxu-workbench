using System.Globalization;
using System.Text;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>
/// 真实 FFmpeg 渲染执行器：预检、同卷临时输出、进度解析、验证后原子移动。
/// </summary>
public sealed class FfmpegRenderExecutor : IRenderExecutor
{
    private const string TempDirectoryName = ".jingxu-tmp";
    // 容器时间基/AAC 帧对齐常见 ±数十毫秒；loudnorm 裁切后仍可能有少量偏差。
    private const double DurationToleranceSeconds = 0.25;
    private static readonly TimeSpan DefaultRenderTimeout = TimeSpan.FromHours(4);

    private readonly IExternalProcessRunner _runner;
    private readonly IMediaProbe _probe;
    private readonly RuntimeResolver _runtimeResolver;
    private readonly string? _userRuntimeDirectory;
    private readonly Func<string, long>? _availableDiskBytes;
    private readonly IVideoEncoderSelector _encoderSelector;

    public FfmpegRenderExecutor(
        IExternalProcessRunner runner,
        IMediaProbe probe,
        RuntimeResolver runtimeResolver,
        string? userRuntimeDirectory = null,
        Func<string, long>? availableDiskBytes = null,
        IVideoEncoderSelector? encoderSelector = null)
    {
        ArgumentNullException.ThrowIfNull(runner);
        ArgumentNullException.ThrowIfNull(probe);
        ArgumentNullException.ThrowIfNull(runtimeResolver);
        _runner = runner;
        _probe = probe;
        _runtimeResolver = runtimeResolver;
        _userRuntimeDirectory = userRuntimeDirectory;
        _availableDiskBytes = availableDiskBytes;
        _encoderSelector = encoderSelector ?? new HardwareVideoEncoderSelector(runner);
    }

    /// <inheritdoc />
    public async Task<RenderExecutionResult> ExecuteAsync(
        RenderJob job,
        IProgress<RenderProgress>? progress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(job);

        if (job.Request is null)
        {
            return RenderExecutionResult.Failed("渲染任务缺少请求快照，无法执行。");
        }

        var request = job.Request;
        var outputPath = Path.GetFullPath(request.OutputPath);
        var outputDirectory = Path.GetDirectoryName(outputPath)!;
        var stagingRoot = Path.Combine(outputDirectory, TempDirectoryName, job.Id.ToString("N"));
        var tempOutputPath = Path.Combine(stagingRoot, "output.mp4");
        var logPath = Path.Combine(stagingRoot, "render.log");

        try
        {
            var preflight = await RunPreflightAsync(request, outputPath, cancellationToken).ConfigureAwait(false);
            if (!preflight.IsSuccess)
            {
                return RenderExecutionResult.Failed(preflight.Error!);
            }

            RuntimeResolution ffmpeg;
            try
            {
                ffmpeg = _runtimeResolver.Resolve("ffmpeg", _userRuntimeDirectory);
            }
            catch (RuntimeToolNotFoundException)
            {
                return RenderExecutionResult.Failed(
                    "未找到 FFmpeg。请将 FFmpeg 放入 runtime/ffmpeg/，在设置中指定路径，或加入系统 PATH。");
            }

            Directory.CreateDirectory(stagingRoot);

            var isStreamCopy =
                request.SubtitleBurn is null &&
                RenderDecision.For(request).CanStreamCopy;
            var selection = request.SubtitleBurn is not null
                ? VideoEncoderSelection.Cpu()
                : isStreamCopy
                    ? new VideoEncoderSelection(
                        VideoEncoderKind.Libx264,
                        "无损直拷（不重新编码）",
                        "使用无损直拷完成。")
                    : await _encoderSelector
                        .SelectAsync(ffmpeg.Path, request.ProcessingMode, cancellationToken)
                        .ConfigureAwait(false);

            FfmpegCompileResult compileResult;
            TimeSpan expectedDuration;
            if (request.SubtitleBurn is not null)
            {
                var firstClip = request.Plan.Clips[0].Asset.Info;
                var (canvasWidth, canvasHeight) = OutputCanvasResolver.Resolve(request);
                compileResult = SubtitleBurnInCommandCompiler.Compile(
                    ffmpeg.Path,
                    request.SubtitleBurn,
                    tempOutputPath,
                    request.OutputVideoSettings,
                    canvasWidth,
                    canvasHeight,
                    firstClip.FrameRate);
                expectedDuration = request.Plan.Duration;
            }
            else
            {
                compileResult = FfmpegCommandCompiler.Compile(
                    ffmpeg.Path,
                    request,
                    tempOutputPath,
                    selection.Kind);
                expectedDuration = request.Plan.Duration;
            }

            var budget = RenderPreflight.CheckCommandBudget(compileResult.Command.EstimatedCommandLineLength);
            if (!budget.IsSuccess)
            {
                return RenderExecutionResult.Failed(budget.Error!);
            }

            try
            {
                StagingInputMaterializer.Materialize(stagingRoot, compileResult.InputAliases);
            }
            catch (FileNotFoundException ex)
            {
                CleanupMedia(stagingRoot, preserveLog: true);
                return RenderExecutionResult.Failed(ex.Message);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                CleanupMedia(stagingRoot, preserveLog: true);
                return RenderExecutionResult.Failed($"无法准备 staging 输入别名：{ex.Message}");
            }

            IProcessResult processResult;
            try
            {
                processResult = await RunProcessAttemptAsync(
                    compileResult,
                    stagingRoot,
                    expectedDuration,
                    progress,
                    cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                await WriteLogAsync(logPath, "任务已取消。", CancellationToken.None).ConfigureAwait(false);
                CleanupMedia(stagingRoot, preserveLog: true);
                return RenderExecutionResult.Cancelled();
            }

            var log = new StringBuilder();
            log.AppendLine("=== 编码器选择 ===");
            log.AppendLine(selection.DisplayName);
            log.AppendLine();
            AppendAttemptLog(
                log,
                selection.Kind == VideoEncoderKind.Libx264 ? "CPU / 直拷尝试" : "GPU 尝试",
                processResult);

            string? successNotice = selection.Notice;
            if (processResult.ExitCode != 0 &&
                selection.Kind != VideoEncoderKind.Libx264 &&
                IsHardwareEncoderFailure(selection.Kind, processResult.StandardError))
            {
                TryDelete(tempOutputPath);
                log.AppendLine();
                log.AppendLine("=== 自动回退 CPU ===");
                log.AppendLine("GPU 编码初始化失败，已改用 libx264。");
                log.AppendLine();

                var cpuCompileResult = FfmpegCommandCompiler.Compile(
                    ffmpeg.Path,
                    request,
                    tempOutputPath,
                    VideoEncoderKind.Libx264);
                var cpuBudget = RenderPreflight.CheckCommandBudget(
                    cpuCompileResult.Command.EstimatedCommandLineLength);
                if (!cpuBudget.IsSuccess)
                {
                    await WriteLogAsync(logPath, log.ToString(), cancellationToken).ConfigureAwait(false);
                    CleanupMedia(stagingRoot, preserveLog: true);
                    return RenderExecutionResult.Failed(cpuBudget.Error!);
                }

                try
                {
                    StagingInputMaterializer.Materialize(stagingRoot, cpuCompileResult.InputAliases);
                }
                catch (FileNotFoundException ex)
                {
                    await WriteLogAsync(logPath, log.ToString(), cancellationToken).ConfigureAwait(false);
                    CleanupMedia(stagingRoot, preserveLog: true);
                    return RenderExecutionResult.Failed(ex.Message);
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    await WriteLogAsync(logPath, log.ToString(), cancellationToken).ConfigureAwait(false);
                    CleanupMedia(stagingRoot, preserveLog: true);
                    return RenderExecutionResult.Failed($"无法准备 staging 输入别名：{ex.Message}");
                }

                try
                {
                    processResult = await RunProcessAttemptAsync(
                        cpuCompileResult,
                        stagingRoot,
                        expectedDuration,
                        progress,
                        cancellationToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    log.AppendLine("CPU 回退过程中任务已取消。");
                    await WriteLogAsync(logPath, log.ToString(), CancellationToken.None).ConfigureAwait(false);
                    CleanupMedia(stagingRoot, preserveLog: true);
                    return RenderExecutionResult.Cancelled();
                }

                AppendAttemptLog(log, "CPU 尝试", processResult);
                successNotice = "GPU 编码不可用，已自动改用 CPU 完成。";
            }

            if (processResult.ExitCode != 0)
            {
                await WriteLogAsync(logPath, log.ToString(), cancellationToken)
                    .ConfigureAwait(false);
                CleanupMedia(stagingRoot, preserveLog: true);
                return RenderExecutionResult.Failed(MapProcessFailure(processResult.ExitCode, processResult.StandardError));
            }

            await WriteLogAsync(logPath, log.ToString(), cancellationToken)
                .ConfigureAwait(false);

            var validation = await ValidateOutputAsync(tempOutputPath, expectedDuration, request, cancellationToken)
                .ConfigureAwait(false);
            if (!validation.IsSuccess)
            {
                CleanupMedia(stagingRoot, preserveLog: true);
                return RenderExecutionResult.Failed(validation.Error!);
            }

            MoveToFinalOutput(tempOutputPath, outputPath);
            CleanupStagingDirectory(stagingRoot, preserveLog: true);
            return RenderExecutionResult.Success(successNotice);
        }
        catch (OperationCanceledException)
        {
            CleanupMedia(stagingRoot, preserveLog: true);
            return RenderExecutionResult.Cancelled();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            CleanupMedia(stagingRoot, preserveLog: true);
            return RenderExecutionResult.Failed($"写入输出文件失败：{ex.Message}");
        }
        catch (Exception ex)
        {
            CleanupMedia(stagingRoot, preserveLog: true);
            return RenderExecutionResult.Failed($"渲染编译失败：{ex.Message}");
        }
    }

    private async Task<IProcessResult> RunProcessAttemptAsync(
        FfmpegCompileResult compileResult,
        string stagingRoot,
        TimeSpan expectedDuration,
        IProgress<RenderProgress>? progress,
        CancellationToken cancellationToken)
    {
        foreach (var auxiliary in compileResult.AuxiliaryFiles)
        {
            var auxiliaryPath = Path.Combine(stagingRoot, auxiliary.FileName);
            await File.WriteAllTextAsync(
                auxiliaryPath,
                auxiliary.Content,
                cancellationToken).ConfigureAwait(false);
        }

        var processRequest = ProcessRequest.Create(
            compileResult.Command.Executable,
            compileResult.Command.Arguments,
            workingDirectory: stagingRoot,
            priority: ExternalProcessPriority.BelowNormal);

        using var timeoutCts = new CancellationTokenSource(DefaultRenderTimeout);
        using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            timeoutCts.Token);
        return await _runner.RunAsync(
            processRequest,
            CreateProgressHandler(progress, expectedDuration),
            linkedCts.Token).ConfigureAwait(false);
    }

    private async Task<Result<Unit>> RunPreflightAsync(
        RenderRequest request,
        string outputPath,
        CancellationToken cancellationToken)
    {
        var inputs = RenderPreflight.CheckInputs(request);
        if (!inputs.IsSuccess)
        {
            return inputs;
        }

        var outputDir = RenderPreflight.CheckOutputDirectory(outputPath);
        if (!outputDir.IsSuccess)
        {
            return outputDir;
        }

        if (_availableDiskBytes is not null)
        {
            var directory = Path.GetDirectoryName(outputPath)!;
            var driveRoot = Path.GetPathRoot(directory) ?? directory;
            var required = RenderPreflight.EstimateRequiredBytes(request);
            var available = _availableDiskBytes(driveRoot);
            var disk = RenderPreflight.CheckDisk(required, available);
            if (!disk.IsSuccess)
            {
                return disk;
            }
        }

        await Task.CompletedTask.ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        return Result<Unit>.Success(default);
    }

    private static Progress<string>? CreateProgressHandler(
        IProgress<RenderProgress>? progress,
        TimeSpan expectedDuration)
    {
        if (progress is null)
        {
            return null;
        }

        var gate = new object();
        var blockBuilder = new StringBuilder();
        return new Progress<string>(line =>
        {
            lock (gate)
            {
                blockBuilder.AppendLine(line);
                if (line.StartsWith("progress=", StringComparison.Ordinal))
                {
                    ReportProgress(progress, blockBuilder.ToString(), expectedDuration);
                    blockBuilder.Clear();
                }
            }
        });
    }

    private static void ReportProgress(
        IProgress<RenderProgress> progress,
        string block,
        TimeSpan expectedDuration)
    {
        var parsed = FfmpegProgressParser.Parse(block);
        double? percent = null;
        if (expectedDuration > TimeSpan.Zero && parsed.Position > TimeSpan.Zero)
        {
            percent = Math.Clamp(
                parsed.Position.TotalSeconds / expectedDuration.TotalSeconds * 100.0,
                0,
                99.5);
        }

        progress.Report(new RenderProgress(parsed.Position, parsed.Speed, percent));
    }

    private async Task<Result<Unit>> ValidateOutputAsync(
        string tempOutputPath,
        TimeSpan expectedDuration,
        RenderRequest request,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(tempOutputPath))
        {
            return Result<Unit>.Failure("渲染完成但未生成输出文件。");
        }

        var fileInfo = new FileInfo(tempOutputPath);
        if (fileInfo.Length == 0)
        {
            return Result<Unit>.Failure("渲染输出为零字节，已拒绝提交。");
        }

        try
        {
            var probed = await _probe.ProbeAsync(tempOutputPath, cancellationToken).ConfigureAwait(false);
            if (probed.Duration <= TimeSpan.Zero)
            {
                return Result<Unit>.Failure("无法读取输出视频时长，已拒绝提交。");
            }

            var delta = Math.Abs((probed.Duration - expectedDuration).TotalSeconds);
            var tolerance = Math.Max(DurationToleranceSeconds, 1.0 / (double)Math.Max(probed.FrameRate, 1m));
            if (delta > tolerance)
            {
                return Result<Unit>.Failure(
                    $"输出时长与预期不符（预期 {expectedDuration.TotalSeconds:0.###} 秒，实际 {probed.Duration.TotalSeconds:0.###} 秒）。");
            }

            var outputSettings = request.OutputVideoSettings;
            if (!outputSettings.IsOriginalResolution)
            {
                var expectedSize = ResolveExpectedOutputSize(request);
                var actualSize = OutputCanvasResolver.NormalizeDimensions(
                    probed.Width,
                    probed.Height,
                    probed.RotationDegrees);
                if (actualSize != expectedSize)
                {
                    return Result<Unit>.Failure(
                        $"输出分辨率与所选规格不符（预期 {expectedSize.Width}×{expectedSize.Height}，实际 {actualSize.Width}×{actualSize.Height}）。");
                }
            }

            if (!outputSettings.IsOriginalFrameRate)
            {
                var expectedFrameRate = outputSettings.ResolveFrameRate(
                    request.Plan.Clips[0].Asset.Info.FrameRate);
                if (Math.Abs(probed.FrameRate - expectedFrameRate) > 0.01m)
                {
                    return Result<Unit>.Failure(
                        $"输出帧率与所选规格不符（预期 {expectedFrameRate:0.###} fps，实际 {probed.FrameRate:0.###} fps）。");
                }
            }
        }
        catch (MediaProbeException ex)
        {
            return Result<Unit>.Failure($"输出验证失败：{ex.Message}");
        }

        return Result<Unit>.Success(default);
    }

    private static (int Width, int Height) ResolveExpectedOutputSize(RenderRequest request)
    {
        var (canvasWidth, canvasHeight) = OutputCanvasResolver.Resolve(request);
        return request.OutputVideoSettings.ResolveTargetSize(canvasWidth, canvasHeight);
    }

    private static void MoveToFinalOutput(string tempOutputPath, string finalOutputPath)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(finalOutputPath)!);
        if (File.Exists(finalOutputPath))
        {
            File.Replace(tempOutputPath, finalOutputPath, null);
        }
        else
        {
            File.Move(tempOutputPath, finalOutputPath);
        }
    }

    private static string MapProcessFailure(int exitCode, string stderr)
    {
        var summary = SummarizeStderr(stderr);
        return string.IsNullOrWhiteSpace(summary)
            ? $"FFmpeg 渲染失败，退出码 {exitCode}。"
            : $"FFmpeg 渲染失败，退出码 {exitCode}：{summary}";
    }

    private static string SummarizeStderr(string stderr)
    {
        if (string.IsNullOrWhiteSpace(stderr))
        {
            return string.Empty;
        }

        var lines = stderr.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (lines.Length == 0)
        {
            return string.Empty;
        }

        for (var index = lines.Length - 1; index >= 0; index--)
        {
            if (!IsGenericFfmpegFailureTrailer(lines[index]))
            {
                return lines[index];
            }
        }

        return lines[^1];
    }

    private static bool IsGenericFfmpegFailureTrailer(string line) =>
        line.Equals("Conversion failed!", StringComparison.OrdinalIgnoreCase) ||
        line.Equals("Error reinitializing filters!", StringComparison.OrdinalIgnoreCase) ||
        line.Equals("Error while filtering: Invalid argument", StringComparison.OrdinalIgnoreCase) ||
        line.Contains("Qavg:", StringComparison.OrdinalIgnoreCase) ||
        line.StartsWith("video:", StringComparison.OrdinalIgnoreCase) ||
        line.StartsWith("frame=", StringComparison.OrdinalIgnoreCase);

    internal static bool IsHardwareEncoderFailure(VideoEncoderKind encoder, string stderr)
    {
        if (encoder == VideoEncoderKind.Libx264 || string.IsNullOrWhiteSpace(stderr))
        {
            return false;
        }

        var hasEncoderFamily = encoder switch
        {
            VideoEncoderKind.H264Nvenc =>
                ContainsAny(stderr, "h264_nvenc", "nvenc", "nvcuda", "cuda"),
            VideoEncoderKind.H264Qsv =>
                ContainsAny(stderr, "h264_qsv", "qsv", "mfx"),
            VideoEncoderKind.H264Amf =>
                ContainsAny(stderr, "h264_amf", "amf"),
            _ => false
        };
        if (!hasEncoderFamily)
        {
            return false;
        }

        return ContainsAny(
            stderr,
            "no capable devices found",
            "cannot load nvcuda",
            "error initializing output stream",
            "failed to initialise",
            "failed to initialize",
            "device setup failed",
            "device lost",
            "unsupported device",
            "initializing an internal mfx session",
            "failed to create mfx session",
            "amf failed to initialise",
            "encoder initialization failed");
    }

    private static bool ContainsAny(string value, params string[] tokens) =>
        tokens.Any(token => value.Contains(token, StringComparison.OrdinalIgnoreCase));

    private static string CombineOutput(IProcessResult result)
    {
        var builder = new StringBuilder();
        if (!string.IsNullOrWhiteSpace(result.StandardOutput))
        {
            builder.AppendLine(result.StandardOutput);
        }

        if (!string.IsNullOrWhiteSpace(result.StandardError))
        {
            builder.AppendLine(result.StandardError);
        }

        return builder.ToString();
    }

    private static void AppendAttemptLog(
        StringBuilder builder,
        string title,
        IProcessResult result)
    {
        builder.Append("=== ").Append(title).AppendLine(" ===");
        builder.Append("退出码：").AppendLine(result.ExitCode.ToString(CultureInfo.InvariantCulture));
        var output = CombineOutput(result);
        builder.AppendLine(string.IsNullOrWhiteSpace(output) ? "（无进程输出）" : output.TrimEnd());
    }

    private static async Task WriteLogAsync(string logPath, string content, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);
        await File.WriteAllTextAsync(logPath, content, cancellationToken).ConfigureAwait(false);
    }

    private static void CleanupMedia(string stagingRoot, bool preserveLog)
    {
        if (!Directory.Exists(stagingRoot))
        {
            return;
        }

        foreach (var file in Directory.EnumerateFiles(stagingRoot))
        {
            if (preserveLog && Path.GetFileName(file).Equals("render.log", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            TryDelete(file);
        }
    }

    private static void CleanupStagingDirectory(string stagingRoot, bool preserveLog)
    {
        if (!Directory.Exists(stagingRoot))
        {
            return;
        }

        if (preserveLog)
        {
            foreach (var file in Directory.EnumerateFiles(stagingRoot))
            {
                if (!Path.GetFileName(file).Equals("render.log", StringComparison.OrdinalIgnoreCase))
                {
                    TryDelete(file);
                }
            }

            return;
        }

        TryDeleteDirectory(stagingRoot);
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private static void TryDeleteDirectory(string path)
    {
        try
        {
            Directory.Delete(path, recursive: true);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
