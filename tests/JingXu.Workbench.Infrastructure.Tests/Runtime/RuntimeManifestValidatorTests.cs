using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Tests.Runtime;

public sealed class RuntimeManifestValidatorTests
{
    [Fact]
    public void Every_required_runtime_has_version_hash_source_and_license()
    {
        var manifest = RuntimeManifest.Load(RuntimeManifestFixtures.Read("runtime-manifest.json"));
        var issues = RuntimeManifestValidator.Validate(manifest);

        Assert.Empty(issues);
        Assert.Contains(manifest.Components, x => x.Kind == RuntimeKind.Ffmpeg);
        Assert.Contains(manifest.Components, x => x.Kind == RuntimeKind.WhisperModel);
    }

    [Fact]
    public void Missing_sha256_is_reported()
    {
        const string json =
            """
            {
              "schemaVersion": 1,
              "components": [
                {
                  "kind": "Ffmpeg",
                  "displayName": "FFmpeg",
                  "relativePath": "ffmpeg/ffmpeg.exe",
                  "required": true,
                  "versionArguments": ["-version"],
                  "licenseId": "GPL-3.0-or-later",
                  "sourceUrl": "https://ffmpeg.org",
                  "sourceCodeUrl": "https://github.com/FFmpeg/FFmpeg"
                }
              ]
            }
            """;

        var manifest = RuntimeManifest.Load(json);
        var issues = RuntimeManifestValidator.Validate(manifest);

        Assert.Contains(issues, x => x.Contains("sha256", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Rooted_relative_path_is_rejected()
    {
        const string json =
            """
            {
              "schemaVersion": 1,
              "components": [
                {
                  "kind": "Ffmpeg",
                  "displayName": "FFmpeg",
                  "relativePath": "C:/ffmpeg/ffmpeg.exe",
                  "required": true,
                  "versionArguments": ["-version"],
                  "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                  "licenseId": "GPL-3.0-or-later",
                  "sourceUrl": "https://ffmpeg.org",
                  "sourceCodeUrl": "https://github.com/FFmpeg/FFmpeg"
                }
              ]
            }
            """;

        var manifest = RuntimeManifest.Load(json);
        var issues = RuntimeManifestValidator.Validate(manifest);

        Assert.Contains(issues, x => x.Contains("relativePath", StringComparison.Ordinal));
    }
}
