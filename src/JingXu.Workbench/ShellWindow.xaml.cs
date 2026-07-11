using System.ComponentModel;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;
using JingXu.Workbench.Features.Shell;

namespace JingXu.Workbench;

/// <summary>
/// 工作台壳层窗口。code-behind 仅承载无法自然绑定的窗口行为：
/// 自定义标题栏的最小化/最大化/关闭、启动 stagger 入场、导航过渡淡入、
/// 以及最大化时的边缘裁切补偿。业务逻辑位于 <see cref="ShellViewModel"/>。
/// </summary>
public partial class ShellWindow : Window
{
    private ShellViewModel? _shell;

    public ShellWindow()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (_shell is not null)
        {
            _shell.PropertyChanged -= OnShellPropertyChanged;
        }

        _shell = e.NewValue as ShellViewModel;

        if (_shell is not null)
        {
            _shell.PropertyChanged += OnShellPropertyChanged;
        }
    }

    private void OnShellPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(ShellViewModel.CurrentModule))
        {
            AnimateNavigationFade();
        }
    }

    private void OnLoaded(object sender, RoutedEventArgs e) => PlayEntranceStagger();

    // ── 启动 stagger：六区依次淡入 + 上移 ──────────────────────────────
    private void PlayEntranceStagger()
    {
        FrameworkElement[] regions =
        [
            TitleBarRegion, ModuleRailRegion, MaterialRailRegion,
            CenterRegion, InspectorRegion, QueueRegion
        ];

        var ease = TryFindResource("Motion.Ease") as IEasingFunction
            ?? new CubicEase { EasingMode = EasingMode.EaseOut };
        var step = TryFindResource("Motion.StaggerStepSeconds") is double s ? s : 0.045;
        var rise = TryFindResource("Motion.RisePixels") is double r ? r : 8;
        var duration = new Duration(TimeSpan.FromMilliseconds(160));

        for (var i = 0; i < regions.Length; i++)
        {
            var region = regions[i];
            var transform = new TranslateTransform(0, rise);
            region.RenderTransform = transform;
            region.Opacity = 0;

            var begin = TimeSpan.FromSeconds(step * i);
            region.BeginAnimation(
                OpacityProperty,
                new DoubleAnimation(0, 1, duration) { BeginTime = begin, EasingFunction = ease });
            transform.BeginAnimation(
                TranslateTransform.YProperty,
                new DoubleAnimation(rise, 0, duration) { BeginTime = begin, EasingFunction = ease });
        }
    }

    // ── 导航过渡：模块切换时内容淡入 ──────────────────────────────────
    private void AnimateNavigationFade()
    {
        var ease = TryFindResource("Motion.Ease") as IEasingFunction
            ?? new CubicEase { EasingMode = EasingMode.EaseOut };
        ModuleContentHost.BeginAnimation(
            OpacityProperty,
            new DoubleAnimation(0.2, 1, new Duration(TimeSpan.FromMilliseconds(140))) { EasingFunction = ease });
    }

    // ── 自定义标题栏窗口控制 ──────────────────────────────────────────
    private void OnMinimize(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;

    private void OnMaximizeRestore(object sender, RoutedEventArgs e) =>
        WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;

    private void OnClose(object sender, RoutedEventArgs e) => Close();

    private void OnStateChanged(object? sender, EventArgs e)
    {
        if (WindowState == WindowState.Maximized)
        {
            // 最大化时窗口向外延伸出调整边框，补偿内边距以避免内容被裁切。
            RootBorder.Padding = new Thickness(8);
            RootBorder.BorderThickness = new Thickness(0);
            MaximizeButton.Content = TryFindResource("Icon.Win.Restore");
            MaximizeButton.SetValue(System.Windows.Automation.AutomationProperties.NameProperty, "还原窗口");
        }
        else
        {
            RootBorder.Padding = new Thickness(0);
            RootBorder.BorderThickness = new Thickness(1);
            MaximizeButton.Content = TryFindResource("Icon.Win.Maximize");
            MaximizeButton.SetValue(System.Windows.Automation.AutomationProperties.NameProperty, "最大化窗口");
        }
    }
}
