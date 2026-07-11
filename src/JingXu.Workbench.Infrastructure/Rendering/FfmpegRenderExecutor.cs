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
    private const double DurationToleranceSeconds = 0.1;

    private readonly IExternalProcessRunner _runner;
    private readonly IMediaProbe _probe;
    private readonly RuntimeResolver _runtimeResolver;
    private readonly string? _userRuntimeDirectory;
    private readonly Func<string, long>? _availableDiskBytes;

    public FfmpegRenderExecutor(
        IExternalProcessRunner runner,
        IMediaProbe probe,
        RuntimeResolver runtimeResolver,
        string? userRuntimeDirectory = null,
        Func<string, long>? availableDiskBytes = null)
    {
        ArgumentNullException.ThrowIfNull(runner);
        ArgumentNullException.ThrowIfNull(probe);
        ArgumentNullException.ThrowIfNull(runtimeResolver);
        _runner = runner;
        _probe = probe;
        _runtimeResolver = runtimeResolver;
        _userRuntimeDirectory = userRuntimeDirectory;
        _availableDiskBytes = availableDiskBytes;
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

            FfmpegCompileResult compileResult;
            TimeSpan expectedDuration;
            if (request.SubtitleBurn is not null)
            {
                compileResult = SubtitleBurnInCommandCompiler.Compile(ffmpeg.Path, request.SubtitleBurn, tempOutputPath);
                expectedDuration = request.Plan.Duration;
            }
            else
            {
                compileResult = FfmpegCommandCompiler.Compile(ffmpeg.Path, request, tempOutputPath);
                expectedDuration = request.Plan.Duration;
            }

            var budget = RenderPreflight.CheckCommandBudget(compileResult.Command.EstimatedCommandLineLength);
            if (!budget.IsSuccess)
            {
                return RenderExecutionResult.Failed(budget.Error!);
            }

            foreach (var auxiliary in compileResult.AuxiliaryFiles)
            {
                var auxiliaryPath = Path.Combine(stagingRoot, auxiliary.FileName);
                await File.WriteAllTextAsync(auxiliaryPath, auxiliary.Content, cancellationToken).ConfigureAwait(false);
            }

            var processRequest = ProcessRequest.Create(
                compileResult.Command.Executable,
                compileResult.Command.Arguments,
                workingDirectory: stagingRoot);

            IProcessResult processResult;
            try
            {
                processResult = await _runner.RunAsync(
                    processRequest,
                    CreateProgressHandler(progress),
                    cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                await WriteLogAsync(logPath, "任务已取消。", cancellationToken).ConfigureAwait(false);
                CleanupMedia(stagingRoot, preserveLog: true);
                return RenderExecutionResult.Cancelled();
            }

            await WriteLogAsync(logPath, CombineOutput(processResult), cancellationToken)
                .ConfigureAwait(false);

            if (processResult.ExitCode != 0)
            {
                CleanupMedia(stagingRoot, preserveLog: true);
                return RenderExecutionResult.Failed(MapProcessFailure(processResult.ExitCode, processResult.StandardError));
            }

            var validation = await ValidateOutputAsync(tempOutputPath, expectedDuration, cancellationToken)
                .ConfigureAwait(false);
            if (!validation.IsSuccess)
            {
                CleanupMedia(stagingRoot, preserveLog: true);
                return RenderExecutionResult.Failed(validation.Error!);
            }

            MoveToFinalOutput(tempOutputPath, outputPath);
            CleanupStagingDirectory(stagingRoot, preserveLog: true);
            return RenderExecutionResult.Success();
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

    private static Progress<string>? CreateProgressHandler(IProgress<RenderProgress>? progress)
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
                    ReportProgress(progress, blockBuilder.ToString());
                    blockBuilder.Clear();
                }
            }
        });
    }

    private static void ReportProgress(IProgress<RenderProgress> progress, string block)
    {
        var parsed = FfmpegProgressParser.Parse(block);
        progress.Report(new RenderProgress(parsed.Position, parsed.Speed, null));
    }

    private async Task<Result<Unit>> ValidateOutputAsync(
        string tempOutputPath,
        TimeSpan expectedDuration,
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
        }
        catch (MediaProbeException ex)
        {
            return Result<Unit>.Failure($"输出验证失败：{ex.Message}");
        }

        return Result<Unit>.Success(default);
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
        return lines.Length == 0 ? string.Empty : lines[^1];
    }

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
