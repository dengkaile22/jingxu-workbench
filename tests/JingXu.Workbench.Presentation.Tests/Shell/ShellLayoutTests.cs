using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using JingXu.Workbench.Features.Settings;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Features.Stickers;
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

    [Fact]
    public void Rail_selection_switches_the_real_module_content()
    {
        _app.Invoke(() =>
        {
            var shell = ShellViewModelTestFactory.Create();
            var window = CreateWindow(shell, 1280, 720);

            try
            {
                window.Show();
                window.UpdateLayout();

                var rail = FindDescendant<ListBox>(
                    window,
                    list => AutomationProperties.GetName(list) == "模块导航");
                Assert.NotNull(rail);

                rail!.SelectedValue = WorkspaceModule.Settings;
                window.UpdateLayout();

                var host = Assert.IsType<ContentControl>(window.FindName("ModuleContentHost"));
                Assert.Same(shell.CurrentModule, host.Content);
                Assert.Equal(WorkspaceModule.Settings, shell.CurrentModule.ModuleKind);
                Assert.NotNull(FindDescendant<SettingsView>(host));

                rail.SelectedValue = WorkspaceModule.Stickers;
                window.UpdateLayout();

                Assert.Same(shell.StickerModule, host.Content);
                Assert.Equal(WorkspaceModule.Stickers, shell.CurrentModule.ModuleKind);
                Assert.NotNull(FindDescendant<StickerEditorView>(host));
            }
            finally
            {
                window.Close();
            }
        });
    }

    [Theory]
    [InlineData(WorkspaceModule.Overlays)]
    [InlineData(WorkspaceModule.Stickers)]
    [InlineData(WorkspaceModule.Downloads)]
    [InlineData(WorkspaceModule.Queue)]
    [InlineData(WorkspaceModule.Settings)]
    public void Tool_modules_use_the_full_center_workspace_at_customer_window_size(
        WorkspaceModule module)
    {
        _app.Invoke(() =>
        {
            var shell = ShellViewModelTestFactory.Create();
            shell.NavigateCommand.Execute(module);
            var window = CreateWindow(shell, 1280, 720);

            try
            {
                window.Show();
                window.UpdateLayout();

                var center = Assert.IsAssignableFrom<FrameworkElement>(window.FindName("CenterRegion"));
                var gate = Assert.IsAssignableFrom<FrameworkElement>(window.FindName("GateWell"));
                var host = Assert.IsAssignableFrom<FrameworkElement>(window.FindName("ModuleContentHost"));

                Assert.Equal(Visibility.Collapsed, gate.Visibility);
                Assert.Equal(center.ActualHeight, host.ActualHeight, precision: 1);
                var hostTop = host.TransformToAncestor(center).Transform(new Point(0, 0)).Y;
                Assert.InRange(hostTop, -1, 1);
            }
            finally
            {
                window.Close();
            }
        });
    }

    [Fact]
    public void Composition_module_keeps_the_gate_preview_above_its_controls()
    {
        _app.Invoke(() =>
        {
            var shell = ShellViewModelTestFactory.Create();
            var window = CreateWindow(shell, 1280, 720);

            try
            {
                window.Show();
                window.UpdateLayout();

                var center = Assert.IsAssignableFrom<FrameworkElement>(window.FindName("CenterRegion"));
                var gate = Assert.IsAssignableFrom<FrameworkElement>(window.FindName("GateWell"));
                var host = Assert.IsAssignableFrom<FrameworkElement>(window.FindName("ModuleContentHost"));

                Assert.Equal(Visibility.Visible, gate.Visibility);
                Assert.True(host.ActualHeight < center.ActualHeight);
                var hostTop = host.TransformToAncestor(center).Transform(new Point(0, 0)).Y;
                Assert.True(hostTop > 0);
            }
            finally
            {
                window.Close();
            }
        });
    }

    [Fact]
    public void Module_content_is_clipped_to_the_center_workspace()
    {
        _app.Invoke(() =>
        {
            var shell = ShellViewModelTestFactory.Create();
            shell.NavigateCommand.Execute(WorkspaceModule.Stickers);
            var window = CreateWindow(shell, 1280, 720);

            try
            {
                window.Show();
                window.UpdateLayout();

                var host = Assert.IsType<ContentControl>(window.FindName("ModuleContentHost"));
                Assert.True(host.ClipToBounds);
            }
            finally
            {
                window.Close();
            }
        });
    }

    private static JingXu.Workbench.ShellWindow CreateWindow(
        ShellViewModel shell,
        double width,
        double height) =>
        new()
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

    private static T? FindDescendant<T>(
        DependencyObject root,
        Func<T, bool>? predicate = null)
        where T : DependencyObject
    {
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(root); i++)
        {
            var child = VisualTreeHelper.GetChild(root, i);
            if (child is T match && (predicate is null || predicate(match)))
            {
                return match;
            }

            var descendant = FindDescendant(child, predicate);
            if (descendant is not null)
            {
                return descendant;
            }
        }

        return null;
    }
}
