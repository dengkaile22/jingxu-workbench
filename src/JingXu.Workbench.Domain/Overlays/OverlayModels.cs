using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Domain.Overlays;

/// <summary>蒙版叠加模式。</summary>
public enum OverlayMode
{
    /// <summary>自由覆盖层：可调位置、尺寸与透明度。</summary>
    FreeCover,

    /// <summary>全屏低透明度覆盖。</summary>
    FullFrameLowOpacity,

    /// <summary>形状遮罩。</summary>
    ShapeMask
}

/// <summary>蒙版素材在目标区域的适配方式。</summary>
public enum OverlayFitMode
{
    /// <summary>填满裁切（默认）。</summary>
    FillCrop,

    /// <summary>完整适配（Contain）。</summary>
    Contain,

    /// <summary>拉伸。</summary>
    Stretch
}

/// <summary>蒙版音频处理方式。</summary>
public enum OverlayAudioMode
{
    /// <summary>丢弃蒙版音轨（默认）。</summary>
    Discard,

    /// <summary>与主音轨混合。</summary>
    Mix
}

/// <summary>形状遮罩几何类型。</summary>
public enum ShapeKind
{
    Rectangle,
    RoundedRectangle,
    Ellipse,
    ImportedPng
}

/// <summary>蒙版层定义。</summary>
/// <param name="Scale">内容缩放倍率，1.0 为 100%（在边界框内均匀缩放）。</param>
/// <param name="OffsetX">相对画面的水平位移（归一化 -1~1，0 为不偏移）。</param>
/// <param name="OffsetY">相对画面的垂直位移（归一化 -1~1，0 为不偏移）。</param>
/// <param name="RotationDegrees">顺时针旋转角度（-360~360 度）。</param>
/// <param name="Feather">边缘羽化强度（0~1，0 为硬边，1 为最大羽化）。</param>
public sealed record OverlayLayer(
    string Name,
    string SourcePath,
    TimeSpan SourceDuration,
    OverlayMode Mode,
    NormalizedRect Bounds,
    double Opacity,
    int StartClipIndex,
    int ZIndex,
    OverlayFitMode Fit = OverlayFitMode.FillCrop,
    OverlayAudioMode AudioMode = OverlayAudioMode.Discard,
    ShapeKind Shape = ShapeKind.Rectangle,
    string? AlphaPngPath = null,
    double Scale = 1.0,
    double OffsetX = 0,
    double OffsetY = 0,
    double RotationDegrees = 0,
    double Feather = 0)
{
    /// <summary>默认透明度。</summary>
    public const double DefaultOpacity = 1.0;

    /// <summary>全屏低透明度模式默认透明度。</summary>
    public const double FullFrameDefaultOpacity = 0.20;

    /// <summary>默认缩放倍率（100%）。</summary>
    public const double DefaultScale = 1.0;

    /// <summary>允许的最小缩放倍率。</summary>
    public const double MinScale = 0.01;

    /// <summary>允许的最大缩放倍率。</summary>
    public const double MaxScale = 4.0;

    /// <summary>位移归一化下界。</summary>
    public const double MinOffset = -1.0;

    /// <summary>位移归一化上界。</summary>
    public const double MaxOffset = 1.0;

    /// <summary>旋转角度下界（度）。</summary>
    public const double MinRotationDegrees = -360.0;

    /// <summary>旋转角度上界（度）。</summary>
    public const double MaxRotationDegrees = 360.0;

    /// <summary>羽化强度下界。</summary>
    public const double MinFeather = 0.0;

    /// <summary>羽化强度上界。</summary>
    public const double MaxFeather = 1.0;

    /// <summary>创建截图风格顶部全宽自由覆盖预设。</summary>
    public static OverlayLayer CreateScreenshotPreset(string sourcePath, TimeSpan sourceDuration) =>
        new(
            "截图蒙版",
            sourcePath,
            sourceDuration,
            OverlayMode.FreeCover,
            new NormalizedRect(0, 0, 1, 0.48),
            DefaultOpacity,
            StartClipIndex: 1,
            ZIndex: 0);

    /// <summary>创建全屏低透明度覆盖层。</summary>
    public static OverlayLayer CreateFullFramePreset(string sourcePath, TimeSpan sourceDuration) =>
        new(
            "全屏蒙版",
            sourcePath,
            sourceDuration,
            OverlayMode.FullFrameLowOpacity,
            NormalizedRect.FullFrame,
            FullFrameDefaultOpacity,
            StartClipIndex: 1,
            ZIndex: 0,
            Fit: OverlayFitMode.FillCrop);

    /// <summary>创建形状遮罩层。</summary>
    public static OverlayLayer CreateShapeMask(
        string sourcePath,
        TimeSpan sourceDuration,
        NormalizedRect bounds,
        ShapeKind shape = ShapeKind.Rectangle) =>
        new(
            "形状蒙版",
            sourcePath,
            sourceDuration,
            OverlayMode.ShapeMask,
            bounds,
            DefaultOpacity,
            StartClipIndex: 1,
            ZIndex: 0,
            Shape: shape);

    /// <summary>验证层参数。</summary>
    public Result<OverlayLayer> Validate(int clipCount)
    {
        if (string.IsNullOrWhiteSpace(SourcePath))
        {
            return Result<OverlayLayer>.Failure("蒙版素材路径不能为空。");
        }

        if (SourceDuration <= TimeSpan.Zero)
        {
            return Result<OverlayLayer>.Failure("蒙版素材时长必须大于零。");
        }

        if (Opacity is < 0 or > 1)
        {
            return Result<OverlayLayer>.Failure("蒙版透明度必须在 0 到 1 之间。");
        }

        if (StartClipIndex < 1 || StartClipIndex > clipCount)
        {
            return Result<OverlayLayer>.Failure($"起始片段必须在 1 到 {clipCount} 之间。");
        }

        if (Bounds.Width <= 0 || Bounds.Height <= 0)
        {
            return Result<OverlayLayer>.Failure("蒙版区域面积必须大于零。");
        }

        if (Mode == OverlayMode.ShapeMask &&
            Shape == ShapeKind.ImportedPng &&
            string.IsNullOrWhiteSpace(AlphaPngPath))
        {
            return Result<OverlayLayer>.Failure("导入 PNG 遮罩时必须提供 Alpha 图像路径。");
        }

        if (Scale is < MinScale or > MaxScale)
        {
            return Result<OverlayLayer>.Failure($"蒙版缩放必须在 {MinScale} 到 {MaxScale} 之间。");
        }

        if (OffsetX is < MinOffset or > MaxOffset || OffsetY is < MinOffset or > MaxOffset)
        {
            return Result<OverlayLayer>.Failure($"蒙版位移必须在 {MinOffset} 到 {MaxOffset} 之间。");
        }

        if (RotationDegrees is < MinRotationDegrees or > MaxRotationDegrees)
        {
            return Result<OverlayLayer>.Failure($"蒙版旋转必须在 {MinRotationDegrees} 到 {MaxRotationDegrees} 度之间。");
        }

        if (Feather is < MinFeather or > MaxFeather)
        {
            return Result<OverlayLayer>.Failure($"蒙版羽化必须在 {MinFeather} 到 {MaxFeather} 之间。");
        }

        return Result<OverlayLayer>.Success(this);
    }
}

/// <summary>蒙版素材库条目。</summary>
public sealed record OverlayLibraryEntry(
    Guid Id,
    string FilePath,
    IReadOnlyList<string> Tags,
    string? ThumbnailPath,
    DateTimeOffset? LastUsedAt);

/// <summary>解析后的蒙版时间轴。</summary>
public sealed record ResolvedOverlay(
    OverlayLayer Layer,
    TimeSpan Start,
    TimeSpan ActiveDuration,
    int LoopCount,
    TimeSpan LastLoopDuration);
