using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Application.Projects;

namespace JingXu.Workbench.Application.Rendering;

/// <summary>
/// 将编排计划转为入队用的 <see cref="RenderRequest"/> 快照。
/// </summary>
public static class RenderRequestFactory
{
    /// <summary>默认项目根目录（多来源任务的「分镜输出」父目录）。</summary>
    public static string DefaultProjectDirectory => WorkbenchDataPaths.GetDataDirectory();

    /// <summary>导入前的占位默认目录（多来源策略：项目根下的「分镜输出」）。</summary>
    public static string DefaultOutputDirectory =>
        Path.Combine(DefaultProjectDirectory, "分镜输出");

    /// <summary>
    /// 按素材路径推导默认输出目录：单一源文件夹 → <c>源\分镜输出</c>；
    /// 多来源或无有效路径 → <c>项目\分镜输出</c>。
    /// </summary>
    public static string ResolveDefaultOutputDirectory(
        IEnumerable<string> mediaPaths,
        string? projectDirectory = null)
    {
        ArgumentNullException.ThrowIfNull(mediaPaths);

        var folders = mediaPaths
            .Where(static p => !string.IsNullOrWhiteSpace(p))
            .Select(static p =>
            {
                try
                {
                    return Path.GetDirectoryName(Path.GetFullPath(p.Trim()));
                }
                catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
                {
                    return Path.GetDirectoryName(p.Trim());
                }
            })
            .Where(static d => !string.IsNullOrWhiteSpace(d))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Cast<string>()
            .ToArray();

        var project = string.IsNullOrWhiteSpace(projectDirectory)
            ? DefaultProjectDirectory
            : projectDirectory.Trim();

        if (folders.Length == 1)
        {
            return Path.Combine(folders[0], "分镜输出");
        }

        return Path.Combine(project, "分镜输出");
    }

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
        IReadOnlyList<ImageSticker> stickers = null!,
        MainMaterialBoostPlan? mainMaterialBoost = null,
        OutputVideoSettings outputVideoSettings = default,
        DoubleScreenEffectPlan? doubleScreen = null,
        VideoProcessingMode processingMode = VideoProcessingMode.Auto,
        IReadOnlyList<MediaAsset>? doubleScreenSourceAssets = null,
        FourScreenEffectPlan? fourScreen = null,
        IReadOnlyList<MediaAsset>? fourScreenSourceAssets = null) =>
        CreateForPlans(
            plans,
            outputDirectory,
            outputFileNamePrefix,
            profile,
            aspect,
            overlayLayersPerPlan: null,
            sharedOverlayLayers: overlayLayers,
            effectTemplate: effectTemplate,
            bgm: bgm,
            stickers: stickers,
            mainMaterialBoost: mainMaterialBoost,
            outputVideoSettings: outputVideoSettings,
            doubleScreen: doubleScreen,
            stickersPerPlan: null,
            processingMode: processingMode,
            doubleScreenSourceAssets: doubleScreenSourceAssets,
            fourScreen: fourScreen,
            fourScreenSourceAssets: fourScreenSourceAssets);


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
        IReadOnlyList<ImageSticker> stickers = null!,
        MainMaterialBoostPlan? mainMaterialBoost = null,
        OutputVideoSettings outputVideoSettings = default,
        DoubleScreenEffectPlan? doubleScreen = null,
        IEnumerable<string>? reservedOutputPaths = null,
        IReadOnlyList<IReadOnlyList<ImageSticker>>? stickersPerPlan = null,
        VideoProcessingMode processingMode = VideoProcessingMode.Auto,
        IReadOnlyList<BgmMixPlan>? bgmPerPlan = null,
        IReadOnlyList<MediaAsset>? doubleScreenSourceAssets = null,
        FourScreenEffectPlan? fourScreen = null,
        IReadOnlyList<MediaAsset>? fourScreenSourceAssets = null)
    {
        ArgumentNullException.ThrowIfNull(plans);
        ArgumentNullException.ThrowIfNull(profile);
        ArgumentNullException.ThrowIfNull(aspect);

        if (doubleScreen is not null && fourScreen is not null)
        {
            throw new ArgumentException("双屏与四屏不能同时启用。", nameof(fourScreen));
        }

        if (overlayLayersPerPlan is not null && overlayLayersPerPlan.Count != plans.Count)
        {
            throw new ArgumentException("蒙版层数量必须与编排计划数量一致。", nameof(overlayLayersPerPlan));
        }

        if (stickersPerPlan is not null && stickersPerPlan.Count != plans.Count)
        {
            throw new ArgumentException("贴纸轨道数量必须与编排计划数量一致。", nameof(stickersPerPlan));
        }

        if (bgmPerPlan is not null && bgmPerPlan.Count > plans.Count)
        {
            throw new ArgumentException("BGM 计划数量不能多于编排计划数量。", nameof(bgmPerPlan));
        }

        var hasBgm = bgm is not null || (bgmPerPlan is { Count: > 0 });
        var usesStandardEffect = effectTemplate is not null && effectTemplate.Id != EffectTemplates.None.Id;
        var hasEffects = usesStandardEffect || stickers is { Count: > 0 } || doubleScreen is not null;
        var hasMainBoost = mainMaterialBoost is not null && mainMaterialBoost.IsActive;

        if (doubleScreen?.SourceMode == DoubleScreenSourceMode.RandomCurrentFolder &&
            (doubleScreenSourceAssets is null || doubleScreenSourceAssets.Count == 0))
        {
            throw new ArgumentException(
                "双屏随机素材模式需要提供当前素材文件夹中的视频素材。",
                nameof(doubleScreenSourceAssets));
        }

        if (plans.Count == 0)
        {
            return [];
        }

        var directory = Path.GetFullPath(outputDirectory.Trim());
        var prefix = SanitizeFileNamePrefix(outputFileNamePrefix);
        var reserved = reservedOutputPaths?.Select(Path.GetFullPath).ToHashSet(StringComparer.OrdinalIgnoreCase)
            ?? new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var outputPaths = AllocateOutputPaths(directory, prefix, plans.Count, reserved);

        RenderRequest CreateRequest(CompositionPlan plan, string outputPath, IReadOnlyList<OverlayLayer> layers, IReadOnlyList<ImageSticker> planStickers, int planIndex)
        {
            var hasOverlays = layers.Count > 0;
            var planHasEffects = usesStandardEffect || planStickers.Count > 0 || doubleScreen is not null || fourScreen is not null;
            DoubleScreenEffectPlan? planDoubleScreen = doubleScreen;
            if (doubleScreen is not null && doubleScreen.SourceMode == DoubleScreenSourceMode.RandomCurrentFolder)
            {
                var materialized = doubleScreen.MaterializeForPlan(
                    plan,
                    doubleScreenSourceAssets!,
                    planIndex);
                if (!materialized.IsSuccess)
                {
                    throw new InvalidOperationException(materialized.Error);
                }

                planDoubleScreen = materialized.Value!;
            }

            FourScreenEffectPlan? planFourScreen = null;
            if (fourScreen is not null)
            {
                var materialized = fourScreen.MaterializeForPlan(plan, fourScreenSourceAssets ?? [], planIndex);
                if (!materialized.IsSuccess)
                {
                    throw new InvalidOperationException(materialized.Error);
                }

                planFourScreen = materialized.Value!;
            }

            MaterializedEffect? effect = null;
            if (usesStandardEffect && effectTemplate is not null)
            {
                effect = effectTemplate.Materialize(plan.Seed);
            }

            MaterializedMainMaterialBoost? materializedBoost = null;
            if (hasMainBoost && mainMaterialBoost is not null)
            {
                materializedBoost = mainMaterialBoost.Materialize(plan.Seed, plan.Clips.Count);
            }

            // 每计划独立 BGM（音频库）优先，回退到共享 BGM
            var planBgm = bgmPerPlan is not null && planIndex < bgmPerPlan.Count
                ? bgmPerPlan[planIndex]
                : bgm;
            var planHasBgm = planBgm is not null;

            return new RenderRequest(
                plan,
                outputPath,
                profile,
                aspect,
                layers,
                HasOverlays: hasOverlays,
                HasEffects: planHasEffects,
                HasBgm: planHasBgm,
                HasMainMaterialBoost: hasMainBoost,
                Effect: effect,
                Bgm: planBgm,
                Stickers: planStickers,
                MainMaterialBoost: materializedBoost,
                OutputVideoSettings: outputVideoSettings,
                DoubleScreen: planDoubleScreen,
                ProcessingMode: processingMode,
                FourScreen: planFourScreen);
        }

        if (plans.Count == 1)
        {
            var layers = ResolveLayers(overlayLayersPerPlan, sharedOverlayLayers, index: 0);
            var planStickers = stickersPerPlan?[0] ?? stickers ?? Array.Empty<ImageSticker>();
            return [CreateRequest(plans[0], outputPaths[0], layers, planStickers, 0)];
        }

        return plans
            .Select((plan, index) => CreateRequest(
                plan,
                outputPaths[index],
                ResolveLayers(overlayLayersPerPlan, sharedOverlayLayers, index),
                stickersPerPlan?[index] ?? stickers ?? Array.Empty<ImageSticker>(),
                index))
            .ToArray();
    }

    private static List<string> AllocateOutputPaths(
        string directory,
        string prefix,
        int count,
        HashSet<string> reserved)
    {
        if (count == 1)
        {
            return [AllocateAvailablePath(directory, prefix, startIndex: 0, reserved)];
        }

        var paths = new List<string>(count);
        var nextIndex = 1;
        while (paths.Count < count)
        {
            var candidate = Path.Combine(directory, $"{prefix}_{nextIndex:D3}.mp4");
            var fullPath = Path.GetFullPath(candidate);
            if (!File.Exists(fullPath) && !reserved.Contains(fullPath))
            {
                paths.Add(candidate);
            }

            nextIndex++;
            if (nextIndex > 999)
            {
                throw new InvalidOperationException($"无法在目录 {directory} 中为 {prefix} 分配 {count} 个唯一文件名。");
            }
        }

        return paths;
    }

    private static string AllocateAvailablePath(
        string directory,
        string prefix,
        int startIndex,
        HashSet<string> reserved)
    {
        if (startIndex == 0)
        {
            var candidate = Path.Combine(directory, $"{prefix}.mp4");
            var fullPath = Path.GetFullPath(candidate);
            if (!File.Exists(fullPath) && !reserved.Contains(fullPath))
            {
                return candidate;
            }
        }

        for (var index = Math.Max(startIndex, 1); index <= 999; index++)
        {
            var candidate = Path.Combine(directory, $"{prefix}_{index:D3}.mp4");
            var fullPath = Path.GetFullPath(candidate);
            if (!File.Exists(fullPath) && !reserved.Contains(fullPath))
            {
                return candidate;
            }
        }

        throw new InvalidOperationException($"无法在目录 {directory} 中为 {prefix} 分配唯一文件名。");
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
