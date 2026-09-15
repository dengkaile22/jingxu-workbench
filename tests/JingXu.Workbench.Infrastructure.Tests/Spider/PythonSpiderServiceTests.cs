using System.Globalization;
using System.IO;
using System.Text;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Spider;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Spider;
using Xunit;

namespace JingXu.Workbench.Infrastructure.Tests.Spider;

public sealed class PythonSpiderServiceTests
{
    [Fact]
    public void ResolveSpiderDirectory_FindsPublishedRuntimeLayout()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var spiderDirectory = Path.Combine(tempRoot, "runtime", "spider");
            Directory.CreateDirectory(spiderDirectory);
            File.WriteAllText(Path.Combine(spiderDirectory, "cli.py"), string.Empty);

            var service = new PythonSpiderService(new ExternalProcessRunner(), appRoot: tempRoot);

            Assert.Equal(Path.GetFullPath(spiderDirectory), service.ResolveSpiderDirectory());
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public void ResolveSpiderDirectory_FindsSourceTreeLayout()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var spiderDirectory = Path.Combine(tempRoot, "src", "JingXu.Spider");
            Directory.CreateDirectory(spiderDirectory);
            File.WriteAllText(Path.Combine(spiderDirectory, "cli.py"), string.Empty);

            var service = new PythonSpiderService(new ExternalProcessRunner(), appRoot: tempRoot);

            Assert.Equal(Path.GetFullPath(spiderDirectory), service.ResolveSpiderDirectory());
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public void ResolveSpiderDirectory_FindsLegacyPortableLayout()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var spiderDirectory = Path.Combine(tempRoot, "爬虫抖音和快手");
            Directory.CreateDirectory(spiderDirectory);
            File.WriteAllText(Path.Combine(spiderDirectory, "cli.py"), string.Empty);

            var service = new PythonSpiderService(new ExternalProcessRunner(), appRoot: tempRoot);

            Assert.Equal(Path.GetFullPath(spiderDirectory), service.ResolveSpiderDirectory());
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public void ResolvePythonExecutable_FindsBundledRuntime()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var pythonDirectory = Path.Combine(tempRoot, "runtime", "python");
            Directory.CreateDirectory(pythonDirectory);
            var pythonExe = Path.Combine(pythonDirectory, "python.exe");
            File.WriteAllText(pythonExe, string.Empty);

            var service = new PythonSpiderService(new ExternalProcessRunner(), appRoot: tempRoot);
            var resolution = service.ResolvePythonExecutable();

            Assert.True(resolution.IsBundled);
            Assert.Equal(Path.GetFullPath(pythonExe), resolution.Path);
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public async Task SaveAndLoadConfig_RoundTripsAllFields()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var dataDirectory = Path.Combine(tempRoot, "data");
            var service = new PythonSpiderService(
                new ExternalProcessRunner(),
                appRoot: tempRoot,
                dataDirectory: dataDirectory);

            var initial = new SpiderConfig
            {
                Accounts = [new SpiderAccount { Name = "测试账号", Platform = "douyin", UrlOrId = "12345" }],
                TimeConfig = new SpiderTimeConfig
                {
                    Mode = "range",
                    Days = 10,
                    StartDate = "2026-09-01",
                    EndDate = "2026-09-15"
                },
                FilterConfig = new SpiderFilterConfig
                {
                    MinAccountCount = 3,
                    MinTotalOccurrences = 4,
                    FilterBy = "both",
                    EnableFuzzyCluster = false,
                    FuzzyThreshold = 0.82
                },
                Headless = true,
                MaxScrollsPerAccount = 40
            };

            await service.SaveConfigAsync(initial);
            var loaded = await service.LoadConfigAsync();

            Assert.Equal("range", loaded.TimeConfig.Mode);
            Assert.Equal(10, loaded.TimeConfig.Days);
            Assert.Equal("2026-09-01", loaded.TimeConfig.StartDate);
            Assert.Equal("2026-09-15", loaded.TimeConfig.EndDate);
            Assert.Equal(3, loaded.FilterConfig.MinAccountCount);
            Assert.Equal(4, loaded.FilterConfig.MinTotalOccurrences);
            Assert.Equal("both", loaded.FilterConfig.FilterBy);
            Assert.False(loaded.FilterConfig.EnableFuzzyCluster);
            Assert.Equal(0.82, loaded.FilterConfig.FuzzyThreshold, precision: 3);
            Assert.True(loaded.Headless);
            Assert.Equal(40, loaded.MaxScrollsPerAccount);
            Assert.Equal(Path.GetFullPath(dataDirectory), service.DataDirectory);
            Assert.True(File.Exists(service.ConfigPath));
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public async Task RunCrawlAsync_ParsesOutputAndBuildsArguments()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var spiderDirectory = Path.Combine(tempRoot, "runtime", "spider");
            Directory.CreateDirectory(spiderDirectory);
            File.WriteAllText(Path.Combine(spiderDirectory, "cli.py"), string.Empty);

