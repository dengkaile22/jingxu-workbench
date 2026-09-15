using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Domain.Effects;

public enum FourScreenSourceMode
{
    CurrentClip,
    RandomCurrentFolder
}

public enum FourScreenPosition
{
    TopLeft,
    TopRight,
    BottomLeft,
    BottomRight
}

/// <summary>入队时确定的一格素材、位置和主素材标记。</summary>
public sealed record FourScreenCellSelection(FourScreenPosition Position, MediaAsset SourceAsset, bool IsMain);

/// <summary>一个片段的四格素材快照，位置按左上、右上、左下、右下区分。</summary>
public sealed record FourScreenClipSelection(int ClipIndex, IReadOnlyList<FourScreenCellSelection> Cells);

/// <summary>从指定片段至结尾的 2×2 四屏效果，所有素材与位置在入队时固定。</summary>
public sealed record FourScreenEffectPlan
{
    public const int DefaultFeatherPixels = 48;
    public const int MaxFeatherPixels = 256;

    public int StartClipIndex { get; init; }
    public FourScreenSourceMode SourceMode { get; init; }
    public bool FeatherEnabled { get; init; }
    public int FeatherPixels { get; init; }
    public IReadOnlyList<FourScreenClipSelection> ClipSelections { get; init; }

    public FourScreenEffectPlan(
        int StartClipIndex,
        FourScreenSourceMode SourceMode = FourScreenSourceMode.CurrentClip,
        bool FeatherEnabled = true,
        int FeatherPixels = DefaultFeatherPixels,
        IReadOnlyList<FourScreenClipSelection>? ClipSelections = null)
    {
        this.StartClipIndex = StartClipIndex;
        this.SourceMode = SourceMode;
        this.FeatherEnabled = FeatherEnabled;
        this.FeatherPixels = FeatherPixels;
        this.ClipSelections = ClipSelections ?? [];
    }

    public static Result<FourScreenEffectPlan> Create(
        int startClipIndex,
        FourScreenSourceMode sourceMode = FourScreenSourceMode.CurrentClip,
        bool featherEnabled = true,
        int featherPixels = DefaultFeatherPixels) =>
        startClipIndex < 1
            ? Result<FourScreenEffectPlan>.Failure("四屏起始视频必须从 1 开始。")
            : !Enum.IsDefined(sourceMode)
                ? Result<FourScreenEffectPlan>.Failure("四屏素材来源无效。")
                : featherPixels is < 0 or > MaxFeatherPixels
                    ? Result<FourScreenEffectPlan>.Failure($"四屏羽化宽度必须在 0 到 {MaxFeatherPixels} 像素之间。")
                    : Result<FourScreenEffectPlan>.Success(new FourScreenEffectPlan(
                        startClipIndex, sourceMode, featherEnabled, featherPixels));

    public bool AppliesTo(int zeroBasedClipIndex) =>
        zeroBasedClipIndex >= 0 && zeroBasedClipIndex + 1 >= StartClipIndex;

    public FourScreenClipSelection? SelectionFor(int zeroBasedClipIndex) =>
        ClipSelections.FirstOrDefault(selection => selection.ClipIndex == zeroBasedClipIndex);

