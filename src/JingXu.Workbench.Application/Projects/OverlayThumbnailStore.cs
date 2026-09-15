namespace JingXu.Workbench.Application.Projects;

/// <summary>蒙版素材库缩略图缓存路径。</summary>
public static class OverlayThumbnailStore
{
    /// <summary>缩略图根目录（%LOCALAPPDATA%\JingXu\overlay-thumbs）。</summary>
    public static string RootDirectory =>
        Path.Combine(
            WorkbenchDataPaths.GetDataDirectory(),
            "overlay-thumbs");

    /// <summary>按素材绝对路径派生稳定缩略图路径。</summary>
    public static string GetThumbnailPath(string mediaFilePath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(mediaFilePath);
        var full = Path.GetFullPath(mediaFilePath);
        var hash = full.GetHashCode(StringComparison.OrdinalIgnoreCase);
        var name = $"{unchecked((uint)hash):x8}_{Path.GetFileNameWithoutExtension(full)}.jpg";
        foreach (var c in Path.GetInvalidFileNameChars())
        {
            name = name.Replace(c, '_');
        }

        return Path.Combine(RootDirectory, name);
    }
}
