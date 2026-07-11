using System.Windows;
using JingXu.Workbench.Bootstrap;

namespace JingXu.Workbench;

/// <summary>
/// 应用入口。启动时构建组合根，创建壳层窗口并显示。
/// 基类 <c>System.Windows.Application</c> 由 XAML 生成的分部类提供，
/// 此处不重复指定以避开与 <c>JingXu.Workbench.Application</c> 命名空间的歧义。
/// </summary>
public partial class App
{
    protected override void OnStartup(StartupEventArgs e)
    {
        AppExceptionLogger.Install(this);

        if (e.Args.Contains("--self-test", StringComparer.Ordinal))
        {
            var exitCode = SelfTestRunner.Run(e.Args);
            Shutdown(exitCode);
            return;
        }

        if (e.Args.Any(a => string.Equals(a, "--import-smoke", StringComparison.OrdinalIgnoreCase)))
        {
            var exitCode = ImportSmokeRunner.Run(e.Args);
            Shutdown(exitCode);
            return;
        }

        if (e.Args.Any(a => string.Equals(a, "--overlay-smoke", StringComparison.OrdinalIgnoreCase)))
        {
            var exitCode = OverlaySmokeRunner.Run(e.Args);
            Shutdown(exitCode);
            return;
        }

        base.OnStartup(e);

        var compositionRoot = new AppCompositionRoot();
        var shell = compositionRoot.CreateShell();

        var window = new ShellWindow { DataContext = shell };
        MainWindow = window;
        window.Show();
    }
}
