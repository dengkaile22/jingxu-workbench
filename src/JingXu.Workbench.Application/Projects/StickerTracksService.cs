using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Stickers;

namespace JingXu.Workbench.Application.Projects;

public sealed class StickerTracksDocument
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; } = CurrentSchemaVersion;

    [JsonPropertyName("tracks")]
    public IReadOnlyList<StickerTrack> Tracks { get; init; } = [];

    public static StickerTracksDocument Empty { get; } = new();
}

public sealed class StickerTracksService
{
    private readonly IAtomicJsonStore<StickerTracksDocument> _store;
    private readonly string _defaultPath;

    public StickerTracksService(
        IAtomicJsonStore<StickerTracksDocument> store,
        string? defaultPath = null)
    {
        _store = store;
        _defaultPath = string.IsNullOrWhiteSpace(defaultPath) ? DefaultTracksPath : defaultPath;
    }

    public static string DefaultTracksPath =>
        Path.Combine(
            WorkbenchDataPaths.GetDataDirectory(),
            "sticker-tracks.json");

    public string StorePath => _defaultPath;

    public async Task<StickerTracksDocument> LoadAsync(
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var target = path ?? _defaultPath;
        if (!File.Exists(target))
        {
            return StickerTracksDocument.Empty;
        }

        var result = await _store.LoadAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document;
    }

    public async Task SaveAsync(
        StickerTracksDocument document,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var target = path ?? _defaultPath;
        var directory = Path.GetDirectoryName(target);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        await _store.SaveAsync(target, document, DocumentAccessMode.ReadWrite, cancellationToken)
            .ConfigureAwait(false);
    }
}
