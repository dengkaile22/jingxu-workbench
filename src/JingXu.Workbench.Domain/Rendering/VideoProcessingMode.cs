namespace JingXu.Workbench.Domain.Rendering;

/// <summary>
/// 用户为单条渲染任务选择的视频编码处理策略。
/// </summary>
public enum VideoProcessingMode
{
    /// <summary>优先使用可用的 GPU 编码器，否则使用 CPU。</summary>
    Auto,

    /// <summary>始终使用 CPU 软件编码。</summary>
    Cpu,

    /// <summary>优先使用 GPU 编码器；不可用或初始化失败时安全回退 CPU。</summary>
    Gpu
}
