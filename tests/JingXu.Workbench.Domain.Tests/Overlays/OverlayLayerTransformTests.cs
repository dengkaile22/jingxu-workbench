using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Domain.Tests.Overlays;

public sealed class OverlayLayerTransformTests
{
    [Fact]
    public void Default_transform_matches_jianying_neutral_values()
    {
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2));

        Assert.Equal(OverlayLayer.DefaultScale, layer.Scale);
        Assert.Equal(0, layer.OffsetX);
        Assert.Equal(0, layer.OffsetY);
        Assert.Equal(0, layer.RotationDegrees);
        Assert.Equal(0, layer.Feather);
    }

    [Fact]
    public void Imported_mask_preset_defaults_to_soft_split_feather()
    {
        var layer = OverlayLayer.CreateImportedMaskPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2));

        Assert.Equal(OverlayLayer.GhostOverlayFeather, layer.Feather);
        Assert.Equal(OverlayLayer.GhostOverlayTopFade, layer.TopFade);
        Assert.True(layer.Feather > 0);
    }

    [Theory]
    [InlineData(0.5)]
    [InlineData(2.0)]
    public void Valid_scale_passes_validation(double scale)
    {
        var layer = BaseLayer() with { Scale = scale };
        var result = layer.Validate(clipCount: 3);
        Assert.True(result.IsSuccess);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(5.0)]
    public void Invalid_scale_fails_validation(double scale)
    {
        var layer = BaseLayer() with { Scale = scale };
        var result = layer.Validate(clipCount: 3);
        Assert.False(result.IsSuccess);
        Assert.Contains("缩放", result.Error, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(-0.5, 0.5)]
    [InlineData(0.5, -0.5)]
    public void Valid_offset_passes_validation(double offsetX, double offsetY)
    {
        var layer = BaseLayer() with { OffsetX = offsetX, OffsetY = offsetY };
        Assert.True(layer.Validate(3).IsSuccess);
    }

    [Theory]
    [InlineData(-1.5, 0)]
    [InlineData(0, 1.5)]
    public void Invalid_offset_fails_validation(double offsetX, double offsetY)
    {
        var layer = BaseLayer() with { OffsetX = offsetX, OffsetY = offsetY };
        var result = layer.Validate(3);
        Assert.False(result.IsSuccess);
        Assert.Contains("位移", result.Error, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(-45)]
    [InlineData(90)]
    [InlineData(360)]
    public void Valid_rotation_passes_validation(double degrees)
    {
        var layer = BaseLayer() with { RotationDegrees = degrees };
        Assert.True(layer.Validate(3).IsSuccess);
    }

    [Theory]
    [InlineData(-361)]
    [InlineData(400)]
    public void Invalid_rotation_fails_validation(double degrees)
    {
        var layer = BaseLayer() with { RotationDegrees = degrees };
        var result = layer.Validate(3);
        Assert.False(result.IsSuccess);
        Assert.Contains("旋转", result.Error, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(0.5)]
    [InlineData(1)]
    public void Valid_feather_passes_validation(double feather)
    {
        var layer = BaseLayer() with { Feather = feather };
        Assert.True(layer.Validate(3).IsSuccess);
    }

    [Theory]
    [InlineData(-0.1)]
    [InlineData(1.1)]
    public void Invalid_feather_fails_validation(double feather)
    {
        var layer = BaseLayer() with { Feather = feather };
        var result = layer.Validate(3);
        Assert.False(result.IsSuccess);
        Assert.Contains("羽化", result.Error, StringComparison.Ordinal);
    }

    private static OverlayLayer BaseLayer() =>
        OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2));
}
