using System.Windows;
using JingXu.Workbench.Presentation.Tests.Infrastructure;

namespace JingXu.Workbench.Presentation.Tests.Shell;

[Collection(WpfAppScope.Name)]
public sealed class ShellLayoutTests
{
    private readonly WpfAppFixture _app;

    public ShellLayoutTests(WpfAppFixture app) => _app = app;

    [Theory]
    [InlineData(1600, 900)]
    [InlineData(1920, 1080)]
    public void Core_regions_have_positive_size_within_client_area(double width, double height)
    {
        _app.Invoke(() =>
        {
            var shell = ShellViewModelTestFactory.Create();
            var window = new JingXu.Workbench.ShellWindow
            {
                DataContext = shell,
                WindowStartupLocation = WindowStartupLocation.Manual,
                Left = -20000,
                Top = -20000,
                Width = width,
                Height = height,
                ShowActivated = false,
                ShowInTaskbar = false
            };

            try
            {
                window.Show();
                window.UpdateLayout();

                string[] regions =
                [
                    "TitleBarRegion", "ModuleRailRegion", "MaterialRailRegion",
                    "CenterRegion", "InspectorRegion", "QueueRegion", "GateWell", "ModuleContentHost"
                ];

                foreach (var name in regions)
                {
                    var element = window.FindName(name) as FrameworkElement;
                    Assert.NotNull(element);
                    Assert.True(
                        element!.ActualWidth > 0 && element.ActualHeight > 0,
                        $"区域「{name}」尺寸非正：{element.ActualWidth}×{element.ActualHeight}。");
                    Assert.True(
                        element.ActualWidth <= window.ActualWidth + 1 &&
                        element.ActualHeight <= window.ActualHeight + 1,
                        $"区域「{name}」超出窗口客户区。");
                }
            }
            finally
            {
                window.Close();
            }
        });
    }
}
