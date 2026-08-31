using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Domain.Rendering;

/// <summary>
/// 入队时的不可变渲染请求快照。后续界面修改不影响已入队任务。
/// </summary>
public sealed record RenderRequest(
    CompositionPlan Plan,
    string OutputPath,
    RenderProfile Profile,
    OutputAspect Aspect,
    IReadOnlyList<OverlayLayer> OverlayLayers,
    bool HasOverlays = false,
    bool HasEffects = false,
    bool HasSubtitles = false,
    bool HasBgm = false,
    bool HasMainMaterialBoost = false,
    SubtitleBurnInPlan? SubtitleBurn = null,
    MaterializedEffect? Effect = null,
    BgmMixPlan? Bgm = null,
    IReadOnlyList<ImageSticker> Stickers = null!,
    MaterializedMainMaterialBoost? MainMaterialBoost = null,
    OutputVideoSettings OutputVideoSettings = default,
    DoubleScreenEffectPlan? DoubleScreen = null,
    VideoProcessingMode ProcessingMode = VideoProcessingMode.Auto)
{
    /// <summary>是否包含可编译的蒙版层。</summary>
    public bool HasRenderableOverlays => HasOverlays && (OverlayLayers?.Count ?? 0) > 0;

    /// <summary>是否包含可编译的差异化画面效果或贴纸。</summary>
    public bool HasRenderableEffects =>
        HasEffects && (Effect?.HasVisualAdjustments == true || (Stickers ?? []) is { Count: > 0 } || DoubleScreen is not null);

    /// <summary>是否包含可编译的 BGM 混音。</summary>
    public bool HasRenderableBgm => HasBgm && Bgm is not null;

    /// <summary>是否包含可编译的主素材音量/缩放增强（仅主轨）。</summary>
    public bool HasRenderableMainMaterialBoost =>
        HasMainMaterialBoost && MainMaterialBoost is not null && MainMaterialBoost.IsActive;
}
