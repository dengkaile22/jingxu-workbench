using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Domain.Tests.Rendering;

public sealed class UnifiedAspectPolicyTests
{
    [Fact]
    public void Disabled_policy_returns_inherit_first_aspect()
    {
        var aspect = UnifiedAspectPolicy.Disabled.ToOutputAspect();

        Assert.True(aspect.IsSuccess);
        Assert.True(aspect.Value!.InheritFromFirstClip);
        Assert.Equal(AspectFitMode.CenterCrop, aspect.Value.FitMode);
    }

    [Fact]
    public void Vertical_preset_builds_1080x1920_custom_aspect()
    {
        var policy = new UnifiedAspectPolicy(
            IsEnabled: true,
            Preset: OutputCanvasPreset.Vertical9x16,
            ClipFitMode: AspectFitMode.Letterbox);

        var aspect = policy.ToOutputAspect();

        Assert.True(aspect.IsSuccess);
        Assert.False(aspect.Value!.InheritFromFirstClip);
        Assert.Equal(1080, aspect.Value.TargetWidth);
        Assert.Equal(1920, aspect.Value.TargetHeight);
        Assert.Equal(AspectFitMode.Letterbox, aspect.Value.FitMode);
    }

    [Fact]
    public void Custom_preset_requires_positive_dimensions()
    {
        var policy = new UnifiedAspectPolicy(
            IsEnabled: true,
            Preset: OutputCanvasPreset.Custom,
            CustomWidth: 0,
            CustomHeight: 1920);

        var aspect = policy.ToOutputAspect();

        Assert.False(aspect.IsSuccess);
        Assert.Contains("宽度", aspect.Error, StringComparison.Ordinal);
    }

    [Fact]
    public void Apply_overlay_fit_updates_layers_when_enabled()
    {
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2));
        var policy = new UnifiedAspectPolicy(
            IsEnabled: true,
            OverlayFitMode: OverlayFitMode.Contain);

        var applied = policy.ApplyOverlayFit([layer]);

        Assert.Equal(OverlayFitMode.Contain, applied[0].Fit);
        Assert.Equal(layer.Bounds, applied[0].Bounds);
        Assert.Equal(layer.Scale, applied[0].Scale);
    }

    [Fact]
    public void Apply_overlay_fit_preserves_transform_fields()
    {
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2)) with
        {
            Scale = 0.75,
            OffsetX = 0.1,
            RotationDegrees = 15,
            Feather = 0.3
        };
        var policy = new UnifiedAspectPolicy(
            IsEnabled: true,
            OverlayFitMode: OverlayFitMode.Stretch);

        var applied = policy.ApplyOverlayFit([layer]);

        Assert.Equal(OverlayFitMode.Stretch, applied[0].Fit);
        Assert.Equal(0.75, applied[0].Scale);
        Assert.Equal(15, applied[0].RotationDegrees);
    }

    [Fact]
    public void Preview_description_mentions_enabled_canvas_and_fit_modes()
    {
        var policy = new UnifiedAspectPolicy(
            IsEnabled: true,
            Preset: OutputCanvasPreset.Vertical9x16,
            ClipFitMode: AspectFitMode.CenterCrop,
            OverlayFitMode: OverlayFitMode.FillCrop);

        var text = policy.BuildPreviewDescription();

        Assert.Contains("已启用统一比例", text);
        Assert.Contains("1080×1920", text);
        Assert.Contains("Cover", text);
    }

    [Fact]
    public void Disabled_preview_mentions_inherit_first()
    {
        var text = UnifiedAspectPolicy.Disabled.BuildPreviewDescription(1080, 1920);

        Assert.Contains("未启用统一比例", text);
        Assert.Contains("继承", text);
    }
}
