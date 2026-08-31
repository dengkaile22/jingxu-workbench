using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Application.Overlays;

/// <summary>入队前将工作台蒙版配置解析为可渲染的成片叠加层。</summary>
public static class OverlayEnqueueResolver
{
    /// <summary>素材库随机蒙版默认时长（秒）。</summary>
    public const double DefaultLibrarySourceDurationSeconds = 3;

    /// <summary>校验蒙版开关与素材库是否满足入队条件；通过时返回 <c>null</c>。</summary>
    public static string? ValidateForEnqueue(
        OverlayWorkbenchState state,
        int libraryEntryCount,
        IReadOnlyList<OverlayLibraryEntry>? libraryEntries = null)
    {
        ArgumentNullException.ThrowIfNull(state);

        if (!state.IsEnabled)
        {
            return null;
        }

        if (state.UseRandomLibrarySource && libraryEntryCount == 0)
        {
            return "已开启「随机替换素材库蒙版」，但素材库为空。请先在蒙版页注册素材。";
        }

        if (!state.HasLayers && !state.UseRandomLibrarySource)
        {
            return "已开启蒙版覆盖，但未配置蒙版层。请先在蒙版页添加轨道，或开启随机替换素材库。";
        }

        if (state.UseRandomLibrarySource && libraryEntries is { Count: > 0 })
        {
            foreach (var entry in libraryEntries)
            {
                if (entry.VisualSettings is not { } visualSettings)
                {
                    continue;
                }

                var validation = visualSettings.Validate();
                if (!validation.IsSuccess)
                {
                    return $"蒙版素材库条目“{Path.GetFileName(entry.FilePath)}”的视觉参数无效：" +
                           $"{validation.Error}。请在蒙版页重新设置后再入队。";
                }
            }
        }

        return null;
    }

    /// <summary>为单条成片计划解析蒙版层；关闭开关时返回空列表。</summary>
    public static IReadOnlyList<OverlayLayer> ResolveForPlan(
        OverlayWorkbenchState state,
        IReadOnlyList<OverlayLibraryEntry> library,
        CompositionPlan plan,
        long planOrdinal = 0,
        int? randomSelectionSeed = null)
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
            throw new InvalidOperationException("蒙版素材库为空，无法随机替换。");
        }

        var entry = OverlaySourceSelector.SelectReplacement(
            library,
            randomSelectionSeed ?? plan.Seed,
            planOrdinal);
        var template = templates.FirstOrDefault(layer => !layer.IsSelfSource);
        if (template is null)
        {
            // 未配置外部蒙版轨道时：从库取一条并套用库内视觉参数。
            var layer = OverlayLayer.CreateImportedMaskPreset(
                entry.FilePath,
                TimeSpan.FromSeconds(DefaultLibrarySourceDurationSeconds));
            return
            [
                entry.VisualSettings is null
                    ? layer
                    : layer.WithVisualSettings(entry.VisualSettings)
            ];
        }

        // 随机模式是“替换”而不是“追加叠加”：每条成片只保留一个外部蒙版，
        // 沿用第一条外部轨道的位置、尺寸、透明度和羽化参数。
        return [template with { SourcePath = entry.FilePath }];
    }

    /// <summary>
    /// 对解析后的蒙版层探测真实素材时长（随机库换源后尤其重要）。
    /// 探测失败时保留原时长；自叠影跳过探测。
    /// </summary>
    public static async Task<IReadOnlyList<OverlayLayer>> ProbeSourceDurationsAsync(
        IReadOnlyList<OverlayLayer> layers,
        IMediaProbe mediaProbe,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(layers);
        ArgumentNullException.ThrowIfNull(mediaProbe);
        if (layers.Count == 0)
        {
            return layers;
        }

        var probed = new OverlayLayer[layers.Count];
        for (var i = 0; i < layers.Count; i++)
        {
            var layer = layers[i];
            if (layer.IsSelfSource)
            {
                probed[i] = layer;
                continue;
            }

            try
            {
                var info = await mediaProbe.ProbeAsync(layer.SourcePath, cancellationToken).ConfigureAwait(false);
                probed[i] = info.Duration > TimeSpan.Zero
                    ? layer with { SourceDuration = info.Duration }
                    : layer;
            }
            catch
            {
                probed[i] = layer;
            }
        }

        return probed;
    }
}
