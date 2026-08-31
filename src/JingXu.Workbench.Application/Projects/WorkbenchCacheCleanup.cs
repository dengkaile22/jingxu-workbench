namespace JingXu.Workbench.Application.Projects;

/// <summary>工作台缓存 / 临时目录清理结果。</summary>
public sealed record WorkbenchCacheCleanupResult(
    int DeletedDirectories,
    int DeletedFiles,
    long FreedBytes,
    IReadOnlyList<string> Errors)
{
    public string SummaryText
    {
        get
        {
            if (DeletedDirectories == 0 && DeletedFiles == 0)
            {
                return Errors.Count == 0
                    ? "没有可清理的缓存或临时文件。"
                    : $"清理未删除任何项；{Errors.Count} 处跳过。";
            }

            var mb = FreedBytes / (1024.0 * 1024.0);
            var baseText = $"已清理 {DeletedDirectories} 个目录、{DeletedFiles} 个文件，约释放 {mb:0.#} MB。";
            return Errors.Count == 0 ? baseText : $"{baseText}（{Errors.Count} 处跳过）";
        }
    }
}

/// <summary>清理 JingXu 渲染暂存与 %TEMP% 下 jingxu-* 临时目录。</summary>
public static class WorkbenchCacheCleanup
{
    /// <summary>
    /// 清理临时与渲染暂存。不会删除用户项目 JSON、素材库或成片输出本身。
    /// </summary>
    public static WorkbenchCacheCleanupResult Cleanup(
        string? dataDirectory = null,
        string? tempDirectory = null,
        IEnumerable<string>? extraSearchRoots = null)
    {
        var dataRoot = dataDirectory
            ?? Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "JingXu");
        var tempRoot = tempDirectory ?? Path.GetTempPath();

        var deletedDirs = 0;
        var deletedFiles = 0;
        long freed = 0;
        var errors = new List<string>();

        foreach (var dir in EnumerateTempJingXuDirectories(tempRoot))
        {
            TryDeleteDirectory(dir, ref deletedDirs, ref freed, errors);
        }

        foreach (var staging in EnumerateStagingDirectories(dataRoot, extraSearchRoots))
        {
            TryDeleteDirectory(staging, ref deletedDirs, ref freed, errors);
        }

        // 清理数据目录下常见临时后缀文件（不含业务 JSON）。
        if (Directory.Exists(dataRoot))
        {
            foreach (var file in Directory.EnumerateFiles(dataRoot, "*.tmp", SearchOption.TopDirectoryOnly)
                         .Concat(Directory.EnumerateFiles(dataRoot, "*.bak", SearchOption.TopDirectoryOnly)))
            {
                TryDeleteFile(file, ref deletedFiles, ref freed, errors);
            }
        }

        return new WorkbenchCacheCleanupResult(deletedDirs, deletedFiles, freed, errors);
    }

    private static IEnumerable<string> EnumerateTempJingXuDirectories(string tempRoot)
    {
        if (!Directory.Exists(tempRoot))
        {
            yield break;
        }

        var overlayPreviewDirectory = Path.Combine(tempRoot, "JingXu", "overlay-preview");
        if (Directory.Exists(overlayPreviewDirectory))
        {
            yield return overlayPreviewDirectory;
        }

        string[] entries;
        try
        {
            entries = Directory.GetDirectories(tempRoot, "jingxu-*", SearchOption.TopDirectoryOnly);
        }
        catch (IOException)
        {
            yield break;
        }
        catch (UnauthorizedAccessException)
        {
            yield break;
        }

        foreach (var entry in entries)
        {
            yield return entry;
        }
    }

    private static IEnumerable<string> EnumerateStagingDirectories(
        string dataRoot,
        IEnumerable<string>? extraSearchRoots)
    {
        var roots = new List<string>();
        if (Directory.Exists(dataRoot))
        {
            roots.Add(dataRoot);
            var defaultOutput = Path.Combine(dataRoot, "分镜输出");
            if (Directory.Exists(defaultOutput))
            {
                roots.Add(defaultOutput);
            }
        }

        if (extraSearchRoots is not null)
        {
            roots.AddRange(extraSearchRoots.Where(Directory.Exists));
        }

        foreach (var root in roots.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            IEnumerable<string> stagingDirs;
            try
            {
                stagingDirs = Directory.EnumerateDirectories(
                    root,
                    ".jingxu-tmp",
                    SearchOption.AllDirectories);
            }
            catch (IOException)
            {
                continue;
            }
            catch (UnauthorizedAccessException)
            {
                continue;
            }

            foreach (var staging in stagingDirs)
            {
                yield return staging;
            }
        }
    }

    private static void TryDeleteDirectory(
        string path,
        ref int deletedDirs,
        ref long freed,
        List<string> errors)
    {
        try
        {
            if (!Directory.Exists(path))
            {
                return;
            }

            freed += EstimateDirectorySize(path);
            Directory.Delete(path, recursive: true);
            deletedDirs++;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or DirectoryNotFoundException)
        {
            errors.Add($"{path}: {ex.Message}");
        }
    }

    private static void TryDeleteFile(
        string path,
        ref int deletedFiles,
        ref long freed,
        List<string> errors)
    {
        try
        {
            if (!File.Exists(path))
            {
                return;
            }

            var info = new FileInfo(path);
            freed += info.Length;
            File.Delete(path);
            deletedFiles++;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            errors.Add($"{path}: {ex.Message}");
        }
    }

    private static long EstimateDirectorySize(string path)
    {
        try
        {
            return Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories)
                .Select(f =>
                {
                    try
                    {
                        return new FileInfo(f).Length;
                    }
                    catch
                    {
                        return 0L;
                    }
                })
                .Sum();
        }
        catch
        {
            return 0;
        }
    }
}
