namespace JingXu.Workbench.IntegrationTests.Packaging;

/// <summary>发布与打包相关路径。</summary>
internal static class BuildPaths
{
    private static readonly Lazy<string> RepoRootLazy = new(ResolveRepoRoot);

    public static string RepoRoot => RepoRootLazy.Value;

    public static string RuntimeManifest => Path.Combine(RepoRoot, "build", "runtime-manifest.json");

    public static string StagedRuntime => Path.Combine(RepoRoot, "artifacts", "staging", "runtime");

    public static string PublishDirectory => Path.Combine(RepoRoot, "artifacts", "publish", "win-x64");

    public static string PortableDirectory => Path.Combine(RepoRoot, "artifacts", "staging", "portable");

    public static string ReleaseDirectory => Path.Combine(RepoRoot, "artifacts", "release");

    public static string PortableZip =>
        Path.Combine(ReleaseDirectory, "JingXu-Workbench-Portable-win-x64.zip");

    public static string SetupExe =>
        Path.Combine(ReleaseDirectory, "JingXu-Workbench-Setup-win-x64.exe");

    public static string Sha256Sums => Path.Combine(ReleaseDirectory, "SHA256SUMS.txt");

    public static string ThirdPartyNotices => Path.Combine(RepoRoot, "THIRD_PARTY_NOTICES.md");

    public static string InstallerProductWxs => Path.Combine(RepoRoot, "build", "Installer", "Product.wxs");

    private static string ResolveRepoRoot()
    {
        var current = new DirectoryInfo(AppContext.BaseDirectory);
        while (current is not null)
        {
            if (File.Exists(Path.Combine(current.FullName, "JingXu.Workbench.sln")))
            {
                return current.FullName;
            }

            current = current.Parent;
        }

        throw new InvalidOperationException("无法定位仓库根目录（缺少 JingXu.Workbench.sln）。");
    }
}
