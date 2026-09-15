using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Spider;
using JingXu.Workbench.Features.Downloads;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Features.Spider;
using JingXu.Workbench.Presentation.Tests.Infrastructure;
using JingXu.Workbench.Presentation.Tests.Shell;

namespace JingXu.Workbench.Presentation.Tests.Spider;

public sealed class SpiderViewModelTests
{
    [Fact]
    public async Task Initialize_restores_config_thresholds_and_last_result()
    {
        var reportPath = CreateTempFile(".xlsx");
        try
        {
            var service = new StubSpiderService
            {
                Config = new SpiderConfig
                {
                    Accounts = [new SpiderAccount { Name = "达人A", Platform = "douyin", UrlOrId = "1" }],
                    TimeConfig = new SpiderTimeConfig { Mode = "range", Days = 10, StartDate = "2026-09-01", EndDate = "2026-09-15" },
                    FilterConfig = new SpiderFilterConfig
                    {
                        MinAccountCount = 3,
                        MinTotalOccurrences = 2,
                        FilterBy = "both",
                        FuzzyThreshold = 0.82
                    },
                    MaxScrollsPerAccount = 40,
                    Headless = true
                },
                LastResult = new SpiderRunResult
                {
                    Success = true,
                    SavedAt = new DateTimeOffset(2026, 9, 15, 20, 30, 0, TimeSpan.FromHours(8)),
                    ExportedExcelPath = reportPath,
                    RetainedProducts =
                    [
                        new SpiderProductResult
                        {
                            ProductName = "超能洗衣液3kg",
                            CleanedName = "超能洗衣液3kg",
                            Platform = "douyin",
                            AccountCount = 2,
                            VideoCount = 2
                        }
                    ],
                    AllItems =
                    [
                        new SpiderVideoItem { CleanedName = "超能洗衣液3kg", VideoUrl = "https://www.douyin.com/video/1" }
                    ]
                }
            };

            var launcher = new RecordingFolderLauncher();
            var (viewModel, _) = CreateViewModel(service, launcher);
            await viewModel.InitializeAsync();

            Assert.Single(viewModel.Accounts);
            Assert.Equal("range", viewModel.TimeMode);
            Assert.False(viewModel.IsDaysMode);
            Assert.True(viewModel.IsRangeMode);
            Assert.Equal(3, viewModel.MinAccountCount);
            Assert.Equal(2, viewModel.MinTotalOccurrences);
            Assert.Equal("both", viewModel.FilterBy);
            Assert.Equal(0.82, viewModel.FuzzyThreshold, precision: 3);
            Assert.Equal(40, viewModel.MaxScrolls);
            Assert.True(viewModel.Headless);

            Assert.Single(viewModel.RetainedProducts);
            Assert.True(viewModel.HasReport);
            Assert.Equal(reportPath, viewModel.LastReportPath);
            Assert.Contains("2026-09-15 20:30", viewModel.LastResultText, StringComparison.Ordinal);
        }
        finally
        {
            File.Delete(reportPath);
        }
    }

    [Fact]
    public async Task Open_report_and_video_use_folder_launcher()
    {
        var reportPath = CreateTempFile(".xlsx");
        try
        {
            var service = new StubSpiderService
            {
                LastResult = new SpiderRunResult
                {
                    Success = true,
                    ExportedExcelPath = reportPath
                }
            };

            var launcher = new RecordingFolderLauncher();
            var (viewModel, _) = CreateViewModel(service, launcher);
            await viewModel.InitializeAsync();

            viewModel.OpenReportCommand.Execute(null);
            Assert.Equal([reportPath], launcher.OpenedFiles);

            viewModel.SelectedProductItem = new SpiderVideoItem { VideoUrl = "https://www.douyin.com/video/9" };
            viewModel.OpenSelectedVideoCommand.Execute(null);
            Assert.Equal([reportPath, "https://www.douyin.com/video/9"], launcher.OpenedFiles);
        }
        finally
        {
            File.Delete(reportPath);
        }
    }

