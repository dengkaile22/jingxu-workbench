using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;

namespace JingXu.Workbench.Domain.Effects;

/// <summary>画面镜像模式。</summary>
public enum MirrorMode
{
    /// <summary>不镜像。</summary>
    None,

    /// <summary>水平镜像。</summary>
    Horizontal,

    /// <summary>垂直镜像。</summary>
    Vertical
}

/// <summary>由模板种子实例化后的差异化效果参数。</summary>
public sealed record MaterializedEffect(
    MirrorMode Mirror,
    double CropPercent,
    double Brightness,
    double Contrast,
    double Saturation,
    double DenoiseStrength,
    bool ClearMetadata,
    double RotationDegrees = 0)
{
    /// <summary>播放速率恒为 1.0，差异化处理不得改变业务时长。</summary>
    public const double PlaybackRate = 1.0;

    /// <summary>无视觉效果的身份效果。</summary>
    public static MaterializedEffect Identity { get; } = new(
        MirrorMode.None,
        CropPercent: 0,
        Brightness: 0,
        Contrast: 1,
        Saturation: 1,
        DenoiseStrength: 0,
        ClearMetadata: false,
        RotationDegrees: 0);

    /// <summary>是否包含需要重新编码的画面调整。</summary>
    public bool HasVisualAdjustments =>
        Mirror != MirrorMode.None
        || CropPercent > 0
        || Math.Abs(Brightness) > 0.0001
        || Math.Abs(Contrast - 1.0) > 0.0001
        || Math.Abs(Saturation - 1.0) > 0.0001
        || DenoiseStrength > 0
        || Math.Abs(RotationDegrees) > 0.0001;
}

