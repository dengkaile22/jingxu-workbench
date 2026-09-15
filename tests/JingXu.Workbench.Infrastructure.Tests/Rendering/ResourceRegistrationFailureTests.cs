using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Tests.Runtime;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

[CollectionDefinition("Resource environment", DisableParallelization = true)]
public sealed class ResourceEnvironmentFixture;

[Collection("Resource environment")]
public sealed class ResourceRegistrationFailureTests
{
    [Fact]
    public async Task Unwritable_registry_reports_frame_error_without_deleting_previous_preview()
    {
        using var dir = new TemporaryDirectory();
        var blockedRoot = dir.File("blocked-registry", "blocked");
        var previous = Environment.GetEnvironmentVariable("JINGXU_DATA_DIRECTORY");
        Environment.SetEnvironmentVariable("JINGXU_DATA_DIRECTORY", blockedRoot);
        try
        {
            var input = dir.File("input.mp4", "input");
            var preview = dir.File("preview.jpg", "previous-preview");
            using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
            var extractor = new JingXu.Workbench.Infrastructure.Media.FfmpegMediaFrameExtractor(
                new FakeProcessRunner(0), new JingXu.Workbench.Infrastructure.Runtime.RuntimeResolver(layout.AppRoot, layout.PathLookup));
            var result = await extractor.ExtractFirstFrameAsync(input, preview, default);
            Assert.False(result.IsSuccess);
            Assert.Equal("previous-preview", File.ReadAllText(preview));
        }
        finally { Environment.SetEnvironmentVariable("JINGXU_DATA_DIRECTORY", previous); }
    }

    [Fact]
    public async Task Unwritable_resource_registry_returns_failure_instead_of_throwing()
    {
        using var dir = new TemporaryDirectory();
        var blockedRoot = dir.File("not-a-directory", "blocked");
        var previous = Environment.GetEnvironmentVariable("JINGXU_DATA_DIRECTORY");
        Environment.SetEnvironmentVariable("JINGXU_DATA_DIRECTORY", blockedRoot);
        try
        {
            var input = dir.File("input.mp4", "input");
            using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
            var executor = RenderExecutorFactory.Create(layout, new FakeProcessRunner(0));
            var result = await executor.ExecuteAsync(RenderJob.CreateQueued(TestJobs.RequestFor([input], dir.Root)), null, default);
            Assert.False(result.IsSuccess);
            Assert.NotNull(result.FailureInfo);
        }
        finally { Environment.SetEnvironmentVariable("JINGXU_DATA_DIRECTORY", previous); }
    }
}
