namespace JingXu.Workbench.Infrastructure.Runtime;

/// <summary>单个运行时组件的诊断结果。</summary>
public sealed record RuntimeComponentStatus(
    RuntimeKind Kind,
    string DisplayName,
    bool IsAvailable,
    bool IsRequired,
    string Message,
    string SuggestedAction,
    string? ResolvedPath,
    RuntimeSource? Source);
