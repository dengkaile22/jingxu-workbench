namespace JingXu.Workbench.IntegrationTests.Media;

/// <summary>在系统 PATH 中查找 FFmpeg 运行时。</summary>
internal static class FfmpegRuntimeProbe
{
    public static string? FindFfmpeg() => FindExecutable("ffmpeg");

    public static string? FindFfprobe() => FindExecutable("ffprobe");

    private static string? FindExecutable(string tool)
    {
        var name = OperatingSystem.IsWindows() ? tool + ".exe" : tool;
        var pathEnv = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathEnv))
        {
            return null;
        }

        foreach (var dir in pathEnv.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            var candidate = Path.Combine(dir.Trim(), name);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }
}