    public Result<FourScreenEffectPlan> MaterializeForPlan(
        CompositionPlan plan,
        IReadOnlyList<MediaAsset> sourceAssets,
        int planIndex)
    {
        ArgumentNullException.ThrowIfNull(plan);
        ArgumentNullException.ThrowIfNull(sourceAssets);

        var validation = Create(StartClipIndex, SourceMode, FeatherEnabled, FeatherPixels);
        if (!validation.IsSuccess)
        {
            return validation;
        }

        if (StartClipIndex > plan.Clips.Count)
        {
            return Result<FourScreenEffectPlan>.Failure($"四屏起始视频必须在 1 到 {plan.Clips.Count} 之间。");
        }

        if (SourceMode == FourScreenSourceMode.RandomCurrentFolder && sourceAssets.Count == 0)
        {
            return Result<FourScreenEffectPlan>.Failure("四屏随机素材需要已导入的素材池。");
        }

        var normalized = sourceAssets
            .OrderBy(asset => asset.SequenceIndex ?? int.MaxValue)
            .ThenBy(asset => asset.Path, StringComparer.OrdinalIgnoreCase)
            .ThenBy(asset => asset.Id)
            .DistinctBy(asset => Path.GetFullPath(asset.Path), StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var selections = new List<FourScreenClipSelection>();

        for (var clipIndex = 0; clipIndex < plan.Clips.Count; clipIndex++)
        {
            if (!AppliesTo(clipIndex))
            {
                continue;
            }

            var main = plan.Clips[clipIndex].Asset;
            var random = new DeterministicRandom(unchecked(
                (long)((ulong)(uint)plan.Seed * 0x9E3779B97F4A7C15UL)
                ^ ((long)planIndex * unchecked((long)0xBF58476D1CE4E5B9UL))
                ^ ((long)clipIndex * 0x1F123BB5L) ^ 0x4F555253L));
            var randomMode = SourceMode == FourScreenSourceMode.RandomCurrentFolder;
            var mainPosition = randomMode ? random.Next(4) : 0;
            var folder = Path.GetDirectoryName(Path.GetFullPath(main.Path));
            var candidates = randomMode
                ? normalized.Where(asset => !SameAsset(asset, main) && string.Equals(
                    Path.GetDirectoryName(Path.GetFullPath(asset.Path)), folder, StringComparison.OrdinalIgnoreCase)).ToArray()
                : [];

            // 一格内先洗牌，再按顺序取完候选后循环；不跨洗牌周期抽样，避免充足时出现重复。
            for (var index = candidates.Length - 1; index > 0; index--)
            {
                var other = random.Next(index + 1);
                (candidates[index], candidates[other]) = (candidates[other], candidates[index]);
            }

            var cells = new FourScreenCellSelection[4];
            var auxiliaryIndex = 0;
            for (var position = 0; position < cells.Length; position++)
            {
                var isMain = position == mainPosition;
                var source = isMain || candidates.Length == 0
                    ? main
                    : candidates[auxiliaryIndex++ % candidates.Length];
                cells[position] = new FourScreenCellSelection((FourScreenPosition)position, source, isMain);
            }

            selections.Add(new FourScreenClipSelection(clipIndex, Array.AsReadOnly(cells)));
        }

        return Result<FourScreenEffectPlan>.Success(this with { ClipSelections = selections.AsReadOnly() });
    }

    private static bool SameAsset(MediaAsset left, MediaAsset right) =>
        left.Id == right.Id || SameFile(left, right);

    private static bool SameFile(MediaAsset left, MediaAsset right) => string.Equals(
            Path.GetFullPath(left.Path), Path.GetFullPath(right.Path), StringComparison.OrdinalIgnoreCase);

    /// <summary>校验排队快照，拒绝缺格、重复位置、错误主素材或未物化任务。</summary>
    public Result<Unit> ValidateForPlan(CompositionPlan plan)
    {
        ArgumentNullException.ThrowIfNull(plan);
        const string error = "四屏素材快照不完整或无效，请重新入队后再开始渲染。";
        if (!Create(StartClipIndex, SourceMode, FeatherEnabled, FeatherPixels).IsSuccess ||
            StartClipIndex > plan.Clips.Count ||
            ClipSelections is null || ClipSelections.Any(selection => selection is null) ||
            ClipSelections.Count != plan.Clips.Count - StartClipIndex + 1 ||
            ClipSelections.Select(selection => selection.ClipIndex).Distinct().Count() != ClipSelections.Count)
        {
            return Result<Unit>.Failure(error);
        }

        foreach (var selection in ClipSelections)
        {
            if (selection.ClipIndex < 0 || selection.ClipIndex >= plan.Clips.Count || !AppliesTo(selection.ClipIndex) ||
                selection.Cells is null || selection.Cells.Count != 4 ||
                selection.Cells.Any(cell => cell is null || cell.SourceAsset is null ||
                    string.IsNullOrWhiteSpace(cell.SourceAsset.Path) || !Enum.IsDefined(cell.Position)) ||
                selection.Cells.Select(cell => cell.Position).Distinct().Count() != 4 ||
                selection.Cells.Count(cell => cell.IsMain) != 1)
            {
                return Result<Unit>.Failure(error);
            }

            var main = plan.Clips[selection.ClipIndex].Asset;
            if (!SameFile(selection.Cells.Single(cell => cell.IsMain).SourceAsset, main) ||
                (SourceMode == FourScreenSourceMode.CurrentClip && selection.Cells.Any(cell => !SameFile(cell.SourceAsset, main))))
            {
                return Result<Unit>.Failure(error);
            }
        }

        return Result<Unit>.Success(default);
    }
}
