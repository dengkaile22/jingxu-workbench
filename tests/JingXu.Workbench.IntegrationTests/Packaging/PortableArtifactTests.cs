namespace JingXu.Workbench.IntegrationTests.Packaging;

public sealed class PortableArtifactTests
{
    [Fact]
    public void Portable_artifact_is_self_contained_and_has_required_runtime_layout()
    {
        var result = PortableArtifactVerifier.Verify(BuildPaths.PortableDirectory);
        Assert.True(result.HasExecutable("JingXu.Workbench.exe"));
        Assert.True(result.HasRuntime("ffmpeg/ffmpeg.exe"));
        Assert.True(result.HasRuntime("ffmpeg/ffprobe.exe"));
        Assert.True(result.HasRuntime("whisper/models/ggml-base.bin"));
        Assert.Empty(result.DebugAndTestAssemblies);
    }

    [Fact]
    public void Portable_zip_exists_with_expected_name()
    {
        Assert.True(File.Exists(BuildPaths.PortableZip), $"缺少便携版压缩包：{BuildPaths.PortableZip}");
        Assert.Equal("JingXu-Workbench-Portable-win-x64.zip", Path.GetFileName(BuildPaths.PortableZip));
    }
}
