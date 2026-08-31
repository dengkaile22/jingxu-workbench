using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.Windows.Data;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Features.Shell;

namespace JingXu.Workbench.Features.Queue;

/// <summary>队列列表的筛选范围。</summary>
public enum QueueScope
{
    /// <summary>全部任务。</summary>
    All,

    /// <summary>进行中（已入队 / 准备 / 渲染 / 收尾）。</summary>
    Active,

    /// <summary>已结束（完成 / 失败 / 取消）。</summary>
    Finished
}

/// <summary>
/// 任务队列模块视图模型。绑定协调器后，将 JobsChanged（可能来自后台线程）
/// 经由 <see cref="IUiDispatcher"/> 同步到 ObservableCollection，避免 CollectionView 跨线程异常。
/// </summary>
public sealed partial class RenderQueueViewModel : WorkspaceModuleViewModel
{
    private readonly IUiDispatcher _uiDispatcher;
    private readonly object _collectionSync = new();
    private bool _suppressJobsChanged;
    private RenderCoordinator? _coordinator;

    public override WorkspaceModule ModuleKind => WorkspaceModule.Queue;

    public override string Title => "任务队列";

    /// <summary>全部任务（真实数据源）。</summary>
    public ObservableCollection<RenderJobRowViewModel> Jobs { get; } = [];

    /// <summary>按当前筛选范围可见的任务。</summary>
    public ObservableCollection<RenderJobRowViewModel> VisibleJobs { get; } = [];

