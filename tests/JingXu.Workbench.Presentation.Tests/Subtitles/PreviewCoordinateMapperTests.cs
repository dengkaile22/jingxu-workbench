using System.Windows;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Features.Subtitles;

namespace JingXu.Workbench.Presentation.Tests.Subtitles;

public sealed class PreviewCoordinateMapperTests
{
    [Fact]
    public void Sixteen_by_nine_in_matching_viewport_fills_without_letterbox()
    {
        var mapper = new PreviewCoordinateMapper(1920, 1080, rotationDegrees: 0);
        var layout = mapper.ComputeLayout(960, 540);

        Assert.Equal(0, layout.ContentLeft, 3);
        Assert.Equal(0, layout.ContentTop, 3);
        Assert.Equal(960, layout.ContentWidth, 3);
        Assert.Equal(540, layout.ContentHeight, 3);
    }

    [Fact]
    public void Wide_video_in_square_viewport_letterboxes_vertically()
    {
        var mapper = new PreviewCoordinateMapper(1920, 1080, rotationDegrees: 0);
        var layout = mapper.ComputeLayout(400, 400);

        Assert.True(layout.ContentHeight < 400);
        Assert.Equal(400, layout.ContentWidth, 3);
        Assert.True(layout.ContentTop > 0);
        Assert.Equal(0, layout.ContentLeft, 3);
    }

    [Fact]
    public void Normalized_rect_round_trips_through_viewport_mapping()
    {
        var mapper = new PreviewCoordinateMapper(1280, 720, rotationDegrees: 0);
        var layout = mapper.ComputeLayout(640, 360);
        var original = new NormalizedRect(0.1, 0.7, 0.8, 0.2);

        var viewport = PreviewCoordinateMapper.NormalizedToViewportRect(original, layout);
        var back = PreviewCoordinateMapper.ViewportRectToNormalized(
            viewport.X,
            viewport.Y,
            viewport.Width,
            viewport.Height,
            layout);

        Assert.True(back.IsSuccess);
        Assert.Equal(original.X, back.Value!.X, 3);
        Assert.Equal(original.Y, back.Value.Y, 3);
        Assert.Equal(original.Width, back.Value.Width, 3);
        Assert.Equal(original.Height, back.Value.Height, 3);
    }

    [Fact]
    public void Rotation_ninety_swaps_display_aspect_for_layout()
    {
        var mapper = new PreviewCoordinateMapper(1920, 1080, rotationDegrees: 90);
        var layout = mapper.ComputeLayout(540, 960);

        Assert.Equal(540, layout.ContentWidth, 3);
        Assert.Equal(960, layout.ContentHeight, 3);
    }

    [Fact]
    public void Selection_outside_content_fails_conversion()
    {
        var mapper = new PreviewCoordinateMapper(1920, 1080, rotationDegrees: 0);
        var layout = mapper.ComputeLayout(640, 360);
        var outsideX = layout.ContentRight + 20;
        var result = PreviewCoordinateMapper.ViewportRectToNormalized(
            outsideX,
            layout.ContentTop,
            10,
            10,
            layout);

        Assert.False(result.IsSuccess);
    }
}
