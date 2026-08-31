using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Stickers;

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

/// <summary>效果模板中的一条贴纸轨道参数快照。</summary>
public sealed class StickerTrackTemplateDto
{
    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    [JsonPropertyName("path")]
    public string Path { get; init; } = string.Empty;

    [JsonPropertyName("x")]
    public double X { get; init; }

    [JsonPropertyName("y")]
    public double Y { get; init; }

    [JsonPropertyName("width")]
    public double Width { get; init; } = 0.2;

    [JsonPropertyName("height")]
    public double Height { get; init; } = 0.2;

    [JsonPropertyName("opacity")]
    public double Opacity { get; init; } = 1.0;

    [JsonPropertyName("rotationDegrees")]
    public double RotationDegrees { get; init; }

    [JsonPropertyName("isEnabled")]
    public bool IsEnabled { get; init; } = true;

    [JsonPropertyName("fixedAspectRatio")]
    public FixedAspectRatio FixedAspectRatio { get; init; } = FixedAspectRatio.None;
}

/// <summary>效果模板关联的界面处理参数。</summary>
public sealed class EffectTemplateSettingsDto
{
    [JsonPropertyName("variationIntensityPercent")]
    public int VariationIntensityPercent { get; init; } = 100;

    [JsonPropertyName("stickerTracks")]
    public IReadOnlyList<StickerTrackTemplateDto> StickerTracks { get; init; } = [];
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

    /// <summary>按模板 Id 关联的强度与多贴纸轨道参数。</summary>
    [JsonPropertyName("settingsByTemplateId")]
    public IReadOnlyDictionary<string, EffectTemplateSettingsDto> SettingsByTemplateId { get; init; } =
        new Dictionary<string, EffectTemplateSettingsDto>(StringComparer.Ordinal);

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
        var result = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document;
    }

    private async Task<DocumentLoadResult<EffectTemplateDocument>> LoadDocumentAsync(
        string target,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(target))
        {
            return new DocumentLoadResult<EffectTemplateDocument>(
                EffectTemplateDocument.WithDefaults,
                DocumentAccessMode.ReadWrite);
        }

        var result = await _store.LoadAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document.Templates.Count == 0
            ? new DocumentLoadResult<EffectTemplateDocument>(
                EffectTemplateDocument.WithDefaults,
                result.AccessMode)
            : result;
    }

    /// <summary>原子保存模板库。</summary>
    public async Task SaveAsync(
        EffectTemplateDocument document,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var target = path ?? _defaultPath;
        var loaded = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        await SaveCoreAsync(document, target, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
    }

    private async Task SaveCoreAsync(
        EffectTemplateDocument document,
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

    /// <summary>重命名用户效果模板，保留模板标识与贴纸快照。</summary>
    public async Task<(EffectTemplateDocument Document, bool Renamed)> RenameUserTemplateAsync(
        string templateId,
        string displayName,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(templateId);
        ArgumentException.ThrowIfNullOrWhiteSpace(displayName);

        var target = path ?? _defaultPath;
        var loaded = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        var document = loaded.Document;
        if (IsBuiltinTemplateId(templateId))
        {
            return (document, false);
        }

        var template = document.Templates.FirstOrDefault(candidate => candidate.Id == templateId);
        if (template is null)
        {
            return (document, false);
        }

        var updated = new EffectTemplateDocument
        {
            SchemaVersion = document.SchemaVersion,
            Templates = document.Templates
                .Select(candidate => candidate.Id == templateId
                    ? candidate with { DisplayName = displayName.Trim() }
                    : candidate)
                .ToArray(),
            StickersByTemplateId = document.StickersByTemplateId,
            SettingsByTemplateId = document.SettingsByTemplateId
        };
        await SaveCoreAsync(updated, target, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
        return (updated, true);
    }

    /// <summary>删除用户效果模板及其对应的贴纸快照。</summary>
    public async Task<(EffectTemplateDocument Document, bool Removed)> DeleteUserTemplateAsync(
        string templateId,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(templateId);

        var target = path ?? _defaultPath;
        var loaded = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        var document = loaded.Document;
        if (IsBuiltinTemplateId(templateId) || document.Templates.All(candidate => candidate.Id != templateId))
        {
            return (document, false);
        }

        var stickers = new Dictionary<string, StickerTemplateDto>(
            document.StickersByTemplateId,
            StringComparer.Ordinal);
        stickers.Remove(templateId);
        var settings = new Dictionary<string, EffectTemplateSettingsDto>(
            document.SettingsByTemplateId,
            StringComparer.Ordinal);
        settings.Remove(templateId);

        var updated = new EffectTemplateDocument
        {
            SchemaVersion = document.SchemaVersion,
            Templates = document.Templates.Where(candidate => candidate.Id != templateId).ToArray(),
            StickersByTemplateId = stickers,
            SettingsByTemplateId = settings
        };
        await SaveCoreAsync(updated, target, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
        return (updated, true);
    }

    private static bool IsBuiltinTemplateId(string templateId) =>
        templateId == EffectTemplates.None.Id || templateId == EffectTemplates.StandardVariation().Id;
}
