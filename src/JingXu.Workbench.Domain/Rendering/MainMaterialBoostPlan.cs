using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;

namespace JingXu.Workbench.Domain.Rendering;

/// <summary>主素材音量/缩放参数模式：固定值或区间内随机。</summary>
public enum MainMaterialBoostMode
{
    /// <summary>全部分镜使用同一固定百分比。</summary>
    Fixed,

    /// <summary>每个分镜在区间内独立随机（种子可复现）。</summary>
    Random
}

/// <summary>
/// 拼接合成主素材的音量调大与缩放（100%–110%）。
/// 仅作用于主轨 concat 前各 clip；蒙版/贴纸/BGM 输入不受影响。
/// </summary>
/// <remarks>
/// 响度假设：启用音量时，各 clip 音频在增益前先经单遍
/// <c>loudnorm=I=-16:TP=-1.5:LRA=11</c> 归一到相近响度，再叠加 100%–110% 的
/// <c>volume</c> 增益。非双遍测量，短片段可能略有偏差。
/// </remarks>
public sealed record MainMaterialBoostPlan(
    bool EnableVolume,
    MainMaterialBoostMode VolumeMode,
    double VolumeMinPercent,
    double VolumeMaxPercent,
    bool EnableScale,
    MainMaterialBoostMode ScaleMode,
    double ScaleMinPercent,
    double ScaleMaxPercent)
{
    /// <summary>允许的最小百分比（100% = 不放大）。</summary>
    public const double MinPercent = 100;

    /// <summary>允许的最大百分比。</summary>
    public const double MaxPercent = 110;

    /// <summary>是否有任一增强需要写入滤镜图。</summary>
    public bool IsActive => EnableVolume || EnableScale;

    /// <summary>创建并校验主素材增强计划。</summary>
    public static Result<MainMaterialBoostPlan> Create(
        bool enableVolume,
        MainMaterialBoostMode volumeMode,
        double volumeMinPercent,
        double volumeMaxPercent,
        bool enableScale,
        MainMaterialBoostMode scaleMode,
        double scaleMinPercent,
        double scaleMaxPercent)
    {
        if (!enableVolume && !enableScale)
        {
            return Result<MainMaterialBoostPlan>.Failure("请至少启用音量或缩放之一。");
        }

        var volumeRange = ValidatePercentRange(
            enableVolume,
            volumeMode,
            volumeMinPercent,
            volumeMaxPercent,
            "音量");
        if (!volumeRange.IsSuccess)
        {
            return Result<MainMaterialBoostPlan>.Failure(volumeRange.Error!);
        }

        var scaleRange = ValidatePercentRange(
            enableScale,
            scaleMode,
            scaleMinPercent,
            scaleMaxPercent,
            "缩放");
        if (!scaleRange.IsSuccess)
        {
            return Result<MainMaterialBoostPlan>.Failure(scaleRange.Error!);
        }

        return Result<MainMaterialBoostPlan>.Success(new MainMaterialBoostPlan(
            enableVolume,
            volumeMode,
            volumeRange.Value!.Min,
            volumeRange.Value.Max,
            enableScale,
            scaleMode,
            scaleRange.Value!.Min,
            scaleRange.Value.Max));
    }

    /// <summary>按任务种子为每个主轨 clip 物化音量/缩放倍率（1.0–1.1）。</summary>
    public MaterializedMainMaterialBoost Materialize(int seed, int clipCount)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(clipCount);

        var volumeFactors = new double[clipCount];
        var scaleFactors = new double[clipCount];

        for (var i = 0; i < clipCount; i++)
        {
            volumeFactors[i] = EnableVolume
                ? SampleFactor(seed, branchBase: 100, clipIndex: i, VolumeMode, VolumeMinPercent, VolumeMaxPercent)
                : 1.0;
            scaleFactors[i] = EnableScale
                ? SampleFactor(seed, branchBase: 200, clipIndex: i, ScaleMode, ScaleMinPercent, ScaleMaxPercent)
                : 1.0;
        }

        return new MaterializedMainMaterialBoost(
            EnableVolume,
            EnableScale,
            volumeFactors,
            scaleFactors);
    }

    private static double SampleFactor(
        int seed,
        int branchBase,
        int clipIndex,
        MainMaterialBoostMode mode,
        double minPercent,
        double maxPercent)
    {
        if (mode == MainMaterialBoostMode.Fixed || Math.Abs(maxPercent - minPercent) < 0.000001)
        {
            return Math.Round(minPercent / 100.0, 6);
        }

        var rng = DeterministicRandom.FromBranch(seed, branchBase + clipIndex);
        var percent = minPercent + (maxPercent - minPercent) * rng.NextDouble();
        return Math.Round(percent / 100.0, 6);
    }

    private static Result<(double Min, double Max)> ValidatePercentRange(
        bool enabled,
        MainMaterialBoostMode mode,
        double minPercent,
        double maxPercent,
        string label)
    {
        if (!enabled)
        {
            return Result<(double, double)>.Success((MinPercent, MinPercent));
        }

        if (mode == MainMaterialBoostMode.Fixed)
        {
            if (minPercent is < MinPercent or > MaxPercent)
            {
                return Result<(double, double)>.Failure(
                    $"拼接主素材{label}固定值必须在 {MinPercent}%–{MaxPercent}% 之间。");
            }

            return Result<(double, double)>.Success((minPercent, minPercent));
        }

        if (minPercent is < MinPercent or > MaxPercent || maxPercent is < MinPercent or > MaxPercent)
        {
            return Result<(double, double)>.Failure(
                $"拼接主素材{label}随机区间必须在 {MinPercent}%–{MaxPercent}% 之间。");
        }

        if (minPercent > maxPercent)
        {
            return Result<(double, double)>.Failure(
                $"拼接主素材{label}随机下限不能大于上限。");
        }

        return Result<(double, double)>.Success((minPercent, maxPercent));
    }
}

/// <summary>已按种子物化的主轨各 clip 音量/缩放倍率。</summary>
public sealed record MaterializedMainMaterialBoost(
    bool EnableVolume,
    bool EnableScale,
    IReadOnlyList<double> VolumeFactors,
    IReadOnlyList<double> ScaleFactors)
{
    /// <summary>是否需要写入主轨滤镜。</summary>
    public bool IsActive => EnableVolume || EnableScale;

    /// <summary>启用音量时先 loudnorm 再 volume（见 <see cref="MainMaterialBoostPlan"/> 备注）。</summary>
    public bool NormalizeLoudness => EnableVolume;
}
