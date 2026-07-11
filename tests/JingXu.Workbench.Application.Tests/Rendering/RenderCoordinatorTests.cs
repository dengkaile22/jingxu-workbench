using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Tests.Rendering;

public sealed class RenderCoordinatorTests
{
    [Fact]
    public async Task Never_runs_more_than_configured_concurrency()
    {
        var executor = new GateRenderExecutor();
        var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), maxConcurrency: 2);
        await coordinator.EnqueueAsync(RenderJobs.Create(4), default);
        await executor.WaitUntilStartedAsync(2);
        Assert.Equal(2, executor.MaxObservedConcurrency);
        Assert.Equal(2, executor.StartedCount);
        await coordinator.ShutdownAsync(default);
    }

    [Fact]
    public async Task Failure_is_isolated_and_next_job_starts()
    {
        var executor = new ScriptedRenderExecutor([Outcome.Fail("坏素材"), Outcome.Success()]);
        var result = await RenderCoordinatorTestDriver.RunToIdleAsync(
            executor,
            RenderJobs.Create(2),
            maxConcurrency: 1);
        Assert.Equal(2, result.Count);
        Assert.Contains(result, j => j.State == JobState.Failed);
        Assert.Contains(result, j => j.State == JobState.Completed);
    }

    [Fact]
    public async Task PauseQueue_starts_no_new_jobs()
    {
        var executor = new GateRenderExecutor();
        var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), maxConcurrency: 1);
        coordinator.PauseQueue();
        await coordinator.EnqueueAsync(RenderJobs.Create(2), default);
        await Task.Delay(100);
        Assert.Equal(0, executor.StartedCount);
        coordinator.ResumeQueue();
        await executor.WaitUntilStartedAsync(1);
        Assert.Equal(1, executor.StartedCount);
        await coordinator.ShutdownAsync(default);
    }

    [Fact]
    public async Task CancelJobAsync_affects_only_one_job()
    {
        var executor = new GateRenderExecutor();
        var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), maxConcurrency: 2);
        var jobs = RenderJobs.Create(2);
        await coordinator.EnqueueAsync(jobs, default);
        await executor.WaitUntilStartedAsync(2);
        var targetId = jobs[0].Id;
        await coordinator.CancelJobAsync(targetId, default);
        await Task.Delay(200);
        var afterCancel = coordinator.Jobs;
        Assert.Equal(JobState.Cancelled, afterCancel.Single(j => j.Id == targetId).State);
        Assert.True(afterCancel.Single(j => j.Id == jobs[1].Id).State
            is JobState.Running or JobState.Preparing);
        await coordinator.ShutdownAsync(default);
    }

    [Fact]
    public async Task Store_failure_does_not_publish_fake_state()
    {
        var executor = new ScriptedRenderExecutor([Outcome.Success()]);
        var store = new FailingQueueStore(failAfterPersistCount: 1);
        var coordinator = RenderCoordinator.Create(executor, store, maxConcurrency: 1);
        var job = RenderJobs.Create(1).Single();
        await coordinator.EnqueueAsync([job], default);
        await Task.Delay(300);
        Assert.Equal(JobState.Queued, coordinator.Jobs.Single().State);
        Assert.Equal(2, store.PersistAttempts);
        await coordinator.ShutdownAsync(default);
    }

    [Fact]
    public async Task Max_concurrency_change_applies_after_active_leases_finish()
    {
        var executor = new GateRenderExecutor();
        var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), maxConcurrency: 1);
        await coordinator.EnqueueAsync(RenderJobs.Create(3), default);
        await executor.WaitUntilStartedAsync(1);
        await coordinator.SetMaxConcurrencyAsync(2, default);
        Assert.Equal(1, executor.StartedCount);
        executor.ReleaseOne();
        await executor.WaitUntilStartedAsync(2);
        Assert.Equal(2, executor.MaxObservedConcurrency);
        await coordinator.ShutdownAsync(default);
    }

    [Fact]
    public async Task Shutdown_waits_for_state_persistence()
    {
        var executor = new ScriptedRenderExecutor([Outcome.Success()]);
        var store = new SlowQueueStore(persistDelay: TimeSpan.FromMilliseconds(200));
        var coordinator = RenderCoordinator.Create(executor, store, maxConcurrency: 1);
        await coordinator.EnqueueAsync(RenderJobs.Create(1), default);
        await RenderCoordinatorTestDriver.WaitUntilIdleAsync(coordinator);
        await coordinator.ShutdownAsync(default);
        Assert.True(store.LastPersistCompleted);
    }
}
