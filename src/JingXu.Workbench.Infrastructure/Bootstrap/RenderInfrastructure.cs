using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Bootstrap;

/// <summary>基础设施层渲染服务工厂。</summary>
public static class RenderInfrastructure
{
    /// <summary>创建真实 FFmpeg 渲染执行器。</summary>
    public static IRenderExecutor CreateFfmpegRenderExecutor(string appRoot, string? userRuntimeDirectory = null) =>
        new FfmpegRenderExecutor(
            new ExternalProcessRunner(),
            CreateMediaProbe(appRoot, userRuntimeDirectory),
            new RuntimeResolver(appRoot, ResolveFromPath),
            userRuntimeDirectory,
            driveRoot => new DriveInfo(driveRoot).AvailableFreeSpace);

    /// <summary>创建 FFprobe 媒体探测器。</summary>
    public static IMediaProbe CreateMediaProbe(string appRoot, string? userRuntimeDirectory = null) =>
        new FfprobeMediaProbe(
            new ExternalProcessRunner(),
            new RuntimeResolver(appRoot, ResolveFromPath),
            userRuntimeDirectory);

    private static string? ResolveFromPath(string executableName)
    {
        var pathValue = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathValue))
        {
            return null;
        }

        foreach (var folder in pathValue.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            var candidate = Path.Combine(folder.Trim(), executableName);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }
}
