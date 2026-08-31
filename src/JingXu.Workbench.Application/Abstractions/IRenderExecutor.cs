using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Abstractions;

/// <summary>
/// 渲染进度更新。
/// </summary>
public sealed record RenderProgress(TimeSpan Position, double Speed, double? Percent);

/// <summary>
/// 渲染失败信息（中文摘要）。
/// </summary>
public sealed record RenderFailure(string Message);

/// <summary>
/// 渲染执行结果。
/// </summary>
public sealed record RenderExecutionResult(
    bool IsSuccess,
    RenderFailure? FailureInfo,
    bool IsCancelled,
    string? Notice = null)
{
    public static RenderExecutionResult Success(string? notice = null) =>
        new(true, null, false, notice);

    public static RenderExecutionResult Failed(string message) =>
        new(false, new RenderFailure(message), false, null);

    public static RenderExecutionResult Cancelled() => new(false, null, true, null);
}

/// <summary>
/// 执行单个渲染任务。实现负责调用 FFmpeg（通过 ArgumentList）并报告进度。
/// </summary>
public interface IRenderExecutor
{
    Task<RenderExecutionResult> ExecuteAsync(
        RenderJob job,
        IProgress<RenderProgress>? progress,
        CancellationToken cancellationToken);
}

/// <summary>
/// 渲染队列持久化存储。每次状态转移前必须先持久化成功，再发布可观察队列。
/// </summary>
public interface IRenderQueueStore
{
    IReadOnlyList<RenderJob> Jobs { get; }

    Task PersistAsync(IReadOnlyList<RenderJob> jobs, CancellationToken cancellationToken);
}