            var dataDirectory = Path.Combine(tempRoot, "data");
            Directory.CreateDirectory(dataDirectory);
            var excelPath = Path.Combine(dataDirectory, "exports", "报表.xlsx");
            Directory.CreateDirectory(Path.GetDirectoryName(excelPath)!);
            File.WriteAllText(excelPath, "stub");

            var runner = new RecordingRunner((arguments, _) =>
            {
                var jsonPath = arguments[arguments.IndexOf("--json-out") + 1];
                File.WriteAllText(jsonPath, """
                    {
                      "retained_products": [
                        {
                          "商品名称": "超能洗衣液3kg",
                          "清洗名称": "超能洗衣液3kg",
                          "涉及平台": "douyin",
                          "带货账号数": 2,
                          "带货视频数": 3,
                          "对标账号明细": "达人A, 达人B",
                          "参考价格": "¥39.9",
                          "示例视频链接": "https://www.douyin.com/video/1"
                        }
                      ],
                      "all_items": [
                        {
                          "平台": "douyin",
                          "账号名称": "达人A",
                          "账号ID": "sec-1",
                          "视频ID": "v1",
                          "视频标题": "测试视频",
                          "视频链接": "https://www.douyin.com/video/1",
                          "发布时间": "2026-09-15 10:00:00",
                          "商品ID": "p1",
                          "商品原始名称": "【官方正品】超能洗衣液3kg",
                          "清洗后名称": "超能洗衣液3kg",
                          "售价": "¥39.9",
                          "商品链接": "https://item/1"
                        }
                      ],
                      "excel_path": "%EXCEL%"
                    }
                    """.Replace("%EXCEL%", excelPath.Replace("\\", "\\\\"), StringComparison.Ordinal));
                return new ProcessResult(0, string.Empty, string.Empty);
            });

            var service = new PythonSpiderService(runner, appRoot: tempRoot, dataDirectory: dataDirectory);
            var config = new SpiderConfig
            {
                Accounts = [new SpiderAccount { Name = "达人A", Platform = "douyin", UrlOrId = "1", Enabled = true }],
                TimeConfig = new SpiderTimeConfig { Mode = "days", Days = 5 },
                FilterConfig = new SpiderFilterConfig
                {
                    MinAccountCount = 2,
                    MinTotalOccurrences = 1,
                    FilterBy = "both",
                    FuzzyThreshold = 0.7
                },
                MaxScrollsPerAccount = 12,
                Headless = true
            };

            var result = await service.RunCrawlAsync(config);

            Assert.True(result.Success, result.Message);
            Assert.Single(result.RetainedProducts);
            Assert.Single(result.AllItems);
            Assert.Single(result.RetainedProducts[0].Items);
            Assert.Equal(excelPath, result.ExportedExcelPath);
            Assert.Contains("共获得 1 款跨账号爆品与 1 条明细", result.Message, StringComparison.Ordinal);

            var recorded = runner.Requests.Single();
            var jsonOutIndex = recorded.IndexOf("--json-out");
            Assert.True(jsonOutIndex >= 0);
            Assert.StartsWith("jingxu-spider-", Path.GetFileName(recorded[jsonOutIndex + 1]), StringComparison.Ordinal);
            Assert.Contains("--profile-dir", recorded);
            Assert.Contains("--export-dir", recorded);
            Assert.Contains(service.ProfileDirectory, recorded);
            Assert.Contains("--time-mode", recorded);
            Assert.Contains("days", recorded);
            Assert.Contains("--min-occurrences", recorded);
            Assert.Contains("--filter-by", recorded);
            Assert.Contains("both", recorded);
            Assert.Contains("--max-scrolls", recorded);
            Assert.Contains("12", recorded);
            Assert.Contains("--headless", recorded);
            Assert.Equal(Path.Combine(dataDirectory, "config.json"), service.ConfigPath);
            Assert.True(File.Exists(service.ConfigPath));

            // 成功结果自动落快照，重启后可恢复。
            Assert.True(File.Exists(service.LastResultPath));
            var snapshot = await service.LoadLastResultAsync();
            Assert.NotNull(snapshot);
            Assert.Single(snapshot!.RetainedProducts);
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public async Task RunCrawlAsync_ReturnsFailureMessageOnNonZeroExit()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var spiderDirectory = Path.Combine(tempRoot, "runtime", "spider");
            Directory.CreateDirectory(spiderDirectory);
            File.WriteAllText(Path.Combine(spiderDirectory, "cli.py"), string.Empty);

            var runner = new RecordingRunner((_, _) => new ProcessResult(7, string.Empty, "Traceback: boom"));
            var service = new PythonSpiderService(
                runner,
                appRoot: tempRoot,
                dataDirectory: Path.Combine(tempRoot, "data"));

