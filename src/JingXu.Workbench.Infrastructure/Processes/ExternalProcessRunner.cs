using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using JingXu.Workbench.Application.Abstractions;

namespace JingXu.Workbench.Infrastructure.Processes;

/// <summary>
/// 使用独立参数列表安全执行外部进程的实现。
/// 关闭 shell 执行、重定向标准输出与标准错误，并在等待退出前并发排空两条流以避免死锁；
/// 通过 Windows Job Object 与 <see cref="Process.Kill(bool)"/> 保证取消时终止整个进程树。
/// </summary>
public sealed class ExternalProcessRunner : IExternalProcessRunner
{
    /// <inheritdoc />
    public async Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);

        var startInfo = new ProcessStartInfo
        {
            FileName = request.Executable,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };

        foreach (var argument in request.Arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        if (!string.IsNullOrEmpty(request.WorkingDirectory))
        {
            startInfo.WorkingDirectory = request.WorkingDirectory;
        }

        foreach (var (key, value) in request.EnvironmentOverrides)
        {
            startInfo.Environment[key] = value;
        }

        using var process = new Process { StartInfo = startInfo };

        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException($"无法启动外部进程：{request.Executable}");
            }
        }
        catch (Win32Exception ex)
        {
            throw new InvalidOperationException(
                $"无法启动外部进程：{request.Executable}（Win32 {ex.NativeErrorCode}：{ex.Message}）",
                ex);
        }
        catch (System.IO.FileNotFoundException ex)
        {
            throw new InvalidOperationException(
                $"无法启动外部进程：找不到可执行文件 {request.Executable}",
                ex);
        }

        ApplyPriority(process, request.Priority);

        using var jobObject = AssociateJobObject(process);

        // 在等待退出前即开始排空双流，避免管道缓冲区写满导致的死锁。
        var standardOutputTask = ReadStandardOutputAsync(process, progress, cancellationToken);
        var standardErrorTask = process.StandardError.ReadToEndAsync(cancellationToken);

        try
        {
            await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            var standardOutput = await standardOutputTask.ConfigureAwait(false);
            var standardError = await standardErrorTask.ConfigureAwait(false);
            return new ProcessResult(process.ExitCode, standardOutput, standardError);
        }
        catch (OperationCanceledException)
        {
            TerminateProcessTree(process, jobObject);
            await ObserveAsync(standardOutputTask, standardErrorTask).ConfigureAwait(false);
            throw;
        }
    }

    private static void ApplyPriority(Process process, ExternalProcessPriority priority)
    {
        if (!OperatingSystem.IsWindows() || priority == ExternalProcessPriority.Normal)
        {
            return;
        }

        try
        {
            process.PriorityClass = priority switch
            {
                ExternalProcessPriority.BelowNormal => ProcessPriorityClass.BelowNormal,
                _ => ProcessPriorityClass.Normal
            };
        }
        catch (Win32Exception)
        {
            // 某些受限 Windows 环境不允许调整优先级；继续执行比渲染失败更重要。
        }
        catch (InvalidOperationException)
        {
            // 极短命进程可能在设置优先级前已经退出。
        }
    }

    private static WindowsJobObject? AssociateJobObject(Process process)
    {
        if (!OperatingSystem.IsWindows())
        {
            return null;
        }

        WindowsJobObject? jobObject = null;
        try
        {
            jobObject = new WindowsJobObject();
            jobObject.AssignProcess(process);
            return jobObject;
        }
        catch (Win32Exception)
        {
            // 关联失败时回退到 Kill(entireProcessTree)。
            jobObject?.Dispose();
            return null;
        }
        catch (PlatformNotSupportedException)
        {
            jobObject?.Dispose();
            return null;
        }
    }

    private static async Task<string> ReadStandardOutputAsync(
        Process process,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        if (progress is null)
        {
            return await process.StandardOutput.ReadToEndAsync(cancellationToken).ConfigureAwait(false);
        }

        var builder = new StringBuilder();
        while (await process.StandardOutput.ReadLineAsync(cancellationToken).ConfigureAwait(false) is { } line)
        {
            progress.Report(line);
            builder.Append(line).Append('\n');
        }

        return builder.ToString();
    }

    private static void TerminateProcessTree(Process process, WindowsJobObject? jobObject)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch (InvalidOperationException)
        {
            // 进程可能已退出。
        }
        catch (Win32Exception)
        {
            // 终止失败时仍尝试通过 Job Object 兜底。
        }

        jobObject?.Terminate();
    }

    private static async Task ObserveAsync(params Task[] tasks)
    {
        foreach (var task in tasks)
        {
            try
            {
                await task.ConfigureAwait(false);
            }
            catch
            {
                // 取消或流被关闭引发的异常已无关紧要，忽略以完成清理。
            }
        }
    }
}
