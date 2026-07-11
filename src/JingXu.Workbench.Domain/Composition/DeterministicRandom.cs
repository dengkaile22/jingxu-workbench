namespace JingXu.Workbench.Domain.Composition;

/// <summary>
/// 基于 SplitMix64 的确定性伪随机数发生器。
/// 使用自有实现而非 System.Random，确保种子在 .NET 版本升级后仍然稳定可复现。
/// </summary>
public sealed class DeterministicRandom
{
    private ulong _state;

    /// <summary>
    /// 使用指定种子初始化。
    /// </summary>
    public DeterministicRandom(long seed)
    {
        _state = unchecked((ulong)seed);
    }

    /// <summary>
    /// 从指定种子和命名分支派生一个新的独立随机源。
    /// </summary>
    public static DeterministicRandom FromBranch(int baseSeed, int branchIndex)
    {
        // 使用 baseSeed 和 branchIndex 组合生成稳定的子种子
        var mixer = new DeterministicRandom(baseSeed);
        for (var i = 0; i <= branchIndex; i++)
        {
            mixer.NextUInt64();
        }

        return new DeterministicRandom(unchecked((long)mixer.NextUInt64()));
    }

    /// <summary>
    /// 返回下一个 64 位伪随机值（SplitMix64 算法）。
    /// </summary>
    public ulong NextUInt64()
    {
        unchecked
        {
            _state += 0x9E3779B97F4A7C15UL;
            var z = _state;
            z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
            z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
            return z ^ (z >> 31);
        }
    }

    /// <summary>
    /// 返回 [0.0, 1.0) 范围内的均匀分布浮点数。
    /// </summary>
    public double NextDouble() => NextUInt64() / (double)ulong.MaxValue;

    /// <summary>
    /// 返回 [0, exclusiveMax) 范围内的均匀分布整数。
    /// </summary>
    public int Next(int exclusiveMax)
    {
        if (exclusiveMax <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(exclusiveMax), "上界必须为正整数。");
        }

        // 使用拒绝采样避免模偏差
        var threshold = unchecked((ulong)(-(long)exclusiveMax % exclusiveMax));
        while (true)
        {
            var r = NextUInt64();
            if (r >= threshold)
            {
                return (int)(r % (ulong)exclusiveMax);
            }
        }
    }
}
