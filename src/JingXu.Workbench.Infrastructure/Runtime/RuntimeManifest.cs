using System.Text.Json;
using System.Text.Json.Serialization;

namespace JingXu.Workbench.Infrastructure.Runtime;

/// <summary>运行时清单中的单个组件条目。</summary>
public sealed record RuntimeManifestComponent(
    RuntimeKind Kind,
    string DisplayName,
    string RelativePath,
    bool Required,
    string? Sha256,
    string? LicenseId,
    string? SourceUrl,
    string? SourceCodeUrl,
    IReadOnlyList<string>? VersionArguments = null);

/// <summary>可审计的第三方运行时清单。</summary>
public sealed class RuntimeManifest
{
    private const string PlaceholderSha256 = "0000000000000000000000000000000000000000000000000000000000000000";

    private RuntimeManifest(int schemaVersion, IReadOnlyList<RuntimeManifestComponent> components)
    {
        SchemaVersion = schemaVersion;
        Components = components;
    }

    /// <summary>清单架构版本。</summary>
    public int SchemaVersion { get; }

    /// <summary>全部组件条目。</summary>
    public IReadOnlyList<RuntimeManifestComponent> Components { get; }

    /// <summary>从 JSON 文本加载清单。</summary>
    public static RuntimeManifest Load(string json)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(json);

        var dto = JsonSerializer.Deserialize<RuntimeManifestDto>(json, SerializerOptions)
            ?? throw new InvalidOperationException("运行时清单 JSON 为空。");

        if (dto.Components is null || dto.Components.Count == 0)
        {
            throw new InvalidOperationException("运行时清单未包含任何组件。");
        }

        var components = dto.Components
            .Select(MapComponent)
            .ToArray();

        return new RuntimeManifest(dto.SchemaVersion, components);
    }

    /// <summary>从文件加载清单。</summary>
    public static RuntimeManifest LoadFromFile(string absolutePath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(absolutePath);
        return Load(File.ReadAllText(absolutePath));
    }

    /// <summary>内置默认清单（与 <c>build/runtime-manifest.json</c> 结构一致）。</summary>
    public static RuntimeManifest Default { get; } = CreateBuiltIn();

    private static RuntimeManifest CreateBuiltIn() =>
        new(
            schemaVersion: 1,
            components:
            [
                Component(
                    RuntimeKind.Ffmpeg,
                    "FFmpeg",
                    "ffmpeg/ffmpeg.exe",
                    required: true,
                    ["-version"],
                    "https://ffmpeg.org/download.html",
                    "https://github.com/FFmpeg/FFmpeg",
                    "GPL-3.0-or-later"),
                Component(
                    RuntimeKind.Ffprobe,
                    "FFprobe",
                    "ffmpeg/ffprobe.exe",
                    required: true,
                    ["-version"],
                    "https://ffmpeg.org/download.html",
                    "https://github.com/FFmpeg/FFmpeg",
                    "GPL-3.0-or-later"),
                Component(
                    RuntimeKind.WhisperCli,
                    "Whisper.cpp",
                    "whisper/whisper-cli.exe",
                    required: false,
                    ["--help"],
                    "https://github.com/ggerganov/whisper.cpp/releases",
                    "https://github.com/ggerganov/whisper.cpp",
                    "MIT"),
                Component(
                    RuntimeKind.WhisperModel,
                    "Whisper 多语言 base 模型",
                    "whisper/models/ggml-base.bin",
                    required: false,
                    versionArguments: null,
                    "https://huggingface.co/ggerganov/whisper.cpp",
                    "https://github.com/ggerganov/whisper.cpp",
                    "MIT"),
                Component(
                    RuntimeKind.Tesseract,
                    "Tesseract OCR",
                    "tesseract/tesseract.exe",
                    required: false,
                    ["--version"],
                    "https://github.com/tesseract-ocr/tesseract",
                    "https://github.com/tesseract-ocr/tesseract",
                    "Apache-2.0")
            ]);

    private static RuntimeManifestComponent Component(
        RuntimeKind kind,
        string displayName,
        string relativePath,
        bool required,
        IReadOnlyList<string>? versionArguments,
        string sourceUrl,
        string sourceCodeUrl,
        string licenseId) =>
        new(
            kind,
            displayName,
            relativePath,
            required,
            PlaceholderSha256,
            licenseId,
            sourceUrl,
            sourceCodeUrl,
            versionArguments);

    private static RuntimeManifestComponent MapComponent(RuntimeManifestComponentDto dto)
    {
        if (!Enum.TryParse<RuntimeKind>(dto.Kind, ignoreCase: true, out var kind))
        {
            throw new InvalidOperationException($"未知的运行时种类：{dto.Kind}");
        }

        return new RuntimeManifestComponent(
            kind,
            dto.DisplayName ?? string.Empty,
            dto.RelativePath ?? string.Empty,
            dto.Required,
            dto.Sha256,
            dto.LicenseId,
            dto.SourceUrl,
            dto.SourceCodeUrl,
            dto.VersionArguments);
    }

    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    private sealed class RuntimeManifestDto
    {
        [JsonPropertyName("schemaVersion")]
        public int SchemaVersion { get; set; }

        [JsonPropertyName("components")]
        public List<RuntimeManifestComponentDto>? Components { get; set; }
    }

    private sealed class RuntimeManifestComponentDto
    {
        [JsonPropertyName("kind")]
        public string? Kind { get; set; }

        [JsonPropertyName("displayName")]
        public string? DisplayName { get; set; }

        [JsonPropertyName("relativePath")]
        public string? RelativePath { get; set; }

        [JsonPropertyName("required")]
        public bool Required { get; set; }

        [JsonPropertyName("sha256")]
        public string? Sha256 { get; set; }

        [JsonPropertyName("licenseId")]
        public string? LicenseId { get; set; }

        [JsonPropertyName("sourceUrl")]
        public string? SourceUrl { get; set; }

        [JsonPropertyName("sourceCodeUrl")]
        public string? SourceCodeUrl { get; set; }

        [JsonPropertyName("versionArguments")]
        public List<string>? VersionArguments { get; set; }
    }
}
