namespace JingXu.Workbench.Domain.Effects;

/// <summary>音频库条目。</summary>
public sealed record AudioLibraryEntry(
    Guid Id,
    string FilePath,
    TimeSpan Duration,
    string? DisplayName,
    DateTimeOffset? LastUsedAt)
{
    public string FileName => System.IO.Path.GetFileName(FilePath);
}

/// <summary>音频音量模式。</summary>
public enum AudioVolumeMode
{
    /// <summary>使用默认音量（BGM 默认 18%）。</summary>
    Default,

    /// <summary>固定音量值。</summary>
    Fixed,

    /// <summary>在区间内随机。</summary>
    RandomRange
}

/// <summary>音频增益映射。</summary>
public static class AudioVolumeMapping
{
    /// <summary>允许的最小音量百分比。</summary>
    public const double MinPercent = -100;

    /// <summary>允许的最大音量百分比。</summary>
    public const double MaxPercent = 100;

    /// <summary>
    /// 将用户界面 -100~+100 的百分比值映射为 FFmpeg volume 增益因子。
    /// -100 → 0.0（静音），0 → 0.18（默认 BGM 音量），+100 → 1.0（最大）。
    /// 这样用户调负值就能获得比默认更小的音量。
    /// </summary>
    public static double PercentToGain(double percent)
    {
        var clamped = Math.Clamp(percent, MinPercent, MaxPercent);
        const double defaultBgmGain = 0.18;
        if (clamped <= 0)
        {
            // -100~0：从静音线性过渡到默认 BGM 音量
            return defaultBgmGain * (1.0 + clamped / 100.0);
        }
        // 0~+100：从默认 BGM 音量线性过渡到最大（100%）
        return defaultBgmGain + (1.0 - defaultBgmGain) * (clamped / 100.0);
    }
}

/// <summary>
/// 音频库物化后的混音计划（入队时生成，可转为 BgmMixPlan 复用现有渲染管线）。
/// </summary>
public sealed record AudioLibraryMixPlan(
    string Path,
    TimeSpan SourceDuration,
    double OriginalVolume,
    double BgmVolume,
    double FadeOutSeconds)
{
    /// <summary>物化为 BgmMixPlan（复用现有渲染管线）。</summary>
    public BgmMixPlan ToBgmMixPlan() =>
        new(Path, OriginalVolume, BgmVolume, FadeOutSeconds);
}
