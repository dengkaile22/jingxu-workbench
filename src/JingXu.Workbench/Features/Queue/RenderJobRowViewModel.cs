using CommunityToolkit.Mvvm.ComponentModel;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Features.Shell;

namespace JingXu.Workbench.Features.Queue;

/// <summary>
/// 队列中单个渲染任务的行视图模型。以「形状 + 颜色 + 文字」呈现状态，并展示进度。
/// 同一 <see cref="JobId"/> 可就地 <see cref="Apply"/> 更新，避免进度刷新时反复分配行实例。
/// </summary>
public sealed class RenderJobRowViewModel : ObservableObject
{
    private RenderJob _job;
    private string _title;

    public RenderJobRowViewModel(RenderJob job, string title)
    {
        ArgumentNullException.ThrowIfNull(job);
        ArgumentException.ThrowIfNullOrWhiteSpace(title);
        _job = job;
        _title = title;
    }

    /// <summary>用最新任务快照刷新本行（保持同一 ViewModel 实例）。</summary>
    public void Apply(RenderJob job, string title)
    {
        ArgumentNullException.ThrowIfNull(job);
        ArgumentException.ThrowIfNullOrWhiteSpace(title);
        if (job.Id != _job.Id)
        {
            throw new InvalidOperationException("不能将不同 Id 的任务应用到同一行视图模型。");
        }

        _job = job;
        if (!string.Equals(_title, title, StringComparison.Ordinal))
        {
            _title = title;
            OnPropertyChanged(nameof(Title));
        }

        OnPropertyChanged(nameof(State));
        OnPropertyChanged(nameof(Status));
        OnPropertyChanged(nameof(CanRetry));
        OnPropertyChanged(nameof(ProgressPercent));
        OnPropertyChanged(nameof(ShowProgress));
        OnPropertyChanged(nameof(ProgressText));
    }

    /// <summary>任务显示名称。</summary>
    public string Title => _title;

    /// <summary>任务的稳定标识。</summary>
    public Guid JobId => _job.Id;

    /// <summary>任务的稳定标识短码。</summary>
    public string ShortId => _job.Id.ToString("N")[..8];

    /// <summary>当前状态。</summary>
    public JobState State => _job.State;

    /// <summary>状态呈现信息（文字 / 图标 / 颜色 / 可访问名称）。</summary>
    public StatusPresentation Status => StatusPresentation.For(_job.State);

    /// <summary>是否可重试。</summary>
    public bool CanRetry => _job.CanRetry;

    /// <summary>进度百分比（0–100）；无进度时为 0。</summary>
    public double ProgressPercent => _job.ProgressPercent ?? (IsActivelyRendering ? 0 : 0);

    /// <summary>是否显示进度条（准备/渲染/收尾）。</summary>
    public bool ShowProgress =>
        _job.State is JobState.Preparing or JobState.Running or JobState.Finalizing;

    /// <summary>进度文案。</summary>
    public string ProgressText
    {
        get
        {
            if (_job.State == JobState.Completed && !string.IsNullOrWhiteSpace(_job.Notice))
            {
                return _job.Notice!;
            }

            if (!string.IsNullOrWhiteSpace(_job.ProgressPhase))
            {
                return _job.ProgressPhase!;
            }

            return _job.State switch
            {
                JobState.Preparing => "准备中…",
                JobState.Running => "渲染中…",
                JobState.Finalizing => "收尾中…",
                JobState.Queued => "排队中",
                JobState.Completed => "已完成",
                JobState.Failed => _job.Error ?? "失败",
                JobState.Cancelled => "已取消",
                _ => Status.Text
            };
        }
    }

    private bool IsActivelyRendering =>
        _job.State is JobState.Preparing or JobState.Running or JobState.Finalizing;
}
