using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Features.Shell;

namespace JingXu.Workbench.Features.Queue;

/// <summary>
/// 队列中单个渲染任务的行视图模型。以「形状 + 颜色 + 文字」呈现状态。
/// </summary>
public sealed class RenderJobRowViewModel
{
    private readonly RenderJob _job;

    public RenderJobRowViewModel(RenderJob job, string title)
    {
        _job = job;
        Title = title;
    }

    /// <summary>任务显示名称。</summary>
    public string Title { get; }

    /// <summary>任务的稳定标识短码。</summary>
    public string ShortId => _job.Id.ToString("N")[..8];

    /// <summary>当前状态。</summary>
    public JobState State => _job.State;

    /// <summary>状态呈现信息（文字 / 图标 / 颜色 / 可访问名称）。</summary>
    public StatusPresentation Status => StatusPresentation.For(_job.State);

    /// <summary>是否可重试。</summary>
    public bool CanRetry => _job.CanRetry;
}