    [Fact]
    public async Task Open_report_without_snapshot_reports_status()
    {
        var service = new StubSpiderService();
        var launcher = new RecordingFolderLauncher();
        var (viewModel, _) = CreateViewModel(service, launcher);
        await viewModel.InitializeAsync();

        Assert.False(viewModel.HasReport);
        viewModel.OpenReportCommand.Execute(null);

        Assert.Empty(launcher.OpenedFiles);
        Assert.Contains("暂无可打开的报表", viewModel.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Sending_selected_product_injects_urls_into_download_module()
    {
        var service = new StubSpiderService();
        var launcher = new RecordingFolderLauncher();
        var downloads = CreateDownloadViewModel();
        var navigation = new List<WorkspaceModule>();
        var viewModel = new SpiderViewModel(
            service,
            downloads,
            new DirectUiDispatcher(),
            launcher,
            module => navigation.Add(module));
        await viewModel.InitializeAsync();

        viewModel.SelectedProduct = new SpiderProductResult
        {
            ProductName = "爆品A",
            SampleVideoUrl = "https://www.douyin.com/video/1",
            Items =
            [
                new SpiderVideoItem { VideoUrl = "https://www.douyin.com/video/2" },
                new SpiderVideoItem { VideoUrl = "https://www.douyin.com/video/2" }
            ]
        };

        viewModel.SendSelectedVideosToDownloadsCommand.Execute(null);

        Assert.Equal(2, downloads.Items.Count);
        Assert.Contains(downloads.Items, item => item.Url == "https://www.douyin.com/video/1");
        Assert.Contains(downloads.Items, item => item.Url == "https://www.douyin.com/video/2");
        Assert.Equal([WorkspaceModule.Downloads], navigation);
    }

    [Fact]
    public async Task Import_accounts_parses_lines_detects_platform_and_skips_duplicates()
    {
        var service = new StubSpiderService
        {
            Config = new SpiderConfig
            {
                Accounts =
                [
                    new SpiderAccount
                    {
                        Name = "已存在",
                        Platform = "douyin",
                        UrlOrId = "https://www.douyin.com/user/MS4w-existing"
                    }
                ]
            }
        };

        var (viewModel, _) = CreateViewModel(service, new RecordingFolderLauncher());
        await viewModel.InitializeAsync();

        viewModel.BulkAccountText = string.Join(
            '\n',
            "交个朋友直播间 https://www.douyin.com/user/MS4w-new",
            "https://www.kuaishou.com/profile/3x6df89v345",
            "老铁B 3xabc",
            "https://www.douyin.com/user/MS4w-existing",
            "   ");

        await viewModel.ImportAccountsCommand.ExecuteAsync(null);

        Assert.Equal(4, viewModel.Accounts.Count);
        Assert.Contains("已导入 3 个账号", viewModel.StatusMessage, StringComparison.Ordinal);
        Assert.Contains("跳过 1 行", viewModel.StatusMessage, StringComparison.Ordinal);
        Assert.Equal(string.Empty, viewModel.BulkAccountText);

        var douyin = viewModel.Accounts.Single(a => a.UrlOrId.Contains("MS4w-new", StringComparison.Ordinal));
        Assert.Equal("douyin", douyin.Platform);
        Assert.Equal("交个朋友直播间", douyin.Name);

        var kuaishou = viewModel.Accounts.Single(a => a.UrlOrId.Contains("kuaishou.com", StringComparison.Ordinal));
        Assert.Equal("kuaishou", kuaishou.Platform);

        var idOnly = viewModel.Accounts.Single(a => a.UrlOrId == "3xabc");
        Assert.Equal("老铁B", idOnly.Name);
        Assert.Equal("douyin", idOnly.Platform);
    }

    private static string CreateTempFile(string extension)
    {
        var path = Path.Combine(Path.GetTempPath(), $"spider-vm-{Guid.NewGuid():N}{extension}");
        File.WriteAllText(path, string.Empty);
        return path;
    }

    private static (SpiderViewModel ViewModel, List<WorkspaceModule> Navigation) CreateViewModel(
        ISpiderService service,
        RecordingFolderLauncher launcher)
    {
        var navigation = new List<WorkspaceModule>();
        var viewModel = new SpiderViewModel(
            service,
            CreateDownloadViewModel(),
            new DirectUiDispatcher(),
            launcher,
            module => navigation.Add(module));
        return (viewModel, navigation);
    }

    private static DownloadViewModel CreateDownloadViewModel() =>
        new(new StubVideoDownloader(), new StubVideoUrlResolver(), new DirectUiDispatcher());

    private sealed class StubSpiderService : ISpiderService
    {
        public SpiderConfig Config { get; set; } = new();

        public SpiderRunResult? LastResult { get; set; }

        public Task<SpiderConfig> LoadConfigAsync(CancellationToken ct = default) => Task.FromResult(Config);

        public Task SaveConfigAsync(SpiderConfig config, CancellationToken ct = default)
        {
            Config = config;
            return Task.CompletedTask;
        }

        public Task<SpiderRunResult> RunCrawlAsync(
            SpiderConfig config,
            Action<string>? onLogMessage = null,
            CancellationToken ct = default) =>
            Task.FromResult(LastResult ?? new SpiderRunResult { Success = true, Message = "stub" });

        public Task SaveLastResultAsync(SpiderRunResult result, CancellationToken ct = default)
        {
            LastResult = result;
            return Task.CompletedTask;
        }

        public Task<SpiderRunResult?> LoadLastResultAsync(CancellationToken ct = default) =>
            Task.FromResult(LastResult);

        public Task LaunchLoginAsync(string platform, Action<string>? onLogMessage = null, CancellationToken ct = default) =>
            Task.CompletedTask;

        public Task<bool> LaunchStandaloneGuiAsync(CancellationToken ct = default) => Task.FromResult(false);

        public Task<SpiderEnvironmentStatus> CheckEnvironmentAsync(CancellationToken ct = default) =>
            Task.FromResult(new SpiderEnvironmentStatus
            {
                PythonAvailable = true,
                DependenciesInstalled = true,
                DataDirectory = Path.GetTempPath(),
                Message = "stub"
            });
    }

    private sealed class StubVideoDownloader : IVideoDownloader
    {
        public Task DownloadAsync(
            string url,
            string outputPath,
            IProgress<DownloadProgress> progress,
            CancellationToken cancellationToken) => Task.CompletedTask;
    }

    private sealed class StubVideoUrlResolver : IVideoUrlResolver
    {
        public Task<ResolvedVideoInfo> ResolveAsync(string inputUrl, CancellationToken cancellationToken) =>
            Task.FromResult(new ResolvedVideoInfo(inputUrl));
    }
}
