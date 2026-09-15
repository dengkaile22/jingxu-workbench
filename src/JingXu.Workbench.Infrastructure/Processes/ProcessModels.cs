using System.Collections.ObjectModel;
using JingXu.Workbench.Application.Abstractions;

namespace JingXu.Workbench.Infrastructure.Processes;

/// <summary>
/// 外部进程请求。仅暴露独立参数列表工厂，绝不接受预拼接命令行字符串，
/// 以杜绝 shell 注入。
/// </summary>
public sealed record ProcessRequest : IProcessRequest
{
    private static readonly IReadOnlyDictionary<string, string> EmptyEnvironment =
        ReadOnlyDictionary<string, string>.Empty;

    /// <inheritdoc />
    public required string Executable { get; init; }

    /// <inheritdoc />
    public required IReadOnlyList<string> Arguments { get; init; }

    /// <inheritdoc />
    public string? WorkingDirectory { get; init; }

    /// <inheritdoc />
    public IReadOnlyDictionary<string, string> EnvironmentOverrides { get; init; } = EmptyEnvironment;

    /// <inheritdoc />
    public ExternalProcessPriority Priority { get; init; } = ExternalProcessPriority.Normal;

    /// <inheritdoc />
    public System.Text.Encoding? OutputEncoding { get; init; }

    /// <summary>
    /// 创建进程请求。参数以独立列表传入，保证不发生 shell 字符串拼接。
    /// </summary>
    /// <param name="executable">可执行文件（绝对路径，或可经 PATH 解析的文件名）。</param>
    /// <param name="arguments">独立参数列表。</param>
    /// <param name="workingDirectory">工作目录，可为空。</param>
    /// <param name="environmentOverrides">环境变量覆盖，可为空。</param>
    /// <param name="priority">子进程调度优先级。</param>
    /// <param name="outputEncoding">标准输出/错误的文本编码，可为空（使用系统默认代码页）。</param>
    public static ProcessRequest Create(
        string executable,
        IReadOnlyList<string> arguments,
        string? workingDirectory = null,
        IReadOnlyDictionary<string, string>? environmentOverrides = null,
        ExternalProcessPriority priority = ExternalProcessPriority.Normal,
        System.Text.Encoding? outputEncoding = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(executable);
        ArgumentNullException.ThrowIfNull(arguments);

        return new ProcessRequest
        {
            Executable = executable,
            Arguments = [.. arguments],
            WorkingDirectory = workingDirectory,
            EnvironmentOverrides = environmentOverrides is null
                ? EmptyEnvironment
                : new ReadOnlyDictionary<string, string>(new Dictionary<string, string>(environmentOverrides)),
            Priority = priority,
            OutputEncoding = outputEncoding
        };
    }
}

/// <summary>外部进程执行结果。</summary>
public sealed record ProcessResult(int ExitCode, string StandardOutput, string StandardError) : IProcessResult;