/// <summary>可保存、可复现的差异化效果模板。</summary>
public sealed record EffectVariationTemplate(
    string Id,
    string DisplayName,
    bool EnableMirror,
    double MinCropPercent,
    double MaxCropPercent,
    double MinBrightness,
    double MaxBrightness,
    double MinContrast,
    double MaxContrast,
    double MinSaturation,
    double MaxSaturation,
    double MinDenoise,
    double MaxDenoise,
    bool EnableMetadataClearing,
    bool EnableRotate = false,
    double MinRotationDegrees = 0,
    double MaxRotationDegrees = 0)
{
    /// <summary>
    /// 按强度系数缩放差异化区间（1.0 = 原强度；0 = 接近无效果；最大 2.0）。
    /// 裁切钳制在 0%–3%；调色相对中性值缩放；降噪按比例缩放；旋转按比例缩放。
    /// </summary>
    public EffectVariationTemplate ScaleIntensity(double intensity)
    {
        var factor = Math.Clamp(intensity, 0, 2);
        if (Math.Abs(factor - 1.0) < 0.0000001)
        {
            return this;
        }

        static double ScaleAround(double value, double center, double f) =>
            center + (value - center) * f;

        var minCrop = Math.Clamp(MinCropPercent * factor, 0, 3);
        var maxCrop = Math.Clamp(MaxCropPercent * factor, 0, 3);
        if (minCrop > maxCrop)
        {
            (minCrop, maxCrop) = (maxCrop, minCrop);
        }

        var minBrightness = ScaleAround(MinBrightness, 0, factor);
        var maxBrightness = ScaleAround(MaxBrightness, 0, factor);
        if (minBrightness > maxBrightness)
        {
            (minBrightness, maxBrightness) = (maxBrightness, minBrightness);
        }

        var minContrast = ScaleAround(MinContrast, 1, factor);
        var maxContrast = ScaleAround(MaxContrast, 1, factor);
        if (minContrast > maxContrast)
        {
            (minContrast, maxContrast) = (maxContrast, minContrast);
        }

        var minSaturation = ScaleAround(MinSaturation, 1, factor);
        var maxSaturation = ScaleAround(MaxSaturation, 1, factor);
        if (minSaturation > maxSaturation)
        {
            (minSaturation, maxSaturation) = (maxSaturation, minSaturation);
        }

        var minDenoise = Math.Max(0, MinDenoise * factor);
        var maxDenoise = Math.Max(minDenoise, MaxDenoise * factor);

        var minRotation = MinRotationDegrees * factor;
        var maxRotation = MaxRotationDegrees * factor;
        if (minRotation > maxRotation)
        {
            (minRotation, maxRotation) = (maxRotation, minRotation);
        }

        return this with
        {
            EnableMirror = EnableMirror && factor >= 0.35,
            MinCropPercent = Math.Round(minCrop, 4),
            MaxCropPercent = Math.Round(maxCrop, 4),
            MinBrightness = Math.Round(minBrightness, 4),
            MaxBrightness = Math.Round(maxBrightness, 4),
            MinContrast = Math.Round(minContrast, 4),
            MaxContrast = Math.Round(maxContrast, 4),
            MinSaturation = Math.Round(minSaturation, 4),
            MaxSaturation = Math.Round(maxSaturation, 4),
            MinDenoise = Math.Round(minDenoise, 4),
            MaxDenoise = Math.Round(maxDenoise, 4),
            EnableMetadataClearing = EnableMetadataClearing && factor >= 0.5,
            EnableRotate = EnableRotate && factor >= 0.35,
            MinRotationDegrees = Math.Round(minRotation, 4),
            MaxRotationDegrees = Math.Round(maxRotation, 4)
        };
    }

    /// <summary>从任务种子实例化效果参数。</summary>
    public MaterializedEffect Materialize(int seed)
    {
        var mirror = EnableMirror
            ? (MirrorMode)DeterministicRandom.FromBranch(seed, branchIndex: 0).Next(3)
            : MirrorMode.None;

        var cropRng = DeterministicRandom.FromBranch(seed, branchIndex: 1);
        var cropPercent = MinCropPercent + (MaxCropPercent - MinCropPercent) * cropRng.NextDouble();

        var brightness = SampleRange(seed, branchIndex: 2, MinBrightness, MaxBrightness);
        var contrast = SampleRange(seed, branchIndex: 3, MinContrast, MaxContrast);
        var saturation = SampleRange(seed, branchIndex: 4, MinSaturation, MaxSaturation);
        var denoise = SampleRange(seed, branchIndex: 5, MinDenoise, MaxDenoise);

        var clearMetadata = EnableMetadataClearing
            && DeterministicRandom.FromBranch(seed, branchIndex: 6).Next(2) == 1;

        var rotation = EnableRotate
            ? SampleRange(seed, branchIndex: 7, MinRotationDegrees, MaxRotationDegrees)
            : 0;

        return new MaterializedEffect(
            mirror,
            Math.Round(cropPercent, 4),
            Math.Round(brightness, 4),
            Math.Round(contrast, 4),
            Math.Round(saturation, 4),
            Math.Round(denoise, 4),
            clearMetadata,
            Math.Round(rotation, 4));
    }

    /// <summary>创建并验证模板范围。</summary>
    public static Result<EffectVariationTemplate> Create(
        string id,
        string displayName,
        bool enableMirror,
        double minCropPercent,
        double maxCropPercent,
        double minBrightness,
        double maxBrightness,
        double minContrast,
        double maxContrast,
        double minSaturation,
        double maxSaturation,
        double minDenoise,
        double maxDenoise,
        bool enableMetadataClearing,
        bool enableRotate = false,
        double minRotationDegrees = 0,
        double maxRotationDegrees = 0)
    {
        if (string.IsNullOrWhiteSpace(id))
        {
            return Result<EffectVariationTemplate>.Failure("效果模板标识不能为空。");
        }

        if (string.IsNullOrWhiteSpace(displayName))
        {
            return Result<EffectVariationTemplate>.Failure("效果模板名称不能为空。");
        }

        if (minCropPercent < 0 || maxCropPercent > 3 || minCropPercent > maxCropPercent)
        {
            return Result<EffectVariationTemplate>.Failure("安全裁切范围必须在 0% 到 3% 之间。");
        }

        if (minBrightness > maxBrightness || minContrast > maxContrast || minSaturation > maxSaturation)
        {
            return Result<EffectVariationTemplate>.Failure("效果参数最小值不能大于最大值。");
        }

        if (minDenoise < 0 || maxDenoise < minDenoise)
        {
            return Result<EffectVariationTemplate>.Failure("降噪强度范围无效。");
        }

        if (minRotationDegrees > maxRotationDegrees
            || minRotationDegrees < -15
            || maxRotationDegrees > 15)
        {
            return Result<EffectVariationTemplate>.Failure("旋转角度范围必须在 -15° 到 15° 之间，且最小值不大于最大值。");
        }

        return Result<EffectVariationTemplate>.Success(
            new EffectVariationTemplate(
                id.Trim(),
                displayName.Trim(),
                enableMirror,
                minCropPercent,
                maxCropPercent,
                minBrightness,
                maxBrightness,
                minContrast,
                maxContrast,
                minSaturation,
                maxSaturation,
                minDenoise,
                maxDenoise,
                enableMetadataClearing,
                enableRotate,
                minRotationDegrees,
                maxRotationDegrees));
    }

    private static double SampleRange(int seed, int branchIndex, double min, double max)
    {
        if (Math.Abs(max - min) < 0.0000001)
        {
            return min;
        }

        var rng = DeterministicRandom.FromBranch(seed, branchIndex);
        return min + rng.NextDouble() * (max - min);
    }
}

