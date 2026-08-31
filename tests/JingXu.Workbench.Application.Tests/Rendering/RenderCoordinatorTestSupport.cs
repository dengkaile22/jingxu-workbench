using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Tests.Rendering;

internal static class RenderJobs
{
    public static IReadOnlyList<RenderJob> Create(int count) =>
        Enumerable.Range(0, count)
            .Select(_ => RenderJob.CreateDraft().Enqueue())
            .ToList();

    public static RenderJob WithState(JobState state) => RenderJob.WithState(state);
}

internal sealed record Outcome(bool IsSuccess, string? Error)
{
    public static Outcome Success() => new(true, null);
    public static Outcome Fail(string error) => new(false, error);
}

internal sealed class GateRenderExecutor : IRenderExecutor
{
    private readonly object _sync = new();
    private int _running;
    private int _started;
    private readonly List<TaskCompletionSource> _releaseGates = [];

    public int MaxObservedConcurrency { get; private set; }
    public int StartedCount => _started;

    public async Task<RenderExecutionResult> ExecuteAsync(
        RenderJob job,
        IProgress<RenderProgress>? progress,
        CancellationToken cancellationToken)
    {
        TaskCompletionSource release;
        lock (_sync)
        {
            _started++;
            var current = Interlocked.Increment(ref _running);
            MaxObservedConcurrency = Math.Max(MaxObservedConcurrency, current);
            release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            _releaseGates.Add(release);
        }

        try
        {
            using var registration = cancellationToken.Register(() => release.TrySetResult());
            await release.Task.ConfigureAwait(false);
            return RenderExecutionResult.Success();
        }
        catch (OperationCanceledException)
        {
            return RenderExecutionResult.Cancelled();
        }
        finally
        {
            Interlocked.Decrement(ref _running);
        }
    }

    public Task WaitUntilStartedAsync(int count)
    {
        var deadline = Environment.TickCount64 + 5_000;
        while (Environment.TickCount64 < deadline)
        {
            if (StartedCount >= count)
            {
                return Task.CompletedTask;
            }

            Thread.Sleep(10);
        }

        throw new TimeoutException($"等待 {count} 个任务启动超时，当前已启动 {StartedCount} 个。");
    }

    public void ReleaseOne()
    {
        TaskCompletionSource? gate;
        lock (_sync)
        {
            gate = _releaseGates.FirstOrDefault(g => !g.Task.IsCompleted);
        }

        gate?.TrySetResult();
    }
}

internal sealed class ScriptedRenderExecutor : IRenderExecutor
{
    private readonly Queue<Outcome> _outcomes;
    private readonly object _sync = new();

    public ScriptedRenderExecutor(IEnumerable<Outcome> outcomes) =>
        _outcomes = new Queue<Outcome>(outcomes);

    public Task<RenderExecutionResult> ExecuteAsync(
        RenderJob job,
        IProgress<RenderProgress>? progress,
        CancellationToken cancellationToken)
    {
        Outcome outcome;
        lock (_sync)
        {
            if (_outcomes.Count == 0)
            {
                throw new InvalidOperationException("脚本化执行器没有更多预设结果。");
            }

            outcome = _outcomes.Dequeue();
        }

        if (cancellationToken.IsCancellationRequested)
        {
            return Task.FromResult(RenderExecutionResult.Cancelled());
        }

        return Task.FromResult(outcome.IsSuccess
            ? RenderExecutionResult.Success()
            : RenderExecutionResult.Failed(outcome.Error!));
    }
}

internal sealed class BurstyProgressRenderExecutor(int reportCount) : IRenderExecutor
{
    private readonly TaskCompletionSource _reportsIssued =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly TaskCompletionSource _release =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    public async Task<RenderExecutionResult> ExecuteAsync(
        RenderJob job,
        IProgress<RenderProgress>? progress,
        CancellationToken cancellationToken)
    {
        for (var index = 0; index < reportCount; index++)
        {
            var percent = index / 10.0;
            progress?.Report(new RenderProgress(TimeSpan.FromMilliseconds(index), 1.0, percent));
        }

        _reportsIssued.TrySetResult();
        using var registration = cancellationToken.Register(() => _release.TrySetCanceled(cancellationToken));
        try
        {
            await _release.Task.ConfigureAwait(false);
            return RenderExecutionResult.Success();
        }
        catch (OperationCanceledException)
        {
            return RenderExecutionResult.Cancelled();
        }
    }

    public async Task WaitUntilReportsIssuedAsync() =>
        await _reportsIssued.Task.WaitAsync(TimeSpan.FromSeconds(5));

    public void Release() => _release.TrySetResult();
}

internal sealed class NoticeRenderExecutor(string notice) : IRenderExecutor
{
    public Task<RenderExecutionResult> ExecuteAsync(
        RenderJob job,
        IProgress<RenderProgress>? progress,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(RenderExecutionResult.Success(notice));
    }
}

internal sealed class CountingImmediateRenderExecutor : IRenderExecutor
{
    private int _startedCount;

