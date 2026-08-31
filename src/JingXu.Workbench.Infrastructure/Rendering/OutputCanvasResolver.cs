using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>
/// Resolves the render canvas before an optional export-resolution scale is applied.
/// This is shared by normal composition, subtitle burn-in, and output validation.
/// </summary>
internal static class OutputCanvasResolver
{
    public static (int Width, int Height) Resolve(RenderRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        if (!request.Aspect.InheritFromFirstClip &&
            request.Aspect.TargetWidth is > 0 &&
            request.Aspect.TargetHeight is > 0)
        {
            return (MakeEven(request.Aspect.TargetWidth.Value), MakeEven(request.Aspect.TargetHeight.Value));
        }

        var first = request.Plan.Clips[0].Asset.Info;
        return NormalizeDimensions(first);
    }

    public static (int Width, int Height) NormalizeDimensions(MediaInfo info)
    {
        var (w, h) = info.RotationDegrees is 90 or 270
            ? (info.Height, info.Width)
            : (info.Width, info.Height);
        return (MakeEven(w), MakeEven(h));
    }

    public static (int Width, int Height) NormalizeDimensions(int width, int height, int rotationDegrees)
    {
        var (w, h) = rotationDegrees is 90 or 270 ? (height, width) : (width, height);
        return (MakeEven(w), MakeEven(h));
    }

    private static int MakeEven(int value) => Math.Max(2, value & ~1);
}
