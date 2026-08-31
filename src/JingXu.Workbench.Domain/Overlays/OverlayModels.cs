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
    /// <summary>填满裁切（默认）：按覆盖区比例 Cover，异比例（如 9:16→上半横框）会裁掉大量上下内容。</summary>
    FillCrop,

    /// <summary>完整适配（Contain）。</summary>
    Contain,

    /// <summary>拉伸。</summary>
    Stretch,

    /// <summary>
    /// 先按成片画幅比例中心裁切蒙版源（可上下偏移选取），再对齐画布后取覆盖区。
    /// 对齐剪映「蒙版裁成 3:4 再覆盖商品」；统一比例 3:4 时的推荐默认。
    /// </summary>
    MatchCanvasCrop
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
/// <param name="Feather">分割线/边缘羽化强度（0~1，0 为硬边，1 为最大羽化；同时软化覆盖区底边与 alpha 边缘）。</param>
/// <param name="TopFade">
/// 红框区域内垂直 alpha 渐变：0 关闭；&gt;0 表示叠层在边界框内自底（画面中间一带）实、向顶变淡。
/// 默认 1=整框高度线性羽化（中间实 → 顶透明）；下半屏无蒙版因 Bounds 只覆盖上半红框。
/// </param>
/// <param name="SourceCropY">
/// 蒙版源按画幅比例裁切时的上下选取偏移（-1 偏上 / 0 居中 / 1 偏下）。
/// 仅 <see cref="OverlayFitMode.MatchCanvasCrop"/> 生效；对应剪映 3:4 选框上下拖动。
/// </param>
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
    double Feather = 0,
    double TopFade = 0,
    double SourceCropY = 0,
    NormalizedRect? SourceCropBounds = null)
{
    /// <summary>
    /// 主片自叠影哨兵路径：渲染时从当前主轨画面 split，而非另开外部输入。
    /// </summary>
    public const string SelfSourceMarker = ":self:";

    /// <summary>默认透明度。</summary>
    public const double DefaultOpacity = 1.0;

    /// <summary>全屏低透明度模式默认透明度。</summary>
    public const double FullFrameDefaultOpacity = 0.20;

    /// <summary>导入蒙版默认透明度（红框区内半透明叠影；略降以免盖住下半商品主体）。</summary>
    public const double GhostOverlayOpacity = 0.28;

    /// <summary>历史兼容：旧自叠影放大倍率（导入默认不再放大）。</summary>
    public const double GhostOverlayScale = 1.0;

    /// <summary>历史兼容：导入默认不再垂直偏移。</summary>
    public const double GhostOverlayOffsetY = 0;

    /// <summary>
    /// 红框内垂直渐变：1=整框高度自底实到顶淡（中间→上）。
    /// </summary>
    public const double GhostOverlayTopFade = 1.0;

    /// <summary>
    /// 导入/叠影蒙版默认分割线羽化：覆盖区底边软接到下层商品，避免硬切缝。
    /// </summary>
    public const double GhostOverlayFeather = 0.28;

    /// <summary>是否为主片自叠影（源等于当前成片画面）。</summary>
    public bool IsSelfSource =>
        string.Equals(SourcePath, SelfSourceMarker, StringComparison.Ordinal);

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

    /// <summary>上半垂直渐变下界（0=关闭）。</summary>
    public const double MinTopFade = 0.0;

    /// <summary>上半垂直渐变上界（1=整框高度线性中间实→顶淡）。</summary>
    public const double MaxTopFade = 1.0;

    /// <summary>蒙版源裁切上下偏移下界（偏上）。</summary>
    public const double MinSourceCropY = -1.0;

    /// <summary>蒙版源裁切上下偏移上界（偏下）。</summary>
    public const double MaxSourceCropY = 1.0;

    /// <summary>
    /// 导入蒙版素材默认：FreeCover 对准参考图上半红框 + 中间→上垂直 alpha。
    /// Bounds≈Y 0.05–0.47、Opacity≈0.28、Scale=1、TopFade=1。
    /// Fit 仍为 FillCrop；统一比例 3:4 入队时由混剪策略改为 MatchCanvasCrop。
    /// </summary>
    public static OverlayLayer CreateImportedMaskPreset(string sourcePath, TimeSpan sourceDuration) =>
        CreateGhostOverlayPreset(sourcePath, sourceDuration);

    /// <summary>
    /// 3:4 成片推荐：画幅裁切覆盖（先裁蒙版为画幅比例再叠），可配合 SourceCropY 上下选取。
    /// </summary>
    public static OverlayLayer CreateImportedMaskPresetForCanvas(
        string sourcePath,
        TimeSpan sourceDuration,
        OverlayFitMode fit = OverlayFitMode.MatchCanvasCrop) =>
        CreateGhostOverlayPreset(sourcePath, sourceDuration) with { Fit = fit };

    /// <summary>
    /// 主片自叠影（次要能力）：把当前成片裁到红框区半透明叠回，带中间→上渐变。
    /// <paramref name="sourceDuration"/> 建议用成片时长，避免循环计数失真。
    /// </summary>
    public static OverlayLayer CreateSelfGhostPreset(TimeSpan sourceDuration) =>
        CreateGhostOverlayPreset(SelfSourceMarker, sourceDuration) with
        {
            Name = "自叠影"
        };

    /// <summary>
    /// 叠影预设：上半红框 FreeCover + 框内中间→上垂直 alpha（下半干净）。
    /// </summary>
    public static OverlayLayer CreateGhostOverlayPreset(string sourcePath, TimeSpan sourceDuration) =>
        new(
            "叠影蒙版",
            sourcePath,
            sourceDuration,
            OverlayMode.FreeCover,
            ImportedMaskBounds,
            GhostOverlayOpacity,
            StartClipIndex: 1,
            ZIndex: 0,
            Fit: OverlayFitMode.FillCrop,
            Scale: GhostOverlayScale,
            OffsetY: GhostOverlayOffsetY,
            Feather: GhostOverlayFeather,
            TopFade: GhostOverlayTopFade);

    /// <summary>
    /// 导入蒙版默认边界（参考图大红框：上半屏略收，约 Y 0.05–0.47、X 近全宽略缩，减轻盖住下半商品）。
    /// </summary>
    public static NormalizedRect ImportedMaskBounds { get; } = new(0.05, 0.05, 0.90, 0.42);

    /// <summary>右下角人物画中画边界（可选预设，非导入默认）。</summary>
    public static NormalizedRect PipMaskBounds { get; } = new(0.52, 0.52, 0.42, 0.42);

    /// <summary>创建右下角人物画中画层（不透明 Contain）。</summary>
    public static OverlayLayer CreatePipMaskPreset(string sourcePath, TimeSpan sourceDuration) =>
        new(
            "画中画蒙版",
            sourcePath,
            sourceDuration,
            OverlayMode.FreeCover,
            PipMaskBounds,
            DefaultOpacity,
            StartClipIndex: 1,
            ZIndex: 0,
            Fit: OverlayFitMode.Contain);

    /// <summary>创建截图风格顶部全宽自由覆盖预设（横幅/截图类蒙版；人物蒙版请用 <see cref="CreateImportedMaskPreset"/>）。</summary>
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

    /// <summary>提取可复用的视觉参数快照。</summary>
    public OverlayVisualSettings ToVisualSettings() => OverlayVisualSettings.FromLayer(this);

    /// <summary>套用视觉参数快照，同时保留本层素材、时间轴、音频和形状数据。</summary>
    public OverlayLayer WithVisualSettings(OverlayVisualSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        return settings.ApplyTo(this);
    }

    /// <summary>验证层参数。</summary>
    public Result<OverlayLayer> Validate(int clipCount)
    {
        if (string.IsNullOrWhiteSpace(SourcePath))
        {
            return Result<OverlayLayer>.Failure("蒙版素材路径不能为空。");
        }

        if (!IsSelfSource && SourcePath.StartsWith(':'))
        {
            return Result<OverlayLayer>.Failure("未知的蒙版源标记。");
        }

        if (SourceDuration <= TimeSpan.Zero)
        {
            return Result<OverlayLayer>.Failure("蒙版素材时长必须大于零。");
        }

        if (Opacity is < 0 or > 1)
        {
            return Result<OverlayLayer>.Failure("蒙版不透明度必须在 0 到 1 之间。");
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

        if (TopFade is < MinTopFade or > MaxTopFade)
        {
            return Result<OverlayLayer>.Failure($"蒙版上半渐变必须在 {MinTopFade} 到 {MaxTopFade} 之间。");
        }

        if (SourceCropY is < MinSourceCropY or > MaxSourceCropY)
        {
            return Result<OverlayLayer>.Failure($"蒙版选取偏移必须在 {MinSourceCropY} 到 {MaxSourceCropY} 之间。");
        }

        var visualValidation = ToVisualSettings().Validate();
        if (!visualValidation.IsSuccess)
        {
            return Result<OverlayLayer>.Failure(visualValidation.Error!);
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
    DateTimeOffset? LastUsedAt,
    OverlayVisualSettings? VisualSettings = null);

/// <summary>解析后的蒙版时间轴。</summary>
public sealed record ResolvedOverlay(
    OverlayLayer Layer,
    TimeSpan Start,
    TimeSpan ActiveDuration,
    int LoopCount,
    TimeSpan LastLoopDuration);
