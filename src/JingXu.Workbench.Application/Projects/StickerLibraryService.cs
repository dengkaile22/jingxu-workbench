using System.Collections.Concurrent;
using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Stickers;

namespace JingXu.Workbench.Application.Projects;

/// <summary>贴纸素材库文档。</summary>
public sealed class StickerLibraryDocument
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; } = CurrentSchemaVersion;

    [JsonPropertyName("entries")]
    public IReadOnlyList<StickerLibraryEntry> Entries { get; init; } = [];

    public static StickerLibraryDocument Empty { get; } = new();

    public StickerLibraryDocument WithEntry(StickerLibraryEntry entry)
    {
        ArgumentNullException.ThrowIfNull(entry);
        var list = Entries.Where(e => e.Id != entry.Id).ToList();
        list.Add(entry);
        return new StickerLibraryDocument { Entries = list };
    }

    public StickerLibraryDocument WithoutEntry(Guid id)
    {
        var list = Entries.Where(e => e.Id != id).ToList();
        return new StickerLibraryDocument { Entries = list };
    }
}

/// <summary>贴纸库条目。</summary>
public sealed record StickerLibraryEntry(
    Guid Id,
    string FilePath,
    string? ThumbnailPath,
    DateTimeOffset? LastUsedAt)
{
    public string FileName => Path.GetFileName(FilePath);
}

/// <summary>贴纸素材库持久化服务。</summary>
public sealed class StickerLibraryService
{
    private static readonly ConcurrentDictionary<string, SemaphoreSlim> MutationGates =
        new(StringComparer.OrdinalIgnoreCase);

    private readonly IAtomicJsonStore<StickerLibraryDocument> _store;
    private readonly string _defaultLibraryPath;

    public StickerLibraryService(
        IAtomicJsonStore<StickerLibraryDocument> store,
        string? defaultLibraryPath = null)
    {
        _store = store;
        _defaultLibraryPath = defaultLibraryPath ?? DefaultLibraryPath;
    }

    public static string DefaultLibraryPath =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JingXu",
            "sticker-library.json");

    public async Task<StickerLibraryDocument> LoadAsync(string? path = null, CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(path);
        var result = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document;
    }

    public async Task<StickerLibraryDocument> RegisterAsync(
        string filePath,
        string? thumbnailPath = null,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(null);
        return await MutateAsync(target, async path =>
        {
            var loaded = await LoadDocumentAsync(path, cancellationToken).ConfigureAwait(false);
            var normalized = Path.GetFullPath(filePath);
            var existing = loaded.Document.Entries.FirstOrDefault(e =>
                string.Equals(Path.GetFullPath(e.FilePath), normalized, StringComparison.OrdinalIgnoreCase));
            var id = existing?.Id ?? Guid.NewGuid();
            var entry = new StickerLibraryEntry(id, normalized, thumbnailPath, DateTimeOffset.Now);
            var document = loaded.Document.WithEntry(entry);
            await _store.SaveAsync(path, document, DocumentAccessMode.ReadWrite, cancellationToken).ConfigureAwait(false);
            return document;
        }, cancellationToken).ConfigureAwait(false);
    }

    public async Task<StickerLibraryDocument> RemoveAsync(
        Guid id,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(null);
        return await MutateAsync(target, async path =>
        {
            var loaded = await LoadDocumentAsync(path, cancellationToken).ConfigureAwait(false);
            var document = loaded.Document.WithoutEntry(id);
            await _store.SaveAsync(path, document, DocumentAccessMode.ReadWrite, cancellationToken).ConfigureAwait(false);
            return document;
        }, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>清空贴纸素材库全部记录，不删除磁盘上的原始图片文件。</summary>
    public async Task<(StickerLibraryDocument Document, int Removed)> ClearAllAsync(
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(null);
        return await MutateAsync(target, async path =>
        {
            var loaded = await LoadDocumentAsync(path, cancellationToken).ConfigureAwait(false);
            var removed = loaded.Document.Entries.Count;
            if (removed == 0)
            {
                return (loaded.Document, 0);
            }

            var empty = StickerLibraryDocument.Empty;
            await _store.SaveAsync(path, empty, DocumentAccessMode.ReadWrite, cancellationToken)
                .ConfigureAwait(false);
            return (empty, removed);
        }, cancellationToken).ConfigureAwait(false);
    }

    private string ResolveLibraryPath(string? path) =>
        Path.GetFullPath(path ?? _defaultLibraryPath);

    private async Task<DocumentLoadResult<StickerLibraryDocument>> LoadDocumentAsync(
        string target,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(target))
        {
            return new DocumentLoadResult<StickerLibraryDocument>(
                StickerLibraryDocument.Empty,
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
