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
    public void Msi_installer_sources_exist_and_bundle_sources_are_absent()
    {
        var installerDir = Path.Combine(BuildPaths.RepoRoot, "build", "Installer");
        Assert.True(File.Exists(Path.Combine(installerDir, "Package.wxs")));
        Assert.True(File.Exists(Path.Combine(installerDir, "License.rtf")));
        Assert.True(File.Exists(Path.Combine(installerDir, "JingXu.Workbench.Msi.wixproj")));
        Assert.False(File.Exists(Path.Combine(installerDir, "Bundle.wxs")));
        Assert.False(File.Exists(Path.Combine(installerDir, "JingXu.Workbench.Bundle.wixproj")));
    }

    [Fact]
    public void Installer_shortcuts_use_explicit_user_registry_and_install_path()
    {
        var wix = File.ReadAllText(BuildPaths.InstallerPackageWxs);

        Assert.DoesNotContain("Root=\"HKMU\"", wix, StringComparison.Ordinal);
        Assert.Contains("Root=\"HKCU\"", wix, StringComparison.Ordinal);
        Assert.Contains("Target=\"[INSTALLFOLDER]炳恒快速混剪.exe\"", wix, StringComparison.Ordinal);
        Assert.DoesNotContain("Target=\"[#MainExecutableFile]\"", wix, StringComparison.Ordinal);
    }
}
