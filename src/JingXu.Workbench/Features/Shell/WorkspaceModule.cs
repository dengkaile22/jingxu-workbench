namespace JingXu.Workbench.Features.Shell;

/// <summary>
/// 工作台的功能模块。对应左侧模块导航栏的条目。
/// 未实现具体视图的模块在 M1 阶段导航项禁用，但实例仍在
/// <see cref="ShellViewModel"/> 中预创建缓存，供后续里程碑启用。
/// </summary>
public enum WorkspaceModule
{
    /// <summary>批量混剪（M2 启用）。</summary>
    Composition,

    /// <summary>蒙版模板（M2 启用）。</summary>
    Overlays,

    /// <summary>字幕处理（M3 启用）。</summary>
    Subtitles,

    /// <summary>任务队列。</summary>
    Queue,

    /// <summary>设置。</summary>
    Settings
}
