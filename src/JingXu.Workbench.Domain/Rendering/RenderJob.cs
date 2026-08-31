namespace JingXu.Workbench.Domain.Rendering;

/// <summary>
/// 渲染任务状态机。
/// </summary>
public enum JobState
{
    /// <summary>草稿，尚未入队。</summary>
    Draft,

    /// <summary>已入队，等待调度。</summary>
    Queued,

    /// <summary>正在准备（预检、构建命令）。</summary>
    Preparing,

    /// <summary>正在渲染。</summary>
    Running,

    /// <summary>正在完成（验证输出、移动文件、生成封面）。</summary>
    Finalizing,

    /// <summary>已完成。</summary>
    Completed,

    /// <summary>已失败。</summary>
    Failed,

    /// <summary>已取消。</summary>
    Cancelled
}

/// <summary>
/// 不可变渲染任务记录。仅通过合法状态转移方法生成新实例。
/// </summary>
public sealed record RenderJob
{
    public Guid Id { get; init; }
    public JobState State { get; init; }
    public string? Error { get; init; }
    public string? Notice { get; init; }
    public bool CanRetry { get; init; }
    public int AttemptCount { get; init; }
    public DateTimeOffset CreatedAt { get; init; }
    public DateTimeOffset? CompletedAt { get; init; }

    /// <summary>入队时的不可变请求快照；占位任务可为空。</summary>
    public RenderRequest? Request { get; init; }

    /// <summary>渲染进度百分比（0–100）；未知时为 null。</summary>
    public double? ProgressPercent { get; init; }

    /// <summary>当前进度阶段文案（如「渲染中 42%」）。</summary>
    public string? ProgressPhase { get; init; }

    private RenderJob() { }

    /// <summary>更新进度字段（不改变任务状态）。</summary>
    public RenderJob WithProgress(double? percent, string? phase) =>
        this with
        {
            ProgressPercent = percent is null ? null : Math.Clamp(percent.Value, 0, 100),
            ProgressPhase = phase
        };

    /// <summary>创建草稿任务。</summary>
    public static RenderJob CreateDraft() =>
        new()
        {
            Id = Guid.NewGuid(),
            State = JobState.Draft,
            CreatedAt = DateTimeOffset.UtcNow
        };

    /// <summary>创建已入队任务。</summary>
    public static RenderJob CreateQueued() =>
        CreateDraft() with { State = JobState.Queued };

    /// <summary>携带请求快照创建已入队任务。</summary>
    public static RenderJob CreateQueued(RenderRequest request) =>
        CreateDraft() with { State = JobState.Queued, Request = request };

    /// <summary>入队。</summary>
    public RenderJob Enqueue() =>
        State is JobState.Draft
            ? this with { State = JobState.Queued }
            : throw new InvalidOperationException($"无法从状态 {State} 入队。");

    /// <summary>开始准备。</summary>
    public RenderJob BeginPrepare() =>
        State is JobState.Queued
            ? this with { State = JobState.Preparing, AttemptCount = AttemptCount + 1 }
            : throw new InvalidOperationException($"无法从状态 {State} 开始准备。");

    /// <summary>开始渲染。</summary>
    public RenderJob BeginRun() =>
        State is JobState.Preparing
            ? this with { State = JobState.Running }
            : throw new InvalidOperationException($"无法从状态 {State} 开始渲染。");

    /// <summary>开始完成阶段。</summary>
    public RenderJob BeginFinalize() =>
        State is JobState.Running
            ? this with { State = JobState.Finalizing }
            : throw new InvalidOperationException($"无法从状态 {State} 开始完成。");

    /// <summary>标记完成。</summary>
    public RenderJob Complete(string? notice = null) =>
        State is JobState.Finalizing
            ? this with
            {
                State = JobState.Completed,
                CompletedAt = DateTimeOffset.UtcNow,
                Notice = notice,
                ProgressPercent = 100,
                ProgressPhase = null
            }
            : throw new InvalidOperationException($"无法从状态 {State} 标记完成。");

    /// <summary>标记失败。</summary>
    public RenderJob Fail(string error, bool canRetry = true) =>
        State is JobState.Preparing or JobState.Running or JobState.Finalizing
            ? this with
            {
                State = JobState.Failed,
                Error = error,
                Notice = null,
                CanRetry = canRetry,
                ProgressPhase = null
            }
            : throw new InvalidOperationException($"无法从状态 {State} 标记失败。");

    /// <summary>取消。</summary>
    public RenderJob Cancel() =>
        State is JobState.Queued or JobState.Preparing or JobState.Running or JobState.Finalizing
            ? this with
            {
                State = JobState.Cancelled,
                CompletedAt = DateTimeOffset.UtcNow,
                Notice = null,
                ProgressPhase = null
            }
            : throw new InvalidOperationException($"无法从状态 {State} 取消。");

    /// <summary>重试（从失败恢复为入队）。</summary>
    public RenderJob Retry() =>
        State is JobState.Failed && CanRetry
            ? this with
            {
                State = JobState.Queued,
                Error = null,
                Notice = null,
                ProgressPercent = null,
                ProgressPhase = null
            }
            : throw new InvalidOperationException($"无法从状态 {State} 重试（CanRetry={CanRetry}）。");

    /// <summary>
    /// 创建处于 Running 状态的任务（用于测试恢复场景）。
    /// </summary>
    internal static RenderJob Running(Guid id) =>
        new()
        {
            Id = id,
            State = JobState.Running,
            CreatedAt = DateTimeOffset.UtcNow,
            AttemptCount = 1
        };

    /// <summary>
    /// 创建处于指定状态的任务（用于测试恢复场景）。
    /// </summary>
    internal static RenderJob WithState(JobState state) =>
        new()
        {
            Id = Guid.NewGuid(),
            State = state,
            CreatedAt = DateTimeOffset.UtcNow
        };
}
