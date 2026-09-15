using System.Collections.Concurrent;
using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Common;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Application.Projects;

/// <summary>音频库文档。</summary>
public sealed class AudioLibraryDocument
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; } = CurrentSchemaVersion;

    [JsonPropertyName("entries")]
    public IReadOnlyList<AudioLibraryEntry> Entries { get; init; } = [];

    public static AudioLibraryDocument Empty { get; } = new();

    public AudioLibraryDocument WithEntry(AudioLibraryEntry entry)
    {
        ArgumentNullException.ThrowIfNull(entry);
        var list = Entries.Where(e => e.Id != entry.Id).ToList();
        list.Add(entry);
        return new AudioLibraryDocument { Entries = list };
    }

    public AudioLibraryDocument WithoutEntry(Guid id)
    {
        var list = Entries.Where(e => e.Id != id).ToList();
        return new AudioLibraryDocument { Entries = list };
    }
}

/// <summary>音频库持久化服务。</summary>
public sealed class AudioLibraryService
{
    private static readonly ConcurrentDictionary<string, SemaphoreSlim> MutationGates =
        new(StringComparer.OrdinalIgnoreCase);

    private readonly IAtomicJsonStore<AudioLibraryDocument> _store;
    private readonly string _defaultLibraryPath;

    public AudioLibraryService(
        IAtomicJsonStore<AudioLibraryDocument> store,
        string? defaultLibraryPath = null)
    {
        _store = store;
        _defaultLibraryPath = defaultLibraryPath ?? DefaultLibraryPath;
    }

    public static string DefaultLibraryPath =>
        Path.Combine(
            WorkbenchDataPaths.GetDataDirectory(),
            "audio-library.json");

    /// <summary>加载音频库（自动清理已失效的条目）。</summary>
    public async Task<AudioLibraryDocument> LoadAsync(
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(path);
        var result = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document;
    }

    public async Task<AudioLibraryDocument> RegisterAsync(
        string filePath,
        TimeSpan duration,
        string? displayName = null,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(null);
        return await MutateAsync(
            target,
            async resolvedPath =>
            {
                var loaded = await LoadDocumentAsync(resolvedPath, cancellationToken)
                    .ConfigureAwait(false);
                var normalized = Path.GetFullPath(filePath);
                var existing = loaded.Document.Entries.FirstOrDefault(e =>
                    string.Equals(
                        Path.GetFullPath(e.FilePath),
                        normalized,
                        StringComparison.OrdinalIgnoreCase));
                var id = existing?.Id ?? Guid.NewGuid();
                var entry = new AudioLibraryEntry(
                    id,
                    normalized,
                    duration,
                    displayName ?? Path.GetFileNameWithoutExtension(filePath),
                    DateTimeOffset.UtcNow);
                var document = loaded.Document.WithEntry(entry);
                await _store
                    .SaveAsync(resolvedPath, document, DocumentAccessMode.ReadWrite, cancellationToken)
                    .ConfigureAwait(false);
                return document;
            },
            cancellationToken).ConfigureAwait(false);
    }

    public async Task<AudioLibraryDocument> RemoveAsync(
        Guid id,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(null);
        return await MutateAsync(
            target,
            async resolvedPath =>
            {
                var loaded = await LoadDocumentAsync(resolvedPath, cancellationToken)
                    .ConfigureAwait(false);
                var document = loaded.Document.WithoutEntry(id);
                await _store
                    .SaveAsync(resolvedPath, document, DocumentAccessMode.ReadWrite, cancellationToken)
                    .ConfigureAwait(false);
                return document;
            },
            cancellationToken).ConfigureAwait(false);
    }

    /// <summary>清空音频库全部记录，不删除磁盘上的原始音频文件。</summary>
    public async Task<(AudioLibraryDocument Document, int Removed)> ClearAllAsync(
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(null);
        return await MutateAsync(
            target,
            async resolvedPath =>
            {
                var loaded = await LoadDocumentAsync(resolvedPath, cancellationToken)
                    .ConfigureAwait(false);
                var removed = loaded.Document.Entries.Count;
                if (removed == 0)
                {
                    return (loaded.Document, 0);
                }

                var empty = AudioLibraryDocument.Empty;
                await _store
                    .SaveAsync(resolvedPath, empty, DocumentAccessMode.ReadWrite, cancellationToken)
                    .ConfigureAwait(false);
                return (empty, removed);
            },
            cancellationToken).ConfigureAwait(false);
    }

    /// <summary>清理文件中不存在的条目，返回清理后文档与移除数量。</summary>
    /// <param name="cache">可选的文件存在性缓存，重复检测同一文件时加速。</param>
    public async Task<(AudioLibraryDocument Document, int Removed)> PruneMissingAsync(
        string? libraryPath = null,
        FileExistenceCache? cache = null,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(libraryPath);
        return await MutateAsync(
            target,
            async resolvedPath =>
            {
                var loaded = await LoadDocumentAsync(resolvedPath, cancellationToken)
                    .ConfigureAwait(false);
                var kept = cache is null
                    ? loaded.Document.Entries.Where(e => File.Exists(e.FilePath)).ToList()
                    : loaded.Document.Entries.Where(e => cache.Exists(e.FilePath)).ToList();
                var removed = loaded.Document.Entries.Count - kept.Count;
                if (removed == 0)
                {
                    return (loaded.Document, 0);
                }

                var pruned = new AudioLibraryDocument { Entries = kept };
                await _store
                    .SaveAsync(resolvedPath, pruned, DocumentAccessMode.ReadWrite, cancellationToken)
                    .ConfigureAwait(false);
                return (pruned, removed);
            },
            cancellationToken).ConfigureAwait(false);
    }

    private string ResolveLibraryPath(string? path) =>
        Path.GetFullPath(path ?? _defaultLibraryPath);

    private async Task<DocumentLoadResult<AudioLibraryDocument>> LoadDocumentAsync(
        string target,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(target))
        {
            return new DocumentLoadResult<AudioLibraryDocument>(
                AudioLibraryDocument.Empty,
                DocumentAccessMode.ReadWrite);
        }

        return await _store.LoadAsync(target, cancellationToken).ConfigureAwait(false);
    }

    private static async Task<TResult> MutateAsync<TResult>(
        string target,
        Func<string, Task<TResult>> mutation,
        CancellationToken cancellationToken)
    {
        var gate = MutationGates.GetOrAdd(target, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            return await mutation(target).ConfigureAwait(false);
        }
        finally
        {
            gate.Release();
        }
    }
}
