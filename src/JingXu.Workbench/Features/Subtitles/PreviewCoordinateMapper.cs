using System.Windows;
using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Features.Subtitles;

/// <summary>
/// 预览画面中的视频内容矩形（考虑信箱、旋转与 DPI 缩放）。
/// </summary>
/// <param name="ContentLeft">内容区左边界（视口坐标）。</param>
/// <param name="ContentTop">内容区上边界（视口坐标）。</param>
/// <param name="ContentWidth">内容区宽度（视口坐标）。</param>
/// <param name="ContentHeight">内容区高度（视口坐标）。</param>
/// <param name="FrameWidth">标准化后的帧宽（像素）。</param>
/// <param name="FrameHeight">标准化后的帧高（像素）。</param>
public readonly record struct PreviewLayout(
    double ContentLeft,
    double ContentTop,
    double ContentWidth,
    double ContentHeight,
    int FrameWidth,
    int FrameHeight)
{
    /// <summary>内容区右边界。</summary>
    public double ContentRight => ContentLeft + ContentWidth;

    /// <summary>内容区下边界。</summary>
    public double ContentBottom => ContentTop + ContentHeight;
}

/// <summary>
/// 在 WPF 预览视口与归一化视频坐标之间转换，处理 Uniform 信箱、旋转与像素宽高比。
/// </summary>
public sealed class PreviewCoordinateMapper
{
    private readonly int _frameWidth;
    private readonly int _frameHeight;
    private readonly int _displayWidth;
    private readonly int _displayHeight;

    public PreviewCoordinateMapper(int frameWidth, int frameHeight, int rotationDegrees, double pixelAspectRatio = 1.0)
    {
        if (frameWidth <= 0 || frameHeight <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(frameWidth), "帧尺寸必须大于零。");
        }

        if (pixelAspectRatio <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(pixelAspectRatio), "像素宽高比必须大于零。");
        }

        _frameWidth = frameWidth;
        _frameHeight = frameHeight;

        var normalizedRotation = ((rotationDegrees % 360) + 360) % 360;
        var swapAxes = normalizedRotation is 90 or 270;
        var rawWidth = swapAxes ? frameHeight : frameWidth;
        var rawHeight = swapAxes ? frameWidth : frameHeight;
        _displayWidth = Math.Max(1, (int)Math.Round(rawWidth * pixelAspectRatio));
        _displayHeight = Math.Max(1, rawHeight);
    }

    /// <summary>根据视口尺寸计算 Uniform 信箱布局。</summary>
    public PreviewLayout ComputeLayout(double viewportWidth, double viewportHeight, double dpiScale = 1.0)
    {
        if (viewportWidth <= 0 || viewportHeight <= 0)
        {
            return new PreviewLayout(0, 0, 0, 0, _frameWidth, _frameHeight);
        }

        var safeDpi = dpiScale <= 0 ? 1.0 : dpiScale;
        var viewW = viewportWidth / safeDpi;
        var viewH = viewportHeight / safeDpi;
        var scale = Math.Min(viewW / _displayWidth, viewH / _displayHeight);
        var contentW = _displayWidth * scale;
        var contentH = _displayHeight * scale;
        var left = (viewW - contentW) / 2.0;
        var top = (viewH - contentH) / 2.0;

        return new PreviewLayout(left, top, contentW, contentH, _frameWidth, _frameHeight);
    }

    /// <summary>将视口内的选择矩形转换为归一化视频区域。</summary>
    public static Result<NormalizedRect> ViewportRectToNormalized(
        double viewportX,
        double viewportY,
        double viewportWidth,
        double viewportHeight,
        PreviewLayout layout)
    {
        if (layout.ContentWidth <= 0 || layout.ContentHeight <= 0)
        {
            return Result<NormalizedRect>.Failure("预览区域尚未就绪。");
        }

        var x1 = Math.Max(viewportX, layout.ContentLeft);
        var y1 = Math.Max(viewportY, layout.ContentTop);
        var x2 = Math.Min(viewportX + viewportWidth, layout.ContentRight);
        var y2 = Math.Min(viewportY + viewportHeight, layout.ContentBottom);

        if (x2 - x1 < 1 || y2 - y1 < 1)
        {
            return Result<NormalizedRect>.Failure("选择区域过小或不在视频画面内。");
        }

        var normX = (x1 - layout.ContentLeft) / layout.ContentWidth;
        var normY = (y1 - layout.ContentTop) / layout.ContentHeight;
        var normW = (x2 - x1) / layout.ContentWidth;
        var normH = (y2 - y1) / layout.ContentHeight;

        return NormalizedRect.Create(normX, normY, normW, normH);
    }

    /// <summary>将归一化区域映射到视口坐标（用于叠加层绘制）。</summary>
    public static Rect NormalizedToViewportRect(NormalizedRect region, PreviewLayout layout)
    {
        if (layout.ContentWidth <= 0 || layout.ContentHeight <= 0)
        {
            return Rect.Empty;
        }

        return new Rect(
            layout.ContentLeft + region.X * layout.ContentWidth,
            layout.ContentTop + region.Y * layout.ContentHeight,
            region.Width * layout.ContentWidth,
            region.Height * layout.ContentHeight);
    }
}