            var result = await service.RunCrawlAsync(new SpiderConfig());

            Assert.False(result.Success);
            Assert.Contains("退出码 7", result.Message, StringComparison.Ordinal);
            Assert.Contains("Traceback: boom", result.Message, StringComparison.Ordinal);
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public async Task RunCrawlAsync_ReportsMissingSpiderDirectory()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var service = new PythonSpiderService(
                new RecordingRunner((_, _) => new ProcessResult(0, string.Empty, string.Empty)),
                appRoot: tempRoot,
                dataDirectory: Path.Combine(tempRoot, "data"));

            var result = await service.RunCrawlAsync(new SpiderConfig());

            Assert.False(result.Success);
            Assert.Contains("未找到选品爬虫源码目录", result.Message, StringComparison.Ordinal);
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public async Task SaveAndLoadLastResult_RoundTripsSnapshotAndRelinksItems()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var dataDirectory = Path.Combine(tempRoot, "data");
            Directory.CreateDirectory(Path.Combine(dataDirectory, "exports"));
            var excelPath = Path.Combine(dataDirectory, "exports", "报表.xlsx");
            File.WriteAllText(excelPath, "stub");

            var service = new PythonSpiderService(
                new ExternalProcessRunner(),
                appRoot: tempRoot,
                dataDirectory: dataDirectory);

            var result = new SpiderRunResult
            {
                Success = true,
                SavedAt = new DateTimeOffset(2026, 9, 15, 21, 5, 0, TimeSpan.FromHours(8)),
                ExportedExcelPath = excelPath,
                RetainedProducts =
                [
                    new SpiderProductResult
                    {
                        ProductName = "爆品A",
                        CleanedName = "爆品A",
                        Platform = "douyin",
                        AccountCount = 2,
                        VideoCount = 2
                    }
                ],
                AllItems =
                [
                    new SpiderVideoItem { CleanedName = "爆品A", VideoUrl = "https://www.douyin.com/video/1" },
                    new SpiderVideoItem { ProductName = "爆品A", VideoUrl = "https://www.douyin.com/video/2" }
                ]
            };

            await service.SaveLastResultAsync(result);
            Assert.True(File.Exists(service.LastResultPath));

            var loaded = await service.LoadLastResultAsync();

            Assert.NotNull(loaded);
            Assert.Single(loaded!.RetainedProducts);
            Assert.Equal(2, loaded.AllItems.Count);
            Assert.Equal(2, loaded.RetainedProducts[0].Items.Count);
            Assert.Equal(excelPath, loaded.ExportedExcelPath);
            Assert.Equal(
                "2026-09-15 21:05:00",
                loaded.SavedAt!.Value.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture));
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public async Task LoadLastResult_ReturnsNullWithoutSnapshot()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var service = new PythonSpiderService(
                new ExternalProcessRunner(),
                appRoot: tempRoot,
                dataDirectory: Path.Combine(tempRoot, "data"));

            Assert.Null(await service.LoadLastResultAsync());
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    [Fact]
    public async Task LoadLastResult_DropsExcelPathWhenReportWasDeleted()
    {
        var tempRoot = CreateTempDirectory();
        try
        {
            var dataDirectory = Path.Combine(tempRoot, "data");
            var service = new PythonSpiderService(
                new ExternalProcessRunner(),
                appRoot: tempRoot,
                dataDirectory: dataDirectory);

            var missingReport = Path.Combine(dataDirectory, "exports", "已删除.xlsx");
            await service.SaveLastResultAsync(new SpiderRunResult
            {
                Success = true,
                ExportedExcelPath = missingReport
            });

            var loaded = await service.LoadLastResultAsync();

            Assert.NotNull(loaded);
            Assert.Null(loaded!.ExportedExcelPath);
        }
        finally
        {
            DeleteQuietly(tempRoot);
        }
    }

    private static string CreateTempDirectory()
    {
        var directory = Path.Combine(Path.GetTempPath(), $"spider_test_{Guid.NewGuid():N}");
        Directory.CreateDirectory(directory);
        return directory;
    }

    private static void DeleteQuietly(string directory)
    {
        try
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private sealed class RecordingRunner : IExternalProcessRunner
    {
        private readonly Func<List<string>, IProcessRequest, IProcessResult> _onRun;

        public RecordingRunner(Func<List<string>, IProcessRequest, IProcessResult> onRun) => _onRun = onRun;

        public List<List<string>> Requests { get; } = [];

        public Task<IProcessResult> RunAsync(
            IProcessRequest request,
            IProgress<string>? progress,
            CancellationToken cancellationToken)
        {
            var arguments = request.Arguments.ToList();
            Requests.Add(arguments);
            return Task.FromResult(_onRun(arguments, request));
        }
    }
}
