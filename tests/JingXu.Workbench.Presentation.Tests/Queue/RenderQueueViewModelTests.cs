using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Features.Queue;

namespace JingXu.Workbench.Presentation.Tests.Queue;

public sealed class RenderQueueViewModelTests
{
    [Fact]
    public void Empty_queue_shows_empty_state_and_zero_counts()
    {
        var vm = new RenderQueueViewModel();

        Assert.True(vm.IsEmpty);
        Assert.Equal(0, vm.TotalCount);
        Assert.Equal(0, vm.ActiveCount);
        Assert.Equal(0, vm.FinishedCount);
        Assert.Contains("队列为空", vm.EmptyHint);
    }

    [Fact]
    public async Task Paused_enqueue_keeps_jobs_in_active_scope()
    {
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), new InMemoryRenderQueueStore(), 1);
        coordinator.PauseQueue();
        var vm = new RenderQueueViewModel();
        vm.BindCoordinator(coordinator);

        await coordinator.EnqueueAsync([RenderJob.CreateDraft().Enqueue(), RenderJob.CreateDraft().Enqueue()], default);

        Assert.Equal(2, vm.TotalCount);
        Assert.Equal(2, vm.ActiveCount);
        Assert.Equal(0, vm.FinishedCount);

        vm.Scope = QueueScope.Active;
        Assert.Equal(2, vm.VisibleJobs.Count);
        vm.Scope = QueueScope.Finished;
        Assert.Empty(vm.VisibleJobs);
    }

    [Fact]
    public async Task Completed_jobs_appear_in_finished_scope()
    {
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), new InMemoryRenderQueueStore(), 1);
        var vm = new RenderQueueViewModel();
        vm.BindCoordinator(coordinator);

        await coordinator.EnqueueAsync([RenderJob.CreateDraft().Enqueue(), RenderJob.CreateDraft().Enqueue()], default);
        await WaitUntilAsync(() => vm.FinishedCount == 2, TimeSpan.FromSeconds(5));

        Assert.Equal(0, vm.ActiveCount);
        vm.Scope = QueueScope.Finished;
        Assert.Equal(2, vm.VisibleJobs.Count);
        Assert.All(vm.VisibleJobs, j => Assert.Equal(JobState.Completed, j.State));
    }

    [Fact]
    public async Task Failed_job_increments_failed_count()
    {
        var coordinator = RenderCoordinator.Create(new FailingRenderExecutor(), new InMemoryRenderQueueStore(), 1);
        var vm = new RenderQueueViewModel();
        vm.BindCoordinator(coordinator);

        await coordinator.EnqueueAsync([RenderJob.CreateDraft().Enqueue()], default);
        await WaitUntilAsync(() => vm.FailedCount == 1, TimeSpan.FromSeconds(5));

        Assert.Equal(1, vm.FinishedCount);
        Assert.Contains("失败 1", vm.SummaryText);
    }

    private static async Task WaitUntilAsync(Func<bool> predicate, TimeSpan timeout)
    {
        var deadline = Environment.TickCount64 + (long)timeout.TotalMilliseconds;
        while (Environment.TickCount64 < deadline)
        {
            if (predicate())
            {
                return;
            }

            await Task.Delay(25);
        }

        throw new TimeoutException("等待队列视图模型更新超时。");
    }

    private sealed class FailingRenderExecutor : IRenderExecutor
    {
        public Task<RenderExecutionResult> ExecuteAsync(
            RenderJob job,
            IProgress<RenderProgress>? progress,
            CancellationToken cancellationToken) =>
            Task.FromResult(RenderExecutionResult.Failed("测试失败"));
    }
}
