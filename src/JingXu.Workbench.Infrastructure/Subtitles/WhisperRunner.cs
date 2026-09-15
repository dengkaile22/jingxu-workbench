using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Subtitles;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Subtitles;

/// <summary>whisper.cpp 本地语音识别。</summary>
public sealed class WhisperRunner : ISpeechRecognizer
{
    private const string WhisperExecutableRelative = "whisper/whisper-cli.exe";
    private const string DefaultModelRelative = "whisper/models/ggml-base.bin";

    private readonly IExternalProcessRunner _runner;
    private readonly RuntimeResolver _runtimeResolver;
    private readonly string _appRoot;
    private readonly string? _userRuntimeDirectory;
    private readonly string _modelRelativePath;

    public WhisperRunner(
        IExternalProcessRunner runner,
        RuntimeResolver runtimeResolver,
        string appRoot,
        string? userRuntimeDirectory = null,
        string? modelRelativePath = null)
    {
        _runner = runner;
        _runtimeResolver = runtimeResolver;
        _appRoot = appRoot;
        _userRuntimeDirectory = userRuntimeDirectory;
        _modelRelativePath = modelRelativePath ?? DefaultModelRelative;
    }

    public async Task<Result<IReadOnlyList<SubtitleCue>>> RecognizeAsync(
        string videoPath,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(videoPath);
        if (!File.Exists(videoPath))
        {
            return Result<IReadOnlyList<SubtitleCue>>.Failure("输入视频不存在。");
        }

        var modelPath = Path.Combine(_appRoot, "runtime", _modelRelativePath.Replace('/', Path.DirectorySeparatorChar));
        if (!File.Exists(modelPath))
        {
            return Result<IReadOnlyList<SubtitleCue>>.Failure(
                "未找到 Whisper 多语言模型。请将 ggml-base.bin 放入 runtime/whisper/models/，或在设置中指定模型路径。");
        }

        RuntimeResolution whisper;
        try
        {
            whisper = _runtimeResolver.ResolveRelative(WhisperExecutableRelative, "whisper-cli", _userRuntimeDirectory);
        }
        catch (RuntimeToolNotFoundException)
        {
            return Result<IReadOnlyList<SubtitleCue>>.Failure(
                "未找到 whisper-cli。请将 whisper.cpp 放入 runtime/whisper/，在设置中指定路径，或加入系统 PATH。");
        }

        var tempRoot = Path.Combine(JingXu.Workbench.Application.Projects.WorkbenchDataPaths.GetTempDirectory(), "jingxu-whisper", Guid.NewGuid().ToString("N"));
        var wavPath = Path.Combine(tempRoot, "audio.wav");
        var outputPrefix = Path.Combine(tempRoot, "result");

        try
        {
            RuntimeResolution ffmpeg;
            using var resource = TempResourceLease.Acquire(tempRoot, isDirectory: true);
            Directory.CreateDirectory(tempRoot);
            try
            {
                ffmpeg = _runtimeResolver.Resolve("ffmpeg", _userRuntimeDirectory);
            }
            catch (RuntimeToolNotFoundException)
            {
                return Result<IReadOnlyList<SubtitleCue>>.Failure(
                    "未找到 FFmpeg，无法提取音频供 Whisper 识别。");
            }

            progress?.Report("正在提取 16kHz 单声道音频…");
            var extractArgs = new[]
            {
                "-y", "-i", videoPath,
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                wavPath
            };
            var extractResult = await _runner.RunAsync(
                ProcessRequest.Create(ffmpeg.Path, extractArgs),
                null,
                cancellationToken).ConfigureAwait(false);
            if (extractResult.ExitCode != 0)
            {
                return Result<IReadOnlyList<SubtitleCue>>.Failure("音频提取失败，无法启动 Whisper。");
            }

            progress?.Report("正在运行 Whisper 识别…");
            var whisperArgs = new List<string>
            {
                "-m", modelPath,
                "-f", wavPath,
                "-l", "auto",
                "-osrt",
                "-of", outputPrefix,
                "-np"
            };
            var whisperResult = await _runner.RunAsync(
                ProcessRequest.Create(whisper.Path, whisperArgs),
                null,
                cancellationToken).ConfigureAwait(false);
            if (whisperResult.ExitCode != 0)
            {
                return Result<IReadOnlyList<SubtitleCue>>.Failure("Whisper 识别失败，请检查模型与运行时。");
            }

            var srtPath = outputPrefix + ".srt";
            if (!File.Exists(srtPath))
            {
                return Result<IReadOnlyList<SubtitleCue>>.Failure("Whisper 未生成 SRT 结果文件。");
            }

            var cues = WhisperSrtParser.Parse(await File.ReadAllTextAsync(srtPath, cancellationToken).ConfigureAwait(false));
            progress?.Report($"识别完成，共 {cues.Count} 条字幕。");
            return Result<IReadOnlyList<SubtitleCue>>.Success(cues);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Result<IReadOnlyList<SubtitleCue>>.Failure($"识别临时文件准备失败：{ex.Message}");
        }
        catch (OperationCanceledException)
        {
            return Result<IReadOnlyList<SubtitleCue>>.Failure("Whisper 识别已取消。");
        }
        finally
        {
            TryDeleteDirectory(tempRoot);
        }
    }

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
