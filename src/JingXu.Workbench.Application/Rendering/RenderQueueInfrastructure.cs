using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Rendering;

/// <summary>
/// 内存队列存储。用于测试与壳层最小接线；生产环境可替换为基于原子 JSON 的实现。
/// </summary>
public sealed class InMemoryRenderQueueStore : IRenderQueueStore
{
    private IReadOnlyList<RenderJob> _jobs = [];

    public IReadOnlyList<RenderJob> Jobs => _jobs;

    public Task PersistAsync(IReadOnlyList<RenderJob> jobs, CancellationToken cancellationToken)
    {
        _jobs = jobs.ToList();
        return Task.CompletedTask;
    }
}

/// <summary>
/// 占位渲染执行器：立即成功。真实 FFmpeg 管线由后续任务接入。
/// </summary>
public sealed class NoOpRenderExecutor : IRenderExecutor
{
    public Task<RenderExecutionResult> ExecuteAsync(
        RenderJob job,
        IProgress<RenderProgress>? progress,
        CancellationToken cancellationToken)
    {
        if (cancellationToken.IsCancellationRequested)
        {
            return Task.FromResult(RenderExecutionResult.Cancelled());
        }

        return Task.FromResult(RenderExecutionResult.Success());
    }
}
