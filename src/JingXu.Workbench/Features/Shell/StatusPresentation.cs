using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Features.Shell;

/// <summary>
/// 任务状态的呈现信息。状态永远以「形状 + 颜色 + 文字」三者共同表达，
/// 不允许仅用颜色区分（满足可访问性要求）。
/// </summary>
/// <param name="Text">中文状态文字。</param>
/// <param name="IconKey">状态图标几何资源键（形状）。</param>
/// <param name="FillKey">状态填充画刷资源键（颜色）。</param>
/// <param name="TextKey">状态文字画刷资源键（对比度达标的文字色）。</param>
/// <param name="AutomationName">供屏幕阅读器与 UI 自动化使用的可访问名称。</param>
public sealed record StatusPresentation(
    string Text,
    string IconKey,
    string FillKey,
    string TextKey,
    string AutomationName)
{
    /// <summary>
    /// 根据任务状态返回其呈现信息。覆盖 <see cref="JobState"/> 的每一个取值。
    /// </summary>
    public static StatusPresentation For(JobState state) => state switch
    {
        JobState.Draft => new(
            "草稿", "Icon.Status.Draft", "Ink.Muted", "Ink.Muted", "任务状态：草稿"),
        JobState.Queued => new(
            "排队中", "Icon.Status.Queued", "Ink.Muted", "Ink.Primary", "任务状态：排队中"),
        JobState.Preparing => new(
            "准备中", "Icon.Status.Active", "Status.Running", "Status.Running.Text", "任务状态：准备中"),
        JobState.Running => new(
            "渲染中", "Icon.Status.Running", "Status.Running", "Status.Running.Text", "任务状态：渲染中"),
        JobState.Finalizing => new(
            "收尾中", "Icon.Status.Active", "Status.Running", "Status.Running.Text", "任务状态：收尾中"),
        JobState.Completed => new(
            "已完成", "Icon.Status.Completed", "Brand.Primary", "Brand.Primary", "任务状态：已完成"),
        JobState.Failed => new(
            "失败", "Icon.Status.Failed", "Status.Failed", "Status.Failed", "任务状态：失败"),
        JobState.Cancelled => new(
            "已取消", "Icon.Status.Cancelled", "Ink.Muted", "Ink.Muted", "任务状态：已取消"),
        _ => throw new ArgumentOutOfRangeException(nameof(state), state, "未知的任务状态。")
    };
}