    [ObservableProperty]
    private QueueScope _scope = QueueScope.All;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(PauseResumeLabel))]
    [NotifyCanExecuteChangedFor(nameof(PauseOrResumeCommand))]
    private bool _isPaused;

    public RenderQueueViewModel(IUiDispatcher uiDispatcher)
    {
        _uiDispatcher = uiDispatcher ?? throw new ArgumentNullException(nameof(uiDispatcher));

        // 即便有漏网的跨线程写入，CollectionView 也可在锁保护下接受变更。
        BindingOperations.EnableCollectionSynchronization(Jobs, _collectionSync);
        BindingOperations.EnableCollectionSynchronization(VisibleJobs, _collectionSync);

        Jobs.CollectionChanged += OnJobsCollectionChanged;
        RefreshVisibleJobs();
    }

    /// <summary>绑定渲染协调器，在队列变更时同步任务行（始终在 UI 调度上下文执行）。</summary>
    public void BindCoordinator(RenderCoordinator coordinator)
    {
        ArgumentNullException.ThrowIfNull(coordinator);
        _coordinator = coordinator;
        IsPaused = coordinator.IsPaused;
        coordinator.JobsChanged += () =>
        {
            // 协调器可能已在 UI 线程触发；仍统一走 RunOnUi，保证幂等且可测。
            var snapshot = coordinator.Jobs;
            RunOnUi(() =>
            {
                IsPaused = coordinator.IsPaused;
                SyncJobs(snapshot);
            });
        };
        RunOnUi(() => SyncJobs(coordinator.Jobs));
        ClearFinishedCommand.NotifyCanExecuteChanged();
        ClearAllCommand.NotifyCanExecuteChanged();
        PauseOrResumeCommand.NotifyCanExecuteChanged();
    }

    private void RunOnUi(Action action)
    {
        if (_uiDispatcher.CheckAccess())
        {
            action();
            return;
        }

        // 进度高频同步用 Post，避免同步 Invoke 卡住输入消息泵。
        _uiDispatcher.Post(action);
    }

    private void SyncJobs(IReadOnlyList<RenderJob> jobs)
    {
        _suppressJobsChanged = true;
        try
        {
            lock (_collectionSync)
            {
                ReconcileJobsById(jobs);
            }
        }
        finally
        {
            _suppressJobsChanged = false;
        }

        RefreshVisibleJobs();
        ClearFinishedCommand.NotifyCanExecuteChanged();
        ClearAllCommand.NotifyCanExecuteChanged();
    }

    /// <summary>
    /// 按 Id 复用行 ViewModel：进度刷新只 Apply，不 new；增删按增量；顺序变化时 Move/Insert，避免 Clear+全量重建。
    /// </summary>
    private void ReconcileJobsById(IReadOnlyList<RenderJob> jobs)
    {
        var existingById = new Dictionary<Guid, RenderJobRowViewModel>(Jobs.Count);
        foreach (var row in Jobs)
        {
            existingById[row.JobId] = row;
        }

        var desired = new List<RenderJobRowViewModel>(jobs.Count);
        for (var index = 0; index < jobs.Count; index++)
        {
            var job = jobs[index];
            var title = $"任务 {index + 1}";
            if (existingById.TryGetValue(job.Id, out var row))
            {
                row.Apply(job, title);
                desired.Add(row);
                existingById.Remove(job.Id);
            }
            else
            {
                desired.Add(new RenderJobRowViewModel(job, title));
            }
        }

        ReconcileCollection(Jobs, desired);
    }

    private static void ReconcileCollection(
        ObservableCollection<RenderJobRowViewModel> current,
        List<RenderJobRowViewModel> desired)
    {
        var desiredSet = new HashSet<RenderJobRowViewModel>(desired);
        for (var index = current.Count - 1; index >= 0; index--)
        {
            if (!desiredSet.Contains(current[index]))
            {
                current.RemoveAt(index);
            }
        }

        for (var index = 0; index < desired.Count; index++)
        {
            var target = desired[index];
            if (index < current.Count && ReferenceEquals(current[index], target))
            {
                continue;
            }

            var existingIndex = -1;
            for (var scan = index; scan < current.Count; scan++)
            {
                if (ReferenceEquals(current[scan], target))
                {
                    existingIndex = scan;
                    break;
                }
            }

            if (existingIndex >= 0)
            {
                current.Move(existingIndex, index);
            }
            else if (index < current.Count)
            {
                current.Insert(index, target);
            }
            else
            {
                current.Add(target);
            }
        }

        while (current.Count > desired.Count)
        {
            current.RemoveAt(current.Count - 1);
        }
    }

    private void RefreshVisibleJobs()
    {
        lock (_collectionSync)
        {
            if (Scope == QueueScope.All)
            {
                ReconcileCollection(VisibleJobs, Jobs.ToList());
            }
            else
            {
                var filtered = Jobs.Where(Matches).ToList();
                ReconcileCollection(VisibleJobs, filtered);
            }
        }

        OnPropertyChanged(nameof(IsEmpty));
        OnPropertyChanged(nameof(TotalCount));
        OnPropertyChanged(nameof(ActiveCount));
        OnPropertyChanged(nameof(RunningCount));
        OnPropertyChanged(nameof(QueuedCount));
        OnPropertyChanged(nameof(FinishedCount));
        OnPropertyChanged(nameof(FailedCount));
        OnPropertyChanged(nameof(SummaryText));
        OnPropertyChanged(nameof(OverallProgressPercent));
        OnPropertyChanged(nameof(HasOverallProgress));
    }

    private bool Matches(RenderJobRowViewModel job) => Scope switch
    {
        QueueScope.All => true,
        QueueScope.Active => IsActive(job.State),
        QueueScope.Finished => !IsActive(job.State),
        _ => true
    };

    /// <summary>队列（按当前筛选）是否为空。</summary>
    public bool IsEmpty => VisibleJobs.Count == 0;

    /// <summary>空状态提示文案。</summary>
    public string EmptyHint { get; } =
        "队列为空。完成编排后点击「加入队列」，任务会显示在这里；可暂停调度、清理已完成或全部任务。";

    public int TotalCount => Jobs.Count;

    /// <summary>未结束任务（排队 + 渲染中），用于「进行中」筛选。</summary>
    public int ActiveCount => Jobs.Count(j => IsActive(j.State));

    /// <summary>真正在执行的任务（准备 / 渲染 / 收尾），不含排队。</summary>
    public int RunningCount => Jobs.Count(j => IsRunning(j.State));

    /// <summary>仍在排队等待调度的任务。</summary>
    public int QueuedCount => Jobs.Count(j => j.State == JobState.Queued);

    public int FinishedCount => Jobs.Count(j => !IsActive(j.State));

    public int FailedCount => Jobs.Count(j => j.State == JobState.Failed);

    public string PauseResumeLabel => IsPaused ? "恢复调度" : "暂停调度";

    /// <summary>底部持久队列条的一行式概览文案。</summary>
    public string SummaryText
    {
        get
        {
            if (TotalCount == 0)
            {
                return IsPaused ? "队列已暂停 · 暂无任务" : "队列空闲 · 暂无任务";
            }

            var pause = IsPaused ? " · 已暂停" : string.Empty;
            return $"共 {TotalCount} 个 · 渲染中 {RunningCount} · 排队 {QueuedCount} · 已结束 {FinishedCount} · 失败 {FailedCount}{pause}";
        }
    }

    /// <summary>整体进度（渲染中任务的平均进度；无渲染时为 0）。</summary>
    public double OverallProgressPercent
    {
        get
        {
            var running = Jobs.Where(j => IsRunning(j.State)).ToList();
            if (running.Count == 0)
            {
                return 0;
            }

            return running.Average(j => j.ProgressPercent);
        }
    }

    public bool HasOverallProgress => RunningCount > 0;

    partial void OnScopeChanged(QueueScope value) => RunOnUi(RefreshVisibleJobs);

    private void OnJobsCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (_suppressJobsChanged)
        {
            return;
        }

        RefreshVisibleJobs();
    }

    private static bool IsActive(JobState state) =>
        state is JobState.Queued or JobState.Preparing or JobState.Running or JobState.Finalizing;

    private static bool IsRunning(JobState state) =>
        state is JobState.Preparing or JobState.Running or JobState.Finalizing;

    [RelayCommand(CanExecute = nameof(CanPauseOrResume))]
    private void PauseOrResume()
    {
        if (_coordinator is null)
        {
            return;
        }

        if (IsPaused)
        {
            _coordinator.ResumeQueue();
            IsPaused = false;
        }
        else
        {
            _coordinator.PauseQueue();
            IsPaused = true;
        }

        OnPropertyChanged(nameof(SummaryText));
    }

    private bool CanPauseOrResume() => _coordinator is not null;

    [RelayCommand(CanExecute = nameof(CanClearFinished))]
    private async Task ClearFinishedAsync()
    {
        if (_coordinator is null)
        {
            return;
        }

        await _coordinator.ClearFinishedJobsAsync(CancellationToken.None).ConfigureAwait(true);
    }

    private bool CanClearFinished() => _coordinator is not null && FinishedCount > 0;

    [RelayCommand(CanExecute = nameof(CanClearAll))]
    private async Task ClearAllAsync()
    {
        if (_coordinator is null)
        {
            return;
        }

        await _coordinator.ClearAllJobsAsync(CancellationToken.None).ConfigureAwait(true);
    }

    private bool CanClearAll() => _coordinator is not null && TotalCount > 0;
}
