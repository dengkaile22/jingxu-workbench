using System.Globalization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.IntegrationTests.Media;

/// <summary>由 FFmpeg 自报峰值工作集，只为真实渲染命令增加测量，不改变媒体处理参数。</summary>
internal sealed class MeasuredRenderProcessRunner : IExternalProcessRunner
{
    private readonly ExternalProcessRunner _runner = new();
    public long PeakWorkingSetKiB { get; private set; }
    public string RenderLog { get; private set; } = string.Empty;

    public void ResetMeasurement()
    {
        PeakWorkingSetKiB = 0;
        RenderLog = string.Empty;
    }

    public async Task<IProcessResult> RunAsync(IProcessRequest request, IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        if (!request.Arguments.Contains("-progress", StringComparer.Ordinal))
        {
            return await _runner.RunAsync(request, progress, cancellationToken);
        }

        var measured = ProcessRequest.Create(request.Executable, ["-benchmark", .. request.Arguments],
            request.WorkingDirectory, request.EnvironmentOverrides, request.Priority);
        var result = await _runner.RunAsync(measured, progress, cancellationToken);
        RenderLog += result.StandardError + Environment.NewLine;
        const string prefix = "bench: maxrss=";
        foreach (var line in result.StandardError.Split('\n', StringSplitOptions.TrimEntries))
        {
            if (line.StartsWith(prefix, StringComparison.Ordinal) && line.EndsWith("KiB", StringComparison.Ordinal) &&
                long.TryParse(line.AsSpan(prefix.Length, line.Length - prefix.Length - 3),
                    NumberStyles.Integer, CultureInfo.InvariantCulture, out var peak))
            {
                PeakWorkingSetKiB = Math.Max(PeakWorkingSetKiB, peak);
            }
        }

        return result;
    }
}
