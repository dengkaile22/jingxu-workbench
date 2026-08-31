using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Features.Queue;
using JingXu.Workbench.Presentation.Tests.Infrastructure;

namespace JingXu.Workbench.Presentation.Tests.Queue;

public sealed class RenderQueueViewModelTests
{
    [Fact]
    public void Empty_queue_shows_empty_state_and_zero_counts()
    {
        var vm = new RenderQueueViewModel(new DirectUiDispatcher());

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
        var vm = new RenderQueueViewModel(new DirectUiDispatcher());
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
        var vm = new RenderQueueViewModel(new DirectUiDispatcher());
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
        var vm = new RenderQueueViewModel(new DirectUiDispatcher());
        vm.BindCoordinator(coordinator);

        await coordinator.EnqueueAsync([RenderJob.CreateDraft().Enqueue()], default);
        await WaitUntilAsync(() => vm.FailedCount == 1, TimeSpan.FromSeconds(5));

        Assert.Equal(1, vm.FinishedCount);
        Assert.Contains("失败 1", vm.SummaryText);
    }

    [Fact]
    public async Task Progress_updates_reuse_row_viewmodels_by_id()
    {
        var store = new InMemoryRenderQueueStore();
        var executor = new SlowProgressRenderExecutor();
        var coordinator = RenderCoordinator.Create(executor, store, maxConcurrency: 1);
        var vm = new RenderQueueViewModel(new DirectUiDispatcher());
        vm.BindCoordinator(coordinator);

        await coordinator.EnqueueAsync([RenderJob.CreateDraft().Enqueue()], default);
        await WaitUntilAsync(() => vm.Jobs.Count == 1, TimeSpan.FromSeconds(2));
        var row = vm.Jobs[0];

        await WaitUntilAsync(() => row.ProgressPercent >= 10, TimeSpan.FromSeconds(5));
        Assert.Same(row, vm.Jobs[0]);
        Assert.Same(row, vm.VisibleJobs[0]);

        await WaitUntilAsync(() => vm.FinishedCount == 1, TimeSpan.FromSeconds(5));
        Assert.Same(row, vm.Jobs[0]);
        Assert.Equal(JobState.Completed, row.State);
    }

    [Fact]
    public void Row_apply_refreshes_progress_for_same_id()
    {
        var job = RenderJob.CreateQueued().BeginPrepare().BeginRun().WithProgress(12, "渲染中 12%");
        var row = new RenderJobRowViewModel(job, "任务 1");
        row.Apply(job.WithProgress(48, "渲染中 48%"), "任务 1");

        Assert.Equal(48, row.ProgressPercent);
        Assert.Equal("渲染中 48%", row.ProgressText);
        Assert.Equal(job.Id, row.JobId);
    }

    [Fact]
    public void Completed_job_displays_processor_or_fallback_notice()
    {
        var completed = RenderJob.CreateQueued()
            .BeginPrepare()
            .BeginRun()
            .BeginFinalize()
            .Complete() with
        {
            Notice = "GPU 编码不可用，已自动改用 CPU 完成。"
        };
        var row = new RenderJobRowViewModel(completed, "成片");

        Assert.Equal(completed.Notice, row.ProgressText);
    }

    [Fact]
    public async Task Clear_finished_reuses_remaining_active_row()
    {
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), new InMemoryRenderQueueStore(), 1);
        var vm = new RenderQueueViewModel(new DirectUiDispatcher());
        vm.BindCoordinator(coordinator);

        await coordinator.EnqueueAsync([RenderJob.CreateDraft().Enqueue()], default);
        await WaitUntilAsync(() => vm.FinishedCount == 1, TimeSpan.FromSeconds(5));
        coordinator.PauseQueue();
        var active = RenderJob.CreateDraft().Enqueue();
        await coordinator.EnqueueAsync([active], default);
        Assert.Equal(2, vm.TotalCount);
        var activeRow = vm.Jobs.Single(j => j.JobId == active.Id);

        await coordinator.ClearFinishedJobsAsync(default);
        Assert.Single(vm.Jobs);
        Assert.Same(activeRow, vm.Jobs[0]);
        Assert.Equal(active.Id, vm.Jobs[0].JobId);
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

    private sealed class SlowProgressRenderExecutor : IRenderExecutor
    {
        public async Task<RenderExecutionResult> ExecuteAsync(
            RenderJob job,
            IProgress<RenderProgress>? progress,
            CancellationToken cancellationToken)
        {
            progress?.Report(new RenderProgress(TimeSpan.FromSeconds(1), 1.0, 15));
            await Task.Delay(40, cancellationToken);
            progress?.Report(new RenderProgress(TimeSpan.FromSeconds(2), 1.0, 55));
            await Task.Delay(40, cancellationToken);
            return RenderExecutionResult.Success();
        }
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
