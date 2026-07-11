using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Projects;

/// <summary>
/// 项目服务：管理项目文件和队列恢复。
/// </summary>
public static class ProjectService
{
    /// <summary>
    /// 恢复中断的任务：将处于活跃状态（Preparing/Running/Finalizing）的任务
    /// 标记为可重试的 Failed 状态。
    /// </summary>
    public static IReadOnlyList<RenderJob> RecoverJobs(IReadOnlyList<RenderJob> jobs)
    {
        var recovered = new List<RenderJob>(jobs.Count);
        foreach (var job in jobs)
        {
            if (job.State is JobState.Preparing or JobState.Running or JobState.Finalizing)
            {
                recovered.Add(job.Fail("应用中断，任务未完成。", canRetry: true));
            }
            else
            {
                recovered.Add(job);
            }
        }

        return recovered;
    }
}
