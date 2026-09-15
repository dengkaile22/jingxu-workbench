using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using JingXu.Workbench.Application.Projects;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>同一输出卷的跨进程空间预留。已写入字节由磁盘余量体现，避免重复扣减。</summary>
public sealed class RenderDiskSpaceReservations
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly string _root;

    public RenderDiskSpaceReservations(string? registryDirectory = null) =>
        _root = Path.GetFullPath(registryDirectory ?? Path.Combine(WorkbenchDataPaths.GetDataDirectory(), "disk-reservations"));

    public Reservation Acquire(string temporaryOutputPath, long outputBytes, Func<string, long> availableBytes)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(outputBytes);
        ArgumentNullException.ThrowIfNull(availableBytes);
        var volume = Path.GetPathRoot(Path.GetFullPath(temporaryOutputPath))!;
        using var process = Process.GetCurrentProcess();
        var record = new ReservationRecord(process.Id, process.StartTime.ToUniversalTime().Ticks,
            volume, 0, [Path.GetFullPath(temporaryOutputPath)]);
        var reservation = new Reservation(this, Guid.NewGuid(), record, availableBytes);
        reservation.Grow(outputBytes, null);
        return reservation;
    }

    private LockScope EnterRegistryLock()
    {
        var key = _root.ToUpperInvariant();
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(key)));
        var mutex = new Mutex(false, "JingXu.DiskReservations." + hash);
        try { mutex.WaitOne(); }
        catch (AbandonedMutexException) { }
        catch { mutex.Dispose(); throw; }
        return new LockScope(mutex);
    }

    private void Grow(Reservation reservation, long bytes, string? copiedPath)
    {
        using var gate = EnterRegistryLock();
        Directory.CreateDirectory(_root);
        var otherPending = 0m;
        foreach (var file in Directory.GetFiles(_root, "*.json"))
        {
            if (file.Equals(reservation.RecordPath, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            try
            {
                var record = JsonSerializer.Deserialize<ReservationRecord>(File.ReadAllText(file), JsonOptions);
                if (record is null || !OwnerAlive(record))
                {
                    File.Delete(file);
                    continue;
                }

                if (record.Volume.Equals(reservation.Record.Volume, StringComparison.OrdinalIgnoreCase))
                {
                    otherPending += PendingBytes(record);
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
            {
                throw new IOException("无法读取并发任务的磁盘预留，请稍后重试。", ex);
            }
        }

        var additional = Math.Ceiling(bytes * 1.25m);
        var required = PendingBytes(reservation.Record) + additional;
        var available = Math.Max(0, reservation.AvailableBytes(reservation.Record.Volume) - otherPending);
        if (required > available)
        {
            throw new IOException($"磁盘空间不足（{reservation.Record.Volume}）：本任务还需约 {required / 1048576m:0.##} MB，扣除其他任务预留后可用约 {available / 1048576m:0.##} MB。请释放空间或等待其他任务结束后重试。");
        }

        var paths = reservation.Record.WrittenPaths;
        if (copiedPath is not null)
        {
            paths = [.. paths, Path.GetFullPath(copiedPath)];
        }

        var updated = reservation.Record with
        {
            ReservedBytes = Math.Min(long.MaxValue, reservation.Record.ReservedBytes + additional),
            WrittenPaths = paths
        };
        var pendingPath = reservation.RecordPath + ".tmp";
        File.WriteAllText(pendingPath, JsonSerializer.Serialize(updated, JsonOptions));
        File.Move(pendingPath, reservation.RecordPath, overwrite: true);
        reservation.Record = updated;
    }

    private static decimal PendingBytes(ReservationRecord record)
    {
        var written = 0m;
        foreach (var path in record.WrittenPaths.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                if (File.Exists(path))
                {
                    written += new FileInfo(path).Length;
                }
            }
            catch (IOException) { }
        }

        return Math.Max(0, record.ReservedBytes - written);
    }

    private static bool OwnerAlive(ReservationRecord record)
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
        catch (ArgumentException) { return false; }
        catch (InvalidOperationException) { return false; }
        catch (System.ComponentModel.Win32Exception) { return true; }
    }

    internal sealed record ReservationRecord(int ProcessId, long ProcessStartTicks, string Volume,
        decimal ReservedBytes, IReadOnlyList<string> WrittenPaths);

    public sealed class Reservation : IDisposable
    {
        private readonly RenderDiskSpaceReservations _owner;
        private bool _disposed;
        internal ReservationRecord Record { get; set; }
        internal Func<string, long> AvailableBytes { get; }
        internal string RecordPath { get; }

        internal Reservation(RenderDiskSpaceReservations owner, Guid id, ReservationRecord record, Func<string, long> availableBytes)
        {
            _owner = owner;
            Record = record;
            AvailableBytes = availableBytes;
            RecordPath = Path.Combine(owner._root, id.ToString("N") + ".json");
        }

        /// <summary>只能在真实复制前增加预算；硬链接和符号链接不重复占用素材字节数。</summary>
        public void ReserveCopy(string destination, long bytes) => Grow(bytes, destination);

        internal void Grow(long bytes, string? destination)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            ArgumentOutOfRangeException.ThrowIfNegative(bytes);
            _owner.Grow(this, bytes, destination);
        }

        public void Dispose()
        {
            if (_disposed) { return; }
            _disposed = true;
            using var gate = _owner.EnterRegistryLock();
            try { File.Delete(RecordPath); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                // 当前进程仍存活时保留记录会阻碍后续任务，因此写入零预留再交给下次扫描回收。
                try { File.WriteAllText(RecordPath, JsonSerializer.Serialize(Record with { ReservedBytes = 0, ProcessId = 0 }, JsonOptions)); }
                catch (Exception writeEx) when (writeEx is IOException or UnauthorizedAccessException)
                { Trace.TraceWarning($"无法释放磁盘预留：{writeEx.Message}"); }
            }
        }
    }

    private sealed class LockScope(Mutex mutex) : IDisposable
    {
        public void Dispose() { mutex.ReleaseMutex(); mutex.Dispose(); }
    }
}
