using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>诊断与媒体暂存分离；只归档文本，按时间和总量回收旧任务日志。</summary>
internal static class RenderDiagnosticStore
{
    private const long RetentionBytes = 64 * 1024 * 1024;
    private static readonly TimeSpan RetentionAge = TimeSpan.FromDays(7);

    public static string? Preserve(RenderJob job, string stagingRoot, string message)
    {
        try
        {
            var outputDirectory = Path.GetDirectoryName(Path.GetFullPath(job.Request!.OutputPath))!;
            var root = Path.Combine(outputDirectory, ".jingxu-logs");
            using var gate = EnterArchiveLock(root);
            var destination = Path.Combine(root, job.Id.ToString("N"));
            Directory.CreateDirectory(destination);
            var logPath = Path.Combine(destination, "render.log");
            var originalLog = Path.Combine(stagingRoot, "render.log");
            if (File.Exists(originalLog))
            {
                File.Copy(originalLog, logPath, overwrite: true);
                File.AppendAllText(logPath, Environment.NewLine + message);
            }
            else
            {
                File.WriteAllText(logPath, message);
            }

            foreach (var fileName in new[] { FfmpegCommandCompiler.FilterComplexScriptFileName, "concat.txt" })
            {
                var source = Path.Combine(stagingRoot, fileName);
                if (File.Exists(source))
                {
                    File.Copy(source, Path.Combine(destination, fileName), overwrite: true);
                }
            }

            try
            {
                Directory.SetLastWriteTimeUtc(destination, DateTime.UtcNow);
                TrimOldDiagnostics(root, destination);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                // 当前日志已成功归档；旧日志被移除或占用不能抹掉当前日志的可访问路径。
                Trace.TraceWarning($"无法修剪旧渲染诊断：{ex.Message}");
            }
            return logPath;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Trace.TraceWarning($"无法归档渲染诊断：{ex.Message}");
            return null;
        }
    }

    private static ArchiveLock EnterArchiveLock(string root)
    {
        var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Path.GetFullPath(root).ToUpperInvariant())));
        var mutex = new Mutex(false, "JingXu.RenderDiagnostics." + key);
        try { mutex.WaitOne(); }
        catch (AbandonedMutexException) { }
        catch { mutex.Dispose(); throw; }
        return new ArchiveLock(mutex);
    }

    private sealed class ArchiveLock(Mutex mutex) : IDisposable
    {
        public void Dispose() { mutex.ReleaseMutex(); mutex.Dispose(); }
    }

    private static void TrimOldDiagnostics(string root, string currentDirectory)
    {
        var folders = new DirectoryInfo(root).GetDirectories()
            .Where(folder => Guid.TryParseExact(folder.Name, "N", out _)
                             && (folder.Attributes & FileAttributes.ReparsePoint) == 0)
            .OrderByDescending(static folder => folder.LastWriteTimeUtc);
        long keptBytes = 0;
        foreach (var folder in folders)
        {
            var files = folder.GetFiles();
            var size = files.Sum(static file => file.Length);
            // 当前任务必须保留完整日志；容量淘汰只针对其他已结束任务。
            if (folder.FullName.Equals(currentDirectory, StringComparison.OrdinalIgnoreCase)
                || (DateTime.UtcNow - folder.LastWriteTimeUtc <= RetentionAge && keptBytes + size <= RetentionBytes))
            {
                keptBytes += size;
                continue;
            }

            foreach (var file in files.Where(static file => file.Name is "render.log" or "filter_complex.txt" or "concat.txt"))
            {
                file.Delete();
            }

            if (!folder.EnumerateFileSystemInfos().Any())
            {
                folder.Delete();
            }
        }
    }
}
