using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.IntegrationTests.Packaging;

public sealed class RuntimePackageTests
{
    [Fact]
    public void Staged_runtime_contains_every_manifest_file_with_matching_hash()
    {
        var manifest = RuntimeManifest.Load(File.ReadAllText(BuildPaths.RuntimeManifest));
        var result = RuntimePackageVerifier.Verify(BuildPaths.StagedRuntime, manifest);
        Assert.True(result.IsSuccess, string.Join(Environment.NewLine, result.Issues));
    }

    [Fact]
    public void Notices_cover_every_component_and_source_offer()
    {
        var result = NoticeVerifier.Verify(BuildPaths.RuntimeManifest, BuildPaths.ThirdPartyNotices);
        Assert.Empty(result.MissingComponents);
        Assert.Empty(result.MissingSourceLinks);
    }
}