    public int StartedCount => Volatile.Read(ref _startedCount);

    public Task<RenderExecutionResult> ExecuteAsync(
        RenderJob job,
        IProgress<RenderProgress>? progress,
        CancellationToken cancellationToken)
    {
        Interlocked.Increment(ref _startedCount);
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(RenderExecutionResult.Success());
    }
}

internal sealed class OutOfOrderQueueStore : IRenderQueueStore
{
    private readonly object _sync = new();
    private readonly TaskCompletionSource _firstTransitionEntered =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly TaskCompletionSource _releaseFirstTransition =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private IReadOnlyList<RenderJob> _jobs = [];
    private int _persistCount;

    public IReadOnlyList<RenderJob> Jobs => _jobs;

    public async Task PersistAsync(IReadOnlyList<RenderJob> jobs, CancellationToken cancellationToken)
    {
        var persistNumber = Interlocked.Increment(ref _persistCount);
        if (persistNumber == 2)
        {
            _firstTransitionEntered.TrySetResult();
            await _releaseFirstTransition.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
        }

        lock (_sync)
        {
            _jobs = jobs.ToList();
        }
    }

    public async Task WaitUntilFirstTransitionAsync() =>
        await _firstTransitionEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));

    public void ReleaseFirstTransition() => _releaseFirstTransition.TrySetResult();
}

internal sealed class InMemoryQueueStore : IRenderQueueStore
{
    private IReadOnlyList<RenderJob> _jobs = [];

    public IReadOnlyList<RenderJob> Jobs => _jobs;

    public Task PersistAsync(IReadOnlyList<RenderJob> jobs, CancellationToken cancellationToken)
    {
        _jobs = jobs.ToList();
        return Task.CompletedTask;
    }
}

internal sealed class FailingQueueStore : IRenderQueueStore
{
    private readonly int _failAfterPersistCount;
    private IReadOnlyList<RenderJob> _jobs = [];

    public FailingQueueStore(int failAfterPersistCount) =>
        _failAfterPersistCount = failAfterPersistCount;

    public int PersistAttempts { get; private set; }

    public IReadOnlyList<RenderJob> Jobs => _jobs;

    public Task PersistAsync(IReadOnlyList<RenderJob> jobs, CancellationToken cancellationToken)
    {
        PersistAttempts++;
        if (PersistAttempts > _failAfterPersistCount)
        {
            throw new IOException("模拟队列持久化失败。");
        }

        _jobs = jobs.ToList();
        return Task.CompletedTask;
    }
}

internal sealed class SlowQueueStore : IRenderQueueStore
{
    private readonly TimeSpan _persistDelay;
    private IReadOnlyList<RenderJob> _jobs = [];

    public SlowQueueStore(TimeSpan persistDelay) => _persistDelay = persistDelay;

    public bool LastPersistCompleted { get; private set; }

    public IReadOnlyList<RenderJob> Jobs => _jobs;

    public async Task PersistAsync(IReadOnlyList<RenderJob> jobs, CancellationToken cancellationToken)
    {
        await Task.Delay(_persistDelay, cancellationToken).ConfigureAwait(false);
        _jobs = jobs.ToList();
        LastPersistCompleted = true;
    }
}

internal sealed class CountingSlowQueueStore(TimeSpan persistDelay) : IRenderQueueStore
{
    private IReadOnlyList<RenderJob> _jobs = [];
    private int _persistCount;

    public IReadOnlyList<RenderJob> Jobs => _jobs;

    public int PersistCount => Volatile.Read(ref _persistCount);

    public async Task PersistAsync(IReadOnlyList<RenderJob> jobs, CancellationToken cancellationToken)
    {
        await Task.Delay(persistDelay, cancellationToken).ConfigureAwait(false);
        _jobs = jobs.ToList();
        Interlocked.Increment(ref _persistCount);
    }
}

internal static class RenderCoordinatorTestDriver
{
    public static async Task<IReadOnlyList<RenderJob>> RunToIdleAsync(
        IRenderExecutor executor,
        IReadOnlyList<RenderJob> jobs,
        int maxConcurrency = 2)
    {
        var coordinator = RenderCoordinator.Create(executor, new InMemoryQueueStore(), maxConcurrency);
        await coordinator.EnqueueAsync(jobs, default).ConfigureAwait(false);
        await WaitUntilIdleAsync(coordinator).ConfigureAwait(false);
        await coordinator.ShutdownAsync(default).ConfigureAwait(false);
        return coordinator.Jobs;
    }

    public static async Task WaitUntilIdleAsync(RenderCoordinator coordinator)
    {
        var deadline = Environment.TickCount64 + 5_000;
        while (Environment.TickCount64 < deadline)
        {
            if (coordinator.Jobs.All(j => j.State is JobState.Completed or JobState.Failed or JobState.Cancelled))
            {
                return;
            }

            await Task.Delay(20).ConfigureAwait(false);
        }

        throw new TimeoutException("等待队列空闲超时。");
    }
}
