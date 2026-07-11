using System;
using System.Threading;
using System.Windows.Threading;
using WpfApplication = System.Windows.Application;

namespace JingXu.Workbench.Presentation.Tests.Infrastructure;

/// <summary>
/// 在专用 STA 线程上创建单个 WPF <see cref="Application"/>（加载合并的主题字典），
/// 并运行一个 Dispatcher 循环，供主题与布局测试在 UI 线程上执行代码。
/// 通过集合固定装置共享，确保整个进程只存在一个 Application 实例。
/// </summary>
public sealed class WpfAppFixture : IDisposable
{
    private readonly Thread _thread;
    private readonly ManualResetEventSlim _ready = new(false);
    private Dispatcher? _dispatcher;
    private Exception? _startupError;

    public WpfAppFixture()
    {
        _thread = new Thread(Run) { IsBackground = true, Name = "WpfAppFixture" };
        _thread.SetApartmentState(ApartmentState.STA);
        _thread.Start();
        _ready.Wait();

        if (_startupError is not null)
        {
            throw new InvalidOperationException("WPF 测试宿主初始化失败。", _startupError);
        }
    }

    private void Run()
    {
        try
        {
            var app = WpfApplication.Current ?? new JingXu.Workbench.App();
            if (app is JingXu.Workbench.App typed && app.Resources.MergedDictionaries.Count == 0)
            {
                typed.InitializeComponent();
            }

            _dispatcher = Dispatcher.CurrentDispatcher;
        }
        catch (Exception ex)
        {
            _startupError = ex;
            _ready.Set();
            return;
        }

        _ready.Set();
        Dispatcher.Run();
    }

    public T Invoke<T>(Func<T> func) => _dispatcher!.Invoke(func);

    public void Invoke(Action action) => _dispatcher!.Invoke(action);

    public void Dispose()
    {
        _dispatcher?.InvokeShutdown();
        _ready.Dispose();
    }
}

/// <summary>共享 WPF 宿主的测试集合定义。</summary>
[CollectionDefinition(Name)]
public sealed class WpfAppScope : ICollectionFixture<WpfAppFixture>
{
    public const string Name = "WpfApp";
}
