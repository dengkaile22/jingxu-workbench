using System.Security.Cryptography;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.IntegrationTests.Packaging;

internal sealed record RuntimePackageVerificationResult(bool IsSuccess, IReadOnlyList<string> Issues);

/// <summary>校验已 staging 的运行时目录与清单一致。</summary>
internal static class RuntimePackageVerifier
{
    private const string PlaceholderSha256 = "0000000000000000000000000000000000000000000000000000000000000000";

    public static RuntimePackageVerificationResult Verify(string stagedRuntimeRoot, RuntimeManifest manifest)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(stagedRuntimeRoot);
        ArgumentNullException.ThrowIfNull(manifest);

        var issues = new List<string>();

        if (!Directory.Exists(stagedRuntimeRoot))
        {
            issues.Add($"运行时 staging 目录不存在：{stagedRuntimeRoot}");
            return new RuntimePackageVerificationResult(false, issues);
        }

        foreach (var component in manifest.Components)
        {
            var destination = Path.Combine(stagedRuntimeRoot, component.RelativePath.Replace('/', Path.DirectorySeparatorChar));
            if (!File.Exists(destination))
            {
                issues.Add($"{component.DisplayName}：缺少文件 {component.RelativePath}");
                continue;
            }

            if (string.IsNullOrWhiteSpace(component.Sha256))
            {
                issues.Add($"{component.DisplayName}：清单缺少 sha256。");
                continue;
            }

            if (string.Equals(component.Sha256, PlaceholderSha256, StringComparison.OrdinalIgnoreCase))
            {
                issues.Add($"{component.DisplayName}：清单仍使用占位 sha256，发布前必须更新为固定哈希。");
                continue;
            }

            var actual = ComputeSha256(destination);
            if (!string.Equals(actual, component.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                issues.Add($"{component.DisplayName}：哈希不匹配。期望 {component.Sha256}，实际 {actual}");
            }
        }

        return new RuntimePackageVerificationResult(issues.Count == 0, issues);
    }

    private static string ComputeSha256(string filePath)
    {
        using var stream = File.OpenRead(filePath);
        var hash = SHA256.HashData(stream);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
