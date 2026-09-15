using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Tests.Rendering;

public sealed class RenderResourceSchedulingTests
{
    [Fact]
    public async Task High_resolution_four_screen_jobs_run_one_at_a_time_even_with_four_slots()
    {
        var executor = new GateRenderExecutor();
        await using var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), 4);
        await coordinator.EnqueueAsync([FourScreenJob(1080, 1440), FourScreenJob(1080, 1440)], default);
        await executor.WaitUntilStartedAsync(1);
        await Task.Delay(100);
        Assert.Equal(1, executor.StartedCount);
        Assert.Equal(4, coordinator.MaxConcurrency);

        executor.ReleaseOne();
        await executor.WaitUntilStartedAsync(2);
        Assert.Equal(1, executor.MaxObservedConcurrency);
        executor.ReleaseOne();
        await RenderCoordinatorTestDriver.WaitUntilIdleAsync(coordinator);
    }

    [Fact]
    public async Task Heavy_job_waits_for_existing_work_and_preserves_queue_order()
    {
        var executor = new GateRenderExecutor();
        await using var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), 4);
        var ordinary = RenderJobs.Create(1)[0];
        var heavy = FourScreenJob(1920, 1080);
        var next = RenderJobs.Create(1)[0];
        await coordinator.EnqueueAsync([ordinary, heavy, next], default);
        await executor.WaitUntilStartedAsync(1);
        await Task.Delay(100);
        Assert.Equal(JobState.Queued, coordinator.Jobs.Single(job => job.Id == heavy.Id).State);
        Assert.Equal(JobState.Queued, coordinator.Jobs.Single(job => job.Id == next.Id).State);

        executor.ReleaseOne();
        await executor.WaitUntilStartedAsync(2);
        await Task.Delay(100);
        Assert.Equal(2, executor.StartedCount);
        Assert.Equal(JobState.Queued, coordinator.Jobs.Single(job => job.Id == next.Id).State);
        executor.ReleaseOne();
        await executor.WaitUntilStartedAsync(3);
        Assert.Equal(1, executor.MaxObservedConcurrency);
    }

    [Fact]
    public async Task Cancelling_exclusive_job_releases_slots_for_ordinary_work()
    {
        var executor = new GateRenderExecutor();
        await using var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), 2);
        var heavy = FourScreenJob(1080, 1920);
        await coordinator.EnqueueAsync([heavy, .. RenderJobs.Create(2)], default);
        await executor.WaitUntilStartedAsync(1);
        await coordinator.CancelJobAsync(heavy.Id, default);
        await executor.WaitUntilStartedAsync(3);

        Assert.Equal(JobState.Cancelled, coordinator.Jobs.Single(job => job.Id == heavy.Id).State);
        Assert.Equal(2, executor.MaxObservedConcurrency);
    }

    [Fact]
    public async Task Small_four_screen_jobs_keep_configured_parallelism()
    {
        var executor = new GateRenderExecutor();
        await using var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), 2);
        await coordinator.EnqueueAsync([FourScreenJob(320, 240), FourScreenJob(320, 240)], default);
        await executor.WaitUntilStartedAsync(2);
        Assert.Equal(2, executor.MaxObservedConcurrency);
    }

    [Theory]
    [InlineData(320, 240, OutputResolutionPreset.P1080, 1)]
    [InlineData(1080, 1440, OutputResolutionPreset.P480, 2)]
    public async Task Resource_guard_uses_the_actual_four_screen_render_dimensions(
        int width, int height, OutputResolutionPreset resolution, int expectedStarts)
    {
        var executor = new GateRenderExecutor();
        await using var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), 2);
        var original = FourScreenJob(width, height).Request!;
        var request = original with { OutputVideoSettings = new OutputVideoSettings(resolution) };
        await coordinator.EnqueueAsync([RenderJob.CreateQueued(request), RenderJob.CreateQueued(request)], default);
        await executor.WaitUntilStartedAsync(1);
        await Task.Delay(100);
        Assert.Equal(expectedStarts, executor.StartedCount);
    }

    [Fact]
    public async Task Cancelling_a_reserved_job_before_dispatch_does_not_stall_the_next_job()
    {
        var executor = new GateRenderExecutor();
        var store = new InMemoryQueueStore();
        var heavy = FourScreenJob(1080, 1440);
        await store.PersistAsync([heavy, .. RenderJobs.Create(1)], default);
        await using var coordinator = RenderCoordinator.Create(executor, store, 2);
        // 固定在预留槽位和 Task.Run 启动之间取消，避免靠线程池调度概率触发竞态。
        var binding = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
        object?[] reserved = [null];
        var reserve = typeof(RenderCoordinator).GetMethod("TryReserveQueuedJob", binding)!;
        Assert.True((bool)reserve.Invoke(coordinator, reserved)!);
        await coordinator.CancelJobAsync(heavy.Id, default);
        var dispatch = typeof(RenderCoordinator).GetMethod("ProcessJobAsync", binding)!;
        await (Task)dispatch.Invoke(coordinator, [reserved[0]])!;
        await executor.WaitUntilStartedAsync(1);
        Assert.Equal(JobState.Cancelled, coordinator.Jobs.Single(job => job.Id == heavy.Id).State);
    }

    [Fact]
    public async Task Progress_reports_real_render_speed_alongside_percentage()
    {
        var executor = new ProgressExecutor();
        await using var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), 1);
        await coordinator.EnqueueAsync(RenderJobs.Create(1), default);
        await executor.Reported.Task.WaitAsync(TimeSpan.FromSeconds(5));

        Assert.Contains("0.1×", coordinator.Jobs.Single().ProgressPhase, StringComparison.Ordinal);
        Assert.Equal(10, coordinator.Jobs.Single().ProgressPercent);
        executor.Release.TrySetResult();
        await RenderCoordinatorTestDriver.WaitUntilIdleAsync(coordinator);
    }

    private static RenderJob FourScreenJob(int width, int height)
    {
        var asset = new MediaAsset(Guid.NewGuid(), "four.mp4", 1,
            new MediaInfo(TimeSpan.FromSeconds(2), width, height, 30m, "h264", "aac", true, 0));
        var plan = new CompositionPlan([new PlannedClip(asset, TimeSpan.Zero, asset.Info.Duration)],
            asset.Info.Duration, 0, TimeSpan.Zero);
        var request = new RenderRequest(plan, "out.mp4", RenderProfile.Balanced, OutputAspect.InheritFirst,
            [], HasEffects: true, FourScreen: new FourScreenEffectPlan(1));
        return RenderJob.CreateQueued(request);
    }

    private sealed class ProgressExecutor : IRenderExecutor
    {
        public TaskCompletionSource Reported { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public async Task<RenderExecutionResult> ExecuteAsync(RenderJob job, IProgress<RenderProgress>? progress,
            CancellationToken cancellationToken)
        {
            progress?.Report(new RenderProgress(TimeSpan.FromSeconds(1), .1, 10));
            Reported.TrySetResult();
            await Release.Task.WaitAsync(cancellationToken);
            return RenderExecutionResult.Success();
        }
    }
}
