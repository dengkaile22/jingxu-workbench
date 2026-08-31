using System.Windows.Threading;
using JingXu.Workbench.Application.Abstractions;

namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// WPF 生产环境 UI 调度器。构造时固定捕获 Dispatcher，避免运行期
/// <c>Application.Current</c> 为空时误在调用线程执行（会触发 CollectionView 跨线程异常）。
/// </summary>
public sealed class WpfUiDispatcher : IUiDispatcher
{
    private static readonly DispatcherPriority Priority = DispatcherPriority.Normal;

    private readonly Dispatcher _dispatcher;

    /// <summary>使用指定 Dispatcher；未指定时优先 Application.Current，否则 CurrentDispatcher。</summary>
    public WpfUiDispatcher(Dispatcher? dispatcher = null)
    {
        _dispatcher = dispatcher
            ?? System.Windows.Application.Current?.Dispatcher
            ?? Dispatcher.CurrentDispatcher;
    }

    public void Invoke(Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        if (_dispatcher.CheckAccess())
        {
            action();
            return;
        }

        _dispatcher.Invoke(action, Priority);
    }

    public T Invoke<T>(Func<T> func)
    {
        ArgumentNullException.ThrowIfNull(func);
        if (_dispatcher.CheckAccess())
        {
            return func();
        }

        return _dispatcher.Invoke(func, Priority);
    }

    public bool CheckAccess() => _dispatcher.CheckAccess();

    public void Post(Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        if (_dispatcher.CheckAccess())
        {
            action();
            return;
        }

        _ = _dispatcher.BeginInvoke(action, DispatcherPriority.Loaded);
    }
}
