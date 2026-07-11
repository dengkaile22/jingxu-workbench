using System;
using System.Windows;
using System.Windows.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Presentation.Tests.Infrastructure;
using WpfApplication = System.Windows.Application;

namespace JingXu.Workbench.Presentation.Tests.Themes;

[Collection(WpfAppScope.Name)]
public sealed class ThemeContractTests
{
    private readonly WpfAppFixture _app;

    public ThemeContractTests(WpfAppFixture app) => _app = app;

    [Fact]
    public void Core_palette_keys_resolve_to_brushes()
    {
        string[] keys =
        [
            "Surface.Canvas", "Surface.Panel", "Surface.PanelMuted", "Surface.Rail", "Surface.Sunk",
            "Gate.Well", "Gate.WellDeep", "Brand.Bloom",
            "Brand.Primary", "Brand.PrimaryHover", "Brand.PrimaryPressed",
            "Ink.Primary", "Ink.Muted", "Line.Default", "Line.Strong",
            "Status.Running", "Status.Running.Text", "Status.Failed", "Focus.Ring"
        ];

        _app.Invoke(() =>
        {
            foreach (var key in keys)
            {
                Assert.True(
                    WpfApplication.Current.TryFindResource(key) is SolidColorBrush,
                    $"调色板资源键「{key}」未解析为 SolidColorBrush。");
            }
        });
    }

    [Fact]
    public void Typography_keys_resolve_to_font_families()
    {
        string[] keys = ["Font.Display", "Font.Body", "Font.Mono"];

        _app.Invoke(() =>
        {
            foreach (var key in keys)
            {
                Assert.True(
                    WpfApplication.Current.TryFindResource(key) is FontFamily,
                    $"字体资源键「{key}」未解析为 FontFamily。");
            }
        });
    }

    [Fact]
    public void Control_style_keys_resolve_to_styles()
    {
        string[] keys =
        [
            "Button.Primary", "Button.Secondary", "TitleBar.IconButton", "TitleBar.CloseButton",
            "ModuleRail", "ModuleRail.Item", "Segmented.Item", "Segmented.Container", "Section",
            "Text.Wordmark", "Text.Title", "Text.Body", "Text.Caption", "Text.Mono"
        ];

        _app.Invoke(() =>
        {
            foreach (var key in keys)
            {
                Assert.True(
                    WpfApplication.Current.TryFindResource(key) is Style,
                    $"样式资源键「{key}」未解析为 Style。");
            }
        });
    }

    [Fact]
    public void Metric_keys_resolve()
    {
        _app.Invoke(() =>
        {
            Assert.IsType<CornerRadius>(WpfApplication.Current.TryFindResource("Radius.Standard"));
            Assert.IsType<CornerRadius>(WpfApplication.Current.TryFindResource("Radius.Small"));
            Assert.IsType<double>(WpfApplication.Current.TryFindResource("Size.TitleBar"));
            Assert.IsType<double>(WpfApplication.Current.TryFindResource("Size.Rail"));
        });
    }

    [Fact]
    public void Every_status_presentation_key_resolves_to_a_theme_resource()
    {
        _app.Invoke(() =>
        {
            foreach (var state in Enum.GetValues<JobState>())
            {
                var status = StatusPresentation.For(state);
                Assert.True(
                    WpfApplication.Current.TryFindResource(status.IconKey) is Geometry,
                    $"状态 {state} 的图标键「{status.IconKey}」未解析为 Geometry。");
                Assert.True(
                    WpfApplication.Current.TryFindResource(status.FillKey) is Brush,
                    $"状态 {state} 的填充键「{status.FillKey}」未解析为 Brush。");
                Assert.True(
                    WpfApplication.Current.TryFindResource(status.TextKey) is Brush,
                    $"状态 {state} 的文字键「{status.TextKey}」未解析为 Brush。");
            }
        });
    }

    [Fact]
    public void Module_and_status_icon_geometries_exist()
    {
        string[] geometryKeys =
        [
            "Icon.Module.Composition", "Icon.Module.Overlays", "Icon.Module.Subtitles",
            "Icon.Module.Queue", "Icon.Module.Settings", "Icon.Mark.Interlock",
            "Icon.Status.Running", "Icon.Status.Completed", "Icon.Status.Failed"
        ];

        _app.Invoke(() =>
        {
            foreach (var key in geometryKeys)
            {
                Assert.True(
                    WpfApplication.Current.TryFindResource(key) is Geometry,
                    $"几何资源键「{key}」未解析为 Geometry。");
            }
        });
    }
}
