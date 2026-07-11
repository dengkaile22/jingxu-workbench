namespace JingXu.Workbench.Application.Abstractions;

/// <summary>
/// UI 线程调度抽象。生产环境由 WPF Dispatcher 实现；
/// 测试环境由同步直调实现，避免依赖 Application.Current。
/// </summary>
public interface IUiDispatcher
{
    /// <summary>在 UI 线程上同步执行指定操作。</summary>
    void Invoke(Action action);

    /// <summary>在 UI 线程上同步执行指定操作并返回结果。</summary>
    T Invoke<T>(Func<T> func);

    /// <summary>当前是否已在 UI 线程上。</summary>
    bool CheckAccess();

    /// <summary>将操作投递到 UI 线程稍后执行（不阻塞当前调用）。</summary>
    void Post(Action action);
}
