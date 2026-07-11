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
    SubtitleBurnInPlan? SubtitleBurn = null,
    MaterializedEffect? Effect = null,
    BgmMixPlan? Bgm = null,
    ImageSticker? Sticker = null)
{
    /// <summary>是否包含可编译的蒙版层。</summary>
    public bool HasRenderableOverlays => HasOverlays && OverlayLayers.Count > 0;

    /// <summary>是否包含可编译的差异化画面效果或贴纸。</summary>
    public bool HasRenderableEffects =>
        HasEffects && (Effect?.HasVisualAdjustments == true || Sticker is not null);

    /// <summary>是否包含可编译的 BGM 混音。</summary>
    public bool HasRenderableBgm => HasBgm && Bgm is not null;
}
