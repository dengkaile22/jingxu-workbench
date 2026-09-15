namespace JingXu.Workbench.Application.Projects;

/// <summary>
/// 记录渲染暂存目录位置，便于启动/设置清理找到「素材旁分镜输出」下的孤儿 staging。
/// 只登记 <c>.jingxu-tmp\{jobId}</c>；绝不把用户成片路径写入可删除目标。
/// </summary>
public static class StagingLeaseStore
{
    public const string DirectoryName = "staging-refs";
    public const string RefExtension = ".ref";

    /// <summary>登记本任务的 staging 绝对路径。写入失败不得影响渲染。</summary>
    public static void Track(Guid jobId, string stagingRoot, string? dataDirectory = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(stagingRoot);

        try
        {
            using var gate = TempResourceLease.EnterCleanupScope(dataDirectory);
            var fullStaging = Path.GetFullPath(stagingRoot);
            if (!IsOwnedStagingPath(jobId, fullStaging))
            {
                return;
            }

            var root = GetStoreRoot(dataDirectory);
            Directory.CreateDirectory(root);
            TempResourceLease.Register(jobId, fullStaging, isDirectory: true, dataDirectory);
            File.WriteAllText(Path.Combine(root, RefFileName(jobId)), fullStaging);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or NotSupportedException)
        {
            // 登记失败只影响孤儿扫描，不能让渲染失败。
        }
    }

    /// <summary>staging 已删除后移除登记。文件占用导致目录仍在时不要调用，以便下次启动再扫。</summary>
    public static void Untrack(Guid jobId, string? dataDirectory = null)
    {
        try
        {
            using var gate = TempResourceLease.EnterCleanupScope(dataDirectory);
            TempResourceLease.Unregister(jobId, dataDirectory);
            var path = Path.Combine(GetStoreRoot(dataDirectory), RefFileName(jobId));
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }
    }

    /// <summary>枚举通过校验的暂存路径（路径必须是 .jingxu-tmp\{同一 jobId}）。</summary>
    public static IReadOnlyList<(Guid JobId, string StagingRoot, string RefFilePath)> EnumerateValid(
        string? dataDirectory = null)
    {
        var root = GetStoreRoot(dataDirectory);
        if (!Directory.Exists(root))
        {
            return [];
        }

        string[] files;
        try
        {
            files = Directory.GetFiles(root, "*" + RefExtension, SearchOption.TopDirectoryOnly);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return [];
        }

        var list = new List<(Guid, string, string)>();
        foreach (var file in files)
        {
            if (TryReadValidStaging(file, out var jobId, out var staging))
            {
                list.Add((jobId, staging, file));
            }
        }

        return list;
    }

    /// <summary>
    /// 校验登记内容：目录名必须是 jobId（N 格式），父目录必须是 <c>.jingxu-tmp</c>。
    /// 防止被篡改的 .ref 指向用户成片或素材。
    /// </summary>
    public static bool TryReadValidStaging(string refFilePath, out Guid jobId, out string stagingRoot)
    {
        jobId = Guid.Empty;
        stagingRoot = string.Empty;

        try
        {
            var idText = Path.GetFileNameWithoutExtension(refFilePath);
            if (!Guid.TryParseExact(idText, "N", out jobId))
            {
                return false;
            }

            if (!File.Exists(refFilePath))
            {
                return false;
            }

            var text = File.ReadAllText(refFilePath).Trim();
            if (string.IsNullOrWhiteSpace(text))
            {
                return false;
            }

            var full = Path.GetFullPath(text);
            if (!IsOwnedStagingPath(jobId, full))
            {
                return false;
            }

            stagingRoot = full;
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or NotSupportedException or ArgumentException)
        {
            jobId = Guid.Empty;
            stagingRoot = string.Empty;
            return false;
        }
    }

    public static string GetStoreRoot(string? dataDirectory = null) =>
        Path.Combine(ResolveDataRoot(dataDirectory), DirectoryName);

    internal static bool IsOwnedStagingPath(Guid jobId, string stagingRoot)
    {
        var jobFolder = Path.GetFileName(stagingRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        var parent = Path.GetDirectoryName(stagingRoot);
        if (string.IsNullOrEmpty(parent) || string.IsNullOrEmpty(jobFolder))
        {
            return false;
        }

        var stagingName = Path.GetFileName(parent.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        return jobFolder.Equals(jobId.ToString("N"), StringComparison.OrdinalIgnoreCase)
               && stagingName.Equals(WorkbenchCacheCleanup.StagingDirectoryName, StringComparison.OrdinalIgnoreCase);
    }

    private static string RefFileName(Guid jobId) => jobId.ToString("N") + RefExtension;

    private static string ResolveDataRoot(string? dataDirectory) =>
        string.IsNullOrWhiteSpace(dataDirectory)
            ? WorkbenchDataPaths.GetDataDirectory()
            : dataDirectory;
}
