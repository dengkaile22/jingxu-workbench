using System.Diagnostics;
using System.Text.Json;
using JingXu.Workbench.IntegrationTests.Media;

namespace JingXu.Workbench.IntegrationTests.Packaging;

public sealed class StartupSelfTestTests
{
    [Fact]
    public async Task Self_test_exits_with_json_without_waiting_for_the_window_dispatcher()
    {
        var (ffmpeg, _) = MediaIntegrationHarness.RequireFfmpeg();
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && directory.Name is not "Release" and not "Debug") { directory = directory.Parent; }
        var executable = Path.Combine(BuildPaths.RepoRoot, "src", "JingXu.Workbench", "bin",
            directory?.Name ?? "Release", "net10.0-windows", "炳恒快速混剪.exe");
        Assert.True(File.Exists(executable), "请先构建 WPF 应用，再执行启动自检回归。");
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        var start = new ProcessStartInfo(executable)
        {
            UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        start.ArgumentList.Add("--self-test");
        start.Environment["PATH"] = Path.GetDirectoryName(ffmpeg) + Path.PathSeparator + Environment.GetEnvironmentVariable("PATH");
        start.Environment["JINGXU_DATA_DIRECTORY"] = Path.Combine(workspace.Root, "data");
        start.Environment["JINGXU_TEMP_DIRECTORY"] = Path.Combine(workspace.Root, "temp");
        using var process = new Process { StartInfo = start };
        Assert.True(process.Start());
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        try { await process.WaitForExitAsync(timeout.Token); }
        catch (OperationCanceledException)
        {
            process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync();
            Assert.Fail("启动自检未在15秒内退出，可能在同步等待 WPF Dispatcher 续体。");
        }

        var output = await stdout;
        Assert.True(process.ExitCode == 0, await stderr + Environment.NewLine + output);
        using var json = JsonDocument.Parse(output);
        Assert.True(json.RootElement.GetProperty("success").GetBoolean());
    }
}
