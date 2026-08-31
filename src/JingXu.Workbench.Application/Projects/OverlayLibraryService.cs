using System.Collections.Concurrent;
using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Application.Projects;

/// <summary>蒙版素材库文档。</summary>
public sealed class OverlayLibraryDocument
{
    public const int CurrentSchemaVersion = 2;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; } = CurrentSchemaVersion;

    [JsonPropertyName("entries")]
    public IReadOnlyList<OverlayLibraryEntry> Entries { get; init; } = [];

    /// <summary>创建空库。</summary>
    public static OverlayLibraryDocument Empty { get; } = new();

    /// <summary>添加或更新条目。</summary>
    public OverlayLibraryDocument WithEntry(OverlayLibraryEntry entry)
    {
        ArgumentNullException.ThrowIfNull(entry);
        var list = Entries.Where(e => e.Id != entry.Id).ToList();
        list.Add(entry);
        return new OverlayLibraryDocument { Entries = list };
    }

    /// <summary>移除条目。</summary>
    public OverlayLibraryDocument WithoutEntry(Guid id)
    {
        var list = Entries.Where(e => e.Id != id).ToList();
        return new OverlayLibraryDocument { Entries = list };
    }
}

/// <summary>蒙版素材库持久化服务。</summary>
public sealed class OverlayLibraryService
{
    private static readonly ConcurrentDictionary<string, SemaphoreSlim> MutationGates =
        new(StringComparer.OrdinalIgnoreCase);

    private readonly IAtomicJsonStore<OverlayLibraryDocument> _store;
    private readonly string _defaultLibraryPath;

    public OverlayLibraryService(
        IAtomicJsonStore<OverlayLibraryDocument> store,
        string? defaultLibraryPath = null)
    {
        _store = store;
        _defaultLibraryPath = defaultLibraryPath ?? DefaultLibraryPath;
    }

