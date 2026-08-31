using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Domain.Stickers;

/// <summary>贴纸应用的素材比例模式。</summary>
public enum StickerAspectMode
{
    /// <summary>跟随混剪页统一画幅设置。</summary>
    FollowComposition,

    /// <summary>9:16 竖屏。</summary>
    Ratio9x16,

    /// <summary>3:4 竖屏。</summary>
    Ratio3x4,

    /// <summary>1:1 方形。</summary>
    Ratio1x1,

    /// <summary>4:3 横屏。</summary>
    Ratio4x3,

    /// <summary>16:9 横屏。</summary>
    Ratio16x9
}

public enum FixedAspectRatio
{
    None,
    Ratio3x4,
    Ratio9x16,
    Ratio1x1,
    Ratio4x3,
    Ratio16x9
}

/// <summary>贴纸比例模式扩展。</summary>
public static class StickerAspectModeExtensions
{
    public static (int Width, int Height) GetCanvasSize(this StickerAspectMode mode) => mode switch
    {
        StickerAspectMode.Ratio9x16 => (1080, 1920),
        StickerAspectMode.Ratio3x4 => (1080, 1440),
        StickerAspectMode.Ratio1x1 => (1080, 1080),
        StickerAspectMode.Ratio4x3 => (1440, 1080),
        StickerAspectMode.Ratio16x9 => (1920, 1080),
        _ => (1080, 1920)
    };

    public static (int Width, int Height) GetCanvasSize(this FixedAspectRatio ratio) => ratio switch
    {
        FixedAspectRatio.Ratio9x16 => (1080, 1920),
        FixedAspectRatio.Ratio3x4 => (1080, 1440),
        FixedAspectRatio.Ratio1x1 => (1080, 1080),
        FixedAspectRatio.Ratio4x3 => (1440, 1080),
        FixedAspectRatio.Ratio16x9 => (1920, 1080),
        _ => (0, 0)
    };

    public static double GetAspectRatio(this FixedAspectRatio ratio) => ratio switch
    {
        FixedAspectRatio.Ratio9x16 => 9.0 / 16.0,
        FixedAspectRatio.Ratio3x4 => 3.0 / 4.0,
        FixedAspectRatio.Ratio1x1 => 1.0,
        FixedAspectRatio.Ratio4x3 => 4.0 / 3.0,
        FixedAspectRatio.Ratio16x9 => 16.0 / 9.0,
        _ => 0
    };

    public static string GetDisplayName(this FixedAspectRatio ratio) => ratio switch
    {
        FixedAspectRatio.None => "无固定比例",
        FixedAspectRatio.Ratio9x16 => "9:16",
        FixedAspectRatio.Ratio3x4 => "3:4",
        FixedAspectRatio.Ratio1x1 => "1:1",
        FixedAspectRatio.Ratio4x3 => "4:3",
        FixedAspectRatio.Ratio16x9 => "16:9",
        _ => string.Empty
    };

    public static string GetDisplayName(this StickerAspectMode mode) => mode switch
    {
        StickerAspectMode.FollowComposition => "跟随混剪画幅",
        StickerAspectMode.Ratio9x16 => "9:16 竖屏",
        StickerAspectMode.Ratio3x4 => "3:4 竖屏",
        StickerAspectMode.Ratio1x1 => "1:1 方形",
        StickerAspectMode.Ratio4x3 => "4:3 横屏",
        StickerAspectMode.Ratio16x9 => "16:9 横屏",
        _ => string.Empty
    };
}

/// <summary>贴纸轨道：一条成片可叠加多条，每条独立位置/大小/旋转/透明度。</summary>
public sealed record StickerTrack(
    Guid Id,
    string Name,
    string SourcePath,
    NormalizedRect Bounds,
    double Opacity,
    double RotationDegrees,
    bool IsEnabled,
    FixedAspectRatio FixedAspectRatio = FixedAspectRatio.None)
{
    public static Result<StickerTrack> Create(
        string name,
        string sourcePath,
        double x,
        double y,
        double width,
        double height,
        double opacity = 1.0,
        double rotationDegrees = 0.0,
        bool isEnabled = true,
        FixedAspectRatio fixedAspectRatio = FixedAspectRatio.None)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            return Result<StickerTrack>.Failure("贴纸轨道名称不能为空。");
        }

        if (string.IsNullOrWhiteSpace(sourcePath))
        {
            return Result<StickerTrack>.Failure("贴纸素材路径不能为空。");
        }

        var bounds = NormalizedRect.Create(x, y, width, height);
        if (!bounds.IsSuccess)
        {
            return Result<StickerTrack>.Failure(bounds.Error!);
        }

        return Result<StickerTrack>.Success(new StickerTrack(
            Guid.NewGuid(),
            name.Trim(),
            sourcePath.Trim(),
            bounds.Value,
            Math.Clamp(opacity, 0, 1),
            rotationDegrees,
            isEnabled,
            fixedAspectRatio));
    }

    public ImageSticker? ToImageSticker()
    {
        var result = ImageSticker.Create(SourcePath, Bounds.X, Bounds.Y, Bounds.Width, Bounds.Height, Opacity, RotationDegrees);
        return result.IsSuccess ? result.Value : null;
    }
}
