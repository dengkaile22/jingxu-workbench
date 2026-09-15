using System.Globalization;
using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Threading;

namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// 将未处理异常写入 %LOCALAPPDATA%\JingXu\logs\，并尽量阻止进程因 UI/任务异常退出。
/// </summary>
internal static class AppExceptionLogger
{
    private static readonly object Gate = new();
    private static int _messageShown;

    public static void Install(System.Windows.Application application)
    {
        ArgumentNullException.ThrowIfNull(application);

        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
        {
            Write("AppDomain.UnhandledException", args.ExceptionObject as Exception);
            // IsTerminating 时无法阻止退出，但仍尽量弹出中文提示。
            TryShowMessage(args.ExceptionObject as Exception, fatal: args.IsTerminating);
        };

        application.DispatcherUnhandledException += (_, args) =>
        {
            Write("DispatcherUnhandledException", args.Exception);
            args.Handled = true;
            TryShowMessage(args.Exception, fatal: false);
        };

        application.Dispatcher.UnhandledExceptionFilter += (_, args) =>
        {
            Write("Dispatcher.UnhandledExceptionFilter", args.Exception);
            args.RequestCatch = true;
        };

        TaskScheduler.UnobservedTaskException += (_, args) =>
        {
            Write("TaskScheduler.UnobservedTaskException", args.Exception);
            args.SetObserved();
            TryShowMessage(args.Exception, fatal: false);
        };
    }

    private static void TryShowMessage(Exception? exception, bool fatal)
    {
        if (exception is null)
        {
            return;
        }

        // 避免异常风暴时连弹多个对话框。
        if (Interlocked.Exchange(ref _messageShown, 1) == 1)
        {
            return;
        }

        try
        {
            var title = fatal ? "镜序工作台 · 严重错误" : "镜序工作台 · 操作失败";
            var body = fatal
                ? $"程序遇到严重错误，可能即将退出。\n\n{Describe(exception)}\n\n详细日志：%LOCALAPPDATA%\\JingXu\\logs\\"
                : $"操作失败，但程序仍可继续使用。\n\n{Describe(exception)}\n\n详细日志：%LOCALAPPDATA%\\JingXu\\logs\\";

            var dispatcher = System.Windows.Application.Current?.Dispatcher;
            if (dispatcher is null)
            {
                MessageBox.Show(body, title, MessageBoxButton.OK, MessageBoxImage.Error);
                return;
            }

            if (dispatcher.CheckAccess())
            {
                MessageBox.Show(body, title, MessageBoxButton.OK, MessageBoxImage.Error);
            }
            else
            {
                dispatcher.BeginInvoke(() =>
                    MessageBox.Show(body, title, MessageBoxButton.OK, MessageBoxImage.Error));
            }
        }
        catch
        {
            // 提示失败不得再次抛出。
        }
        finally
        {
            // 允许一段时间后再次提示。
            _ = Task.Run(async () =>
            {
                await Task.Delay(3000).ConfigureAwait(false);
                Interlocked.Exchange(ref _messageShown, 0);
            });
        }
    }

    private static string Describe(Exception exception)
    {
        var message = exception.GetBaseException().Message;
        if (string.IsNullOrWhiteSpace(message))
        {
            message = exception.GetType().Name;
        }

        return message.Length <= 400 ? message : message[..400] + "…";
    }

    private static void Write(string source, Exception? exception)
    {
        if (exception is null)
        {
            return;
        }

        try
        {
            var logDirectory = Path.Combine(
                JingXu.Workbench.Application.Projects.WorkbenchDataPaths.GetDataDirectory(),
                "logs");
            Directory.CreateDirectory(logDirectory);

            var logPath = Path.Combine(logDirectory, $"crash-{DateTime.Now:yyyyMMdd}.log");
            var builder = new StringBuilder();
            builder.AppendLine(CultureInfo.InvariantCulture, $"[{DateTime.Now:O}] {source}");
            builder.AppendLine(exception.ToString());
            builder.AppendLine();

            lock (Gate)
            {
                File.AppendAllText(logPath, builder.ToString(), Encoding.UTF8);
            }
        }
        catch
        {
            // 日志写入失败时不得再次抛出，避免二次崩溃。
        }
    }
}
