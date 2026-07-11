using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;

namespace JingXu.Workbench.Domain.Overlays;

/// <summary>根据组合计划解析蒙版时间轴与层级顺序。</summary>
public static class OverlayTimelineResolver
{
    /// <summary>按 Z 索引稳定排序蒙版层（相同索引时按名称排序）。</summary>
    public static IReadOnlyList<OverlayLayer> Sort(IEnumerable<OverlayLayer> layers) =>
        layers
            .OrderBy(layer => layer.ZIndex)
            .ThenBy(layer => layer.Name, StringComparer.Ordinal)
            .ToArray();

    /// <summary>解析单条蒙版在成片时间轴上的起止与循环信息。</summary>
    public static Result<ResolvedOverlay> Resolve(CompositionPlan plan, OverlayLayer layer)
    {
        ArgumentNullException.ThrowIfNull(plan);
        ArgumentNullException.ThrowIfNull(layer);

        var validation = layer.Validate(plan.Clips.Count);
        if (!validation.IsSuccess)
        {
            return Result<ResolvedOverlay>.Failure(validation.Error!);
        }

        if (plan.Duration <= TimeSpan.Zero)
        {
            return Result<ResolvedOverlay>.Failure("组合计划时长为零，无法应用蒙版。");
        }

        var start = ResolveStartTime(plan, layer.StartClipIndex);
        if (start >= plan.Duration)
        {
            return Result<ResolvedOverlay>.Failure("蒙版起始时间超出成片时长。");
        }

        var activeDuration = plan.Duration - start;
        if (activeDuration <= TimeSpan.Zero)
        {
            return Result<ResolvedOverlay>.Failure("蒙版有效时长必须大于零。");
        }

        var (loopCount, lastLoopDuration) = ComputeLoops(activeDuration, layer.SourceDuration);
        return Result<ResolvedOverlay>.Success(
            new ResolvedOverlay(layer, start, activeDuration, loopCount, lastLoopDuration));
    }

    /// <summary>解析并排序全部蒙版层。</summary>
    public static Result<IReadOnlyList<ResolvedOverlay>> ResolveAll(
        CompositionPlan plan,
        IEnumerable<OverlayLayer> layers)
    {
        var sorted = Sort(layers);
        var resolved = new List<ResolvedOverlay>(sorted.Count);

        foreach (var layer in sorted)
        {
            var result = Resolve(plan, layer);
            if (!result.IsSuccess)
            {
                return Result<IReadOnlyList<ResolvedOverlay>>.Failure(result.Error!);
            }

            resolved.Add(result.Value!);
        }

        return Result<IReadOnlyList<ResolvedOverlay>>.Success(resolved);
    }

    private static TimeSpan ResolveStartTime(CompositionPlan plan, int startClipIndex)
    {
        if (startClipIndex <= 1)
        {
            return TimeSpan.Zero;
        }

        var clip = plan.Clips[startClipIndex - 1];
        return clip.Start;
    }

    private static (int LoopCount, TimeSpan LastLoopDuration) ComputeLoops(
        TimeSpan activeDuration,
        TimeSpan sourceDuration)
    {
        var activeSeconds = activeDuration.TotalSeconds;
        var sourceSeconds = sourceDuration.TotalSeconds;

        if (sourceSeconds <= 0)
        {
            return (0, TimeSpan.Zero);
        }

        var fullLoops = (int)Math.Floor(activeSeconds / sourceSeconds);
        var remainderSeconds = activeSeconds - fullLoops * sourceSeconds;

        if (remainderSeconds <= 0.000001)
        {
            return (Math.Max(1, fullLoops), sourceDuration);
        }

        var loopCount = fullLoops + 1;
        var lastLoop = TimeSpan.FromSeconds(remainderSeconds);
        return (loopCount, lastLoop);
    }
}
