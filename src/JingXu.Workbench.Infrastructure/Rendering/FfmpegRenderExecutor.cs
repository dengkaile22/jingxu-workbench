using System.Diagnostics;
using System.Globalization;
using System.Text;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Media;
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
    private readonly IVideoProcessingSelector? _processingSelector;
    private readonly RenderDiskSpaceReservations _diskReservations;

    public FfmpegRenderExecutor(
        IExternalProcessRunner runner,
        IMediaProbe probe,
        RuntimeResolver runtimeResolver,
        string? userRuntimeDirectory = null,
        Func<string, long>? availableDiskBytes = null,
        IVideoEncoderSelector? encoderSelector = null,
        RenderDiskSpaceReservations? diskReservations = null,
        IVideoProcessingSelector? processingSelector = null)
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
        _processingSelector = processingSelector;
        _diskReservations = diskReservations ?? new RenderDiskSpaceReservations();
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

        var outputDirectory = Path.GetDirectoryName(Path.GetFullPath(job.Request.OutputPath))!;
        var stagingRoot = Path.Combine(outputDirectory, TempDirectoryName, job.Id.ToString("N"));
        TempResourceLease? resource = null;
        try
        {
            resource = TempResourceLease.Acquire(stagingRoot, isDirectory: true);
            using var diskReservation = AcquireDiskReservation(job, stagingRoot);
            var result = await ExecuteCoreAsync(job, progress, diskReservation, cancellationToken).ConfigureAwait(false);
            if (!result.IsSuccess && Directory.Exists(stagingRoot))
            {
                var logPath = RenderDiagnosticStore.Preserve(job, stagingRoot,
                    result.FailureInfo?.Message ?? "任务已取消。");
                if (logPath is not null && result.FailureInfo is not null)
                {
                    result = result with { FailureInfo = new RenderFailure(result.FailureInfo.Message + "\n诊断日志：" + logPath) };
                }
            }

            return result;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return RenderExecutionResult.Failed($"渲染资源准备失败：{ex.Message}");
        }
        finally
        {
            if (resource is not null)
            {
                TryDeleteOwnedStaging(job.Id, stagingRoot);
                TryDeleteOwnedTempSubtitle(job.Request.SubtitleBurn?.SubtitleFilePath);
                resource.Dispose();
            }
        }
    }

    private async Task<RenderExecutionResult> ExecuteCoreAsync(
        RenderJob job,
        IProgress<RenderProgress>? progress,
        RenderDiskSpaceReservations.Reservation? diskReservation,
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
            // 登记 staging 位置，便于启动时清掉「素材旁分镜输出」下因崩溃留下的孤儿目录。
            StagingLeaseStore.Track(job.Id, stagingRoot);

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
            var (processingCanvasWidth, processingCanvasHeight) = OutputCanvasResolver.Resolve(request);
            var processingTarget = request.OutputVideoSettings.ResolveTargetSize(processingCanvasWidth, processingCanvasHeight);
            var shouldProbeProcessing = request.ProcessingMode == VideoProcessingMode.Gpu
                || (request.ProcessingMode == VideoProcessingMode.Auto && request.Plan.Clips.Any(clip =>
                    HardwareVideoProcessingPlan.HasDownscaleOpportunity(clip.Asset.Info, request.Aspect.FitMode,
                        processingTarget.Width, processingTarget.Height)));
            var processingPlan = _processingSelector is not null && !isStreamCopy
                && request.SubtitleBurn is null && shouldProbeProcessing
                ? await _processingSelector.SelectAsync(ffmpeg.Path, request.ProcessingMode, selection.Kind, cancellationToken).ConfigureAwait(false)
                : HardwareVideoProcessingPlan.Software;
            if (processingPlan.Kind != HardwareVideoProcessingKind.Software)
            {
                request = await RefreshLegacyPixelFormatsAsync(request, cancellationToken).ConfigureAwait(false);
            }

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
                    selection.Kind,
                    processingPlan);
                expectedDuration = request.Plan.Duration;
            }

            var budget = RenderPreflight.CheckCommandBudget(compileResult.Command.EstimatedCommandLineLength);
            if (!budget.IsSuccess)
            {
                return RenderExecutionResult.Failed(budget.Error!);
            }

            try
            {
                StagingInputMaterializer.Materialize(stagingRoot, compileResult.InputAliases,
                    (path, bytes) => ReserveCopyWithCleanup(diskReservation, path, bytes, job));
            }
            catch (FileNotFoundException ex)
            {
                return RenderExecutionResult.Failed(ex.Message);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
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
                return RenderExecutionResult.Cancelled();
            }

            var log = new StringBuilder();
            log.AppendLine("=== 编码器选择 ===");
            log.AppendLine(selection.DisplayName);
            log.AppendLine("=== 视频处理阶段 ===");
            log.AppendLine(compileResult.ProcessingDescription);
            log.AppendLine();
            AppendAttemptLog(
                log,
                selection.Kind == VideoEncoderKind.Libx264 ? "CPU / 直拷尝试" : "GPU 尝试",
                processResult);

            string? successNotice = compileResult.HardwareDecodedInputs > 0
                || (_processingSelector is not null && !isStreamCopy && request.SubtitleBurn is null)
                ? selection.Notice + " " + compileResult.ProcessingDescription
                : selection.Notice;
            if (processResult.ExitCode != 0 && compileResult.HardwareDecodedInputs > 0
                && (HardwareVideoProcessingFailure.IsHardwareFailure(processResult.StandardError)
                    || IsHardwareEncoderFailure(selection.Kind, processResult.StandardError)))
            {
                // 先移除输入硬解/缩放，保留已选硬编；不能把输入设备问题直接归咎于编码器。
                TryDelete(tempOutputPath);
                log.AppendLine();
                log.AppendLine("=== 回退软件解码，保留所选编码器 ===");
                var softwareDecode = FfmpegCommandCompiler.Compile(ffmpeg.Path, request, tempOutputPath, selection.Kind);
                var decodeBudget = RenderPreflight.CheckCommandBudget(softwareDecode.Command.EstimatedCommandLineLength);
                if (!decodeBudget.IsSuccess)
                {
                    await WriteLogAsync(logPath, log.ToString(), cancellationToken).ConfigureAwait(false);
                    return RenderExecutionResult.Failed(decodeBudget.Error!);
                }

                try
                {
                    // 输入别名与首轮一致，仅重写滤镜辅助文件。
                    processResult = await RunProcessAttemptAsync(softwareDecode, stagingRoot, expectedDuration, progress, cancellationToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    log.AppendLine("软件解码回退过程中任务已取消。");
                    await WriteLogAsync(logPath, log.ToString(), CancellationToken.None).ConfigureAwait(false);
                    return RenderExecutionResult.Cancelled();
                }
                log.AppendLine(softwareDecode.ProcessingDescription);
                AppendAttemptLog(log, "CPU 解码 / 保留编码器尝试", processResult);
                successNotice = $"GPU 硬解或缩放不可用，已使用 CPU 解码；保留 {selection.DisplayName} 编码完成。";
            }

            if (processResult.ExitCode != 0 &&
                selection.Kind != VideoEncoderKind.Libx264 &&
                IsHardwareEncoderFailure(selection.Kind, processResult.StandardError))
            {
                // 本会话记住坏编码器，后续任务直接改探 QSV/AMF 或 CPU，避免每单都先 GPU 失败。
                _encoderSelector.RememberHardwareFailure(ffmpeg.Path, selection.Kind);
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
                    return RenderExecutionResult.Failed(cpuBudget.Error!);
                }

                try
                {
                    StagingInputMaterializer.Materialize(stagingRoot, cpuCompileResult.InputAliases,
                        (path, bytes) => ReserveCopyWithCleanup(diskReservation, path, bytes, job));
                }
                catch (FileNotFoundException ex)
                {
                    await WriteLogAsync(logPath, log.ToString(), cancellationToken).ConfigureAwait(false);
                    return RenderExecutionResult.Failed(ex.Message);
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    await WriteLogAsync(logPath, log.ToString(), cancellationToken).ConfigureAwait(false);
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
                    return RenderExecutionResult.Cancelled();
                }

                AppendAttemptLog(log, "CPU 尝试", processResult);
                successNotice = "GPU 编码不可用，已自动改用 CPU 完成。";
            }

            if (processResult.ExitCode != 0)
            {
                await WriteLogAsync(logPath, log.ToString(), cancellationToken)
                    .ConfigureAwait(false);
                return RenderExecutionResult.Failed(MapProcessFailure(processResult.ExitCode, processResult.StandardError));
            }

            await WriteLogAsync(logPath, log.ToString(), cancellationToken)
                .ConfigureAwait(false);

            var validation = await ValidateOutputAsync(tempOutputPath, expectedDuration, request, cancellationToken)
                .ConfigureAwait(false);
            if (!validation.IsSuccess)
            {
                return RenderExecutionResult.Failed(validation.Error!);
            }

            MoveToFinalOutput(tempOutputPath, outputPath);
            return RenderExecutionResult.Success(successNotice);
        }
        catch (OperationCanceledException)
        {
            return RenderExecutionResult.Cancelled();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return RenderExecutionResult.Failed($"写入输出文件失败：{ex.Message}");
        }
        catch (Exception ex)
        {
            return RenderExecutionResult.Failed($"渲染编译失败：{ex.Message}");
        }
    }

    /// <summary>旧快照没有像素格式时只补本轮主片编译信息，不改变持久化计划、时长或画幅。</summary>
    private async Task<RenderRequest> RefreshLegacyPixelFormatsAsync(RenderRequest request, CancellationToken cancellationToken)
    {
        var known = new Dictionary<string, MediaInfo?>(StringComparer.OrdinalIgnoreCase);
        var clips = request.Plan.Clips.ToArray();
        for (var index = 0; index < clips.Length; index++)
        {
            var asset = clips[index].Asset;
            if (!string.IsNullOrWhiteSpace(asset.Info.PixelFormat)
                || !string.Equals(asset.Info.VideoCodec, "h264", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            if (!known.TryGetValue(asset.Path, out var current))
            {
                try { current = await _probe.ProbeAsync(asset.Path, cancellationToken).ConfigureAwait(false); }
                catch (OperationCanceledException) { throw; }
                catch (Exception ex)
                {
                    Trace.TraceWarning($"无法补充素材像素格式，继续使用软件解码：{ex.Message}");
                    current = null;
                }
                known[asset.Path] = current;
            }
            if (current is not null && current.Width == asset.Info.Width && current.Height == asset.Info.Height
                && current.RotationDegrees == asset.Info.RotationDegrees
                && string.Equals(current.VideoCodec, asset.Info.VideoCodec, StringComparison.OrdinalIgnoreCase))
            {
                clips[index] = clips[index] with { Asset = asset with { Info = asset.Info with { PixelFormat = current.PixelFormat } } };
            }
        }
        return request with { Plan = request.Plan with { Clips = clips } };
    }

    private RenderDiskSpaceReservations.Reservation? AcquireDiskReservation(RenderJob job, string stagingRoot)
    {
        if (_availableDiskBytes is null)
        {
            return null;
        }

        var temporaryOutput = Path.Combine(stagingRoot, "output.mp4");
        var estimated = RenderPreflight.EstimateRequiredBytes(job.Request!);
        try
        {
            return _diskReservations.Acquire(temporaryOutput, estimated, _availableDiskBytes);
        }
        catch (IOException)
        {
            // 清理只跟随本软件失效资源登记；活跃任务（包括本任务）受租约保护。
            WorkbenchCacheCleanup.Cleanup(
                extraSearchRoots: [Path.GetDirectoryName(job.Request!.OutputPath)!],
                protectedJobIds: [job.Id],
                includeOverlayThumbCache: false);
            return _diskReservations.Acquire(temporaryOutput, estimated, _availableDiskBytes);
        }
    }

    private static void ReserveCopyWithCleanup(RenderDiskSpaceReservations.Reservation? reservation,
        string path, long bytes, RenderJob job)
    {
        if (reservation is null)
        {
            return;
        }

        try { reservation.ReserveCopy(path, bytes); }
        catch (IOException)
        {
            WorkbenchCacheCleanup.Cleanup(
                extraSearchRoots: [Path.GetDirectoryName(job.Request!.OutputPath)!],
                protectedJobIds: [job.Id], includeOverlayThumbCache: false);
            reservation.ReserveCopy(path, bytes);
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
        if (exitCode == -12 || ContainsAny(summary, "cannot allocate memory", "out of memory"))
        {
            var detail = string.IsNullOrWhiteSpace(summary) ? string.Empty : $" 原因：{summary}";
            return $"FFmpeg 内存申请失败，退出码 {exitCode}。请关闭其他占用内存的程序，或降低输出分辨率后重试。{detail}";
        }

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

        string? lastUsefulLine = null;
        for (var index = lines.Length - 1; index >= 0; index--)
        {
            var line = lines[index];
            if (IsGenericFfmpegFailureTrailer(line))
            {
                continue;
            }

            lastUsefulLine ??= line;
            // FFmpeg 收尾时还会打印统计、弃用警告；优先展示真正的失败原因。
            if (ContainsAny(line, "error", "failed", "invalid", "cannot", "could not",
                    "no such file", "permission denied", "not found", "unable", "out of memory"))
            {
                return line;
            }
        }

        return lastUsefulLine ?? string.Empty;
    }

    private static bool IsGenericFfmpegFailureTrailer(string line)
    {
        // 新版 FFmpeg 的统计行带有 [out#0/mp4 @ ...] 前缀，不能只匹配行首 video:。
        while (line.StartsWith('[') && line.IndexOf(']') is var end && end >= 0)
        {
            line = line[(end + 1)..].TrimStart();
        }

        return line.Equals("Conversion failed!", StringComparison.OrdinalIgnoreCase) ||
            line.Equals("Error reinitializing filters!", StringComparison.OrdinalIgnoreCase) ||
            line.Equals("Error while filtering: Invalid argument", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Qavg:", StringComparison.OrdinalIgnoreCase) ||
            line.StartsWith("video:", StringComparison.OrdinalIgnoreCase) ||
            line.StartsWith("frame=", StringComparison.OrdinalIgnoreCase) ||
            line.StartsWith("Task finished with error code:", StringComparison.OrdinalIgnoreCase) ||
            line.StartsWith("Terminating thread with return code", StringComparison.OrdinalIgnoreCase);
    }

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
            "cannot load nvencodeapi",
            "error initializing output stream",
            "error while opening encoder",
            "openencodesession",
            "native frames context",
            "nvenc api",
            "failed to initialise",
            "failed to initialize",
            "device setup failed",
            "device lost",
            "unsupported device",
            "initializing an internal mfx session",
            "failed to create mfx session",
            "amf failed to initialise",
            "encoder initialization failed",
            "out of memory");
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

    /// <summary>
    /// 删除本任务 staging。文件被占用时吞掉 IO 异常并保留 lease，下次启动再扫；不得抛出以免卡住状态机。
    /// </summary>
    private static void TryDeleteOwnedStaging(Guid jobId, string stagingRoot)
    {
        TryDeleteDirectoryBestEffort(stagingRoot);
        // 共享 .jingxu-tmp 父目录交给协调后的清理器；其他任务可能正在其中创建自己的目录。
        // 清理失败的路径由外层 TempResourceLease 在释放时登记为失效资源，供后续回收。
        StagingLeaseStore.Untrack(jobId);
    }

    /// <summary>字幕实验室的临时 ASS 在烧录结束后删除；用户自选字幕路径绝不动。</summary>
    private static void TryDeleteOwnedTempSubtitle(string? subtitlePath)
    {
        if (!WorkbenchCacheCleanup.IsOwnedTempSubtitlePath(subtitlePath) || subtitlePath is null)
        {
            return;
        }

        TempResourceLease.TryDeleteUnusedSubtitle(subtitlePath);
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException ex)
        {
            Trace.TraceWarning($"无法删除临时文件 {path}：{ex.Message}");
        }
        catch (UnauthorizedAccessException ex)
        {
            Trace.TraceWarning($"无权删除临时文件 {path}：{ex.Message}");
        }
    }

    private static void TryDeleteDirectoryBestEffort(string path)
    {
        try
        {
            if (!Directory.Exists(path))
            {
                return;
            }

            foreach (var file in Directory.GetFiles(path, "*", SearchOption.AllDirectories))
            {
                TryDelete(file);
            }

            foreach (var dir in Directory.GetDirectories(path, "*", SearchOption.AllDirectories)
                         .OrderByDescending(static d => d.Length))
            {
                TryDeleteDirectoryIfEmpty(dir);
            }

            TryDeleteDirectoryIfEmpty(path);
        }
        catch (IOException ex)
        {
            Trace.TraceWarning($"无法删除暂存目录 {path}：{ex.Message}");
        }
        catch (UnauthorizedAccessException ex)
        {
            Trace.TraceWarning($"无权删除暂存目录 {path}：{ex.Message}");
        }
    }

    private static void TryDeleteDirectoryIfEmpty(string path)
    {
        try
        {
            if (Directory.Exists(path) && !Directory.EnumerateFileSystemEntries(path).Any())
            {
                Directory.Delete(path, recursive: false);
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
