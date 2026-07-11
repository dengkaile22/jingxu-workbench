namespace JingXu.Workbench.IntegrationTests.Packaging;

internal sealed class PortableArtifactVerificationResult
{
    public List<string> DebugAndTestAssemblies { get; } = [];

    public bool HasExecutable(string relativePath)
    {
        var full = Path.Combine(Root, relativePath.Replace('/', Path.DirectorySeparatorChar));
        return File.Exists(full);
    }

    public bool HasRuntime(string relativePath) => HasExecutable(Path.Combine("runtime", relativePath));

    public required string Root { get; init; }
}

/// <summary>校验便携版目录结构与内容。</summary>
internal static class PortableArtifactVerifier
{
    private static readonly string[] ExcludedAssemblySuffixes =
    [
        ".Tests.dll",
        ".Test.dll",
        "testhost.dll",
        "xunit.",
        "Microsoft.TestPlatform."
    ];

    public static PortableArtifactVerificationResult Verify(string portableRoot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(portableRoot);

        var result = new PortableArtifactVerificationResult { Root = portableRoot };
        if (!Directory.Exists(portableRoot))
        {
            return result;
        }

        foreach (var assembly in Directory.EnumerateFiles(portableRoot, "*.dll", SearchOption.AllDirectories))
        {
            var name = Path.GetFileName(assembly);
            if (name.EndsWith(".pdb", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (ExcludedAssemblySuffixes.Any(suffix =>
                    name.Contains(suffix, StringComparison.OrdinalIgnoreCase)))
            {
                result.DebugAndTestAssemblies.Add(assembly);
                continue;
            }

            if (name.EndsWith(".Tests.dll", StringComparison.OrdinalIgnoreCase)
                || name.EndsWith(".pdb", StringComparison.OrdinalIgnoreCase))
            {
                result.DebugAndTestAssemblies.Add(assembly);
            }
        }

        foreach (var pdb in Directory.EnumerateFiles(portableRoot, "*.pdb", SearchOption.AllDirectories))
        {
            result.DebugAndTestAssemblies.Add(pdb);
        }

        return result;
    }
}
