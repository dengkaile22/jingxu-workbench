using System.Diagnostics;
using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.Infrastructure.Tests.Processes;

public sealed class ExternalProcessRunnerTests
{
    [Fact]
    public async Task Runner_drains_both_streams_and_returns_exit_code()
    {
        var request = ProcessRequest.Create("powershell.exe", ["-NoProfile", "-Command", "$host.ui.WriteErrorLine('err'); 'out'; exit 7"]);
        var result = await new ExternalProcessRunner().RunAsync(request, null, default);
        Assert.Equal(7, result.ExitCode);
        Assert.Contains("out", result.StandardOutput);
        Assert.Contains("err", result.StandardError);
    }

    [Fact]
    public async Task Environment_overrides_reach_the_child_process()
    {
        Assert.SkipUnless(OperatingSystem.IsWindows(), "依赖 powershell.exe。");

        var request = ProcessRequest.Create(
            "powershell.exe",
            ["-NoProfile", "-Command", "Write-Output $env:JINGXU_TEST_VAR"],
            environmentOverrides: new Dictionary<string, string> { ["JINGXU_TEST_VAR"] = "jingxu-env-42" });

        var result = await new ExternalProcessRunner().RunAsync(request, null, default);

        Assert.Equal(0, result.ExitCode);
        Assert.Contains("jingxu-env-42", result.StandardOutput);
    }

    [Fact]
    public async Task Working_directory_is_applied()
    {
        Assert.SkipUnless(OperatingSystem.IsWindows(), "依赖 powershell.exe。");

        var marker = Guid.NewGuid().ToString("N");
        var workingDir = Path.Combine(Path.GetTempPath(), "jingxu-cwd-" + marker);
        Directory.CreateDirectory(workingDir);
        try
        {
            var request = ProcessRequest.Create(
                "powershell.exe",
                ["-NoProfile", "-Command", "Write-Output (Get-Location).Path"],
                workingDirectory: workingDir);

            var result = await new ExternalProcessRunner().RunAsync(request, null, default);

            Assert.Contains(marker, result.StandardOutput, StringComparison.Ordinal);
        }
        finally
        {
            try { Directory.Delete(workingDir, recursive: true); }
            catch (IOException) { }
        }
    }

    [Fact]
    public async Task Streamed_progress_receives_output_lines()
    {
        Assert.SkipUnless(OperatingSystem.IsWindows(), "依赖 powershell.exe。");

        var lines = new List<string>();
        var progress = new Progress<string>(line =>
        {
            lock (lines) { lines.Add(line); }
        });

        var request = ProcessRequest.Create(
            "powershell.exe",
            ["-NoProfile", "-Command", "Write-Output 'first'; Write-Output 'second'"]);

        var result = await new ExternalProcessRunner().RunAsync(request, progress, default);

        Assert.Equal(0, result.ExitCode);
        Assert.Contains("first", result.StandardOutput);
        Assert.Contains("second", result.StandardOutput);
    }

    [Fact]
    public async Task Cancellation_terminates_process_and_descendants()
    {
        Assert.SkipUnless(OperatingSystem.IsWindows(), "进程树终止依赖 Windows Job Object。");

        var pidFile = Path.Combine(Path.GetTempPath(), "jingxu-pids-" + Guid.NewGuid().ToString("N") + ".txt");
        try
        {
            var script =
                "$child = Start-Process ping -ArgumentList '-t','127.0.0.1' -PassThru -WindowStyle Hidden; " +
                "Set-Content -LiteralPath '" + pidFile + "' -Value \"$PID`n$($child.Id)\"; " +
                "Start-Sleep -Seconds 60";
            var request = ProcessRequest.Create("powershell.exe", ["-NoProfile", "-Command", script]);

            using var cts = new CancellationTokenSource();
            var runTask = new ExternalProcessRunner().RunAsync(request, null, cts.Token);

            var (parentPid, childPid) = await WaitForPidsAsync(pidFile, TimeSpan.FromSeconds(20));

            await cts.CancelAsync();
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => runTask);

            Assert.True(await WaitUntilExitedAsync(parentPid, TimeSpan.FromSeconds(5)), "父进程未在超时内退出。");
            Assert.True(await WaitUntilExitedAsync(childPid, TimeSpan.FromSeconds(5)), "子进程未在超时内退出。");
        }
        finally
        {
            try { if (File.Exists(pidFile)) File.Delete(pidFile); }
            catch (IOException) { }
        }
    }

    private static async Task<(int Parent, int Child)> WaitForPidsAsync(string pidFile, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (File.Exists(pidFile))
            {
                string content;
                try { content = await File.ReadAllTextAsync(pidFile); }
                catch (IOException) { content = string.Empty; }

                var lines = content.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                if (lines.Length >= 2 && int.TryParse(lines[0], out var parent) && int.TryParse(lines[1], out var child))
                {
                    return (parent, child);
                }
            }

            await Task.Delay(100);
        }

        throw new TimeoutException("未能在超时时间内读取到进程 PID。");
    }

    private static async Task<bool> WaitUntilExitedAsync(int pid, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (!ProcessIsRunning(pid))
            {
                return true;
            }

            await Task.Delay(100);
        }

        return !ProcessIsRunning(pid);
    }

    private static bool ProcessIsRunning(int pid)
    {
        try
        {
            using var process = Process.GetProcessById(pid);
            return !process.HasExited;
        }
        catch (ArgumentException)
        {
            return false;
        }
    }
}
