using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Application.Projects;

/// <summary>蒙版素材库文档。</summary>
public sealed class OverlayLibraryDocument
{
    public const int CurrentSchemaVersion = 1;

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
        var target = path ?? _defaultLibraryPath;
        if (!File.Exists(target))
        {
            return OverlayLibraryDocument.Empty;
        }

        var result = await _store.LoadAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document;
    }

    /// <summary>原子保存素材库。</summary>
    public async Task SaveAsync(
        OverlayLibraryDocument document,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(document);
        var target = path ?? _defaultLibraryPath;
        var directory = Path.GetDirectoryName(target);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        await _store.SaveAsync(target, document, DocumentAccessMode.ReadWrite, cancellationToken)
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

        var document = await LoadAsync(libraryPath, cancellationToken).ConfigureAwait(false);
        var entry = new OverlayLibraryEntry(
            Guid.NewGuid(),
            Path.GetFullPath(filePath),
            tags ?? [],
            thumbnailPath,
            DateTimeOffset.UtcNow);

        await SaveAsync(document.WithEntry(entry), libraryPath, cancellationToken).ConfigureAwait(false);
        return entry;
    }

    /// <summary>记录条目最近使用时间。</summary>
    public async Task TouchAsync(
        Guid entryId,
        string? libraryPath = null,
        CancellationToken cancellationToken = default)
    {
        var document = await LoadAsync(libraryPath, cancellationToken).ConfigureAwait(false);
        var existing = document.Entries.FirstOrDefault(e => e.Id == entryId);
        if (existing is null)
        {
            return;
        }

        var updated = existing with { LastUsedAt = DateTimeOffset.UtcNow };
        await SaveAsync(document.WithEntry(updated), libraryPath, cancellationToken).ConfigureAwait(false);
    }
}
