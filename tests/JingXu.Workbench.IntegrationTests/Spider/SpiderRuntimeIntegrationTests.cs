using System.Text.Json;
using JingXu.Workbench.Application.Spider;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Spider;
using JingXu.Workbench.IntegrationTests.Packaging;

namespace JingXu.Workbench.IntegrationTests.Spider;

/// <summary>
/// 选品爬虫真机集成测试：验证内置 Python、源码目录解析、进程管道与配置落盘。
/// 仅在开发仓具备 src/JingXu.Spider/ 与 runtime/python/ 时运行。
/// </summary>
public sealed class SpiderRuntimeIntegrationTests
{
    [Fact]
    public async Task Environment_check_reports_bundled_python_with_dependencies()
    {
        var (repoRoot, spiderDirectory) = RequireSpiderWorkspace();

        var service = CreateService(repoRoot);
        var status = await service.CheckEnvironmentAsync();

        Assert.True(status.PythonAvailable, status.Message);
        Assert.True(status.DependenciesInstalled, status.Message);
        Assert.True(status.IsBundledPython, status.Message);
        Assert.Equal(Path.GetFullPath(spiderDirectory), service.ResolveSpiderDirectory());
        Assert.EndsWith(
            Path.Combine("runtime", "python", "python.exe"),
            status.PythonPath,
            StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Crawl_without_enabled_accounts_fails_cleanly_through_process_pipeline()
    {
        var (repoRoot, _) = RequireSpiderWorkspace();
        var service = CreateService(repoRoot);

        var result = await service.RunCrawlAsync(new SpiderConfig
        {
            Accounts = [],
            TimeConfig = new SpiderTimeConfig { Mode = "days", Days = 1 },
            FilterConfig = new SpiderFilterConfig { MinAccountCount = 2 }
        });

        Assert.False(result.Success);
        Assert.Contains("退出码 1", result.Message, StringComparison.Ordinal);
        Assert.Contains("未发现任何启用的对标账号", result.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Config_is_written_to_data_directory_not_spider_sources()
    {
        var (repoRoot, spiderDirectory) = RequireSpiderWorkspace();
        var service = CreateService(repoRoot);

        Assert.StartsWith(
            Path.GetFullPath(service.DataDirectory),
            Path.GetFullPath(service.ConfigPath),
            StringComparison.OrdinalIgnoreCase);
        Assert.False(service.ConfigPath.StartsWith(Path.GetFullPath(spiderDirectory), StringComparison.OrdinalIgnoreCase));

        await service.SaveConfigAsync(new SpiderConfig
        {
            Accounts = [new SpiderAccount { Name = "验收账号", Platform = "douyin", UrlOrId = "demo" }]
        });

        using var document = JsonDocument.Parse(await File.ReadAllTextAsync(service.ConfigPath));
        Assert.Equal("验收账号", document.RootElement.GetProperty("accounts")[0].GetProperty("name").GetString());
    }

    private static PythonSpiderService CreateService(string repoRoot) =>
        new(
            new ExternalProcessRunner(),
            appRoot: repoRoot,
            dataDirectory: Path.Combine(Path.GetTempPath(), "jingxu-spider-it-" + Guid.NewGuid().ToString("N")));

    private static (string RepoRoot, string SpiderDirectory) RequireSpiderWorkspace()
    {
        var repoRoot = BuildPaths.RepoRoot;
        var spiderDirectory = Path.Combine(repoRoot, "src", "JingXu.Spider");
        var python = Path.Combine(repoRoot, "runtime", "python", "python.exe");

        if (!File.Exists(Path.Combine(spiderDirectory, "cli.py")) || !File.Exists(python))
        {
            Assert.Skip("开发仓缺少选品爬虫源码或内置 Python（先运行 scripts/Resolve-SpiderRuntime.ps1）。");
        }

        return (repoRoot, spiderDirectory);
    }
}
