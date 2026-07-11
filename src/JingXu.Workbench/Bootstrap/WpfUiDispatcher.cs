using System.Windows.Threading;
using JingXu.Workbench.Application.Abstractions;

namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// WPF 生产环境 UI 调度器。当 Application.Current 不可用或已在 UI 线程时直接调用，
/// 否则通过 Dispatcher.Invoke 同步执行。
/// </summary>
public sealed class WpfUiDispatcher : IUiDispatcher
{
    private static readonly DispatcherPriority Priority = DispatcherPriority.DataBind;

    public void Invoke(Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        var dispatcher = System.Windows.Application.Current?.Dispatcher;
        if (dispatcher is null || dispatcher.CheckAccess())
        {
            action();
            return;
        }

        dispatcher.Invoke(action, Priority);
    }

    public T Invoke<T>(Func<T> func)
    {
        ArgumentNullException.ThrowIfNull(func);
        var dispatcher = System.Windows.Application.Current?.Dispatcher;
        if (dispatcher is null || dispatcher.CheckAccess())
        {
            return func();
        }

        return dispatcher.Invoke(func, Priority);
    }

    public bool CheckAccess()
    {
        var dispatcher = System.Windows.Application.Current?.Dispatcher;
        return dispatcher is null || dispatcher.CheckAccess();
    }
}
