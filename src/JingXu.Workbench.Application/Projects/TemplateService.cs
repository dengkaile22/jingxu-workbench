using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Application.Projects;

/// <summary>效果模板库文档。</summary>
public sealed class EffectTemplateDocument
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; } = CurrentSchemaVersion;

    [JsonPropertyName("templates")]
    public IReadOnlyList<EffectVariationTemplate> Templates { get; init; } = [];

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

    public TemplateService(IAtomicJsonStore<EffectTemplateDocument> store)
    {
        _store = store;
    }

    /// <summary>默认模板库路径。</summary>
    public static string DefaultTemplatePath =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JingXu",
            "effect-templates.json");

    /// <summary>加载模板库；不存在时返回内置默认模板。</summary>
    public async Task<EffectTemplateDocument> LoadAsync(string? path = null, CancellationToken cancellationToken = default)
    {
        var target = path ?? DefaultTemplatePath;
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
        var target = path ?? DefaultTemplatePath;
        var directory = Path.GetDirectoryName(target);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        await _store.SaveAsync(target, document, DocumentAccessMode.ReadWrite, cancellationToken)
            .ConfigureAwait(false);
    }
}
