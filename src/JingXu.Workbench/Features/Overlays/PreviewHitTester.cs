using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Features.Overlays;

/// <summary>蒙版预览框命中区域：中心平移，边/角缩放。</summary>
public enum PreviewHitZone
{
    None,
    Move,
    North,
    South,
    East,
    West,
    NorthEast,
    NorthWest,
    SouthEast,
    SouthWest
}

/// <summary>预览画布上命中蒙版框边角的辅助逻辑。</summary>
public static class PreviewHitTester
{
    public const double HandleThickness = 10;

    public static PreviewHitZone HitTest(
        double canvasX,
        double canvasY,
        double left,
        double top,
        double width,
        double height,
        double handleThickness = HandleThickness)
    {
        if (width <= 0 || height <= 0)
        {
            return PreviewHitZone.None;
        }

        var right = left + width;
        var bottom = top + height;
        var nearLeft = Math.Abs(canvasX - left) <= handleThickness;
        var nearRight = Math.Abs(canvasX - right) <= handleThickness;
        var nearTop = Math.Abs(canvasY - top) <= handleThickness;
        var nearBottom = Math.Abs(canvasY - bottom) <= handleThickness;
        var insideX = canvasX >= left - handleThickness && canvasX <= right + handleThickness;
        var insideY = canvasY >= top - handleThickness && canvasY <= bottom + handleThickness;

        if (!insideX || !insideY)
        {
            return PreviewHitZone.None;
        }

        if (nearTop && nearLeft)
        {
            return PreviewHitZone.NorthWest;
        }

        if (nearTop && nearRight)
        {
            return PreviewHitZone.NorthEast;
        }

        if (nearBottom && nearLeft)
        {
            return PreviewHitZone.SouthWest;
        }

        if (nearBottom && nearRight)
        {
            return PreviewHitZone.SouthEast;
        }

        if (nearTop && canvasX >= left && canvasX <= right)
        {
            return PreviewHitZone.North;
        }

        if (nearBottom && canvasX >= left && canvasX <= right)
        {
            return PreviewHitZone.South;
        }

        if (nearLeft && canvasY >= top && canvasY <= bottom)
        {
            return PreviewHitZone.West;
        }

        if (nearRight && canvasY >= top && canvasY <= bottom)
        {
            return PreviewHitZone.East;
        }

        if (canvasX >= left && canvasX <= right && canvasY >= top && canvasY <= bottom)
        {
            return PreviewHitZone.Move;
        }

        return PreviewHitZone.None;
    }
}

/// <summary>将预览画布上的拖拽转换为受边界约束的归一化矩形。</summary>
public static class PreviewRectangleManipulator
{
    public static NormalizedRect Move(
        NormalizedRect rectangle,
        double deltaCanvasX,
        double deltaCanvasY,
        double canvasWidth,
        double canvasHeight)
    {
        var x = Math.Clamp(
            rectangle.X + deltaCanvasX / canvasWidth,
            0,
            Math.Max(0, 1 - rectangle.Width));
        var y = Math.Clamp(
            rectangle.Y + deltaCanvasY / canvasHeight,
            0,
            Math.Max(0, 1 - rectangle.Height));
        return Round(new NormalizedRect(x, y, rectangle.Width, rectangle.Height));
    }

    public static NormalizedRect Resize(
        NormalizedRect rectangle,
        PreviewHitZone zone,
        double deltaCanvasX,
        double deltaCanvasY,
        double canvasWidth,
        double canvasHeight,
        double minimumSize,
        double displayScale = 1)
    {
        if (zone is PreviewHitZone.None or PreviewHitZone.Move)
        {
            return rectangle;
        }

        var scale = Math.Max(0.01, displayScale);
        var deltaX = deltaCanvasX / (canvasWidth * scale);
        var deltaY = deltaCanvasY / (canvasHeight * scale);
        var x = rectangle.X;
        var y = rectangle.Y;
        var width = rectangle.Width;
        var height = rectangle.Height;

        switch (zone)
        {
            case PreviewHitZone.East:
                width = Math.Clamp(width + deltaX, minimumSize, 1 - x);
                break;
            case PreviewHitZone.West:
            {
                var nextX = Math.Clamp(x + deltaX, 0, x + width - minimumSize);
                width += x - nextX;
                x = nextX;
                break;
            }
            case PreviewHitZone.South:
                height = Math.Clamp(height + deltaY, minimumSize, 1 - y);
                break;
            case PreviewHitZone.North:
            {
                var nextY = Math.Clamp(y + deltaY, 0, y + height - minimumSize);
                height += y - nextY;
                y = nextY;
                break;
            }
            case PreviewHitZone.SouthEast:
                width = Math.Clamp(width + deltaX, minimumSize, 1 - x);
                height = Math.Clamp(height + deltaY, minimumSize, 1 - y);
                break;
            case PreviewHitZone.SouthWest:
            {
                var nextX = Math.Clamp(x + deltaX, 0, x + width - minimumSize);
                width += x - nextX;
                x = nextX;
                height = Math.Clamp(height + deltaY, minimumSize, 1 - y);
                break;
            }
            case PreviewHitZone.NorthEast:
            {
                width = Math.Clamp(width + deltaX, minimumSize, 1 - x);
                var nextY = Math.Clamp(y + deltaY, 0, y + height - minimumSize);
                height += y - nextY;
                y = nextY;
                break;
            }
            case PreviewHitZone.NorthWest:
            {
                var nextX = Math.Clamp(x + deltaX, 0, x + width - minimumSize);
                var nextY = Math.Clamp(y + deltaY, 0, y + height - minimumSize);
                width += x - nextX;
                height += y - nextY;
                x = nextX;
                y = nextY;
                break;
            }
        }

        x = Math.Clamp(x, 0, 1 - minimumSize);
        y = Math.Clamp(y, 0, 1 - minimumSize);
        width = Math.Clamp(width, minimumSize, 1 - x);
        height = Math.Clamp(height, minimumSize, 1 - y);
        return Round(new NormalizedRect(x, y, width, height));
    }

    private static NormalizedRect Round(NormalizedRect rectangle) => new(
        Math.Round(rectangle.X, 4),
        Math.Round(rectangle.Y, 4),
        Math.Round(rectangle.Width, 4),
        Math.Round(rectangle.Height, 4));
}
