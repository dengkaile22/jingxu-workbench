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

/// <summary>
/// 清理 JingXu 渲染暂存与已知临时目录。
/// 会删：staging、滤镜脚本、抽帧/OCR/Whisper 临时目录、下载 .part、overlay 预览、失败半成品。
/// 不删：用户素材、已成功导出的成片、库 JSON、runtime 二进制、应用日志。
/// </summary>
public static class WorkbenchCacheCleanup
{
    /// <summary>渲染暂存目录名（位于成片输出目录下，与成片同卷以便原子移动）。</summary>
    public const string StagingDirectoryName = ".jingxu-tmp";

    /// <summary>蒙版缩略图缓存目录名（位于数据目录下，不是成片）。</summary>
    public const string OverlayThumbsDirectoryName = "overlay-thumbs";

    /// <summary>%TEMP% 下本软件使用的固定目录名；不扫整个 Temp，也不匹配任意 jingxu-*。</summary>
    public static readonly string[] KnownTempDirectoryNames =
    [
        "jingxu-whisper",
        "jingxu-ocr",
        "jingxu-subtitle-burn",
        "jingxu-gate-preview",
        "jingxu-download"
    ];

    /// <summary>
    /// 启动时只清临时/staging 孤儿，不清 overlay-thumbs（仍是可重建缓存，但启动时不必打散正在用的缩略图）。
    /// </summary>
    public static WorkbenchCacheCleanupResult CleanupStartupOrphans(
        string? dataDirectory = null,
        string? tempDirectory = null) =>
        Cleanup(
            dataDirectory,
            tempDirectory,
            extraSearchRoots: null,
            protectedJobIds: null,
            protectedFiles: null,
            includeOverlayThumbCache: false);

