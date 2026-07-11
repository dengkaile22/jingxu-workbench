using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Application.Projects;

/// <summary>与命名效果模板关联的贴纸参数快照（归一化坐标）。</summary>
public sealed class StickerTemplateDto
{
    [JsonPropertyName("path")]
    public string Path { get; init; } = string.Empty;

    [JsonPropertyName("x")]
    public double X { get; init; } = 0.72;

    [JsonPropertyName("y")]
    public double Y { get; init; } = 0.78;

    [JsonPropertyName("width")]
    public double Width { get; init; } = 0.22;

    [JsonPropertyName("height")]
    public double Height { get; init; } = 0.16;

    [JsonPropertyName("opacity")]
    public double Opacity { get; init; } = 1.0;
}

/// <summary>效果模板库文档。</summary>
public sealed class EffectTemplateDocument
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; } = CurrentSchemaVersion;

    [JsonPropertyName("templates")]
    public IReadOnlyList<EffectVariationTemplate> Templates { get; init; } = [];

    /// <summary>按模板 Id 关联的贴纸快照；缺省表示该模板不含贴纸。</summary>
    [JsonPropertyName("stickersByTemplateId")]
    public IReadOnlyDictionary<string, StickerTemplateDto> StickersByTemplateId { get; init; } =
        new Dictionary<string, StickerTemplateDto>(StringComparer.Ordinal);

    /// <summary>内置默认模板集合。</summary>
    public static EffectTemplateDocument WithDefaults { get; } = new()
    {
        Templates =
        [
            EffectTemplates.None,
            EffectTemplates.StandardVariation()
        ]
    };
}

/// <summary>效果模板持久化服务。</summary>
public sealed class TemplateService
{
    private readonly IAtomicJsonStore<EffectTemplateDocument> _store;
    private readonly string _defaultPath;

    public TemplateService(IAtomicJsonStore<EffectTemplateDocument> store, string? defaultPath = null)
    {
        _store = store;
        _defaultPath = string.IsNullOrWhiteSpace(defaultPath) ? DefaultTemplatePath : defaultPath;
    }

    /// <summary>默认模板库路径。</summary>
    public static string DefaultTemplatePath =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JingXu",
            "effect-templates.json");

    /// <summary>当前实例使用的默认路径。</summary>
    public string StorePath => _defaultPath;

    /// <summary>加载模板库；不存在时返回内置默认模板。</summary>
    public async Task<EffectTemplateDocument> LoadAsync(string? path = null, CancellationToken cancellationToken = default)
    {
        var target = path ?? _defaultPath;
        if (!File.Exists(target))
        {
            return EffectTemplateDocument.WithDefaults;
        }

        var result = await _store.LoadAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document.Templates.Count == 0
            ? EffectTemplateDocument.WithDefaults
            : result.Document;
    }

    /// <summary>原子保存模板库。</summary>
    public async Task SaveAsync(
        EffectTemplateDocument document,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(document);
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
