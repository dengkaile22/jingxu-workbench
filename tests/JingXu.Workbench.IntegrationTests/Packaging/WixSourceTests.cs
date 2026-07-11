namespace JingXu.Workbench.IntegrationTests.Packaging;

public sealed class WixSourceTests
{
    [Fact]
    public void Installer_never_manages_user_project_or_output_directories()
    {
        var wix = File.ReadAllText(BuildPaths.InstallerProductWxs);
        Assert.DoesNotContain("分镜输出", wix);
        Assert.DoesNotContain("DocumentsFolder", wix);
        Assert.Contains("MajorUpgrade", wix);
    }

    [Fact]
    public void Installer_sources_exist()
    {
        var installerDir = Path.Combine(BuildPaths.RepoRoot, "build", "Installer");
        Assert.True(File.Exists(Path.Combine(installerDir, "Package.wxs")));
        Assert.True(File.Exists(Path.Combine(installerDir, "Bundle.wxs")));
        Assert.True(File.Exists(Path.Combine(installerDir, "License.rtf")));
        Assert.True(File.Exists(Path.Combine(installerDir, "JingXu.Workbench.Msi.wixproj")));
        Assert.True(File.Exists(Path.Combine(installerDir, "JingXu.Workbench.Bundle.wixproj")));
    }
}
