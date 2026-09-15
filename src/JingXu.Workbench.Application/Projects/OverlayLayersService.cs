using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Application.Projects;

public sealed class OverlayLayersDocument
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; } = CurrentSchemaVersion;

    [JsonPropertyName("layers")]
    public IReadOnlyList<OverlayLayer> Layers { get; init; } = [];

    public static OverlayLayersDocument Empty { get; } = new();
}

public sealed class OverlayLayersService
{
    private readonly IAtomicJsonStore<OverlayLayersDocument> _store;
    private readonly string _defaultPath;

    public OverlayLayersService(
        IAtomicJsonStore<OverlayLayersDocument> store,
        string? defaultPath = null)
    {
        _store = store;
        _defaultPath = string.IsNullOrWhiteSpace(defaultPath) ? DefaultLayersPath : defaultPath;
    }

    public static string DefaultLayersPath =>
        Path.Combine(
            WorkbenchDataPaths.GetDataDirectory(),
            "overlay-layers.json");

    public string StorePath => _defaultPath;

    public async Task<OverlayLayersDocument> LoadAsync(
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var target = path ?? _defaultPath;
        if (!File.Exists(target))
        {
            return OverlayLayersDocument.Empty;
        }

        var result = await _store.LoadAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document;
    }

    public async Task SaveAsync(
        OverlayLayersDocument document,
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