    /// <summary>
    /// 清理临时与渲染暂存。不会删除用户项目 JSON、素材库或成片输出本身。
    /// </summary>
    public static WorkbenchCacheCleanupResult Cleanup(
        string? dataDirectory = null,
        string? tempDirectory = null,
        IEnumerable<string>? extraSearchRoots = null,
        IEnumerable<Guid>? protectedJobIds = null,
        IEnumerable<string>? protectedFiles = null,
        bool includeOverlayThumbCache = true)
    {
        var dataRoot = dataDirectory ?? WorkbenchDataPaths.GetDataDirectory();
        using var cleanupGate = TempResourceLease.EnterCleanupScope(dataRoot);
        var tempRoot = tempDirectory ?? JingXu.Workbench.Application.Projects.WorkbenchDataPaths.GetTempDirectory();
        var protectedIds = protectedJobIds is null
            ? new HashSet<Guid>()
            : protectedJobIds.ToHashSet();
        var protectedFileSet = BuildProtectedFileSet(protectedFiles);
        var registrations = TempResourceLease.ReadRegistrations(dataRoot);
        foreach (var registration in registrations.Where(static item => item.IsAlive))
        {
            protectedFileSet.Add(registration.Path);
            if (registration.IsDirectory)
            {
                protectedFileSet.Add(registration.Path.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                                     + Path.DirectorySeparatorChar);
            }
        }

        var deletedDirs = 0;
        var deletedFiles = 0;
        long freed = 0;
        var errors = new List<string>();

        // 只跟随可验证的本软件暂存登记。任意路径记录不能变成删除用户文件的授权。
        foreach (var registration in registrations.Where(static item => !item.IsAlive))
        {
            var thumbnailRoot = Path.GetFullPath(Path.Combine(dataRoot, OverlayThumbsDirectoryName))
                .TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!includeOverlayThumbCache && registration.Path.StartsWith(thumbnailRoot, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (IsOwnedRegisteredResource(registration.Path, registration.IsDirectory, tempRoot, dataRoot)
                && !IsProtectedFile(registration.Path, protectedFileSet))
            {
                if (registration.IsDirectory)
                {
                    TryDeleteDirectory(registration.Path, protectedFileSet, ref deletedDirs, ref freed, errors);
                }
                else if (!HasReparseAncestor(registration.Path))
                {
                    TryDeleteFile(registration.Path, ref deletedFiles, ref freed, errors);
                    TryDeleteDirectoryIfEmpty(Path.GetDirectoryName(registration.Path)!, protectedFileSet);
                }
            }

            if (!File.Exists(registration.Path) && !Directory.Exists(registration.Path))
            {
                TempResourceLease.TryRemoveRecord(registration.RecordPath);
            }
        }

        foreach (var dir in EnumerateKnownTempDirectories(tempRoot))
        {
            // Whisper/OCR 进行中的 GUID 子目录若被占用会跳过，不把清理失败抛给调用方。
            TryDeleteDirectory(dir, protectedFileSet, ref deletedDirs, ref freed, errors);
        }

        foreach (var name in KnownTempDirectoryNames)
        {
            TryDeleteDirectoryIfEmpty(Path.Combine(tempRoot, name), protectedFileSet);
        }

        var overlayPreviewDirectory = Path.Combine(tempRoot, "JingXu", "overlay-preview");
        TryDeleteDirectory(overlayPreviewDirectory, protectedFileSet, ref deletedDirs, ref freed, errors);
        TryDeleteDirectoryIfEmpty(Path.Combine(tempRoot, "JingXu"), protectedFileSet);

        foreach (var jobDir in EnumerateStagingJobDirectories(dataRoot, extraSearchRoots))
        {
            TryDeleteStagingJobDirectory(
                jobDir,
                protectedIds,
                protectedFileSet,
                ref deletedDirs,
                ref freed,
                errors);
        }

        CleanupTrackedStagingLeases(
            dataRoot,
            protectedIds,
            protectedFileSet,
            ref deletedDirs,
            ref deletedFiles,
            ref freed,
            errors);

        if (includeOverlayThumbCache)
        {
            // 缩略图可按素材路径重建；成片与库 JSON 不在此目录。
            TryDeleteDirectory(
                Path.Combine(dataRoot, OverlayThumbsDirectoryName),
                protectedFileSet,
                ref deletedDirs,
                ref freed,
                errors);
        }

        // 根目录的 .tmp 可能刚关闭、正等待 JSON 原子提交，.bak 可能是用户备份；不将它们当缓存。

        return new WorkbenchCacheCleanupResult(deletedDirs, deletedFiles, freed, errors);
    }

    private static bool IsOwnedRegisteredResource(string path, bool isDirectory, string tempRoot, string dataRoot)
    {
        var full = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var parent = Path.GetDirectoryName(full);
        if (parent is null || HasReparseAncestor(full))
        {
            return false;
        }

        if (isDirectory && Path.GetFileName(parent).Equals(StagingDirectoryName, StringComparison.OrdinalIgnoreCase))
        {
            return Guid.TryParseExact(Path.GetFileName(full), "N", out _);
        }

        if (!isDirectory && Path.GetFileName(parent).Equals(".jingxu-download", StringComparison.OrdinalIgnoreCase))
        {
            return Path.GetExtension(full).Equals(".part", StringComparison.OrdinalIgnoreCase)
                   && Guid.TryParseExact(Path.GetFileNameWithoutExtension(full), "N", out _);
        }

        var roots = KnownTempDirectoryNames.Select(name => Path.Combine(tempRoot, name))
            .Append(Path.Combine(tempRoot, "JingXu", "overlay-preview"))
            .Append(Path.Combine(dataRoot, OverlayThumbsDirectoryName));
        return roots.Any(root => full.StartsWith(Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar)
                                                + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>仅删除字幕实验室写在 %TEMP%\jingxu-subtitle-burn 下的 ASS，不删用户自己的字幕文件。</summary>
    public static bool IsOwnedTempSubtitlePath(string? path, string? tempDirectory = null)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }

        try
        {
            var root = Path.GetFullPath(Path.Combine(tempDirectory ?? JingXu.Workbench.Application.Projects.WorkbenchDataPaths.GetTempDirectory(), "jingxu-subtitle-burn"));
            var prefix = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                         + Path.DirectorySeparatorChar;
            var full = Path.GetFullPath(path);
            return full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return false;
        }
    }

    private static HashSet<string> BuildProtectedFileSet(IEnumerable<string>? protectedFiles)
    {
        var set = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (protectedFiles is null)
        {
            return set;
        }

        foreach (var file in protectedFiles)
        {
            if (string.IsNullOrWhiteSpace(file))
            {
                continue;
            }

            try
            {
                set.Add(Path.GetFullPath(file));
            }
            catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
            {
            }
        }

        return set;
    }

    private static IEnumerable<string> EnumerateKnownTempDirectories(string tempRoot)
    {
        if (!Directory.Exists(tempRoot))
        {
            yield break;
        }

        foreach (var name in KnownTempDirectoryNames)
        {
            var path = Path.Combine(tempRoot, name);
            if (!Directory.Exists(path))
            {
                continue;
            }

            // Whisper/OCR 按会话分子目录；逐个删，避免一次 RecursiveDelete 误伤正在跑的会话。
            if (name is "jingxu-whisper" or "jingxu-ocr")
            {
                IEnumerable<string> sessions;
                try
                {
                    sessions = Directory.EnumerateDirectories(path);
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    continue;
                }

                foreach (var session in sessions)
                {
                    yield return session;
                }

                continue;
            }

            yield return path;
        }
    }

    private static IEnumerable<string> EnumerateStagingJobDirectories(
        string dataRoot,
        IEnumerable<string>? extraSearchRoots)
    {
        foreach (var stagingRoot in EnumerateStagingRootDirectories(dataRoot, extraSearchRoots))
        {
            IEnumerable<string> jobDirs;
            try
            {
                jobDirs = Directory.EnumerateDirectories(stagingRoot);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                continue;
            }

            foreach (var jobDir in jobDirs)
            {
                yield return jobDir;
            }
        }
    }

    private static IEnumerable<string> EnumerateStagingRootDirectories(
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
            roots.Add(Path.Combine(dataRoot, "Output"));
        }

        if (extraSearchRoots is not null)
        {
            roots.AddRange(extraSearchRoots.Where(static root => !string.IsNullOrWhiteSpace(root) && Directory.Exists(root)));
        }

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var root in roots)
        {
            string fullRoot;
            try
            {
                fullRoot = Path.GetFullPath(root);
            }
            catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
            {
                continue;
            }

            if (!seen.Add(fullRoot))
            {
                continue;
            }

            // 不递归扫描整个数据目录或用户磁盘；其他输出目录由 staging-refs 精确登记。
            var staging = Path.Combine(fullRoot, StagingDirectoryName);
            if (Directory.Exists(staging) && !HasReparseAncestor(staging))
            {
                yield return staging;
            }
        }
    }

    private static void CleanupTrackedStagingLeases(
        string dataRoot,
        HashSet<Guid> protectedIds,
        HashSet<string> protectedFiles,
        ref int deletedDirs,
        ref int deletedFiles,
        ref long freed,
        List<string> errors)
    {
        foreach (var (jobId, stagingRoot, refFile) in StagingLeaseStore.EnumerateValid(dataRoot))
        {
            if (protectedIds.Contains(jobId) || IsProtectedFile(stagingRoot, protectedFiles))
            {
                continue;
            }

            TryDeleteStagingJobDirectory(
                stagingRoot,
                protectedIds,
                protectedFiles,
                ref deletedDirs,
                ref freed,
                errors);

            if (!Directory.Exists(stagingRoot))
            {
                TryDeleteFile(refFile, ref deletedFiles, ref freed, errors);
            }
        }

        // 无效/被篡改的登记只丢掉指针，绝不按文件内容去删目标。
        var storeRoot = StagingLeaseStore.GetStoreRoot(dataRoot);
        if (!Directory.Exists(storeRoot))
        {
            return;
        }

        string[] refs;
        try
        {
            refs = Directory.GetFiles(storeRoot, "*" + StagingLeaseStore.RefExtension, SearchOption.TopDirectoryOnly);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return;
        }

        foreach (var file in refs)
        {
            if (StagingLeaseStore.TryReadValidStaging(file, out _, out var staging)
                && (Directory.Exists(staging) || IsProtectedFile(staging, protectedFiles)))
            {
                continue;
            }

            TryDeleteFile(file, ref deletedFiles, ref freed, errors);
        }
    }

    private static void TryDeleteStagingJobDirectory(
        string jobDir,
        HashSet<Guid> protectedIds,
        HashSet<string> protectedFiles,
        ref int deletedDirs,
        ref long freed,
        List<string> errors)
    {
        var name = Path.GetFileName(jobDir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        if (!Guid.TryParseExact(name, "N", out _))
        {
            return;
        }
        if (Guid.TryParseExact(name, "N", out var jobId) && protectedIds.Contains(jobId))
        {
            // 并发渲染：跳过仍在跑的任务目录，避免删掉别人的 staging。
            return;
        }

        TryDeleteDirectory(jobDir, protectedFiles, ref deletedDirs, ref freed, errors);

        var parent = Path.GetDirectoryName(jobDir);
        if (!string.IsNullOrEmpty(parent)
            && string.Equals(Path.GetFileName(parent), StagingDirectoryName, StringComparison.OrdinalIgnoreCase))
        {
            TryDeleteDirectoryIfEmpty(parent, protectedFiles);
        }
    }

    private static void TryDeleteDirectory(
        string path,
        HashSet<string> protectedFiles,
        ref int deletedDirs,
        ref long freed,
        List<string> errors)
    {
        try
        {
            if (!Directory.Exists(path) || HasReparseAncestor(path) || IsProtectedFile(path, protectedFiles))
            {
                return;
            }

            // 先物化再删：边枚举边删除会让 EnumerateFiles 抛错。
            var options = new EnumerationOptions
            {
                RecurseSubdirectories = true,
                AttributesToSkip = FileAttributes.ReparsePoint,
                IgnoreInaccessible = true
            };
            var nestedDirectories = Directory.GetDirectories(path, "*", options);
            var files = nestedDirectories.Prepend(path)
                .SelectMany(directory => Directory.GetFiles(directory, "*", SearchOption.TopDirectoryOnly)).ToArray();
            foreach (var file in files)
            {
                if (IsProtectedFile(file, protectedFiles))
                {
                    continue;
                }

                freed += TryDeleteFileCore(file, errors);
            }

            var dirs = nestedDirectories
                .OrderByDescending(static d => d.Length);
            foreach (var dir in dirs)
            {
                TryDeleteDirectoryIfEmpty(dir, protectedFiles);
            }

            if (Directory.Exists(path) && !Directory.EnumerateFileSystemEntries(path).Any()
                && !ContainsProtectedDescendant(path, protectedFiles))
            {
                Directory.Delete(path, recursive: false);
                deletedDirs++;
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or DirectoryNotFoundException)
        {
            errors.Add($"{path}: {ex.Message}");
        }
    }

    private static void TryDeleteDirectoryIfEmpty(string path, HashSet<string> protectedFiles)
    {
        try
        {
            if (Directory.Exists(path) && !Directory.EnumerateFileSystemEntries(path).Any()
                && !ContainsProtectedDescendant(path, protectedFiles))
            {
                Directory.Delete(path, recursive: false);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or DirectoryNotFoundException)
        {
        }
    }

    private static void TryDeleteFile(
        string path,
        ref int deletedFiles,
        ref long freed,
        List<string> errors)
    {
        if (!File.Exists(path))
        {
            return;
        }

        var size = TryDeleteFileCore(path, errors);
        if (!File.Exists(path))
        {
            deletedFiles++;
            freed += size;
        }
    }

    /// <returns>删除前的字节数；未删除返回 0。</returns>
    private static long TryDeleteFileCore(string path, List<string> errors)
    {
        try
        {
            if (!File.Exists(path) || HasReparseAncestor(path))
            {
                return 0;
            }

            // 删除文件符号链接只移除链接本身，不计入其目标文件的字节数。
            var length = (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0 ? 0 : new FileInfo(path).Length;
            File.Delete(path);
            return length;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            errors.Add($"{path}: {ex.Message}");
            return 0;
        }
    }

    private static bool IsProtectedFile(string path, HashSet<string> protectedFiles)
    {
        if (protectedFiles.Count == 0)
        {
            return false;
        }

        try
        {
            var full = Path.GetFullPath(path);
            return protectedFiles.Contains(full)
                   || protectedFiles.Any(item => item.EndsWith(Path.DirectorySeparatorChar)
                       && full.StartsWith(item, StringComparison.OrdinalIgnoreCase));
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException)
        {
            return false;
        }
    }

    private static bool HasReparseAncestor(string path)
    {
        var full = Path.GetFullPath(path);
        for (var current = Directory.Exists(full) ? full : Path.GetDirectoryName(full);
             !string.IsNullOrEmpty(current); current = Path.GetDirectoryName(current))
        {
            try
            {
                if ((File.Exists(current) || Directory.Exists(current))
                    && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                {
                    return true;
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                return true;
            }
        }

        return false;
    }

    private static bool ContainsProtectedDescendant(string directory, HashSet<string> protectedFiles)
    {
        var prefix = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                     + Path.DirectorySeparatorChar;
        return protectedFiles.Any(path => path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase));
    }
}
