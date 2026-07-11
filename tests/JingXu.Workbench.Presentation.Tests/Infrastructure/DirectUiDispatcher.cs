using JingXu.Workbench.Application.Abstractions;

namespace JingXu.Workbench.Presentation.Tests.Infrastructure;

/// <summary>
/// 测试环境 UI 调度器。所有调用同步直连，CheckAccess 始终返回 true，
/// 避免依赖 Application.Current 或 Dispatcher 消息循环。
/// </summary>
public sealed class DirectUiDispatcher : IUiDispatcher
{
    public void Invoke(Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        action();
    }

    public T Invoke<T>(Func<T> func)
    {
        ArgumentNullException.ThrowIfNull(func);
        return func();
    }

    public bool CheckAccess() => true;

    public void Post(Action action)
    {
        ArgumentNullException.ThrowIfNull(action);
        action();
    }
}
