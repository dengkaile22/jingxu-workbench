using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class RenderDiagnosticStoreTests
{
    [Fact]
    public async Task Concurrent_archives_keep_their_log_paths_while_expired_logs_are_removed()
    {
        using var dir = new TemporaryDirectory();
        var input = dir.File("input.mp4", "input");
        var logs = Path.Combine(dir.Root, ".jingxu-logs");
        for (var index = 0; index < 40; index++)
        {
            var old = Path.Combine(logs, Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(old);
            File.WriteAllText(Path.Combine(old, "render.log"), "expired");
            Directory.SetLastWriteTimeUtc(old, DateTime.UtcNow.AddDays(-10));
        }

        var jobs = Enumerable.Range(0, 12).Select(index =>
        {
            var staging = Path.Combine(dir.Root, "staging-" + index);
            Directory.CreateDirectory(staging);
            File.WriteAllText(Path.Combine(staging, "render.log"), "complete process stderr");
            return (Job: RenderJob.CreateQueued(TestJobs.RequestFor([input], dir.Root)), Staging: staging);
        }).ToArray();
        var paths = await Task.WhenAll(jobs.Select(item => Task.Run(() =>
            RenderDiagnosticStore.Preserve(item.Job, item.Staging, "render failure"))));

        Assert.All(paths, path =>
        {
            Assert.NotNull(path);
            Assert.True(File.Exists(path));
            Assert.Contains("complete process stderr", File.ReadAllText(path), StringComparison.Ordinal);
        });
    }
}
