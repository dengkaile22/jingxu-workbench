using System.Text.Json.Serialization;

namespace JingXu.Workbench.Application.Projects;

/// <summary>
/// 项目文档。包含版本化 JSON schema 版本。
/// </summary>
public sealed class ProjectDocument
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; } = CurrentSchemaVersion;

    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    [JsonPropertyName("projectDirectory")]
    public string ProjectDirectory { get; init; } = string.Empty;

    [JsonPropertyName("createdAt")]
    public DateTimeOffset CreatedAt { get; init; }

    [JsonPropertyName("lastModifiedAt")]
    public DateTimeOffset LastModifiedAt { get; init; }

    /// <summary>创建新项目文档。</summary>
    public static ProjectDocument Create(string name, string projectDirectory) =>
        new()
        {
            Name = name,
            ProjectDirectory = projectDirectory,
            CreatedAt = DateTimeOffset.UtcNow,
            LastModifiedAt = DateTimeOffset.UtcNow
        };
}
