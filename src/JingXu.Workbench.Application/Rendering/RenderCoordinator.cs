using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Rendering;

/// <summary>
/// 有界并发渲染队列协调器。每次合法状态转移先持久化再发布可观察队列。
/// </summary>
public sealed class RenderCoordinator : IAsyncDisposable
{
    /// <summary>
    /// 桌面端可选并发上限。默认仍使用两个任务；升级后的电脑可手动提高到四个。
    /// </summary>
    public const int SafeMaxConcurrency = 4;

    private const double MinimumProgressDelta = 1.0;
    private const long MaximumProgressSilenceMilliseconds = 500;

    private readonly IRenderExecutor _executor;
    private readonly IRenderQueueStore _store;
    private readonly Action<Action>? _marshalToUi;
    private readonly object _sync = new();
    private readonly object _progressPersistSync = new();
    private readonly SemaphoreSlim _stateGate = new(1, 1);
    private readonly SemaphoreSlim _progressPersistSignal = new(0);
    private readonly Dictionary<Guid, CancellationTokenSource> _jobTokens = new();
    private readonly HashSet<Guid> _inflightJobs = new();
    private readonly Dictionary<Guid, long> _lastProgressPublishedAt = new();
    private readonly Dictionary<Guid, (TempResourceLease Lease, string Path)> _subtitleResources = new();

    private List<RenderJob> _jobs;
    private int _maxConcurrency;
    private int _pendingConcurrency;
    private int _activeCount;
    private Guid? _exclusiveJobId;
    private bool _paused;
    private bool _shutdownRequested;
    private Task _persistDrain = Task.CompletedTask;
    private Task _progressPersistWorker;
    private bool _progressPersistRequested;

    private RenderCoordinator(
        IRenderExecutor executor,
        IRenderQueueStore store,
        int maxConcurrency,
        Action<Action>? marshalToUi)
    {
        _executor = executor;
        _store = store;
        _marshalToUi = marshalToUi;
        _maxConcurrency = ClampConcurrency(maxConcurrency);
        _pendingConcurrency = _maxConcurrency;
        _jobs = store.Jobs.ToList();
        _progressPersistWorker = Task.Run(PersistProgressLoopAsync);
        _persistDrain = _progressPersistWorker;
    }

    /// <summary>
    /// 队列变更时触发。若创建时提供了 <c>marshalToUi</c>，则在 UI 调度上下文中触发；
    /// 否则可能在后台线程触发，订阅方必须自行封送。
    /// </summary>
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

    /// <param name="marshalToUi">
    /// 可选：将 <see cref="JobsChanged"/> 同步封送到 UI 线程（例如 <c>IUiDispatcher.Invoke</c>）。
    /// </param>
    public static RenderCoordinator Create(
        IRenderExecutor executor,
        IRenderQueueStore store,
        int maxConcurrency,
        Action<Action>? marshalToUi = null) =>
        new(executor, store, maxConcurrency, marshalToUi);

    /// <summary>批量入队。先入队持久化，再调度执行。</summary>
    public async Task EnqueueAsync(IReadOnlyList<RenderJob> jobs, CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_shutdownRequested, this);
        if (jobs.Count == 0)
        {
            return;
        }

        await _stateGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            List<RenderJob> updated;
            lock (_sync)
            {
                updated = _jobs.Concat(jobs).ToList();
            }

