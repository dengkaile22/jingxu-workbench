using System.Text.RegularExpressions;

namespace JingXu.Workbench.Infrastructure.Runtime;

/// <summary>校验运行时清单条目的完整性。</summary>
public static partial class RuntimeManifestValidator
{
    /// <summary>校验清单并返回中文问题列表；空列表表示通过。</summary>
    public static IReadOnlyList<string> Validate(RuntimeManifest manifest)
    {
        ArgumentNullException.ThrowIfNull(manifest);

        var issues = new List<string>();

        if (manifest.SchemaVersion < 1)
        {
            issues.Add("清单 schemaVersion 必须大于等于 1。");
        }

        foreach (var component in manifest.Components)
        {
            issues.AddRange(ValidateComponent(component));
        }

        return issues;
    }

    private static IEnumerable<string> ValidateComponent(RuntimeManifestComponent component)
    {
        var label = string.IsNullOrWhiteSpace(component.DisplayName)
            ? component.Kind.ToString()
            : component.DisplayName;

        if (string.IsNullOrWhiteSpace(component.DisplayName))
        {
            yield return $"{label}：缺少 displayName。";
        }

        if (string.IsNullOrWhiteSpace(component.RelativePath))
        {
            yield return $"{label}：缺少 relativePath。";
        }
        else if (Path.IsPathRooted(component.RelativePath))
        {
            yield return $"{label}：relativePath 必须是相对 runtime/ 的路径。";
        }

        if (string.IsNullOrWhiteSpace(component.Sha256))
        {
            yield return $"{label}：缺少 sha256。";
        }
        else if (!Sha256Pattern().IsMatch(component.Sha256))
        {
            yield return $"{label}：sha256 格式无效。";
        }

        if (string.IsNullOrWhiteSpace(component.LicenseId))
        {
            yield return $"{label}：缺少 licenseId。";
        }

        if (string.IsNullOrWhiteSpace(component.SourceUrl))
        {
            yield return $"{label}：缺少 sourceUrl。";
        }

        if (component.Kind is RuntimeKind.Ffmpeg or RuntimeKind.Ffprobe or RuntimeKind.WhisperCli
            && string.IsNullOrWhiteSpace(component.SourceCodeUrl))
        {
            yield return $"{label}：可执行组件必须提供 sourceCodeUrl。";
        }

        if (component.Kind is RuntimeKind.Ffmpeg or RuntimeKind.Ffprobe or RuntimeKind.WhisperCli
            or RuntimeKind.Tesseract)
        {
            if (component.VersionArguments is null || component.VersionArguments.Count == 0)
            {
                yield return $"{label}：可执行组件必须提供 versionArguments。";
            }
        }
    }

    [GeneratedRegex("^[0-9a-fA-F]{64}$", RegexOptions.Compiled)]
    private static partial Regex Sha256Pattern();
}
