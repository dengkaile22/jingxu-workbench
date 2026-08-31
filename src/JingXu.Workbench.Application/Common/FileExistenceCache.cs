using System.Collections.Concurrent;

namespace JingXu.Workbench.Application.Common;

/// <summary>
/// 极速文件存在性缓存。
/// File.Exists 本身已是 O(1) 内核调用，但批量编排（如 100 条计划）
/// 可能重复检测同一文件。此缓存以 TTL 避免重复系统调用。
/// 30 秒过期：足够覆盖一次批量入队，又不会让被删除文件长期「假活」。
/// </summary>
public sealed class FileExistenceCache
{
    private static readonly TimeSpan Ttl = TimeSpan.FromSeconds(30);
    private readonly ConcurrentDictionary<string, CacheEntry> _cache =
        new(StringComparer.OrdinalIgnoreCase);

    private readonly struct CacheEntry(bool exists, long tick)
    {
        public bool Exists { get; } = exists;
        public long Tick { get; } = tick;
    }

    /// <summary>检查文件是否存在（缓存加速）。</summary>
    public bool Exists(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }

        var now = Environment.TickCount64;
        if (_cache.TryGetValue(path, out var cached))
        {
            if (now - cached.Tick < Ttl.Ticks)
            {
                return cached.Exists;
            }
        }

        var exists = File.Exists(path);
        _cache[path] = new CacheEntry(exists, now);
        return exists;
    }

    /// <summary>使缓存失效（文件被重新导入/修改时调用）。</summary>
    public void Invalidate(string path)
    {
        _cache.TryRemove(path, out _);
    }

    /// <summary>清空全部缓存（切换项目或长时间空闲时触发）。</summary>
    public void Clear() => _cache.Clear();
}
