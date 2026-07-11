using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Application.Overlays;

/// <summary>入队前将工作台蒙版配置解析为可渲染的成片叠加层。</summary>
public static class OverlayEnqueueResolver
{
    /// <summary>素材库随机蒙版默认时长（秒）。</summary>
    public const double DefaultLibrarySourceDurationSeconds = 3;

    /// <summary>校验蒙版开关与素材库是否满足入队条件；通过时返回 <c>null</c>。</summary>
    public static string? ValidateForEnqueue(OverlayWorkbenchState state, int libraryEntryCount)
    {
        ArgumentNullException.ThrowIfNull(state);

        if (!state.IsEnabled)
        {
            return null;
        }

        if (state.UseRandomLibrarySource && libraryEntryCount == 0)
        {
            return "已开启「随机套用素材库蒙版」，但素材库为空。请先在蒙版页注册素材。";
        }

        if (!state.HasLayers && !state.UseRandomLibrarySource)
        {
            return "已开启蒙版叠加，但未配置蒙版层。请先在蒙版页添加，或开启随机套用素材库。";
        }

        return null;
    }

    /// <summary>为单条成片计划解析蒙版层；关闭开关时返回空列表。</summary>
    public static IReadOnlyList<OverlayLayer> ResolveForPlan(
        OverlayWorkbenchState state,
        IReadOnlyList<OverlayLibraryEntry> library,
        CompositionPlan plan)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(library);
        ArgumentNullException.ThrowIfNull(plan);

        if (!state.IsEnabled)
        {
            return [];
        }

        var templates = state.CreateSnapshot();
        if (!state.UseRandomLibrarySource)
        {
            return templates;
        }

        if (library.Count == 0)
        {
            throw new InvalidOperationException("蒙版素材库为空，无法随机套用。");
        }

        if (templates.Count == 0)
        {
            var entry = OverlaySourceSelector.Select(library, plan.Seed);
            return
            [
                OverlayLayer.CreateFullFramePreset(
                    entry.FilePath,
                    TimeSpan.FromSeconds(DefaultLibrarySourceDurationSeconds))
            ];
        }

        return templates
            .Select((layer, index) =>
            {
                var entry = OverlaySourceSelector.Select(library, plan.Seed, branchIndex: index);
                return layer with { SourcePath = entry.FilePath };
            })
            .ToArray();
    }
}
