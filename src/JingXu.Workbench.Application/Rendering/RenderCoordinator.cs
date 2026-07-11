using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Rendering;

/// <summary>
/// 有界并发渲染队列协调器。每次合法状态转移先持久化再发布可观察队列。
/// </summary>
public sealed class RenderCoordinator : IAsyncDisposable
{
    private readonly IRenderExecutor _executor;
    private readonly IRenderQueueStore _store;
    private readonly object _sync = new();
    private readonly Dictionary<Guid, CancellationTokenSource> _jobTokens = new();
    private readonly HashSet<Guid> _inflightJobs = new();

    private List<RenderJob> _jobs;
    private int _maxConcurrency;
    private int _pendingConcurrency;
    private int _activeCount;
    private bool _paused;
    private bool _shutdownRequested;
    private Task _persistDrain = Task.CompletedTask;

    private RenderCoordinator(IRenderExecutor executor, IRenderQueueStore store, int maxConcurrency)
    {
        _executor = executor;
        _store = store;
        _maxConcurrency = Math.Clamp(maxConcurrency, 1, 4);
        _pendingConcurrency = _maxConcurrency;
        _jobs = store.Jobs.ToList();
    }

    /// <summary>队列变更时触发（在 UI 线程外调用）。</summary>
    public event Action? JobsChanged;

    /// <summary>当前可观察队列快照。</summary>
    public IReadOnlyList<RenderJob> Jobs
    {
        get
        {
            lock (_sync)
            {
                return _jobs.ToList();
            }
        }
    }

    public static RenderCoordinator Create(
        IRenderExecutor executor,
        IRenderQueueStore store,
        int maxConcurrency) =>
        new(executor, store, maxConcurrency);

    /// <summary>批量入队。先入队持久化，再调度执行。</summary>
    public async Task EnqueueAsync(IReadOnlyList<RenderJob> jobs, CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_shutdownRequested, this);
        if (jobs.Count == 0)
        {
            return;
        }

        List<RenderJob> updated;
        lock (_sync)
        {
            updated = _jobs.Concat(jobs).ToList();
        }

