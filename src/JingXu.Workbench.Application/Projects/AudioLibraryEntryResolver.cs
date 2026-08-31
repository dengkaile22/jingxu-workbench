using JingXu.Workbench.Application.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Application.Projects;

/// <summary>
/// 入队时从音频库随机选取音频的编排逻辑。
/// 包含文件存在性检测，失效文件自动跳过。
/// </summary>
public static class AudioLibraryEntryResolver
{
    /// <summary>
    /// 从音频库中为单个成片计划选取一条有效的音频。
    /// 文件不存在时自动尝试下一个随机候补（最多重试 <paramref name="maxAttempts"/> 次），
    /// 全部无效时返回 null（静默跳过，不影响渲染）。
    /// </summary>
    public static AudioLibraryEntry? Resolve(
        IReadOnlyList<AudioLibraryEntry> library,
        int jobSeed,
        long planOrdinal,
        FileExistenceCache fileCache,
        int maxAttempts = 5)
    {
        ArgumentNullException.ThrowIfNull(library);
        ArgumentNullException.ThrowIfNull(fileCache);

        if (library.Count == 0)
        {
            return null;
        }

        var safeMax = Math.Min(maxAttempts, library.Count);
        for (var attempt = 0; attempt < safeMax; attempt++)
        {
            var index = DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
                library.Count,
                jobSeed,
                planOrdinal + attempt, // attempt 偏移保证重试不命中同一文件
                branchIndex: 3);

            if (index < 0 || index >= library.Count)
            {
                continue;
            }

            var entry = library[index];
            if (fileCache.Exists(entry.FilePath))
            {
                return entry;
            }
        }

        // 全部候补都失效，静默跳过
        return null;
    }

    /// <summary>
    /// 将音频库条目物化为混音计划。
    /// </summary>
    public static AudioLibraryMixPlan Materialize(
        AudioLibraryEntry entry,
        AudioVolumeMode volumeMode,
        double fixedVolumePercent,
        double volumeMinPercent,
        double volumeMaxPercent,
        int seed,
        long planOrdinal)
    {
        ArgumentNullException.ThrowIfNull(entry);

        double bgmGain;
        if (volumeMode == AudioVolumeMode.Fixed)
        {
            bgmGain = AudioVolumeMapping.PercentToGain(fixedVolumePercent);
        }
        else if (volumeMode == AudioVolumeMode.RandomRange)
        {
            var rng = DeterministicRandom.FromBranch(seed, 200 + (int)(planOrdinal % 1000));
            var percent = volumeMinPercent +
                          (volumeMaxPercent - volumeMinPercent) * rng.NextDouble();
            bgmGain = AudioVolumeMapping.PercentToGain(percent);
        }
        else
        {
            // Default：保持现有 BGM 默认音量 18%
            bgmGain = 0.18;
        }

        return new AudioLibraryMixPlan(
            entry.FilePath,
            entry.Duration,
            OriginalVolume: 1.0, // 原声保持 100%
            BgmVolume: bgmGain,
            FadeOutSeconds: 1.0);
    }
}
