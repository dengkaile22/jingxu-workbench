namespace JingXu.Workbench.Domain.Composition;

/// <summary>
/// 将素材索引排成一个确定性的随机袋：一轮内每个索引只出现一次，
/// 用完后再从同一随机顺序开始，避免相邻任务反复命中同一素材。
/// </summary>
public static class DeterministicShuffleCycle
{
    /// <summary>按随机袋中的全局抽取序号返回素材索引。</summary>
    public static int SelectIndex(
        int itemCount,
        int seed,
        long selectionOrdinal,
        int branchIndex = 0)
    {
        if (itemCount <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(itemCount), "素材数量必须大于零。");
        }

        ArgumentOutOfRangeException.ThrowIfNegative(selectionOrdinal);
        if (itemCount == 1)
        {
            return 0;
        }

        var order = Enumerable.Range(0, itemCount).ToArray();
        var random = DeterministicRandom.FromBranch(seed, branchIndex);

        // 先随机确定首项，再只洗牌剩余项。这样既保持均匀随机，
        // 也兼容旧算法在序号 0 时使用的随机起点。
        var firstIndex = random.Next(itemCount);
        (order[0], order[firstIndex]) = (order[firstIndex], order[0]);
        for (var i = itemCount - 1; i > 1; i--)
        {
            var target = 1 + random.Next(i);
            (order[i], order[target]) = (order[target], order[i]);
        }

        return order[(int)(selectionOrdinal % itemCount)];
    }

    /// <summary>
    /// 按逐轮重洗牌的随机袋返回素材索引。每轮仍完整覆盖全部素材，
    /// 但下一轮会派生新顺序，并避免轮次交界连续命中同一素材。
    /// </summary>
    public static int SelectIndexWithReshuffledCycles(
        int itemCount,
        int seed,
        long selectionOrdinal,
        int branchIndex = 0)
    {
        if (itemCount <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(itemCount), "素材数量必须大于零。");
        }

        ArgumentOutOfRangeException.ThrowIfNegative(selectionOrdinal);
        if (itemCount <= 2)
        {
            // 两项时连续不重复已经是最大差异，只能保持交替。
            return SelectIndex(itemCount, seed, selectionOrdinal, branchIndex);
        }

        var cycleOrdinal = selectionOrdinal / itemCount;
        var offset = (int)(selectionOrdinal % itemCount);
        var order = BuildCycleOrder(itemCount, seed, cycleOrdinal, branchIndex);
        if (cycleOrdinal > 0)
        {
            var previous = BuildCycleOrder(itemCount, seed, cycleOrdinal - 1, branchIndex);
            if (order.SequenceEqual(previous))
            {
                (order[0], order[1]) = (order[1], order[0]);
            }

            if (order[0] == previous[^1])
            {
                (order[0], order[1]) = (order[1], order[0]);
            }
        }

        return order[offset];
    }

    private static int[] BuildCycleOrder(
        int itemCount,
        int seed,
        long cycleOrdinal,
        int branchIndex)
    {
        var cycleBits = unchecked((long)((ulong)cycleOrdinal * 0x9E3779B97F4A7C15UL));
        var mixedSeed = unchecked(((long)seed << 32) ^ cycleBits ^ (uint)branchIndex);
        var random = new DeterministicRandom(mixedSeed);
        var order = Enumerable.Range(0, itemCount).ToArray();
        for (var index = order.Length - 1; index > 0; index--)
        {
            var target = random.Next(index + 1);
            (order[index], order[target]) = (order[target], order[index]);
        }

        return order;
    }
}