    /// <summary>默认库文件路径。</summary>
    public static string DefaultLibraryPath =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JingXu",
            "overlay-library.json");

    /// <summary>加载素材库；文件不存在时返回空库。</summary>
    public async Task<OverlayLibraryDocument> LoadAsync(string? path = null, CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(path);
        var result = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document;
    }

    private string ResolveLibraryPath(string? path) =>
        Path.GetFullPath(path ?? _defaultLibraryPath);

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

    private static async Task MutateAsync(
        string target,
        Func<string, Task> mutation,
        CancellationToken cancellationToken)
    {
        var gate = MutationGates.GetOrAdd(target, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await mutation(target).ConfigureAwait(false);
        }
        finally
        {
            gate.Release();
        }
    }

    private async Task<DocumentLoadResult<OverlayLibraryDocument>> LoadDocumentAsync(
        string target,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(target))
        {
            return new DocumentLoadResult<OverlayLibraryDocument>(
                OverlayLibraryDocument.Empty,
                DocumentAccessMode.ReadWrite);
        }

        return await _store.LoadAsync(target, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>原子保存素材库。</summary>
    public async Task SaveAsync(
        OverlayLibraryDocument document,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(document);
        var target = ResolveLibraryPath(path);
        await MutateAsync(
                target,
                async resolvedTarget =>
                {
                    var loaded = await LoadDocumentAsync(resolvedTarget, cancellationToken).ConfigureAwait(false);
                    await SaveCoreAsync(document, resolvedTarget, loaded.AccessMode, cancellationToken)
                        .ConfigureAwait(false);
                }, cancellationToken)
            .ConfigureAwait(false);
    }

    private async Task SaveCoreAsync(
        OverlayLibraryDocument document,
        string target,
        DocumentAccessMode accessMode,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(document);
        var directory = Path.GetDirectoryName(target);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        await _store.SaveAsync(target, document, accessMode, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>注册新蒙版素材条目。</summary>
    public async Task<OverlayLibraryEntry> RegisterAsync(
        string filePath,
        IReadOnlyList<string>? tags = null,
        string? thumbnailPath = null,
        string? libraryPath = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(filePath);

        if (!File.Exists(filePath))
        {
            throw new FileNotFoundException("蒙版素材文件不存在。", filePath);
        }

        var target = ResolveLibraryPath(libraryPath);
        var fullPath = Path.GetFullPath(filePath);
        return await MutateAsync(
                target,
                async resolvedTarget =>
                {
                    var loaded = await LoadDocumentAsync(resolvedTarget, cancellationToken).ConfigureAwait(false);
                    var document = loaded.Document;
                    var existing = document.Entries.FirstOrDefault(e =>
                        string.Equals(e.FilePath, fullPath, StringComparison.OrdinalIgnoreCase));

                    // 同一路径只保留一条，避免重复导入把库数量虚高。
                    var entry = existing is null
                        ? new OverlayLibraryEntry(
                            Guid.NewGuid(),
                            fullPath,
                            tags ?? [],
                            thumbnailPath,
                            DateTimeOffset.UtcNow)
                        : existing with
                        {
                            Tags = tags ?? existing.Tags,
                            ThumbnailPath = thumbnailPath ?? existing.ThumbnailPath,
                            LastUsedAt = DateTimeOffset.UtcNow
                        };

                    await SaveCoreAsync(document.WithEntry(entry), resolvedTarget, loaded.AccessMode, cancellationToken)
                        .ConfigureAwait(false);
                    return entry;
                }, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>
    /// 原子地将一份视觉参数快照套用到选中的素材库条目。
    /// 仅更新条目的 <see cref="OverlayLibraryEntry.VisualSettings"/>，不改动素材路径、标签、缩略图或使用记录。
    /// </summary>
    public async Task<(OverlayLibraryDocument Document, int Updated)> ApplyVisualSettingsAsync(
        IReadOnlyCollection<Guid> entryIds,
        OverlayVisualSettings visualSettings,
        string? libraryPath = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(entryIds);
        ArgumentNullException.ThrowIfNull(visualSettings);
        var validation = visualSettings.Validate();
        if (!validation.IsSuccess)
        {
            throw new ArgumentException(validation.Error, nameof(visualSettings));
        }

        var selectedIds = entryIds.ToHashSet();
        var target = ResolveLibraryPath(libraryPath);
        return await MutateAsync(
                target,
                async resolvedTarget =>
                {
                    var loaded = await LoadDocumentAsync(resolvedTarget, cancellationToken).ConfigureAwait(false);
                    var document = loaded.Document;
                    if (selectedIds.Count == 0)
                    {
                        return (document, 0);
                    }

                    var updated = 0;
                    var entries = document.Entries
                        .Select(entry =>
                        {
                            if (!selectedIds.Contains(entry.Id) || entry.VisualSettings == visualSettings)
                            {
                                return entry;
                            }

                            updated++;
                            return entry with { VisualSettings = visualSettings };
                        })
                        .ToArray();
                    if (updated == 0)
                    {
                        return (document, 0);
                    }

                    var updatedDocument = new OverlayLibraryDocument { Entries = entries };
                    await SaveCoreAsync(updatedDocument, resolvedTarget, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
                    return (updatedDocument, updated);
                }, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>
    /// Writes a thumbnail only when the original library entry still exists.
    /// This lets a delayed background thumbnail task finish without re-registering a deleted entry.
    /// </summary>
    public async Task<(OverlayLibraryDocument Document, bool Updated)> UpdateThumbnailIfEntryExistsAsync(
        Guid entryId,
        string thumbnailPath,
        string? libraryPath = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(thumbnailPath);

        var target = ResolveLibraryPath(libraryPath);
        return await MutateAsync(
                target,
                async resolvedTarget =>
                {
                    var loaded = await LoadDocumentAsync(resolvedTarget, cancellationToken).ConfigureAwait(false);
                    var document = loaded.Document;
                    var existing = document.Entries.FirstOrDefault(entry => entry.Id == entryId);
                    if (existing is null ||
                        string.Equals(existing.ThumbnailPath, thumbnailPath, StringComparison.Ordinal))
                    {
                        return (document, false);
                    }

                    var updatedEntry = existing with { ThumbnailPath = thumbnailPath };
                    var updatedDocument = document.WithEntry(updatedEntry);
                    await SaveCoreAsync(updatedDocument, resolvedTarget, loaded.AccessMode, cancellationToken)
                        .ConfigureAwait(false);
                    return (updatedDocument, true);
                }, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>移除路径失效（文件不存在）的条目，返回清理后文档与移除数量。</summary>
    public async Task<(OverlayLibraryDocument Document, int Removed)> PruneMissingAsync(
        string? libraryPath = null,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(libraryPath);
        return await MutateAsync(
                target,
                async resolvedTarget =>
                {
                    var loaded = await LoadDocumentAsync(resolvedTarget, cancellationToken).ConfigureAwait(false);
                    var document = loaded.Document;
                    var kept = document.Entries.Where(e => File.Exists(e.FilePath)).ToList();
                    var removed = document.Entries.Count - kept.Count;
                    if (removed == 0)
                    {
                        return (document, 0);
                    }

                    var pruned = new OverlayLibraryDocument { Entries = kept };
                    await SaveCoreAsync(pruned, resolvedTarget, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
                    return (pruned, removed);
                }, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>按 Id 删除单条素材库条目。</summary>
    public async Task<(OverlayLibraryDocument Document, bool Removed)> DeleteEntryAsync(
        Guid entryId,
        string? libraryPath = null,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(libraryPath);
        return await MutateAsync(
                target,
                async resolvedTarget =>
                {
                    var loaded = await LoadDocumentAsync(resolvedTarget, cancellationToken).ConfigureAwait(false);
                    var document = loaded.Document;
                    if (document.Entries.All(e => e.Id != entryId))
                    {
                        return (document, false);
                    }

                    var updated = document.WithoutEntry(entryId);
                    await SaveCoreAsync(updated, resolvedTarget, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
                    return (updated, true);
                }, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>清空整库条目（不删磁盘上的视频文件）。</summary>
    public async Task<(OverlayLibraryDocument Document, int Removed)> ClearAllAsync(
        string? libraryPath = null,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(libraryPath);
        return await MutateAsync(
                target,
                async resolvedTarget =>
                {
                    var loaded = await LoadDocumentAsync(resolvedTarget, cancellationToken).ConfigureAwait(false);
                    var document = loaded.Document;
                    var removed = document.Entries.Count;
                    if (removed == 0)
                    {
                        return (document, 0);
                    }

                    var empty = OverlayLibraryDocument.Empty;
                    await SaveCoreAsync(empty, resolvedTarget, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
                    return (empty, removed);
                }, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>记录条目最近使用时间。</summary>
    public async Task TouchAsync(
        Guid entryId,
        string? libraryPath = null,
        CancellationToken cancellationToken = default)
    {
        var target = ResolveLibraryPath(libraryPath);
        await MutateAsync(
                target,
                async resolvedTarget =>
                {
                    var loaded = await LoadDocumentAsync(resolvedTarget, cancellationToken).ConfigureAwait(false);
                    var document = loaded.Document;
                    var existing = document.Entries.FirstOrDefault(e => e.Id == entryId);
                    if (existing is null)
                    {
                        return;
                    }

                    var updated = existing with { LastUsedAt = DateTimeOffset.UtcNow };
                    await SaveCoreAsync(document.WithEntry(updated), resolvedTarget, loaded.AccessMode, cancellationToken)
                        .ConfigureAwait(false);
                }, cancellationToken)
            .ConfigureAwait(false);
    }
}
