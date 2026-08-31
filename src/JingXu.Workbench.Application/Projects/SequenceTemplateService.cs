using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Composition;

namespace JingXu.Workbench.Application.Projects;

/// <summary>可保存的素材序号编排模板。</summary>
public sealed record SequenceTemplate(
    [property: JsonPropertyName("id")] Guid Id,
    [property: JsonPropertyName("displayName")] string DisplayName,
    [property: JsonPropertyName("expression")] string Expression);

/// <summary>序号模板库文档。</summary>
public sealed class SequenceTemplateDocument
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; } = CurrentSchemaVersion;

    [JsonPropertyName("templates")]
    public IReadOnlyList<SequenceTemplate> Templates { get; init; } = [];

    /// <summary>空序号模板库。</summary>
    public static SequenceTemplateDocument Empty { get; } = new();

    /// <summary>添加或替换同一标识的模板。</summary>
    public SequenceTemplateDocument WithTemplate(SequenceTemplate template)
    {
        ArgumentNullException.ThrowIfNull(template);

        var templates = Templates.Where(existing => existing.Id != template.Id).ToList();
        templates.Add(template);
        return new SequenceTemplateDocument
        {
            SchemaVersion = SchemaVersion,
            Templates = templates
        };
    }

    /// <summary>移除指定标识的模板。</summary>
    public SequenceTemplateDocument WithoutTemplate(Guid id) =>
        new()
        {
            SchemaVersion = SchemaVersion,
            Templates = Templates.Where(template => template.Id != id).ToArray()
        };
}

/// <summary>序号模板持久化服务。</summary>
public sealed class SequenceTemplateService
{
    private readonly IAtomicJsonStore<SequenceTemplateDocument> _store;
    private readonly string _defaultPath;

    public SequenceTemplateService(
        IAtomicJsonStore<SequenceTemplateDocument> store,
        string? defaultPath = null)
    {
        _store = store;
        _defaultPath = string.IsNullOrWhiteSpace(defaultPath) ? DefaultTemplatePath : defaultPath;
    }

    /// <summary>默认序号模板库路径。</summary>
    public static string DefaultTemplatePath =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JingXu",
            "sequence-templates.json");

    /// <summary>当前实例使用的默认路径。</summary>
    public string StorePath => _defaultPath;

    /// <summary>加载序号模板库；文件不存在时返回空库。</summary>
    public async Task<SequenceTemplateDocument> LoadAsync(
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var target = path ?? _defaultPath;
        var result = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        return result.Document;
    }

    private async Task<DocumentLoadResult<SequenceTemplateDocument>> LoadDocumentAsync(
        string target,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(target))
        {
            return new DocumentLoadResult<SequenceTemplateDocument>(
                SequenceTemplateDocument.Empty,
                DocumentAccessMode.ReadWrite);
        }

        return await _store.LoadAsync(target, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>原子保存序号模板库。</summary>
    public async Task SaveAsync(
        SequenceTemplateDocument document,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var target = path ?? _defaultPath;
        var loaded = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        await SaveCoreAsync(document, target, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
    }

    private async Task SaveCoreAsync(
        SequenceTemplateDocument document,
        string target,
        DocumentAccessMode accessMode,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(document);
        foreach (var template in document.Templates)
        {
            ValidateAndNormalize(template);
        }

        var directory = Path.GetDirectoryName(target);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        await _store.SaveAsync(target, document, accessMode, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>添加或更新序号模板。</summary>
    public async Task<SequenceTemplateDocument> UpsertAsync(
        SequenceTemplate template,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var normalized = ValidateAndNormalize(template);
        var target = path ?? _defaultPath;
        var loaded = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        var updated = loaded.Document.WithTemplate(normalized);
        await SaveCoreAsync(updated, target, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
        return updated;
    }

    /// <summary>重命名指定序号模板。</summary>
    public async Task<(SequenceTemplateDocument Document, bool Renamed)> RenameAsync(
        Guid templateId,
        string displayName,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var normalizedName = NormalizeDisplayName(displayName);
        var target = path ?? _defaultPath;
        var loaded = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        var template = loaded.Document.Templates.FirstOrDefault(candidate => candidate.Id == templateId);
        if (template is null)
        {
            return (loaded.Document, false);
        }

        var updated = loaded.Document.WithTemplate(template with { DisplayName = normalizedName });
        await SaveCoreAsync(updated, target, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
        return (updated, true);
    }

    /// <summary>删除指定序号模板。</summary>
    public async Task<(SequenceTemplateDocument Document, bool Removed)> DeleteAsync(
        Guid templateId,
        string? path = null,
        CancellationToken cancellationToken = default)
    {
        var target = path ?? _defaultPath;
        var loaded = await LoadDocumentAsync(target, cancellationToken).ConfigureAwait(false);
        if (loaded.Document.Templates.All(template => template.Id != templateId))
        {
            return (loaded.Document, false);
        }

        var updated = loaded.Document.WithoutTemplate(templateId);
        await SaveCoreAsync(updated, target, loaded.AccessMode, cancellationToken).ConfigureAwait(false);
        return (updated, true);
    }

    private static SequenceTemplate ValidateAndNormalize(SequenceTemplate template)
    {
        ArgumentNullException.ThrowIfNull(template);
        if (template.Id == Guid.Empty)
        {
            throw new ArgumentException("序号模板标识不能为空。", nameof(template));
        }

        var displayName = NormalizeDisplayName(template.DisplayName);
        if (string.IsNullOrWhiteSpace(template.Expression))
        {
            throw new ArgumentException("序号模板表达式不能为空。", nameof(template));
        }

        var expression = template.Expression.Trim();
        var expressions = FileSequenceParser.SplitExpressions(expression);
        if (expressions.Count == 0)
        {
            throw new ArgumentException("序号模板表达式不能为空。", nameof(template));
        }

        foreach (var item in expressions)
        {
            var parsed = FileSequenceParser.Parse(item);
            if (!parsed.IsSuccess)
            {
                throw new ArgumentException(parsed.Error ?? "序号模板表达式格式无效。", nameof(template));
            }
        }

        return template with { DisplayName = displayName, Expression = expression };
    }

    private static string NormalizeDisplayName(string displayName)
    {
        if (string.IsNullOrWhiteSpace(displayName))
        {
            throw new ArgumentException("序号模板名称不能为空。", nameof(displayName));
        }

        return displayName.Trim();
    }
}
