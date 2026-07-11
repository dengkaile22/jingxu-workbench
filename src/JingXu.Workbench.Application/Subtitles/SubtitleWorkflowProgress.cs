namespace JingXu.Workbench.Application.Subtitles;

/// <summary>字幕工作流阶段进度。</summary>
public sealed record SubtitleWorkflowProgress(string Phase, string Message, double? Percent);
