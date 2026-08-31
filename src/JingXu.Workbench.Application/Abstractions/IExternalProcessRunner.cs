namespace JingXu.Workbench.Application.Abstractions;

/// <summary>外部进程的桌面调度优先级。</summary>
public enum ExternalProcessPriority
{
    /// <summary>继承常规桌面进程优先级。</summary>
    Normal,

    /// <summary>低于桌面 UI；适合长时间占满 CPU 的编码进程。</summary>
    BelowNormal
}

/// <summary>
/// 外部进程请求的只读契约。参数以独立列表暴露，绝不接受预拼接命令行字符串。
/// </summary>
public interface IProcessRequest
{
    /// <summary>可执行文件（绝对路径，或可经 PATH 解析的文件名）。</summary>
    string Executable { get; }

    /// <summary>不可变的参数列表；每一项都作为独立参数传入子进程。</summary>
    IReadOnlyList<string> Arguments { get; }

    /// <summary>工作目录；为空时继承当前进程工作目录。</summary>
    string? WorkingDirectory { get; }

    /// <summary>环境变量覆盖。</summary>
    IReadOnlyDictionary<string, string> EnvironmentOverrides { get; }

    /// <summary>子进程的调度优先级。</summary>
    ExternalProcessPriority Priority { get; }
}

/// <summary>
/// 外部进程运行结果的只读契约。
/// </summary>
public interface IProcessResult
{
    /// <summary>进程退出码。</summary>
    int ExitCode { get; }

    /// <summary>完整标准输出。</summary>
    string StandardOutput { get; }

    /// <summary>完整标准错误。</summary>
    string StandardError { get; }
}

/// <summary>
/// 安全执行外部进程的抽象。实现必须使用独立参数列表，
/// 不得暴露任何接受预拼接命令行字符串的公开 API。
/// </summary>
public interface IExternalProcessRunner
{
    /// <summary>
    /// 运行外部进程，并发排空标准输出与标准错误，返回退出码与完整输出。
    /// </summary>
    /// <param name="request">进程请求。</param>
    /// <param name="progress">可选的标准输出行进度回调；为空时不进行流式回调。</param>
    /// <param name="cancellationToken">取消令牌；取消时终止整个进程树。</param>
    Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken);
}
