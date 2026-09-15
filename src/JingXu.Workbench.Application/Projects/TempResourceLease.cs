using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace JingXu.Workbench.Application.Projects;

/// <summary>在写入前登记临时资源，清理端通过进程启动时间识别仍在使用的资源。</summary>
public sealed class TempResourceLease : IDisposable
{
    public const string DirectoryName = "resource-leases";
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly Guid _id;
    private readonly string? _dataDirectory;
    private bool _disposed;

    private TempResourceLease(Guid id, string? dataDirectory)
    {
        _id = id;
        _dataDirectory = dataDirectory;
    }

    public static TempResourceLease Acquire(string path, bool isDirectory = false, string? dataDirectory = null)
    {
        var id = Guid.NewGuid();
        Register(id, path, isDirectory, dataDirectory);
        return new TempResourceLease(id, dataDirectory);
    }

    /// <summary>读取一致的活跃资源快照，供诊断保留及资源状态查询使用。</summary>
    public static bool IsInUse(string path, string? dataDirectory = null)
    {
        using var gate = EnterCleanupScope(dataDirectory);
        var full = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        return ReadRegistrations(dataDirectory).Any(record => record.IsAlive
            && (record.Path.Equals(full, StringComparison.OrdinalIgnoreCase)
                || record.Path.StartsWith(full + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                || (record.IsDirectory && full.StartsWith(record.Path.TrimEnd(Path.DirectorySeparatorChar)
                                                         + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))));
    }

    /// <summary>字幕可被多个排队任务引用；删除与登记用同一把锁，最后一个使用者结束后才回收。</summary>
    public static void TryDeleteUnusedSubtitle(string? path, string? dataDirectory = null)
    {
        if (path is null || !WorkbenchCacheCleanup.IsOwnedTempSubtitlePath(path))
        {
            return;
        }

        using var gate = EnterCleanupScope(dataDirectory);
        var full = Path.GetFullPath(path);
        if (ReadRegistrations(dataDirectory).Any(record => record.IsAlive
                && (record.Path.Equals(full, StringComparison.OrdinalIgnoreCase)
                    || (record.IsDirectory && full.StartsWith(record.Path.TrimEnd(Path.DirectorySeparatorChar)
                                                              + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)))))
        {
            return;
        }

        try { if (File.Exists(full)) { File.Delete(full); } }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        { Trace.TraceWarning($"无法清理字幕临时文件：{ex.Message}"); }
    }

    internal static void Register(Guid id, string path, bool isDirectory, string? dataDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        using var gate = EnterCleanupScope(dataDirectory);
        using var process = Process.GetCurrentProcess();
        var record = new ResourceRecord(Path.GetFullPath(path), isDirectory, process.Id,
            process.StartTime.ToUniversalTime().Ticks);
        var root = GetStoreRoot(dataDirectory);
        Directory.CreateDirectory(root);
        // 登记和清理共用互斥锁，清理端不会读到半写入记录，也不会在登记前删除新资源。
        File.WriteAllText(Path.Combine(root, id.ToString("N") + ".json"), JsonSerializer.Serialize(record, JsonOptions));
    }

    internal static void Unregister(Guid id, string? dataDirectory)
    {
        using var gate = EnterCleanupScope(dataDirectory);
        TryRemoveRecord(Path.Combine(GetStoreRoot(dataDirectory), id.ToString("N") + ".json"));
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        using var gate = EnterCleanupScope(_dataDirectory);
        var recordPath = Path.Combine(GetStoreRoot(_dataDirectory), _id.ToString("N") + ".json");
        try
        {
            if (File.Exists(recordPath))
            {
                var record = JsonSerializer.Deserialize<ResourceRecord>(File.ReadAllText(recordPath), JsonOptions);
                if (record is not null && (File.Exists(record.Path) || Directory.Exists(record.Path)))
                {
                    // 回收失败或缓存仍保留时，把登记交还清理器；不能丢掉其他卷上的残留位置。
                    File.WriteAllText(recordPath, JsonSerializer.Serialize(record with { ProcessId = 0, ProcessStartTicks = 0 }, JsonOptions));
                    return;
                }
            }

            TryRemoveRecord(recordPath);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            Trace.TraceWarning($"无法释放临时资源登记：{ex.Message}");
        }
    }

    /// <summary>锁必须在获取线程释放；不得跨 await 持有。</summary>
    internal static IDisposable EnterCleanupScope(string? dataDirectory)
    {
        var root = Path.GetFullPath(GetStoreRoot(dataDirectory)).ToUpperInvariant();
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(root)));
        var mutex = new Mutex(false, "JingXu.TempResources." + hash);
        try
        {
            mutex.WaitOne();
        }
        catch (AbandonedMutexException)
        {
            // 原持有进程崩溃后，当前线程已获得互斥锁，可以继续检查失效登记。
        }
        catch
        {
            mutex.Dispose();
            throw;
        }

        return new MutexScope(mutex);
    }

    internal static IReadOnlyList<ResourceRegistration> ReadRegistrations(string? dataDirectory)
    {
        var root = GetStoreRoot(dataDirectory);
        if (!Directory.Exists(root))
        {
            return [];
        }

        var records = new List<ResourceRegistration>();
        foreach (var file in Directory.GetFiles(root, "*.json", SearchOption.TopDirectoryOnly))
        {
            try
            {
                var record = JsonSerializer.Deserialize<ResourceRecord>(File.ReadAllText(file), JsonOptions);
                if (record is null || string.IsNullOrWhiteSpace(record.Path) || !Path.IsPathFullyQualified(record.Path))
                {
                    continue;
                }

                records.Add(new ResourceRegistration(Path.GetFullPath(record.Path), record.IsDirectory,
                    IsOwnerAlive(record), file));
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or ArgumentException)
            {
                Trace.TraceWarning($"无法读取临时资源登记：{ex.Message}");
            }
        }

        return records;
    }

    private static bool IsOwnerAlive(ResourceRecord record)
    {
        if (record.ProcessId <= 0 || record.ProcessStartTicks <= 0)
        {
            return false;
        }

        try
        {
            using var process = Process.GetProcessById(record.ProcessId);
            return !process.HasExited && process.StartTime.ToUniversalTime().Ticks == record.ProcessStartTicks;
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
        catch (System.ComponentModel.Win32Exception)
        {
            // 无权读取进程信息时保守保留，不能据此认定资源已失效。
            return true;
        }
    }

    internal static void TryRemoveRecord(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Trace.TraceWarning($"无法删除临时资源登记：{ex.Message}");
        }
    }

    internal static string GetStoreRoot(string? dataDirectory) => Path.Combine(
        dataDirectory ?? WorkbenchDataPaths.GetDataDirectory(),
        DirectoryName);

    private sealed record ResourceRecord(string Path, bool IsDirectory, int ProcessId, long ProcessStartTicks);

    internal sealed record ResourceRegistration(string Path, bool IsDirectory, bool IsAlive, string RecordPath);

    private sealed class MutexScope(Mutex mutex) : IDisposable
    {
        public void Dispose()
        {
            mutex.ReleaseMutex();
            mutex.Dispose();
        }
    }
}
