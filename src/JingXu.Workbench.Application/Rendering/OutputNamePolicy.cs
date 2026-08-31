namespace JingXu.Workbench.Application.Rendering;

/// <summary>输出文件命名与默认目录策略。</summary>
public static class OutputNamePolicy
{
    /// <summary>
    /// 单一源文件夹时使用 <c>&lt;source&gt;\分镜输出</c>；
    /// 多来源时使用 <c>&lt;project&gt;\分镜输出</c>。
    /// 与 <see cref="RenderRequestFactory.ResolveDefaultOutputDirectory"/> 语义一致。
    /// </summary>
    public static string DefaultDirectory(IReadOnlyList<string> sourceFolders, string projectDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(projectDirectory);
        ArgumentNullException.ThrowIfNull(sourceFolders);

        if (sourceFolders.Count == 1 &&
            !string.IsNullOrWhiteSpace(sourceFolders[0]))
        {
            return Path.Combine(sourceFolders[0], "分镜输出");
        }

        return Path.Combine(projectDirectory, "分镜输出");
    }

    /// <summary>在目标目录中为输出文件分配不冲突的路径（三位序号后缀）。</summary>
    public static string AllocateUniquePath(string directory, string baseFileName)
        => AllocateUniquePath(directory, baseFileName, reservedPaths: null);

    /// <summary>
    /// 在目标目录中为输出文件分配不冲突的路径，同时避开已排队或进行中的任务路径。
    /// </summary>
    public static string AllocateUniquePath(
        string directory,
        string baseFileName,
        IEnumerable<string>? reservedPaths)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(directory);
        ArgumentException.ThrowIfNullOrWhiteSpace(baseFileName);

        var reserved = reservedPaths is null
            ? new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            : new HashSet<string>(reservedPaths.Select(Path.GetFullPath), StringComparer.OrdinalIgnoreCase);

        var candidate = Path.Combine(directory, baseFileName);
        if (IsAvailable(candidate, reserved))
        {
            return candidate;
        }

        var name = Path.GetFileNameWithoutExtension(baseFileName);
        var ext = Path.GetExtension(baseFileName);
        for (var index = 1; index <= 999; index++)
        {
            candidate = Path.Combine(directory, $"{name}_{index:D3}{ext}");
            if (IsAvailable(candidate, reserved))
            {
                return candidate;
            }
        }

        throw new InvalidOperationException($"无法在目录 {directory} 中为 {baseFileName} 分配唯一文件名。");

        static bool IsAvailable(string path, HashSet<string> reserved)
        {
            var fullPath = Path.GetFullPath(path);
            return !File.Exists(fullPath) && !reserved.Contains(fullPath);
        }
    }
}
