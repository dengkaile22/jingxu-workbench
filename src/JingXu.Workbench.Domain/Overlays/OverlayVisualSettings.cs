using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Domain.Overlays;

/// <summary>
/// 可复用的蒙版视觉参数快照。
/// 不包含素材路径、名称、时长、时间轴、音频或形状数据，因此可安全套用到素材库中的其他蒙版。
/// </summary>
public sealed record OverlayVisualSettings(
    NormalizedRect Bounds,
    double Opacity,
    OverlayFitMode Fit,
    double Scale = OverlayLayer.DefaultScale,
    double OffsetX = 0,
    double OffsetY = 0,
    double RotationDegrees = 0,
    double Feather = 0,
    double TopFade = 0,
    double SourceCropY = 0,
    NormalizedRect? SourceCropBounds = null)
{
    /// <summary>从蒙版层提取仅可复用的视觉参数。</summary>
    public static OverlayVisualSettings FromLayer(OverlayLayer layer)
    {
        ArgumentNullException.ThrowIfNull(layer);
        return new OverlayVisualSettings(
            layer.Bounds,
            layer.Opacity,
            layer.Fit,
            layer.Scale,
            layer.OffsetX,
            layer.OffsetY,
            layer.RotationDegrees,
            layer.Feather,
            layer.TopFade,
            layer.SourceCropY,
            layer.SourceCropBounds);
    }

    /// <summary>将视觉参数套用到目标层，保留其素材与时间轴等非视觉字段。</summary>
    public OverlayLayer ApplyTo(OverlayLayer layer)
    {
        ArgumentNullException.ThrowIfNull(layer);
        var validation = Validate();
        if (!validation.IsSuccess)
        {
            throw new InvalidOperationException(validation.Error);
        }

        return layer with
        {
            Bounds = Bounds,
            Opacity = Opacity,
            Fit = Fit,
            Scale = Scale,
            OffsetX = OffsetX,
            OffsetY = OffsetY,
            RotationDegrees = RotationDegrees,
            Feather = Feather,
            TopFade = TopFade,
            SourceCropY = SourceCropY,
            SourceCropBounds = SourceCropBounds
        };
    }

    /// <summary>验证快照中的归一化区域和所有视觉参数范围。</summary>
    public Result<OverlayVisualSettings> Validate()
    {
        var boundsError = ValidateRect(Bounds, "蒙版区域");
        if (boundsError is not null)
        {
            return Result<OverlayVisualSettings>.Failure(boundsError);
        }

        if (!IsInRange(Opacity, 0, 1))
        {
            return Result<OverlayVisualSettings>.Failure("蒙版不透明度必须为 0 到 1 之间的有限数值。");
        }

        if (!Enum.IsDefined<OverlayFitMode>(Fit))
        {
            return Result<OverlayVisualSettings>.Failure("蒙版适配方式无效。");
        }

        if (!IsInRange(Scale, OverlayLayer.MinScale, OverlayLayer.MaxScale))
        {
            return Result<OverlayVisualSettings>.Failure(
                $"蒙版缩放必须在 {OverlayLayer.MinScale} 到 {OverlayLayer.MaxScale} 之间。");
        }

        if (!IsInRange(OffsetX, OverlayLayer.MinOffset, OverlayLayer.MaxOffset) ||
            !IsInRange(OffsetY, OverlayLayer.MinOffset, OverlayLayer.MaxOffset))
        {
            return Result<OverlayVisualSettings>.Failure(
                $"蒙版位移必须在 {OverlayLayer.MinOffset} 到 {OverlayLayer.MaxOffset} 之间。");
        }

        if (!IsInRange(RotationDegrees, OverlayLayer.MinRotationDegrees, OverlayLayer.MaxRotationDegrees))
        {
            return Result<OverlayVisualSettings>.Failure(
                $"蒙版旋转必须在 {OverlayLayer.MinRotationDegrees} 到 {OverlayLayer.MaxRotationDegrees} 度之间。");
        }

        if (!IsInRange(Feather, OverlayLayer.MinFeather, OverlayLayer.MaxFeather))
        {
            return Result<OverlayVisualSettings>.Failure(
                $"蒙版羽化必须在 {OverlayLayer.MinFeather} 到 {OverlayLayer.MaxFeather} 之间。");
        }

        if (!IsInRange(TopFade, OverlayLayer.MinTopFade, OverlayLayer.MaxTopFade))
        {
            return Result<OverlayVisualSettings>.Failure(
                $"蒙版上半渐变必须在 {OverlayLayer.MinTopFade} 到 {OverlayLayer.MaxTopFade} 之间。");
        }

        if (!IsInRange(SourceCropY, OverlayLayer.MinSourceCropY, OverlayLayer.MaxSourceCropY))
        {
            return Result<OverlayVisualSettings>.Failure(
                $"蒙版选取偏移必须在 {OverlayLayer.MinSourceCropY} 到 {OverlayLayer.MaxSourceCropY} 之间。");
        }

        if (SourceCropBounds is { } sourceCropBounds)
        {
            var cropError = ValidateRect(sourceCropBounds, "蒙版源裁切区域");
            if (cropError is not null)
            {
                return Result<OverlayVisualSettings>.Failure(cropError);
            }
        }

        return Result<OverlayVisualSettings>.Success(this);
    }

    private static bool IsInRange(double value, double minimum, double maximum) =>
        double.IsFinite(value) && value >= minimum && value <= maximum;

    private static string? ValidateRect(NormalizedRect rect, string label)
    {
        if (!double.IsFinite(rect.X) || !double.IsFinite(rect.Y) ||
            !double.IsFinite(rect.Width) || !double.IsFinite(rect.Height))
        {
            return $"{label}必须使用有限数值。";
        }

        var result = NormalizedRect.Create(rect.X, rect.Y, rect.Width, rect.Height);
        return result.IsSuccess ? null : $"{label}无效：{result.Error}";
    }
}
