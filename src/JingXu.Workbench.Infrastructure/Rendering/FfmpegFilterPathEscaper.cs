namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>FFmpeg filter 路径转义（Windows 驱动器冒号与反斜杠）。</summary>
public static class FfmpegFilterPathEscaper
{
    /// <summary>将绝对路径转义为 FFmpeg subtitles/delogo 等 filter 可用的形式。</summary>
    public static string EscapeForFilter(string absolutePath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(absolutePath);
        var normalized = absolutePath.Replace('\\', '/');
        if (normalized.Length >= 2 && char.IsLetter(normalized[0]) && normalized[1] == ':')
        {
            normalized = normalized[0] + "\\:" + normalized[2..];
        }

        return normalized.Replace("'", "\\'", StringComparison.Ordinal);
    }
}
