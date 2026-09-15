using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Processes;
using System.Collections.Concurrent;
using System.Diagnostics;

namespace JingXu.Workbench.Infrastructure.Rendering;

public interface IVideoProcessingSelector
{
    Task<HardwareVideoProcessingPlan> SelectAsync(string ffmpegExecutable, VideoProcessingMode mode, VideoEncoderKind encoder, CancellationToken cancellationToken);
    void ResetProbe(string ffmpegExecutable);
}

public sealed class HardwareVideoProcessingSelector : IVideoProcessingSelector
{
    private readonly IExternalProcessRunner _runner;
    private readonly TimeSpan _probeTimeout;
    private readonly ConcurrentDictionary<string, Lazy<Task<HardwareVideoProcessingPlan>>> _cache = new(StringComparer.OrdinalIgnoreCase);

    public HardwareVideoProcessingSelector(IExternalProcessRunner runner, TimeSpan? probeTimeout = null)
    {
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));
        _probeTimeout = probeTimeout is { } timeout && timeout > TimeSpan.Zero ? timeout : TimeSpan.FromSeconds(8);
    }

    public async Task<HardwareVideoProcessingPlan> SelectAsync(string ffmpegExecutable, VideoProcessingMode mode, VideoEncoderKind encoder, CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegExecutable);
        cancellationToken.ThrowIfCancellationRequested();
        if (mode == VideoProcessingMode.Cpu)
        {
            return HardwareVideoProcessingPlan.Software;
        }
        if (mode is not VideoProcessingMode.Auto and not VideoProcessingMode.Gpu)
        {
            throw new ArgumentOutOfRangeException(nameof(mode));
        }

        var key = NormalizePath(ffmpegExecutable) + "|" + encoder;
        var probe = _cache.GetOrAdd(key, _ => new Lazy<Task<HardwareVideoProcessingPlan>>(
            () => ProbeAsync(ffmpegExecutable, encoder), LazyThreadSafetyMode.ExecutionAndPublication));
        return await probe.Value.WaitAsync(cancellationToken).ConfigureAwait(false);
    }

    public void ResetProbe(string ffmpegExecutable)
    {
        if (string.IsNullOrWhiteSpace(ffmpegExecutable)) { return; }
        var prefix = NormalizePath(ffmpegExecutable) + "|";
        foreach (var key in _cache.Keys.Where(key => key.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)))
        {
            _cache.TryRemove(key, out _);
        }
    }

    private async Task<HardwareVideoProcessingPlan> ProbeAsync(string ffmpeg, VideoEncoderKind encoder)
    {
        var directory = Path.Combine(WorkbenchDataPaths.GetTempDirectory(), "jingxu-gpu-probe-" + Guid.NewGuid().ToString("N"));
        TempResourceLease? lease = null;
        try
        {
            lease = TempResourceLease.Acquire(directory, isDirectory: true);
            Directory.CreateDirectory(directory);
            // 必须真实编码后再硬解；lavfi + hwupload 会把部分可用 QSV 设备误判为失败。
            if (!await RunProbeAsync(ffmpeg, directory,
                ["-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=640x480:r=25:d=0.04",
                 "-frames:v", "1", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "sample.mp4"]).ConfigureAwait(false))
            {
                return HardwareVideoProcessingPlan.Software;
            }

            var candidates = new List<HardwareVideoProcessingPlan>();
            if (encoder == VideoEncoderKind.H264Nvenc)
            {
                candidates.Add(new(HardwareVideoProcessingKind.Cuda, true));
            }
            else if (encoder == VideoEncoderKind.H264Qsv)
            {
                candidates.Add(new(HardwareVideoProcessingKind.Qsv, true));
            }
            candidates.Add(new(HardwareVideoProcessingKind.D3D11, false));
            foreach (var plan in candidates)
            {
                var arguments = new List<string> { "-hide_banner", "-loglevel", "error" };
                arguments.AddRange(plan.DeviceArguments);
                arguments.AddRange(plan.InputArguments);
                arguments.AddRange(["-threads", "2", "-i", "sample.mp4", "-vf",
                    plan.CanScale ? plan.ScaleAndDownload(320, 240) : HardwareVideoProcessingPlan.DownloadFilter,
                    "-frames:v", "1", "-an", "-f", "null", "-"]);
                if (await RunProbeAsync(ffmpeg, directory, arguments).ConfigureAwait(false))
                {
                    return plan;
                }
            }
            return HardwareVideoProcessingPlan.Software;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
        {
            Trace.TraceWarning($"GPU 处理探测未完成：{ex.Message}");
            return HardwareVideoProcessingPlan.Software;
        }
        finally
        {
            try { if (Directory.Exists(directory)) { Directory.Delete(directory, recursive: true); } }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            { Trace.TraceWarning($"GPU 探测临时目录等待后续清理：{ex.Message}"); }
            lease?.Dispose();
        }
    }

    private async Task<bool> RunProbeAsync(string ffmpeg, string directory, IReadOnlyList<string> arguments)
    {
        using var timeout = new CancellationTokenSource(_probeTimeout);
        try
        {
            var result = await _runner.RunAsync(ProcessRequest.Create(ffmpeg, arguments, workingDirectory: directory), null, timeout.Token).ConfigureAwait(false);
            return result.ExitCode == 0;
        }
        catch (Exception)
        {
            // 设备启动失败或超时仅降低可用能力，不使正式任务失败。
            return false;
        }
    }

    private static string NormalizePath(string path)
    {
        try { return Path.GetFullPath(path.Trim()); }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException) { return path.Trim(); }
    }
}
