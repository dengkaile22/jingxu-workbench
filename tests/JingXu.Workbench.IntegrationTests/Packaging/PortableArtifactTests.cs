namespace JingXu.Workbench.IntegrationTests.Packaging;

public sealed class PortableArtifactTests
{
    [Fact]
    public void Portable_artifact_is_self_contained_and_has_required_runtime_layout()
    {
        var result = PortableArtifactVerifier.Verify(BuildPaths.PortableDirectory);
        Assert.True(result.HasExecutable("炳恒快速混剪.exe"));
        Assert.True(result.HasRuntime("ffmpeg/ffmpeg.exe"));
        Assert.True(result.HasRuntime("ffmpeg/ffprobe.exe"));
        Assert.True(result.HasRuntime("whisper/models/ggml-base.bin"));
        Assert.Empty(result.DebugAndTestAssemblies);
    }

    [Fact]
    public void Msi_package_exists_with_expected_name()
    {
        var repoRoot = BuildPaths.RepoRoot;
        var distMsi = Path.Combine(repoRoot, "dist", "炳恒快速混剪-win-x64.msi");
        var releaseMsi = Path.Combine(repoRoot, "artifacts", "release", "炳恒快速混剪-win-x64.msi");
        var msiPath = File.Exists(distMsi) ? distMsi : releaseMsi;
        Assert.True(File.Exists(msiPath), $"缺少MSI安装包：{msiPath}");
        Assert.Equal("炳恒快速混剪-win-x64.msi", Path.GetFileName(msiPath));
        Assert.False(File.Exists(Path.Combine(BuildPaths.ReleaseDirectory, "JingXu-Workbench-Setup-win-x64.exe")));
    }
}
