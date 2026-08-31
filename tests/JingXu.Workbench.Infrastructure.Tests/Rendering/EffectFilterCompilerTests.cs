using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class EffectFilterCompilerTests
{
    [Fact]
    public void Variation_never_changes_speed_or_timeline_duration()
    {
        var effect = EffectTemplates.StandardVariation().Materialize(1);
        Assert.Equal(1.0, MaterializedEffect.PlaybackRate);
        Assert.DoesNotContain("setpts", EffectFilterCompiler.Compile(effect));
    }

    [Fact]
    public void Mirror_compiles_hflip_or_vflip()
    {
        var horizontal = new MaterializedEffect(
            MirrorMode.Horizontal,
            CropPercent: 0,
            Brightness: 0,
            Contrast: 1,
            Saturation: 1,
            DenoiseStrength: 0,
            ClearMetadata: false);

        var graph = EffectFilterCompiler.Compile(horizontal);
        Assert.Contains("hflip", graph, StringComparison.Ordinal);

        var vertical = horizontal with { Mirror = MirrorMode.Vertical };
        Assert.Contains("vflip", EffectFilterCompiler.Compile(vertical), StringComparison.Ordinal);
    }

    [Fact]
    public void Color_and_crop_compile_eq_and_crop_tokens()
    {
        var effect = new MaterializedEffect(
            MirrorMode.None,
            CropPercent: 2,
            Brightness: 0.05,
            Contrast: 1.05,
            Saturation: 1.1,
            DenoiseStrength: 1.5,
            ClearMetadata: false);

        var graph = EffectFilterCompiler.Compile(effect);
        Assert.Contains("crop=", graph, StringComparison.Ordinal);
        Assert.Contains("eq=", graph, StringComparison.Ordinal);
        Assert.Contains("hqdn3d=", graph, StringComparison.Ordinal);
    }

    [Fact]
    public void Image_sticker_compiles_overlay_with_normalized_position()
    {
        var sticker = ImageSticker.Create(
            @"C:\贴纸.png",
            x: 0.1,
            y: 0.2,
            width: 0.3,
            height: 0.25,
            opacity: 0.75).Value!;

        var graph = EffectFilterCompiler.CompileSticker(sticker, inputVideoLabel: "vfx", stickerInputIndex: 3, frameWidth: 1920, frameHeight: 1080);
        Assert.Contains("[3:v]", graph, StringComparison.Ordinal);
        Assert.Contains("overlay=", graph, StringComparison.Ordinal);
        Assert.Contains("shortest=1", graph, StringComparison.Ordinal);
        Assert.Contains("colorchannelmixer=aa=0.75", graph, StringComparison.Ordinal);
    }

    [Fact]
    public void Empty_effect_returns_passthrough_label()
    {
        var effect = MaterializedEffect.Identity;
        var result = EffectFilterCompiler.CompileChain(effect, [], inputVideoLabel: "vbase");
        Assert.Equal("vbase", result.OutputVideoLabel);
        Assert.Empty(result.FilterSuffix);
    }
}
