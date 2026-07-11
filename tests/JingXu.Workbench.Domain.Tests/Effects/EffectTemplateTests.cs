using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Domain.Tests.Effects;

public sealed class EffectTemplateTests
{
    [Fact]
    public void Same_seed_materializes_same_randomized_effects()
    {
        var template = EffectTemplates.StandardVariation();
        Assert.Equal(template.Materialize(264513), template.Materialize(264513));
    }

    [Fact]
    public void Different_seeds_produce_different_effects()
    {
        var template = EffectTemplates.StandardVariation();
        Assert.NotEqual(template.Materialize(1), template.Materialize(2));
    }

    [Fact]
    public void Variation_never_changes_playback_rate()
    {
        var effect = EffectTemplates.StandardVariation().Materialize(1);
        Assert.Equal(1.0, MaterializedEffect.PlaybackRate);
    }

    [Fact]
    public void Invalid_crop_range_fails_validation()
    {
        var result = EffectVariationTemplate.Create(
            id: "bad",
            displayName: "无效",
            enableMirror: true,
            minCropPercent: 5,
            maxCropPercent: 3,
            minBrightness: -0.1,
            maxBrightness: 0.1,
            minContrast: 0.9,
            maxContrast: 1.1,
            minSaturation: 0.9,
            maxSaturation: 1.1,
            minDenoise: 0,
            maxDenoise: 2,
            enableMetadataClearing: false);

        Assert.False(result.IsSuccess);
    }

    [Fact]
    public void Bgm_plan_rejects_invalid_volume()
    {
        var result = BgmMixPlan.Create(@"C:\bgm.mp3", originalVolume: 1.5, bgmVolume: 0.2, fadeOutSeconds: 1);
        Assert.False(result.IsSuccess);
        Assert.Contains("原声音量", result.Error, StringComparison.Ordinal);
    }

    [Fact]
    public void Bgm_plan_defaults_match_spec()
    {
        var plan = BgmMixPlan.Create(@"C:\bgm.mp3").Value!;
        Assert.Equal(1.0, plan.OriginalVolume);
        Assert.Equal(0.18, plan.BgmVolume);
        Assert.Equal(1.0, plan.FadeOutSeconds);
    }

    [Fact]
    public void Image_sticker_uses_normalized_bounds()
    {
        var sticker = ImageSticker.Create(
            @"C:\贴纸.png",
            x: 0.1,
            y: 0.2,
            width: 0.3,
            height: 0.25,
            opacity: 0.8).Value!;

        Assert.Equal(0.1, sticker.Bounds.X);
        Assert.Equal(0.8, sticker.Opacity);
    }

    [Fact]
    public void Materialized_effect_with_metadata_clearing_keeps_playback_rate()
    {
        var effect = EffectTemplates.StandardVariation().Materialize(99) with { ClearMetadata = true };
        Assert.True(effect.ClearMetadata);
        Assert.Equal(1.0, MaterializedEffect.PlaybackRate);
    }
}