        await PersistAndPublishAsync(updated, cancellationToken).ConfigureAwait(false);
        RequestPump();
    }

    /// <summary>暂停调度新任务；已在运行的任务继续完成。</summary>
    public void PauseQueue()
    {
        lock (_sync)
        {
            _paused = true;
        }
    }

    /// <summary>恢复调度。</summary>
    public void ResumeQueue()
    {
        lock (_sync)
        {
            _paused = false;
        }

        RequestPump();
    }

    /// <summary>取消指定任务（仅影响该任务的取消令牌）。</summary>
    public async Task CancelJobAsync(Guid jobId, CancellationToken cancellationToken)
    {
        CancellationTokenSource? tokenSource;
        lock (_sync)
        {
            _jobTokens.TryGetValue(jobId, out tokenSource);
        }

        tokenSource?.Cancel();

        RenderJob? job;
        lock (_sync)
        {
            job = _jobs.FirstOrDefault(j => j.Id == jobId);
        }

        if (job is null)
        {
            return;
        }

        if (job.State is JobState.Queued)
        {
            await TransitionJobAsync(job, current => current.Cancel(), cancellationToken).ConfigureAwait(false);
            RequestPump();
        }
    }

    /// <summary>在当前活跃租约全部结束后应用新的并发上限（1–4）。</summary>
    public Task SetMaxConcurrencyAsync(int maxConcurrency, CancellationToken cancellationToken)
    {
        lock (_sync)
        {
            _pendingConcurrency = Math.Clamp(maxConcurrency, 1, 4);
        }

        RequestPump();
        return Task.CompletedTask;
    }

    /// <summary>停止调度并等待进行中的持久化完成。</summary>
    public async Task ShutdownAsync(CancellationToken cancellationToken)
    {
        if (_shutdownRequested)
        {
            await _persistDrain.ConfigureAwait(false);
            return;
        }

        _shutdownRequested = true;

        CancellationTokenSource[] runningTokens;
        lock (_sync)
        {
            runningTokens = _jobTokens.Values.ToArray();
        }

        foreach (var token in runningTokens)
        {
            token.Cancel();
        }

        await _persistDrain.ConfigureAwait(false);
    }

    public async ValueTask DisposeAsync() => await ShutdownAsync(default).ConfigureAwait(false);

    private void RequestPump()
    {
        while (TryReserveQueuedJob(out var job))
        {
            _ = Task.Run(() => ProcessJobAsync(job));
        }
    }

    private bool TryReserveQueuedJob(out RenderJob job)
    {
        lock (_sync)
        {
            if (_shutdownRequested || _paused || _activeCount >= _maxConcurrency)
            {
                job = default!;
                return false;
            }

            var index = _jobs.FindIndex(j => j.State == JobState.Queued && !_inflightJobs.Contains(j.Id));
            if (index < 0)
            {
                job = default!;
                return false;
            }

            _activeCount++;
            _inflightJobs.Add(_jobs[index].Id);
            job = _jobs[index];
            return true;
        }
    }

    private async Task ProcessJobAsync(RenderJob queuedJob)
    {
        using var jobCts = new CancellationTokenSource();
        lock (_sync)
        {
            _jobTokens[queuedJob.Id] = jobCts;
        }

        var shouldPump = true;
        try
        {
            if (!await TransitionJobAsync(queuedJob, current => current.BeginPrepare(), jobCts.Token)
                    .ConfigureAwait(false))
            {
                shouldPump = false;
                return;
            }

            var preparing = GetJob(queuedJob.Id);
            if (preparing is null || preparing.State != JobState.Preparing)
            {
                return;
            }

            if (!await TransitionJobAsync(preparing, current => current.BeginRun(), jobCts.Token)
                    .ConfigureAwait(false))
            {
                return;
            }

            var running = GetJob(queuedJob.Id);
            if (running is null)
            {
                return;
            }

            var progress = new Progress<RenderProgress>(_ => { });
            var result = await _executor.ExecuteAsync(running, progress, jobCts.Token).ConfigureAwait(false);

            var latest = GetJob(queuedJob.Id);
            if (latest is null)
            {
                return;
            }

            if (result.IsCancelled || jobCts.IsCancellationRequested)
            {
                if (latest.State is JobState.Preparing or JobState.Running or JobState.Finalizing)
                {
                    await TransitionJobAsync(latest, current => current.Cancel(), CancellationToken.None)
                        .ConfigureAwait(false);
                }

                return;
            }

            if (!result.IsSuccess)
            {
                var message = result.FailureInfo?.Message ?? "渲染失败。";
                await TransitionJobAsync(latest, current => current.Fail(message), CancellationToken.None)
                    .ConfigureAwait(false);
                return;
            }

            if (!await TransitionJobAsync(latest, current => current.BeginFinalize(), CancellationToken.None)
                    .ConfigureAwait(false))
            {
                return;
            }

            var finalizing = GetJob(queuedJob.Id);
            if (finalizing is null)
            {
                return;
            }

            await TransitionJobAsync(finalizing, current => current.Complete(), CancellationToken.None)
                .ConfigureAwait(false);
        }
        finally
        {
            lock (_sync)
            {
                _jobTokens.Remove(queuedJob.Id);
                _inflightJobs.Remove(queuedJob.Id);
                _activeCount--;
                if (_activeCount == 0)
                {
                    _maxConcurrency = _pendingConcurrency;
                }
            }

            if (shouldPump)
            {
                RequestPump();
            }
        }
    }

    private RenderJob? GetJob(Guid id)
    {
        lock (_sync)
        {
            return _jobs.FirstOrDefault(j => j.Id == id);
        }
    }

    private async Task<bool> TransitionJobAsync(
        RenderJob source,
        Func<RenderJob, RenderJob> transition,
        CancellationToken cancellationToken)
    {
        RenderJob next;
        try
        {
            next = transition(source);
        }
        catch (InvalidOperationException)
        {
            return false;
        }

        List<RenderJob> updated;
        lock (_sync)
        {
            updated = _jobs.Select(j => j.Id == next.Id ? next : j).ToList();
        }

        return await PersistAndPublishAsync(updated, cancellationToken).ConfigureAwait(false);
    }

    private async Task<bool> PersistAndPublishAsync(
        IReadOnlyList<RenderJob> updated,
        CancellationToken cancellationToken)
    {
        var persistTask = RunPersistAsync(updated, cancellationToken);
        lock (_sync)
        {
            _persistDrain = Task.WhenAll(_persistDrain, persistTask);
        }

        var success = await persistTask.ConfigureAwait(false);
        if (!success)
        {
            return false;
        }

        lock (_sync)
        {
            _jobs = updated.ToList();
        }

        JobsChanged?.Invoke();
        return true;
    }

    private static async Task<bool> RunPersistAsync(
        IRenderQueueStore store,
        IReadOnlyList<RenderJob> updated,
        CancellationToken cancellationToken)
    {
        try
        {
            await store.PersistAsync(updated, cancellationToken).ConfigureAwait(false);
            return true;
        }
        catch (IOException)
        {
            return false;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            return false;
        }
    }

    private Task<bool> RunPersistAsync(IReadOnlyList<RenderJob> updated, CancellationToken cancellationToken) =>
        RunPersistAsync(_store, updated, cancellationToken);
}
