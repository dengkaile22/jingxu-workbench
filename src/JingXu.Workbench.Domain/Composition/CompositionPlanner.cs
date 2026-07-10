using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Domain.Composition;

/// <summary>
/// 根据随机或自定义序号生成可复现的成片组合计划。
/// </summary>
public sealed class CompositionPlanner
{
    /// <summary>
    /// 按自定义序号顺序生成组合计划。
    /// </summary>
    /// <param name="assets">可用素材列表。</param>
    /// <param name="indices">所需序号列表（允许重复）。</param>
    /// <param name="transitionDuration">转场重叠时长（硬切时为 Zero）。</param>
    public static Result<CompositionPlan> PlanCustom(
        IReadOnlyList<MediaAsset> assets,
        IReadOnlyList<int> indices,
        TimeSpan transitionDuration)
    {
        if (assets.Count == 0)
        {
            return Result<CompositionPlan>.Failure("素材列表不能为空。");
        }

        if (indices.Count == 0)
        {
            return Result<CompositionPlan>.Failure("序号列表不能为空。");
        }

        var indexMap = BuildIndexMap(assets);

        var clips = new List<PlannedClip>(indices.Count);
        var currentStart = TimeSpan.Zero;

        for (var i = 0; i < indices.Count; i++)
        {
            var index = indices[i];
            if (!indexMap.TryGetValue(index, out var asset))
            {
                return Result<CompositionPlan>.Failure(
                    $"序号 {index}（第 {i + 1} 项）在素材列表中不存在。");
            }

            clips.Add(new PlannedClip(asset, currentStart, asset.Info.Duration));

            // 下一段起始时间 = 当前起始 + 当前时长 - 转场重叠
            currentStart += asset.Info.Duration;
            if (i < indices.Count - 1)
            {
                currentStart -= transitionDuration;
            }
        }

        // 验证转场不超过相邻片段最短时长
        var validationResult = ValidateTransitions(clips, transitionDuration);
        if (!validationResult.IsSuccess)
        {
            return Result<CompositionPlan>.Failure(validationResult.Error!);
        }

        var totalDuration = CalculateTotalDuration(clips, transitionDuration);

        return Result<CompositionPlan>.Success(
            new CompositionPlan(clips, totalDuration, 0, transitionDuration));
    }

    /// <summary>
    /// 生成批量随机组合计划，保证相同种子可复现。
    /// 在排列空间允许时避免重复顺序。
    /// </summary>
    /// <param name="assets">可用素材列表。</param>
    /// <param name="count">需要生成的成片数量。</param>
    /// <param name="seed">随机种子。</param>
    /// <param name="transitionDuration">可选转场重叠时长。</param>
    public static Result<IReadOnlyList<CompositionPlan>> PlanRandomBatch(
        IReadOnlyList<MediaAsset> assets,
        int count,
        int seed,
        TimeSpan? transitionDuration = null)
    {
        if (assets.Count == 0)
        {
            return Result<IReadOnlyList<CompositionPlan>>.Failure("素材列表不能为空。");
        }

        if (count <= 0)
        {
            return Result<IReadOnlyList<CompositionPlan>>.Failure("成片数量必须为正整数。");
        }

        var transition = transitionDuration ?? TimeSpan.Zero;

        // 按序号 → 路径 → ID 排序，确保输入规范化
        var normalized = NormalizeAssets(assets);

        // 计算排列空间
        var factorialSpace = Factorial(normalized.Count);

        var emittedKeys = new HashSet<string>(StringComparer.Ordinal);
        var plans = new List<CompositionPlan>(count);

        for (var attempt = 0; plans.Count < count; attempt++)
        {
            var rng = DeterministicRandom.FromBranch(seed, attempt);

            // Fisher–Yates shuffle
            var shuffled = normalized.ToArray();
            for (var i = shuffled.Length - 1; i > 0; i--)
            {
                var j = rng.Next(i + 1);
                (shuffled[i], shuffled[j]) = (shuffled[j], shuffled[i]);
            }

            var key = string.Join(',', shuffled.Select(a => a.SequenceIndex ?? 0));

            // 排列未耗尽时去重
            if (emittedKeys.Count < factorialSpace && !emittedKeys.Add(key))
            {
                continue;
            }

            // 排列已耗尽时允许重复
            if (emittedKeys.Count >= factorialSpace)
            {
                emittedKeys.Add(key);
            }

            // 构建时间轴
            var clips = new List<PlannedClip>(shuffled.Length);
            var currentStart = TimeSpan.Zero;
            for (var i = 0; i < shuffled.Length; i++)
            {
                clips.Add(new PlannedClip(shuffled[i], currentStart, shuffled[i].Info.Duration));
                currentStart += shuffled[i].Info.Duration;
                if (i < shuffled.Length - 1)
                {
                    currentStart -= transition;
                }
            }

            var totalDuration = CalculateTotalDuration(clips, transition);
            plans.Add(new CompositionPlan(clips, totalDuration, seed, transition));

            // 防止无限循环：尝试次数上限
            if (attempt > count * 100 + 10000)
            {
                break;
            }
        }

        return Result<IReadOnlyList<CompositionPlan>>.Success(plans);
    }

    private static Dictionary<int, MediaAsset> BuildIndexMap(IReadOnlyList<MediaAsset> assets)
    {
        var map = new Dictionary<int, MediaAsset>();
        foreach (var asset in assets)
        {
            if (asset.SequenceIndex.HasValue)
            {
                map[asset.SequenceIndex.Value] = asset;
            }
        }

        return map;
    }

    private static List<MediaAsset> NormalizeAssets(IReadOnlyList<MediaAsset> assets)
    {
        return assets
            .OrderBy(a => a.SequenceIndex ?? int.MaxValue)
            .ThenBy(a => a.Path, StringComparer.OrdinalIgnoreCase)
            .ThenBy(a => a.Id)
            .ToList();
    }

    private static Result<bool> ValidateTransitions(
        List<PlannedClip> clips,
        TimeSpan transitionDuration)
    {
        if (transitionDuration <= TimeSpan.Zero)
        {
            return Result<bool>.Success(true);
        }

        for (var i = 0; i < clips.Count - 1; i++)
        {
            var shorter = clips[i].Duration < clips[i + 1].Duration
                ? clips[i].Duration
                : clips[i + 1].Duration;
            if (transitionDuration >= shorter)
            {
                return Result<bool>.Failure(
                    $"转场时长 {transitionDuration.TotalSeconds:F1} 秒超过了相邻片段 " +
                    $"{clips[i].Asset.SequenceIndex} 和 {clips[i + 1].Asset.SequenceIndex} 的较短时长。");
            }
        }

        return Result<bool>.Success(true);
    }

    private static TimeSpan CalculateTotalDuration(
        List<PlannedClip> clips,
        TimeSpan transitionDuration)
    {
        if (clips.Count == 0)
        {
            return TimeSpan.Zero;
        }

        var total = TimeSpan.Zero;
        foreach (var clip in clips)
        {
            total += clip.Duration;
        }

        // 减去转场重叠
        if (clips.Count > 1)
        {
            total -= transitionDuration * (clips.Count - 1);
        }

        return total;
    }

    private static long Factorial(int n)
    {
        // 安全上限避免溢出
        if (n > 20)
        {
            return long.MaxValue;
        }

        long result = 1;
        for (var i = 2; i <= n; i++)
        {
            result *= i;
        }

        return result;
    }
}
