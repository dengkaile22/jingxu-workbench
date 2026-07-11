using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Rendering;

/// <summary>
/// 将编排计划转为入队用的 <see cref="RenderRequest"/> 快照。
/// </summary>
public static class RenderRequestFactory
{
    /// <summary>默认成片输出目录（与设置页数据根目录下的 Output 子目录一致）。</summary>
    public static string DefaultOutputDirectory =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JingXu",
            "Output");

    /// <summary>
    /// 为每条编排计划生成带唯一输出路径的请求快照。
    /// </summary>
    public static IReadOnlyList<RenderRequest> CreateForPlans(
        IReadOnlyList<CompositionPlan> plans,
        string outputDirectory,
        string outputFileNamePrefix,
        RenderProfile profile,
        OutputAspect aspect,
        IReadOnlyList<OverlayLayer>? overlayLayers = null,
        EffectVariationTemplate? effectTemplate = null,
        BgmMixPlan? bgm = null,
        ImageSticker? sticker = null) =>
        CreateForPlans(
            plans,
            outputDirectory,
            outputFileNamePrefix,
            profile,
            aspect,
            overlayLayersPerPlan: null,
            sharedOverlayLayers: overlayLayers,
            effectTemplate,
            bgm,
            sticker);

    /// <summary>
    /// 为每条编排计划生成请求，支持按任务分别指定蒙版层。
    /// </summary>
    public static IReadOnlyList<RenderRequest> CreateForPlans(
        IReadOnlyList<CompositionPlan> plans,
        string outputDirectory,
        string outputFileNamePrefix,
        RenderProfile profile,
        OutputAspect aspect,
        IReadOnlyList<IReadOnlyList<OverlayLayer>>? overlayLayersPerPlan,
        IReadOnlyList<OverlayLayer>? sharedOverlayLayers,
        EffectVariationTemplate? effectTemplate = null,
        BgmMixPlan? bgm = null,
        ImageSticker? sticker = null)
    {
        ArgumentNullException.ThrowIfNull(plans);
        ArgumentNullException.ThrowIfNull(profile);
        ArgumentNullException.ThrowIfNull(aspect);

        if (overlayLayersPerPlan is not null && overlayLayersPerPlan.Count != plans.Count)
        {
            throw new ArgumentException("蒙版层数量必须与编排计划数量一致。", nameof(overlayLayersPerPlan));
        }

        var hasBgm = bgm is not null;
        var usesStandardEffect = effectTemplate is not null && effectTemplate.Id != EffectTemplates.None.Id;
        var hasEffects = usesStandardEffect || sticker is not null;

        if (plans.Count == 0)
        {
            return [];
        }

        var directory = Path.GetFullPath(outputDirectory.Trim());
        var prefix = SanitizeFileNamePrefix(outputFileNamePrefix);

        RenderRequest CreateRequest(CompositionPlan plan, string outputPath, IReadOnlyList<OverlayLayer> layers)
        {
            var hasOverlays = layers.Count > 0;
            MaterializedEffect? effect = null;
            if (usesStandardEffect && effectTemplate is not null)
            {
                effect = effectTemplate.Materialize(plan.Seed);
            }

            return new RenderRequest(
                plan,
                outputPath,
                profile,
                aspect,
                layers,
                HasOverlays: hasOverlays,
                HasEffects: hasEffects,
                HasBgm: hasBgm,
                Effect: effect,
                Bgm: bgm,
                Sticker: sticker);
        }

        if (plans.Count == 1)
        {
            var layers = ResolveLayers(overlayLayersPerPlan, sharedOverlayLayers, index: 0);
            return [CreateRequest(plans[0], Path.Combine(directory, $"{prefix}.mp4"), layers)];
        }

        return plans
            .Select((plan, index) => CreateRequest(
                plan,
                Path.Combine(directory, $"{prefix}_{index + 1:D3}.mp4"),
                ResolveLayers(overlayLayersPerPlan, sharedOverlayLayers, index)))
            .ToArray();
    }

    private static IReadOnlyList<OverlayLayer> ResolveLayers(
        IReadOnlyList<IReadOnlyList<OverlayLayer>>? overlayLayersPerPlan,
        IReadOnlyList<OverlayLayer>? sharedOverlayLayers,
        int index) =>
        overlayLayersPerPlan is not null
            ? overlayLayersPerPlan[index]
            : sharedOverlayLayers ?? [];

    private static string SanitizeFileNamePrefix(string value)
    {
        var trimmed = value.Trim();
        if (string.IsNullOrEmpty(trimmed))
        {
            return "混剪成片";
        }

        var invalid = Path.GetInvalidFileNameChars();
        var sanitized = new string(trimmed
            .Select(ch => invalid.Contains(ch) ? '_' : ch)
            .ToArray())
            .Trim('.', ' ');

        return string.IsNullOrWhiteSpace(sanitized) ? "混剪成片" : sanitized;
    }
}
