using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Rendering;

/// <summary>
/// 队列恢复策略：将中断的活跃任务映射为可重试的失败状态。
/// </summary>
public static class RenderQueueRecovery
{
    /// <summary>
    /// 恢复单个任务。Preparing / Running / Finalizing 标记为可重试失败。
    /// </summary>
    public static RenderJob Recover(RenderJob job) =>
        job.State is JobState.Preparing or JobState.Running or JobState.Finalizing
            ? job.Fail("应用中断，任务未完成。", canRetry: true)
            : job;

    /// <summary>批量恢复任务列表。</summary>
    public static IReadOnlyList<RenderJob> RecoverAll(IReadOnlyList<RenderJob> jobs) =>
        jobs.Select(Recover).ToList();
}
