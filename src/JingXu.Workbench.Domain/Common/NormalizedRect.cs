using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Domain.Common;

/// <summary>归一化矩形，各边取值范围 [0,1]。</summary>
public readonly record struct NormalizedRect(double X, double Y, double Width, double Height)
{
    /// <summary>右边界（归一化）。</summary>
    public double Right => X + Width;

    /// <summary>下边界（归一化）。</summary>
    public double Bottom => Y + Height;

    /// <summary>全画面矩形。</summary>
    public static NormalizedRect FullFrame { get; } = new(0, 0, 1, 1);

    /// <summary>验证并创建归一化矩形。</summary>
    public static Result<NormalizedRect> Create(double x, double y, double width, double height)
    {
        if (x is < 0 or > 1 || y is < 0 or > 1)
        {
            return Result<NormalizedRect>.Failure("蒙版位置必须在 0 到 1 之间。");
        }

        if (width <= 0 || width > 1 || height <= 0 || height > 1)
        {
            return Result<NormalizedRect>.Failure("蒙版尺寸必须在 0 到 1 之间且大于零。");
        }

        if (x + width > 1.000001 || y + height > 1.000001)
        {
            return Result<NormalizedRect>.Failure("蒙版矩形超出画面范围。");
        }

        return Result<NormalizedRect>.Success(new NormalizedRect(x, y, width, height));
    }

    /// <summary>将归一化边界转换为像素坐标并钳制到帧范围。</summary>
    public (int X, int Y, int Width, int Height) ToPixels(int frameWidth, int frameHeight)
    {
        var x = (int)Math.Round(X * frameWidth);
        var y = (int)Math.Round(Y * frameHeight);
        var w = (int)Math.Round(Width * frameWidth);
        var h = (int)Math.Round(Height * frameHeight);

        if (x < 0)
        {
            x = 0;
        }

        if (y < 0)
        {
            y = 0;
        }

        if (x + w > frameWidth)
        {
            w = frameWidth - x;
        }

        if (y + h > frameHeight)
        {
            h = frameHeight - y;
        }

        return (x, y, Math.Max(1, w), Math.Max(1, h));
    }
}
