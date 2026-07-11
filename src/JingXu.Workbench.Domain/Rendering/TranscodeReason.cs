namespace JingXu.Workbench.Domain.Rendering;

/// <summary>必须重新编码的原因。</summary>
public enum TranscodeReason
{
    /// <summary>存在视频蒙版覆盖层。</summary>
    Overlay,

    /// <summary>存在差异化/滤镜效果。</summary>
    Effects,

    /// <summary>画幅或分辨率与源素材不一致。</summary>
    AspectChange,

    /// <summary>存在字幕处理或烧录。</summary>
    Subtitle,

    /// <summary>存在 BGM 或音频混合。</summary>
    Bgm,

    /// <summary>输入流编码或结构不兼容，无法直拷。</summary>
    StreamMismatch,

    /// <summary>存在非零转场重叠。</summary>
    Transition,

    /// <summary>用户选择了需重新编码的质量档。</summary>
    QualityPreset
}