/// <summary>内置效果模板集合。</summary>
public static class EffectTemplates
{
    /// <summary>标准差异化模板：镜像、轻裁切、轻旋转、轻调色与轻降噪。</summary>
    public static EffectVariationTemplate StandardVariation() =>
        EffectVariationTemplate.Create(
            id: "standard-variation",
            displayName: "标准差异化",
            enableMirror: true,
            minCropPercent: 1,
            maxCropPercent: 3,
            minBrightness: -0.08,
            maxBrightness: 0.08,
            minContrast: 0.95,
            maxContrast: 1.08,
            minSaturation: 0.92,
            maxSaturation: 1.12,
            minDenoise: 0.5,
            maxDenoise: 2.5,
            enableMetadataClearing: true,
            enableRotate: true,
            minRotationDegrees: -2,
            maxRotationDegrees: 2).Value!;

    /// <summary>无效果模板。</summary>
    public static EffectVariationTemplate None { get; } =
        EffectVariationTemplate.Create(
            id: "none",
            displayName: "无",
            enableMirror: false,
            minCropPercent: 0,
            maxCropPercent: 0,
            minBrightness: 0,
            maxBrightness: 0,
            minContrast: 1,
            maxContrast: 1,
            minSaturation: 1,
            maxSaturation: 1,
            minDenoise: 0,
            maxDenoise: 0,
            enableMetadataClearing: false,
            enableRotate: false,
            minRotationDegrees: 0,
            maxRotationDegrees: 0).Value!;
}

/// <summary>BGM 混音参数。</summary>
public sealed record BgmMixPlan(
    string Path,
    double OriginalVolume,
    double BgmVolume,
    double FadeOutSeconds)
{
    /// <summary>创建并验证 BGM 混音计划。</summary>
    public static Result<BgmMixPlan> Create(
        string path,
        double originalVolume = 1.0,
        double bgmVolume = 0.18,
        double fadeOutSeconds = 1.0)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return Result<BgmMixPlan>.Failure("BGM 文件路径不能为空。");
        }

        if (originalVolume is < 0 or > 1)
        {
            return Result<BgmMixPlan>.Failure("原声音量必须在 0 到 1 之间。");
        }

        if (bgmVolume is < 0 or > 1)
        {
            return Result<BgmMixPlan>.Failure("BGM 音量必须在 0 到 1 之间。");
        }

        if (fadeOutSeconds is < 0 or > 30)
        {
            return Result<BgmMixPlan>.Failure("BGM 淡出时长必须在 0 到 30 秒之间。");
        }

        return Result<BgmMixPlan>.Success(
            new BgmMixPlan(path.Trim(), originalVolume, bgmVolume, fadeOutSeconds));
    }
}

/// <summary>简单图片贴纸，使用归一化坐标。</summary>
public sealed record ImageSticker(
    string Path,
    NormalizedRect Bounds,
    double Opacity,
    double RotationDegrees = 0.0)
{
    /// <summary>创建并验证图片贴纸。</summary>
    public static Result<ImageSticker> Create(
        string path,
        double x,
        double y,
        double width,
        double height,
        double opacity = 1.0,
        double rotationDegrees = 0.0)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return Result<ImageSticker>.Failure("贴纸文件路径不能为空。");
        }

        if (opacity is < 0 or > 1)
        {
            return Result<ImageSticker>.Failure("贴纸透明度必须在 0 到 1 之间。");
        }

        var bounds = NormalizedRect.Create(x, y, width, height);
        return bounds.IsSuccess
            ? Result<ImageSticker>.Success(new ImageSticker(path.Trim(), bounds.Value, opacity, rotationDegrees))
            : Result<ImageSticker>.Failure(bounds.Error!);
    }
}
