using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.IntegrationTests.Packaging;

internal sealed record NoticeVerificationResult(
    IReadOnlyList<string> MissingComponents,
    IReadOnlyList<string> MissingSourceLinks);

/// <summary>校验第三方声明文件覆盖清单中的全部组件与来源链接。</summary>
internal static class NoticeVerifier
{
    public static NoticeVerificationResult Verify(string manifestPath, string noticesPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(manifestPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(noticesPath);

        var manifest = RuntimeManifest.LoadFromFile(manifestPath);
        var notices = File.ReadAllText(noticesPath);

        var missingComponents = new List<string>();
        var missingSourceLinks = new List<string>();

        foreach (var component in manifest.Components)
        {
            if (!notices.Contains(component.DisplayName, StringComparison.Ordinal))
            {
                missingComponents.Add(component.DisplayName);
            }

            if (!string.IsNullOrWhiteSpace(component.SourceUrl)
                && !notices.Contains(component.SourceUrl, StringComparison.Ordinal))
            {
                missingSourceLinks.Add($"{component.DisplayName}: {component.SourceUrl}");
            }

            if (!string.IsNullOrWhiteSpace(component.SourceCodeUrl)
                && !notices.Contains(component.SourceCodeUrl, StringComparison.Ordinal))
            {
                missingSourceLinks.Add($"{component.DisplayName}: {component.SourceCodeUrl}");
            }

            if (!string.IsNullOrWhiteSpace(component.LicenseId)
                && !notices.Contains(component.LicenseId, StringComparison.Ordinal))
            {
                missingSourceLinks.Add($"{component.DisplayName}: license {component.LicenseId}");
            }
        }

        return new NoticeVerificationResult(missingComponents, missingSourceLinks);
    }
}