            var resources = new Dictionary<Guid, (TempResourceLease Lease, string Path)>();
            try
            {
                foreach (var job in jobs)
                {
                    var path = job.Request?.SubtitleBurn?.SubtitleFilePath;
                    if (path is not null && WorkbenchCacheCleanup.IsOwnedTempSubtitlePath(path) && !resources.ContainsKey(job.Id))
                    {
                        resources.Add(job.Id, (TempResourceLease.Acquire(path), path));
                    }
                }

                if (await PersistAndPublishCoreAsync(updated, cancellationToken).ConfigureAwait(false))
                {
                    lock (_sync)
                    {
                        foreach (var (id, resource) in resources.ToArray())
                        {
                            if (_subtitleResources.TryAdd(id, resource))
                            {
                                resources.Remove(id);
                            }
                        }
                    }
                }
            }
            finally
            {
                foreach (var resource in resources.Values)
                {
                    resource.Lease.Dispose();
                }
            }
        }
        finally
        {
            _stateGate.Release();
        }

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

    /// <summary>队列是否处于暂停（不再调度新任务）。</summary>
    public bool IsPaused
    {
        get
        {
            lock (_sync)
            {
                return _paused;
            }
        }
    }

    /// <summary>清除已结束任务（完成 / 失败 / 取消），不影响排队与渲染中任务。</summary>
    public async Task ClearFinishedJobsAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_shutdownRequested, this);

        await _stateGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            List<RenderJob> updated;
            lock (_sync)
            {
                updated = _jobs.Where(j => IsActiveState(j.State)).ToList();
                if (updated.Count == _jobs.Count)
                {
                    return;
                }
            }

            await PersistAndPublishCoreAsync(updated, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _stateGate.Release();
        }
    }

    /// <summary>
    /// 清空队列：取消排队任务并移除；取消进行中任务但保留至其结束为 Cancelled；
    /// 立即移除所有非进行中任务。
    /// </summary>
    public async Task ClearAllJobsAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_shutdownRequested, this);

        Guid[] cancelIds;
        lock (_sync)
        {
            cancelIds = _jobs.Select(j => j.Id).ToArray();
        }

        foreach (var id in cancelIds)
        {
            await CancelJobAsync(id, cancellationToken).ConfigureAwait(false);
        }

        await _stateGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            List<RenderJob> updated;
            lock (_sync)
            {
                updated = _jobs.Where(j => _inflightJobs.Contains(j.Id)).ToList();
            }

            await PersistAndPublishCoreAsync(updated, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _stateGate.Release();
        }

        RequestPump();
    }

    private static bool IsActiveState(JobState state) =>
        state is JobState.Queued or JobState.Preparing or JobState.Running or JobState.Finalizing;

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
            if (GetJob(jobId)?.State == JobState.Cancelled)
            {
                ReleaseSubtitleResource(jobId, onlyIfIdle: true);
            }
            RequestPump();
        }
    }

    /// <summary>在当前活跃租约全部结束后应用新的并发上限（1–4）。</summary>
    public Task SetMaxConcurrencyAsync(int maxConcurrency, CancellationToken cancellationToken)
    {
        lock (_sync)
        {
            _pendingConcurrency = ClampConcurrency(maxConcurrency);
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
        _progressPersistSignal.Release();

        CancellationTokenSource[] runningTokens;
        lock (_sync)
        {
            runningTokens = _jobTokens.Values.ToArray();
        }

        foreach (var token in runningTokens)
        {
            token.Cancel();
        }

        foreach (var job in Jobs.Where(static job => job.State == JobState.Queued))
        {
            ReleaseSubtitleResource(job.Id, onlyIfIdle: true);
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
            if (_shutdownRequested || _paused || _activeCount >= _maxConcurrency || _exclusiveJobId is not null)
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

            var exclusive = RequiresExclusiveRender(_jobs[index].Request);
            // 保持队列顺序。高分辨率四屏同时包含多个解码/合成帧池，等待其他任务释放资源后再启动。
            if (exclusive && _activeCount > 0)
            {
                job = default!;
                return false;
            }

            if (exclusive)
            {
                _exclusiveJobId = _jobs[index].Id;
            }

            _activeCount++;
            _inflightJobs.Add(_jobs[index].Id);
            job = _jobs[index];
            return true;
        }
    }

    private static bool RequiresExclusiveRender(RenderRequest? request)
    {
        if (request?.FourScreen is null || request.Plan.Clips.Count == 0 ||
            !request.FourScreen.AppliesTo(request.Plan.Clips.Count - 1))
        {
            return false;
        }

        var first = request.Plan.Clips[0].Asset.Info;
        var customCanvas = !request.Aspect.InheritFromFirstClip &&
            request.Aspect.TargetWidth is > 0 && request.Aspect.TargetHeight is > 0;
        var width = customCanvas ? request.Aspect.TargetWidth!.Value : first.Width;
        var height = customCanvas ? request.Aspect.TargetHeight!.Value : first.Height;
        // 与编译器一致，四屏在应用导出分辨率之后计算；小素材放大也必须受保护。
        try
        {
            var size = request.OutputVideoSettings.ResolveTargetSize(Math.Max(2, width & ~1), Math.Max(2, height & ~1));
            return (long)size.Width * size.Height >= 1280L * 720;
        }
        catch (ArgumentOutOfRangeException)
        {
            // 损坏快照仍由执行器报告失败，不让资源估算异常中止整个队列。
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
        var firstTransitionFailed = false;
        try
        {
            if (!await TransitionJobAsync(queuedJob, current => current.BeginPrepare(), jobCts.Token)
                    .ConfigureAwait(false))
            {
                firstTransitionFailed = true;
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

            var expectedDuration = running.Request?.Plan.Duration ?? TimeSpan.Zero;
            var progress = new InlineProgress<RenderProgress>(p =>
            {
                double? percent = p.Percent;
                if (percent is null && expectedDuration > TimeSpan.Zero && p.Position > TimeSpan.Zero)
                {
                    percent = Math.Clamp(
                        p.Position.TotalSeconds / expectedDuration.TotalSeconds * 100.0,
                        0,
                        99.5);
                }

                var phase = percent is null
                    ? "渲染中…"
                    : $"渲染中 {percent.Value:0.#}%";
                if (p.Speed > 0 && double.IsFinite(p.Speed))
                {
                    phase += $" · {p.Speed.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture)}×";
                }
                UpdateProgress(queuedJob.Id, percent, phase);
            });
            RenderExecutionResult result;
            try
            {
                result = await _executor.ExecuteAsync(running, progress, jobCts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (jobCts.IsCancellationRequested)
            {
                result = RenderExecutionResult.Cancelled();
            }
            catch (Exception ex)
            {
                result = RenderExecutionResult.Failed($"渲染执行失败：{ex.GetBaseException().Message}");
            }

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

            await TransitionJobAsync(
                    finalizing,
                    current => current.Complete(result.Notice),
                    CancellationToken.None)
                .ConfigureAwait(false);
        }
        finally
        {
            ReleaseSubtitleResource(queuedJob.Id);
            lock (_sync)
            {
                _jobTokens.Remove(queuedJob.Id);
                _inflightJobs.Remove(queuedJob.Id);
                if (_exclusiveJobId == queuedJob.Id)
                {
                    _exclusiveJobId = null;
                }
                _lastProgressPublishedAt.Remove(queuedJob.Id);
                _activeCount--;
                if (_activeCount == 0)
                {
                    _maxConcurrency = _pendingConcurrency;
                }
                // 释放执行槽与检查取消状态必须处于同一把锁下，避免取消发布和本次唤醒之间丢失调度。
                // 持久化失败且仍 Queued 时不立即反复重试；已取消或移除则继续后项。
                if (firstTransitionFailed)
                {
                    shouldPump = _jobs.FirstOrDefault(job => job.Id == queuedJob.Id)?.State != JobState.Queued;
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

    private void ReleaseSubtitleResource(Guid id, bool onlyIfIdle = false)
    {
        (TempResourceLease Lease, string Path) resource;
        lock (_sync)
        {
            if (onlyIfIdle && _inflightJobs.Contains(id))
            {
                return;
            }

            if (!_subtitleResources.Remove(id, out resource))
            {
                return;
            }
        }

        resource.Lease.Dispose();
        TempResourceLease.TryDeleteUnusedSubtitle(resource.Path);
    }

    /// <summary>当前渲染并发上限（1–4）。</summary>
    public int MaxConcurrency
    {
        get
        {
            lock (_sync)
            {
                return _maxConcurrency;
            }
        }
    }

    /// <summary>正在执行的任务 Id。缓存清理必须跳过这些 staging，不能误删并发中的任务。</summary>
    public IReadOnlyList<Guid> InflightJobIds
    {
        get
        {
            lock (_sync)
            {
                return _inflightJobs.ToList();
            }
        }
    }

    /// <summary>待应用的并发上限（活跃租约结束后生效）。</summary>
    public int PendingConcurrency
    {
        get
        {
            lock (_sync)
            {
                return _pendingConcurrency;
            }
        }
    }

    private void UpdateProgress(Guid jobId, double? percent, string phase)
    {
        List<RenderJob> updated;
        lock (_sync)
        {
            var index = _jobs.FindIndex(j => j.Id == jobId);
            if (index < 0)
            {
                return;
            }

            var current = _jobs[index];
            if (current.State is not (JobState.Running or JobState.Preparing or JobState.Finalizing))
            {
                return;
            }

            var now = Environment.TickCount64;
            var timeElapsed = !_lastProgressPublishedAt.TryGetValue(jobId, out var lastPublishedAt)
                || now - lastPublishedAt >= MaximumProgressSilenceMilliseconds;
            var progressChangedEnough = current.ProgressPercent is not { } previous
                || percent is not { } next
                || Math.Abs(previous - next) >= MinimumProgressDelta;

            // 文案内包含百分比，不能把“文案不同”作为放行条件，否则每一帧都会穿透节流。
            // 百分比至少变化 1%，或距离上次发布已满 500ms，才刷新 UI 与队列快照。
            if (!progressChangedEnough && !timeElapsed)
            {
                return;
            }

            updated = _jobs.Select(j => j.Id == jobId ? j.WithProgress(percent, phase) : j).ToList();
            _jobs = updated;
            _lastProgressPublishedAt[jobId] = now;
        }

        RaiseJobsChanged();
        // 进度不阻塞渲染：异步落盘，失败忽略；闸门内重新读取最新快照，避免覆盖状态转换。
        QueueLatestStatePersistence();
    }

    private static int ClampConcurrency(int value) => Math.Clamp(value, 1, SafeMaxConcurrency);

    private async Task<bool> TransitionJobAsync(
        RenderJob source,
        Func<RenderJob, RenderJob> transition,
        CancellationToken cancellationToken)
    {
        try
        {
            await _stateGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            return false;
        }

        try
        {
            RenderJob? current;
            lock (_sync)
            {
                current = _jobs.FirstOrDefault(j => j.Id == source.Id);
            }

            if (current is null)
            {
                return false;
            }

            RenderJob next;
            try
            {
                next = transition(current);
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

            return await PersistAndPublishCoreAsync(updated, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _stateGate.Release();
        }
    }

    private async Task<bool> PersistAndPublishCoreAsync(
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

        RaiseJobsChanged();
        return true;
    }

    private void QueueLatestStatePersistence()
    {
        var shouldSignal = false;
        lock (_progressPersistSync)
        {
            if (!_progressPersistRequested)
            {
                _progressPersistRequested = true;
                shouldSignal = true;
            }
        }

        if (shouldSignal)
        {
            _progressPersistSignal.Release();
        }
    }

    private async Task PersistProgressLoopAsync()
    {
        while (true)
        {
            await _progressPersistSignal.WaitAsync().ConfigureAwait(false);
            while (true)
            {
                lock (_progressPersistSync)
                {
                    if (!_progressPersistRequested)
                    {
                        break;
                    }

                    _progressPersistRequested = false;
                }

                await _stateGate.WaitAsync().ConfigureAwait(false);
                try
                {
                    List<RenderJob> snapshot;
                    lock (_sync)
                    {
                        snapshot = _jobs.ToList();
                    }

                    await RunPersistAsync(snapshot, CancellationToken.None).ConfigureAwait(false);
                }
                finally
                {
                    _stateGate.Release();
                }
            }

            lock (_sync)
            {
                if (_shutdownRequested)
                {
                    return;
                }
            }
        }
    }

    private void RaiseJobsChanged()
    {
        var handlers = JobsChanged;
        if (handlers is null)
        {
            return;
        }

        if (_marshalToUi is null)
        {
            handlers();
            return;
        }

        _marshalToUi(() => handlers());
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

    /// <summary>
    /// <see cref="Progress{T}"/> 会把每次 Report 再排入线程池；FFmpeg 高频输出时容易形成回调积压。
    /// 此实现直接在读取进度的后台线程执行轻量处理，UI 发布仍由 marshalToUi 异步完成。
    /// </summary>
    private sealed class InlineProgress<T>(Action<T> handler) : IProgress<T>
    {
        public void Report(T value) => handler(value);
    }
}
