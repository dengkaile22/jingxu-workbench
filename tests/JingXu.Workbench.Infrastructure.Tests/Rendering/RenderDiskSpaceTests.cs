using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;
using JingXu.Workbench.Infrastructure.Runtime;
using JingXu.Workbench.Infrastructure.Tests.Runtime;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class RenderDiskSpaceTests
{
    private static readonly string[] TestVolumes = ["C:\\", "D:\\"];
    [Fact]
    public async Task Different_volumes_can_release_reservations_during_other_volume_acquisition()
    {
        using var dir = new TemporaryDirectory();
        var registry = Path.Combine(dir.Root, "reservations");
        await Task.WhenAll(TestVolumes.Select(volume => Task.Run(() =>
        {
            var manager = new RenderDiskSpaceReservations(registry);
            for (var index = 0; index < 80; index++)
            {
                // 只登记预算，不在这些路径写文件；两个卷的登记共享同一临时注册表。
                using var reservation = manager.Acquire(volume + "jingxu-budget-test-" + Guid.NewGuid().ToString("N") + ".tmp",
                    80, _ => 10_000);
            }
        })));
        Assert.Empty(Directory.GetFiles(registry, "*.json"));
    }

    [Fact]
    public void Copy_budget_is_shared_and_actual_written_bytes_are_not_counted_twice()
    {
        using var dir = new TemporaryDirectory();
        var registry = Path.Combine(dir.Root, "reservations");
        var available = 200L;
        using var first = new RenderDiskSpaceReservations(registry)
            .Acquire(Path.Combine(dir.Root, "first.tmp"), 40, _ => available);
        var alias = Path.Combine(dir.Root, "copied.mp4");
        first.ReserveCopy(alias, 80);
        Assert.Throws<IOException>(() => first.ReserveCopy(Path.Combine(dir.Root, "too-large.mp4"), 80));
        File.WriteAllBytes(alias, new byte[80]);
        available -= 80;

        // 第二个管理器代表另一实例：磁盘已扣除写入的80字节，不能再从预算扣一遍。
        using var second = new RenderDiskSpaceReservations(registry)
            .Acquire(Path.Combine(dir.Root, "second.tmp"), 40, _ => available);
        Assert.Equal(2, Directory.GetFiles(registry, "*.json").Length);
    }

    [Fact]
    public async Task Concurrent_jobs_do_not_overbook_the_same_output_volume()
    {
        using var dir = new TemporaryDirectory();
        var input = dir.File("input.mp4", "input");
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new PausedFirstRenderRunner();
        var executor = new FfmpegRenderExecutor(runner, new FixedProbe(TimeSpan.FromSeconds(2)),
            new RuntimeResolver(layout.AppRoot, layout.PathLookup), availableDiskBytes: _ => 4_000_000,
            diskReservations: new RenderDiskSpaceReservations(Path.Combine(dir.Root, "reservations")));
        var request = TestJobs.RequestFor([input], dir.Root) with { ProcessingMode = VideoProcessingMode.Cpu };
        var first = executor.ExecuteAsync(RenderJob.CreateQueued(request with { OutputPath = Path.Combine(dir.Root, "one.mp4") }), null, default);
        try
        {
            await runner.Started.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var second = await executor.ExecuteAsync(
                RenderJob.CreateQueued(request with { OutputPath = Path.Combine(dir.Root, "two.mp4") }), null, default);
            Assert.False(second.IsSuccess, "两个任务不能各自按同一份可用空间通过预检。");
            Assert.Contains("磁盘", second.FailureInfo!.Message, StringComparison.Ordinal);
        }
        finally
        {
            runner.Finish.TrySetResult();
            await first.WaitAsync(TimeSpan.FromSeconds(5));
        }

        var third = await executor.ExecuteAsync(
            RenderJob.CreateQueued(request with { OutputPath = Path.Combine(dir.Root, "three.mp4") }), null, default);
        Assert.True(third.IsSuccess, third.FailureInfo?.Message);
    }

    private sealed class PausedFirstRenderRunner : IExternalProcessRunner
    {
        private int _calls;
        public TaskCompletionSource Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Finish { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public async Task<IProcessResult> RunAsync(IProcessRequest request, IProgress<string>? progress, CancellationToken cancellationToken)
        {
            var directory = request.WorkingDirectory!;
            Directory.CreateDirectory(directory);
            if (Interlocked.Increment(ref _calls) == 1)
            {
                Started.TrySetResult();
                await Finish.Task.WaitAsync(cancellationToken);
            }

            await File.WriteAllTextAsync(Path.Combine(directory, "output.mp4"), "finished", cancellationToken);
            return new ProcessResult(0, string.Empty, string.Empty);
        }
    }
}
