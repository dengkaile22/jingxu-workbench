using System.Globalization;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>编译硬字幕去除 filter 图。</summary>
public static class SubtitleRemovalFilterCompiler
{
    /// <summary>编译去除 filter；输入标签为 <c>[0:v]</c>，输出 <c>[vsub]</c>。</summary>
    public static string Compile(SubtitleRemovalPlan plan)
    {
        ArgumentNullException.ThrowIfNull(plan);
        var (left, top, width, height) = plan.Region.ToPixels(plan.FrameWidth, plan.FrameHeight);

        return plan.Mode switch
        {
            SubtitleRemovalMode.Blur => CompileBlur(left, top, width, height),
            SubtitleRemovalMode.Delogo => CompileDelogo(left, top, width, height),
            SubtitleRemovalMode.CropAndReframe => CompileCropAndReframe(plan),
            _ => throw new InvalidOperationException($"未知的去字幕模式：{plan.Mode}")
        };
    }

    private static string CompileBlur(int left, int top, int width, int height) =>
        $"[0:v]split=2[base][roi];" +
        $"[roi]crop={width}:{height}:{left}:{top},gblur=sigma=12[blur];" +
        $"[base][blur]overlay={left}:{top}[vsub]";

    private static string CompileDelogo(int left, int top, int width, int height) =>
        $"[0:v]delogo=x={left}:y={top}:w={width}:h={height}[vsub]";

    private static string CompileCropAndReframe(SubtitleRemovalPlan plan)
    {
        var region = plan.Region;
        var touchesTop = region.Y <= 0.001;
        var touchesBottom = region.Bottom >= 0.999;
        if (!touchesTop && !touchesBottom)
        {
            throw new InvalidOperationException("裁切重构仅适用于贴顶或贴底的字幕带。");
        }

        var (left, top, width, height) = region.ToPixels(plan.FrameWidth, plan.FrameHeight);
        if (touchesTop)
        {
            var cropHeight = plan.FrameHeight - (top + height);
            return $"[0:v]crop={plan.FrameWidth}:{cropHeight}:0:{top + height},scale={plan.FrameWidth}:{plan.FrameHeight}[vsub]";
        }

        var bottomCropHeight = plan.FrameHeight - height;
        return $"[0:v]crop={plan.FrameWidth}:{bottomCropHeight}:0:0,scale={plan.FrameWidth}:{plan.FrameHeight}[vsub]";
    }
}
