using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Domain.Rendering;

/// <summary>输出画幅预设。</summary>
public enum OutputCanvasPreset
{
    /// <summary>继承第一条素材的分辨率。</summary>
    InheritFirst,

    /// <summary>竖屏 9:16（1080×1920）。</summary>
    Vertical9x16,

    /// <summary>横屏 16:9（1920×1080）。</summary>
    Horizontal16x9,

    /// <summary>方形 1:1（1080×1080）。</summary>
    Square1x1,

    /// <summary>竖屏 3:4（1080×1440）。</summary>
    Portrait3x4,

    /// <summary>自定义宽高。</summary>
    Custom
}

/// <summary>
/// 混剪「统一比例」策略：控制成片画幅与素材/蒙版各自的 Fit 模式。
/// </summary>
public sealed record UnifiedAspectPolicy(
    bool IsEnabled,
    OutputCanvasPreset Preset = OutputCanvasPreset.Vertical9x16,
    int? CustomWidth = null,
    int? CustomHeight = null,
    AspectFitMode ClipFitMode = AspectFitMode.CenterCrop,
    OverlayFitMode OverlayFitMode = OverlayFitMode.FillCrop)
{
    /// <summary>关闭统一比例时的默认策略。</summary>
    public static UnifiedAspectPolicy Disabled { get; } = new(false);

    /// <summary>解析为入队用的 <see cref="OutputAspect"/>。</summary>
    public Result<OutputAspect> ToOutputAspect()
    {
        if (!IsEnabled)
        {
            return Result<OutputAspect>.Success(OutputAspect.InheritFirst);
        }

        return Preset switch
        {
            OutputCanvasPreset.InheritFirst =>
                Result<OutputAspect>.Success(OutputAspect.InheritFirst with { FitMode = ClipFitMode }),
            OutputCanvasPreset.Vertical9x16 =>
                Result<OutputAspect>.Success(OutputAspect.Custom(1080, 1920, ClipFitMode)),
            OutputCanvasPreset.Horizontal16x9 =>
                Result<OutputAspect>.Success(OutputAspect.Custom(1920, 1080, ClipFitMode)),
            OutputCanvasPreset.Square1x1 =>
                Result<OutputAspect>.Success(OutputAspect.Custom(1080, 1080, ClipFitMode)),
            OutputCanvasPreset.Portrait3x4 =>
                Result<OutputAspect>.Success(OutputAspect.Custom(1080, 1440, ClipFitMode)),
            OutputCanvasPreset.Custom => ResolveCustomOutputAspect(),
            _ => Result<OutputAspect>.Failure("未知的画幅预设。")
        };
    }

    private Result<OutputAspect> ResolveCustomOutputAspect()
    {
        if (CustomWidth is > 0 && CustomHeight is > 0)
        {
            return Result<OutputAspect>.Success(
                OutputAspect.Custom(CustomWidth.Value, CustomHeight.Value, ClipFitMode));
        }

        return Result<OutputAspect>.Failure("自定义画幅的宽度与高度必须大于零。");
    }

    /// <summary>启用统一比例时，将蒙版 Fit 模式应用到各层（保留位置/缩放/旋转/羽化）。</summary>
    public IReadOnlyList<OverlayLayer> ApplyOverlayFit(IReadOnlyList<OverlayLayer> layers)
    {
        ArgumentNullException.ThrowIfNull(layers);

        if (!IsEnabled || layers.Count == 0)
        {
            return layers;
        }

        return layers.Select(layer => layer with { Fit = OverlayFitMode }).ToArray();
    }

    /// <summary>生成混剪页预览说明（中文）。</summary>
    public string BuildPreviewDescription(int? firstClipWidth = null, int? firstClipHeight = null)
    {
        if (!IsEnabled)
        {
            return "未启用统一比例：成片继承第一条素材画幅；异比例片段将按默认居中裁切拼接。";
        }

        var canvas = DescribeCanvas(firstClipWidth, firstClipHeight);
        var clipFit = DescribeClipFit(ClipFitMode);
        var overlayFit = DescribeOverlayFit(OverlayFitMode);
        return $"已启用统一比例：成片画幅 {canvas}；拼接素材 {clipFit}；蒙版素材 {overlayFit}。渲染前主时间线与蒙版均缩放至同一画幅再叠加。";
    }

    private string DescribeCanvas(int? firstClipWidth, int? firstClipHeight) =>
        Preset switch
        {
            OutputCanvasPreset.InheritFirst => DescribeInheritedCanvas(firstClipWidth, firstClipHeight),
            OutputCanvasPreset.Vertical9x16 => "1080×1920（9:16 竖屏）",
            OutputCanvasPreset.Horizontal16x9 => "1920×1080（16:9 横屏）",
            OutputCanvasPreset.Square1x1 => "1080×1080（1:1 方形）",
            OutputCanvasPreset.Portrait3x4 => "1080×1440（3:4 竖屏）",
            OutputCanvasPreset.Custom => DescribeCustomCanvas(),
            _ => "未知"
        };

    private static string DescribeInheritedCanvas(int? firstClipWidth, int? firstClipHeight)
    {
        if (firstClipWidth is > 0 && firstClipHeight is > 0)
        {
            return $"继承首段 {firstClipWidth}×{firstClipHeight}";
        }

        return "继承首段素材分辨率";
    }

    private string DescribeCustomCanvas()
    {
        if (CustomWidth is > 0 && CustomHeight is > 0)
        {
            return $"{CustomWidth}×{CustomHeight}（自定义）";
        }

        return "自定义（请填写有效宽高）";
    }

    private static string DescribeClipFit(AspectFitMode fit) =>
        fit switch
        {
            AspectFitMode.CenterCrop => "Cover 居中裁切",
            AspectFitMode.Letterbox => "Contain 完整适配（黑边）",
            AspectFitMode.Stretch => "Stretch 拉伸填满",
            AspectFitMode.BlurBackground => "模糊背景填充",
            _ => fit.ToString()
        };

    private static string DescribeOverlayFit(OverlayFitMode fit) =>
        fit switch
        {
            OverlayFitMode.FillCrop => "Cover 填满裁切",
            OverlayFitMode.Contain => "Contain 完整适配",
            OverlayFitMode.Stretch => "Stretch 拉伸",
            OverlayFitMode.MatchCanvasCrop => "先裁成画幅再覆盖",
            _ => fit.ToString()
        };

    /// <summary>
    /// 统一比例为 3:4 竖屏时的推荐蒙版适配：先把蒙版裁成画幅比例再覆盖（对齐剪映手动流程）。
    /// </summary>
    public static OverlayFitMode RecommendedOverlayFit(OutputCanvasPreset preset) =>
        preset == OutputCanvasPreset.Portrait3x4
            ? OverlayFitMode.MatchCanvasCrop
            : OverlayFitMode.FillCrop;
}
