using System.ComponentModel;
using System.IO;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Media;

/// <summary>
/// 通过 FFprobe 子进程探测媒体元信息。参数以独立列表传入，不使用 shell 拼接。
/// 子进程隔离运行；超时或启动失败均转为 <see cref="MediaProbeException"/>，不致进程退出。
/// </summary>
public sealed class FfprobeMediaProbe : IMediaProbe
{
    private static readonly TimeSpan DefaultProbeTimeout = TimeSpan.FromSeconds(60);

    private static readonly string[] ProbeArgumentsPrefix =
    [
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,duration:stream_tags=rotate:stream_side_data=rotation:format=duration"
    ];

    private readonly IExternalProcessRunner _runner;
    private readonly RuntimeResolver _runtimeResolver;
    private readonly string? _userRuntimeDirectory;
    private readonly TimeSpan _probeTimeout;

    /// <summary>创建 FFprobe 媒体探测器。</summary>
    /// <param name="runner">外部进程执行器。</param>
    /// <param name="runtimeResolver">运行时定位器。</param>
    /// <param name="userRuntimeDirectory">用户指定的 FFmpeg/FFprobe 目录，可为空。</param>
    /// <param name="probeTimeout">单次探测超时；为空时使用默认 60 秒。</param>
    public FfprobeMediaProbe(
        IExternalProcessRunner runner,
        RuntimeResolver runtimeResolver,
        string? userRuntimeDirectory = null,
        TimeSpan? probeTimeout = null)
    {
        ArgumentNullException.ThrowIfNull(runner);
        ArgumentNullException.ThrowIfNull(runtimeResolver);
        _runner = runner;
        _runtimeResolver = runtimeResolver;
        _userRuntimeDirectory = userRuntimeDirectory;
        _probeTimeout = probeTimeout is { } timeout && timeout > TimeSpan.Zero
            ? timeout
            : DefaultProbeTimeout;
    }

    /// <inheritdoc />
    public async Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(absolutePath);

        RuntimeResolution resolution;
        try
        {
            resolution = _runtimeResolver.Resolve("ffprobe", _userRuntimeDirectory);
        }
        catch (RuntimeToolNotFoundException)
        {
            throw new MediaProbeException(
                absolutePath,
                "未找到 FFprobe。请将 FFmpeg 放入 runtime/ffmpeg/，在设置中指定路径，或加入系统 PATH。");
        }

        var arguments = new List<string>(ProbeArgumentsPrefix.Length + 1);
        arguments.AddRange(ProbeArgumentsPrefix);
        arguments.Add(absolutePath);

        IProcessResult result;
        try
        {
            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeoutCts.CancelAfter(_probeTimeout);
            var request = ProcessRequest.Create(resolution.Path, arguments);
            result = await _runner.RunAsync(request, progress: null, timeoutCts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new MediaProbeException(
                absolutePath,
                $"媒体探测超时（超过 {(int)_probeTimeout.TotalSeconds} 秒）。请检查文件是否损坏或路径是否可访问。");
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex) when (ex is InvalidOperationException or Win32Exception or IOException)
        {
            throw new MediaProbeException(
                absolutePath,
                $"无法启动 FFprobe：{ex.Message}",
                innerException: ex);
        }
        catch (Exception ex)
        {
            // 任何子进程/原生互操作异常都转为业务失败，避免导入闪退。
            throw new MediaProbeException(
                absolutePath,
                $"媒体探测失败：{ex.Message}",
                innerException: ex);
        }

        if (result.ExitCode != 0)
        {
            var stderrSummary = SummarizeStderr(result.StandardError);
            throw new MediaProbeException(
                absolutePath,
                $"媒体探测失败：FFprobe 退出码 {result.ExitCode}。",
                stderrSummary);
        }

        try
        {
            return FfprobeJsonParser.Parse(result.StandardOutput);
        }
        catch (MediaProbeException ex) when (string.IsNullOrEmpty(ex.MediaPath))
        {
            throw new MediaProbeException(
                absolutePath,
                ex.Message,
                SummarizeStderr(result.StandardError),
                ex);
        }
    }

    private static string? SummarizeStderr(string stderr)
    {
        if (string.IsNullOrWhiteSpace(stderr))
        {
            return null;
        }

        var trimmed = stderr.Trim();
        const int maxLength = 500;
        return trimmed.Length <= maxLength ? trimmed : trimmed[..maxLength];
    }
}
