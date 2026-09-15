using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Infrastructure.Rendering;

public enum HardwareVideoProcessingKind { Software, Qsv, Cuda, D3D11 }

/// <summary>设备实测后的输入解码、缩放能力；最终编码器由原有选择器决定。</summary>
public sealed record HardwareVideoProcessingPlan(HardwareVideoProcessingKind Kind, bool CanScale)
{
    public static HardwareVideoProcessingPlan Software { get; } = new(HardwareVideoProcessingKind.Software, false);

    public string DisplayName => Kind switch
    {
        HardwareVideoProcessingKind.Qsv => "Intel QSV",
        HardwareVideoProcessingKind.Cuda => "NVIDIA CUDA",
        HardwareVideoProcessingKind.D3D11 => "D3D11VA",
        _ => "CPU"
    };

    public string Description => Kind == HardwareVideoProcessingKind.Software
        ? "解码与缩放使用 CPU。"
        : $"已实测 {DisplayName} 硬件解码；缩放{(CanScale ? "可用 GPU" : "使用 CPU")}。兼容的 8 位 H.264 主片可启用；循环辅助视频、蒙版与合成使用 CPU。";

    /// <summary>未知、高位深、透明、旋转或超出保守设备范围的输入保持原软件路径。</summary>
    public bool Supports(MediaInfo info) => Kind != HardwareVideoProcessingKind.Software
        && string.Equals(info.VideoCodec, "h264", StringComparison.OrdinalIgnoreCase)
        && string.Equals(info.PixelFormat, "yuv420p", StringComparison.OrdinalIgnoreCase)
        && info.RotationDegrees == 0
        && info.Width is >= 128 and <= 4096 && info.Height is >= 128 and <= 4096
        && (info.Width & 1) == 0 && (info.Height & 1) == 0;

    internal bool ShouldUseInput(MediaInfo info, VideoProcessingMode mode, AspectFitMode fit, int width, int height)
        => Supports(info) && (mode == VideoProcessingMode.Gpu
            || (mode == VideoProcessingMode.Auto && CanScale && HasDownscaleOpportunity(info, fit, width, height)));

    /// <summary>自动模式只在能减少回传像素、且画幅操作可直接在 GPU 缩小时启用输入加速。</summary>
    internal static bool HasDownscaleOpportunity(MediaInfo info, AspectFitMode fit, int width, int height)
    {
        if (!string.Equals(info.VideoCodec, "h264", StringComparison.OrdinalIgnoreCase)
            || info.RotationDegrees != 0 || info.Width is < 128 or > 4096 || info.Height is < 128 or > 4096
            || (!string.IsNullOrWhiteSpace(info.PixelFormat) && !string.Equals(info.PixelFormat, "yuv420p", StringComparison.OrdinalIgnoreCase)))
        {
            return false;
        }
        var size = ResolveHardwareScaledSize(info, fit, width, height);
        return size is { } target && target.Width <= info.Width && target.Height <= info.Height
            && (target.Width < info.Width || target.Height < info.Height);
    }

    internal IReadOnlyList<string> DeviceArguments => Kind switch
    {
        HardwareVideoProcessingKind.Qsv => ["-init_hw_device", "qsv=jxgpu:hw_any"],
        HardwareVideoProcessingKind.Cuda => ["-init_hw_device", "cuda=jxgpu:0"],
        HardwareVideoProcessingKind.D3D11 => ["-init_hw_device", "d3d11va=jxgpu"],
        _ => []
    };

    internal IReadOnlyList<string> InputArguments => Kind switch
    {
        HardwareVideoProcessingKind.Qsv => ["-hwaccel", "qsv", "-hwaccel_device", "jxgpu", "-hwaccel_output_format", "qsv"],
        HardwareVideoProcessingKind.Cuda => ["-hwaccel", "cuda", "-hwaccel_device", "jxgpu", "-hwaccel_output_format", "cuda"],
        HardwareVideoProcessingKind.D3D11 => ["-hwaccel", "d3d11va", "-hwaccel_device", "jxgpu", "-hwaccel_output_format", "d3d11"],
        _ => []
    };

    internal const string DownloadFilter = "hwdownload,format=nv12";

    internal string ScaleAndDownload(int width, int height)
    {
        var filter = Kind == HardwareVideoProcessingKind.Cuda ? "scale_cuda" : "scale_qsv";
        var copyFrames = Kind == HardwareVideoProcessingKind.Cuda ? ":passthrough=0" : string.Empty;
        return FormattableString.Invariant($"{filter}=w={width}:h={height}:format=nv12{copyFrames},{DownloadFilter}");
    }

    /// <summary>精确使用原 scale 的目标像素尺寸；奇数硬件尺寸及双分支模糊背景仍由软件缩放。</summary>
    internal string? BuildMainFitFilter(MediaInfo info, AspectFitMode fit, int width, int height, int inputIndex)
    {
        if (!CanScale || Kind is not HardwareVideoProcessingKind.Qsv and not HardwareVideoProcessingKind.Cuda)
        {
            return null;
        }

        var size = ResolveHardwareScaledSize(info, fit, width, height);
        if (size is not { } target) { return null; }
        var (scaledWidth, scaledHeight) = target;
        var suffix = fit switch
        {
            AspectFitMode.CenterCrop => FormattableString.Invariant($",crop={width}:{height}"),
            AspectFitMode.Letterbox => FormattableString.Invariant($",pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"),
            AspectFitMode.Stretch => string.Empty,
            _ => throw new ArgumentOutOfRangeException(nameof(fit))
        };
        var transform = scaledWidth == info.Width && scaledHeight == info.Height
            ? DownloadFilter
            : ScaleAndDownload(scaledWidth, scaledHeight);
        return FormattableString.Invariant($"[{inputIndex}:v]{transform}{suffix},");
    }

    private static (int Width, int Height)? ResolveHardwareScaledSize(MediaInfo info, AspectFitMode fit, int width, int height)
    {
        if (info.Width <= 0 || info.Height <= 0 || fit is not AspectFitMode.CenterCrop and not AspectFitMode.Letterbox and not AspectFitMode.Stretch)
        {
            return null;
        }

        var scaledWidth = width;
        var scaledHeight = height;
        if (fit is AspectFitMode.CenterCrop or AspectFitMode.Letterbox)
        {
            var fromHeight = (int)Math.Round((double)height * info.Width / info.Height, MidpointRounding.AwayFromZero);
            var fromWidth = (int)Math.Round((double)width * info.Height / info.Width, MidpointRounding.AwayFromZero);
            scaledWidth = fit == AspectFitMode.CenterCrop ? Math.Max(width, fromHeight) : Math.Min(width, fromHeight);
            scaledHeight = fit == AspectFitMode.CenterCrop ? Math.Max(height, fromWidth) : Math.Min(height, fromWidth);
        }

        if (scaledWidth is < 128 or > 4096 || scaledHeight is < 128 or > 4096
            || (scaledWidth & 1) != 0 || (scaledHeight & 1) != 0)
        {
            return null;
        }

        return (scaledWidth, scaledHeight);
    }
}
