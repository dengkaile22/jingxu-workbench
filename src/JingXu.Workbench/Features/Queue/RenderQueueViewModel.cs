using System.Collections.ObjectModel;
using System.Collections.Specialized;
using CommunityToolkit.Mvvm.ComponentModel;
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
/// 任务队列模块视图模型。M1 阶段队列为空，仅提供筛选范围、概览计数与空状态提示；
/// 渲染协调器接入后（后续任务）任务行会自动出现在这里。
/// </summary>
public sealed partial class RenderQueueViewModel : WorkspaceModuleViewModel
{
    public override WorkspaceModule ModuleKind => WorkspaceModule.Queue;

    public override string Title => "任务队列";

    /// <summary>全部任务（真实数据源）。</summary>
    public ObservableCollection<RenderJobRowViewModel> Jobs { get; } = [];

    /// <summary>按当前筛选范围可见的任务。</summary>
    public ObservableCollection<RenderJobRowViewModel> VisibleJobs { get; } = [];

    [ObservableProperty]
    private QueueScope _scope = QueueScope.All;

    public RenderQueueViewModel()
    {
        Jobs.CollectionChanged += OnJobsChanged;
        Refresh();
    }

    /// <summary>绑定渲染协调器，在队列变更时同步任务行。</summary>
    public void BindCoordinator(RenderCoordinator coordinator)
    {
        coordinator.JobsChanged += () => SyncJobs(coordinator.Jobs);
        SyncJobs(coordinator.Jobs);
    }

    private void SyncJobs(IReadOnlyList<RenderJob> jobs)
    {
        Jobs.Clear();
        var index = 1;
        foreach (var job in jobs)
        {
            Jobs.Add(new RenderJobRowViewModel(job, $"任务 {index}"));
            index++;
        }
    }

    /// <summary>队列（按当前筛选）是否为空。</summary>
    public bool IsEmpty => VisibleJobs.Count == 0;

    /// <summary>空状态提示文案。</summary>
    public string EmptyHint { get; } =
        "队列为空。完成编排后点击「加入队列」，任务会显示在这里，可跟踪阶段与进度，并随时取消或重试。";

    public int TotalCount => Jobs.Count;

    public int ActiveCount => Jobs.Count(j => IsActive(j.State));

    public int FinishedCount => Jobs.Count(j => !IsActive(j.State));

    public int FailedCount => Jobs.Count(j => j.State == JobState.Failed);

    /// <summary>底部持久队列条的一行式概览文案。</summary>
    public string SummaryText => TotalCount == 0
        ? "队列空闲 · 暂无任务"
        : $"共 {TotalCount} 个 · 进行中 {ActiveCount} · 已结束 {FinishedCount} · 失败 {FailedCount}";

    partial void OnScopeChanged(QueueScope value) => Refresh();

    private void OnJobsChanged(object? sender, NotifyCollectionChangedEventArgs e) => Refresh();

    private void Refresh()
    {
        VisibleJobs.Clear();
        foreach (var job in Jobs.Where(Matches))
        {
            VisibleJobs.Add(job);
        }

        OnPropertyChanged(nameof(IsEmpty));
        OnPropertyChanged(nameof(TotalCount));
        OnPropertyChanged(nameof(ActiveCount));
        OnPropertyChanged(nameof(FinishedCount));
        OnPropertyChanged(nameof(FailedCount));
        OnPropertyChanged(nameof(SummaryText));
    }

    private bool Matches(RenderJobRowViewModel job) => Scope switch
    {
        QueueScope.All => true,
        QueueScope.Active => IsActive(job.State),
        QueueScope.Finished => !IsActive(job.State),
        _ => true
    };

    private static bool IsActive(JobState state) =>
        state is JobState.Queued or JobState.Preparing or JobState.Running or JobState.Finalizing;
}
