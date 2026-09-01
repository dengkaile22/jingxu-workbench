using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Domain.Effects;

public enum DoubleScreenSourceMode
{
    CurrentClip,
    RandomCurrentFolder
}

public enum DoubleScreenPlacementMode
{
    Top,
    Bottom,
    Random
}

public enum DoubleScreenPlacement
{
    Top,
    Bottom
}

/// <summary>已在入队时确定的双屏辅助素材和覆盖位置。</summary>
public sealed record DoubleScreenClipSelection(
    int ClipIndex,
    MediaAsset SourceAsset,
    DoubleScreenPlacement Placement);

/// <summary>
/// 上下双屏效果：按最终成片中的片段序号，从指定片段开始一直应用到结尾。
/// 随机素材和覆盖位置必须在入队时物化，保证渲染过程可复现。
/// </summary>
public sealed record DoubleScreenEffectPlan
{
    public const int DefaultFeatherPixels = 48;
    public const int MaxFeatherPixels = 256;

    public int StartClipIndex { get; init; }
    public DoubleScreenSourceMode SourceMode { get; init; }
    public DoubleScreenPlacementMode PlacementMode { get; init; }
    public bool FeatherEnabled { get; init; }
    public int FeatherPixels { get; init; }
    public IReadOnlyList<DoubleScreenClipSelection> ClipSelections { get; init; }

    public DoubleScreenEffectPlan(
        int StartClipIndex,
        DoubleScreenSourceMode SourceMode = DoubleScreenSourceMode.CurrentClip,
        DoubleScreenPlacementMode PlacementMode = DoubleScreenPlacementMode.Random,
        bool FeatherEnabled = true,
        int FeatherPixels = DefaultFeatherPixels,
        IReadOnlyList<DoubleScreenClipSelection>? ClipSelections = null)
    {
        this.StartClipIndex = StartClipIndex;
        this.SourceMode = SourceMode;
        this.PlacementMode = PlacementMode;
        this.FeatherEnabled = FeatherEnabled;
        this.FeatherPixels = FeatherPixels;
        this.ClipSelections = ClipSelections ?? [];
    }

    public static Result<DoubleScreenEffectPlan> Create(
        int startClipIndex,
        DoubleScreenSourceMode sourceMode = DoubleScreenSourceMode.CurrentClip,
        DoubleScreenPlacementMode placementMode = DoubleScreenPlacementMode.Random,
        bool featherEnabled = true,
        int featherPixels = DefaultFeatherPixels) =>
        startClipIndex < 1
            ? Result<DoubleScreenEffectPlan>.Failure("双屏起始视频必须从 1 开始。")
            : !Enum.IsDefined(sourceMode)
                ? Result<DoubleScreenEffectPlan>.Failure("双屏素材来源无效。")
                : !Enum.IsDefined(placementMode)
                    ? Result<DoubleScreenEffectPlan>.Failure("双屏覆盖位置无效。")
                    : featherPixels is < 0 or > MaxFeatherPixels
                        ? Result<DoubleScreenEffectPlan>.Failure(
                            $"双屏羽化宽度必须在 0 到 {MaxFeatherPixels} 像素之间。")
                        : Result<DoubleScreenEffectPlan>.Success(new DoubleScreenEffectPlan(
                            startClipIndex,
                            sourceMode,
                            placementMode,
                            featherEnabled,
                            featherPixels));

    public bool AppliesTo(int zeroBasedClipIndex) =>
        zeroBasedClipIndex >= 0 && zeroBasedClipIndex + 1 >= StartClipIndex;

    public DoubleScreenClipSelection? SelectionFor(int zeroBasedClipIndex) =>
        ClipSelections.FirstOrDefault(selection => selection.ClipIndex == zeroBasedClipIndex);

    /// <summary>
    /// 为一条成片按素材文件夹和成片序号生成确定性的随机辅助素材快照。
    /// 当素材文件夹只有当前片段时允许回退到当前片段，避免无法入队。
    /// </summary>
    public Result<DoubleScreenEffectPlan> MaterializeForPlan(
        CompositionPlan plan,
        IReadOnlyList<MediaAsset> currentFolderAssets,
        int planIndex)
    {
        ArgumentNullException.ThrowIfNull(plan);
        ArgumentNullException.ThrowIfNull(currentFolderAssets);

        if (SourceMode != DoubleScreenSourceMode.RandomCurrentFolder)
        {
            return Result<DoubleScreenEffectPlan>.Success(this with { ClipSelections = [] });
        }

        if (currentFolderAssets.Count == 0)
        {
            return Result<DoubleScreenEffectPlan>.Failure("双屏随机素材需要当前文件夹中至少有一个视频素材。");
        }

        var normalized = currentFolderAssets
            .OrderBy(asset => asset.SequenceIndex ?? int.MaxValue)
            .ThenBy(asset => asset.Path, StringComparer.OrdinalIgnoreCase)
            .ThenBy(asset => asset.Id)
            .ToArray();
        var placementRandom = new DeterministicRandom(unchecked(
            (long)((ulong)(uint)plan.Seed * 0x9E3779B97F4A7C15UL)
            ^ ((long)planIndex * unchecked((long)0xBF58476D1CE4E5B9UL))
            ^ 0xD15EA5E5L));
        var selections = new List<DoubleScreenClipSelection>();

        for (var clipIndex = 0; clipIndex < plan.Clips.Count; clipIndex++)
        {
            if (!AppliesTo(clipIndex))
            {
                continue;
            }

            var currentAsset = plan.Clips[clipIndex].Asset;
            var candidates = normalized
                .Where(asset => !SameAsset(asset, currentAsset))
                .ToArray();
            if (candidates.Length == 0)
            {
                candidates = normalized;
            }

            var selectionOrdinal = ((long)Math.Max(planIndex, 0) * Math.Max(plan.Clips.Count, 1)) + clipIndex;
            var sourceIndex = DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
                candidates.Length,
                plan.Seed,
                selectionOrdinal,
                branchIndex: 1501);
            var placement = PlacementMode switch
            {
                DoubleScreenPlacementMode.Top => DoubleScreenPlacement.Top,
                DoubleScreenPlacementMode.Bottom => DoubleScreenPlacement.Bottom,
                _ => placementRandom.Next(2) == 0
                    ? DoubleScreenPlacement.Top
                    : DoubleScreenPlacement.Bottom
            };

            selections.Add(new DoubleScreenClipSelection(
                clipIndex,
                candidates[sourceIndex],
                placement));
        }

        return Result<DoubleScreenEffectPlan>.Success(this with
        {
            ClipSelections = selections
        });
    }

    private static bool SameAsset(MediaAsset left, MediaAsset right) =>
        left.Id == right.Id
        || string.Equals(left.Path, right.Path, StringComparison.OrdinalIgnoreCase);
}
