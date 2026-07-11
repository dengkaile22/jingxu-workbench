namespace JingXu.Workbench.Domain.Rendering;

/// <summary>
/// 输出质量档位。对应规格中的无损 / 高质量 / 平衡 / 小体积。
/// </summary>
public enum QualityPreset
{
    /// <summary>仅在无滤镜且流结构兼容时可用的直拷。</summary>
    Lossless,

    /// <summary>高质量：默认 CRF 18、AAC 192 kbps。</summary>
    High,

    /// <summary>平衡：默认 CRF 22、AAC 160 kbps。</summary>
    Balanced,

    /// <summary>小体积：默认 CRF 27、AAC 128 kbps。</summary>
    Small
}

/// <summary>
/// 不可变渲染质量配置。硬件编码器不可用时由执行层回退到软件编码。
/// </summary>
public sealed record RenderProfile(
    QualityPreset Quality,
    int? VideoCrf,
    int AudioBitrateKbps,
    bool PreferHardwareEncoder)
{
    /// <summary>高质量默认档。</summary>
    public static RenderProfile High { get; } = new(QualityPreset.High, 18, 192, PreferHardwareEncoder: true);

    /// <summary>平衡默认档。</summary>
    public static RenderProfile Balanced { get; } = new(QualityPreset.Balanced, 22, 160, PreferHardwareEncoder: true);

    /// <summary>小体积默认档。</summary>
    public static RenderProfile Small { get; } = new(QualityPreset.Small, 27, 128, PreferHardwareEncoder: true);

    /// <summary>无损直拷档（无 CRF；实际是否可用由预检决定）。</summary>
    public static RenderProfile Lossless { get; } = new(QualityPreset.Lossless, null, 0, PreferHardwareEncoder: false);

    /// <summary>视频 CRF（无损档为 <c>null</c>）。</summary>
    public int? Crf => VideoCrf;

    /// <summary>音频码率（kbps）。</summary>
    public int AudioKbps => AudioBitrateKbps;

    /// <summary>按质量档位返回默认配置。</summary>
    public static RenderProfile For(QualityPreset preset) =>
        preset switch
        {
            QualityPreset.Lossless => Lossless,
            QualityPreset.High => High,
            QualityPreset.Balanced => Balanced,
            QualityPreset.Small => Small,
            _ => throw new ArgumentOutOfRangeException(nameof(preset), preset, "未知的质量档位。")
        };
}
