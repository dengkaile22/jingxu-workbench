using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Downloads;
using JingXu.Workbench.Application.Spider;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Features.Downloads;
using JingXu.Workbench.Features.Shell;

namespace JingXu.Workbench.Features.Spider;

/// <summary>
/// 选品爬虫视图模型：负责对标账号管理、时间与共性保留阈值设定、
/// 爬虫控制台实时输出、爆品结果呈现，以及向下游下载与混剪模块打通。
/// </summary>
public sealed partial class SpiderViewModel : WorkspaceModuleViewModel, IDisposable
{
    private readonly ISpiderService _spiderService;
    private readonly DownloadViewModel _downloadViewModel;
    private readonly IUiDispatcher _dispatcher;
    private readonly IFolderLauncher _folderLauncher;
    private readonly Action<WorkspaceModule>? _navigateToModule;
    private readonly Task _initialization;
    private CancellationTokenSource? _crawlCts;

    public override WorkspaceModule ModuleKind => WorkspaceModule.Spider;
    public override string Title => "选品爬虫";

    public SpiderViewModel(
        ISpiderService spiderService,
        DownloadViewModel downloadViewModel,
        IUiDispatcher dispatcher,
        IFolderLauncher folderLauncher,
        Action<WorkspaceModule>? navigateToModule = null)
    {
        _spiderService = spiderService;
        _downloadViewModel = downloadViewModel;
        _dispatcher = dispatcher;
        _folderLauncher = folderLauncher;
        _navigateToModule = navigateToModule;

        _initialization = InitAsync();
    }

    /// <summary>等待首次环境检测、配置加载与历史结果恢复完成（供测试与宿主同步）。</summary>
    public Task InitializeAsync() => _initialization;

    private async Task InitAsync()
    {
        await CheckEnvironmentAsync().ConfigureAwait(false);
        await LoadConfigAsync().ConfigureAwait(false);
        await LoadLastResultAsync().ConfigureAwait(false);
    }

    public ObservableCollection<SpiderAccount> Accounts { get; } = [];
    public ObservableCollection<SpiderProductResult> RetainedProducts { get; } = [];

    [ObservableProperty]
    private SpiderAccount? _selectedAccount;

    [ObservableProperty]
    private SpiderProductResult? _selectedProduct;

    [ObservableProperty]
    private SpiderVideoItem? _selectedProductItem;

    [ObservableProperty]
    private string _lastResultText = "尚无历史结果；完成一次爬取后会自动保存。";

    [ObservableProperty]
    private string? _lastReportPath;

    [ObservableProperty]
    private string? _dataDirectory;

    [ObservableProperty]
    private string _newAccountPlatform = "douyin";

    [ObservableProperty]
    private string _newAccountUrl = string.Empty;

    [ObservableProperty]
    private string _newAccountName = string.Empty;

    [ObservableProperty]
    private string _bulkAccountText = string.Empty;

    [ObservableProperty]
    private string _timeMode = "days";

    [ObservableProperty]
    private int _timeDays = 7;

    [ObservableProperty]
    private DateTime? _startDate;

    [ObservableProperty]
    private DateTime? _endDate;

    [ObservableProperty]
    private int _minAccountCount = 2;

    [ObservableProperty]
    private int _minTotalOccurrences = 1;

    [ObservableProperty]
    private string _filterBy = "accounts";

    [ObservableProperty]
    private int _maxScrolls = 25;

    [ObservableProperty]
    private double _fuzzyThreshold = 0.75;

    [ObservableProperty]
    private bool _enableFuzzy = true;

    [ObservableProperty]
    private bool _headless = false;

    [ObservableProperty]
    private bool _isRunning = false;

    [ObservableProperty]
    private string _statusMessage = "就绪。添加对标账号后点击「开始爬取与分析」。";

    [ObservableProperty]
    private string _pythonStatusText = "正在检测 Python 环境...";

    [ObservableProperty]
    private bool _pythonAvailable = false;

    [ObservableProperty]
    private string _logText = string.Empty;

    [ObservableProperty]
    private int _selectedTabIndex = 0; // 0: 结果表格, 1: 日志控制台

    public int AccountCount => Accounts.Count;
    public int RetainedCount => RetainedProducts.Count;

    public bool IsDaysMode => string.Equals(TimeMode, "days", StringComparison.OrdinalIgnoreCase);

    public bool IsRangeMode => string.Equals(TimeMode, "range", StringComparison.OrdinalIgnoreCase);

    public bool HasReport => !string.IsNullOrWhiteSpace(LastReportPath) && File.Exists(LastReportPath);

    partial void OnTimeModeChanged(string value)
    {
        OnPropertyChanged(nameof(IsDaysMode));
        OnPropertyChanged(nameof(IsRangeMode));
    }

    partial void OnLastReportPathChanged(string? value) => OnPropertyChanged(nameof(HasReport));

    [RelayCommand]
    public async Task CheckEnvironmentAsync()
    {
        var status = await _spiderService.CheckEnvironmentAsync().ConfigureAwait(false);
        _dispatcher.Invoke(() =>
        {
            PythonAvailable = status.PythonAvailable;
            PythonStatusText = status.Message;
            DataDirectory = status.DataDirectory;
        });
    }

    private async Task LoadLastResultAsync()
    {
        var result = await _spiderService.LoadLastResultAsync().ConfigureAwait(false);
        if (result is null)
        {
            return;
        }

        _dispatcher.Invoke(() =>
        {
            ApplyResult(result);
            LastResultText = DescribeResult(result);
        });
    }

    private void ApplyResult(SpiderRunResult result)
    {
        RetainedProducts.Clear();
        foreach (var product in result.RetainedProducts)
        {
            RetainedProducts.Add(product);
        }

        OnPropertyChanged(nameof(RetainedCount));
        LastReportPath = result.ExportedExcelPath;
    }

    private static string DescribeResult(SpiderRunResult result) =>
        result.SavedAt is { } savedAt
            ? $"上次结果 {savedAt.LocalDateTime:yyyy-MM-dd HH:mm}｜{result.RetainedProducts.Count} 款爆品 / {result.AllItems.Count} 条明细"
            : $"已加载 {result.RetainedProducts.Count} 款爆品 / {result.AllItems.Count} 条明细";

    [RelayCommand]
    public async Task LoadConfigAsync()
    {
        var config = await _spiderService.LoadConfigAsync().ConfigureAwait(false);
        _dispatcher.Invoke(() =>
        {
            Accounts.Clear();
            foreach (var acc in config.Accounts)
            {
                Accounts.Add(acc);
            }

            TimeMode = string.IsNullOrWhiteSpace(config.TimeConfig.Mode) ? "days" : config.TimeConfig.Mode;
            TimeDays = config.TimeConfig.Days > 0 ? config.TimeConfig.Days : 7;
            StartDate = TryParseDate(config.TimeConfig.StartDate);
            EndDate = TryParseDate(config.TimeConfig.EndDate);
            MinAccountCount = config.FilterConfig.MinAccountCount > 0 ? config.FilterConfig.MinAccountCount : 2;
            MinTotalOccurrences = config.FilterConfig.MinTotalOccurrences > 0 ? config.FilterConfig.MinTotalOccurrences : 1;
            FilterBy = string.IsNullOrWhiteSpace(config.FilterConfig.FilterBy) ? "accounts" : config.FilterConfig.FilterBy;
            MaxScrolls = config.MaxScrollsPerAccount > 0 ? config.MaxScrollsPerAccount : 25;
            FuzzyThreshold = config.FilterConfig.FuzzyThreshold > 0 ? config.FilterConfig.FuzzyThreshold : 0.75;
            EnableFuzzy = config.FilterConfig.EnableFuzzyCluster;
            Headless = config.Headless;
            OnPropertyChanged(nameof(AccountCount));
        });
    }

    [RelayCommand]
    public async Task SaveConfigAsync()
    {
        var config = BuildCurrentConfig();
        await _spiderService.SaveConfigAsync(config).ConfigureAwait(false);
    }

    private SpiderConfig BuildCurrentConfig()
    {
        return new SpiderConfig
        {
            Accounts = Accounts.ToList(),
            TimeConfig = new SpiderTimeConfig
            {
                Mode = string.IsNullOrWhiteSpace(TimeMode) ? "days" : TimeMode,
                Days = TimeDays > 0 ? TimeDays : 7,
                StartDate = IsRangeMode && StartDate.HasValue ? StartDate.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) : string.Empty,
                EndDate = IsRangeMode && EndDate.HasValue ? EndDate.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) : string.Empty
            },
            FilterConfig = new SpiderFilterConfig
            {
                MinAccountCount = MinAccountCount,
                MinTotalOccurrences = MinTotalOccurrences,
                FilterBy = string.IsNullOrWhiteSpace(FilterBy) ? "accounts" : FilterBy,
                EnableFuzzyCluster = EnableFuzzy,
                FuzzyThreshold = FuzzyThreshold > 0 ? FuzzyThreshold : 0.75
            },
            Headless = Headless,
            MaxScrollsPerAccount = MaxScrolls > 0 ? MaxScrolls : 25
        };
    }

    private static DateTime? TryParseDate(string value) =>
        DateTime.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed) ? parsed : null;

    [RelayCommand]
    public async Task AddAccountAsync()
    {
        if (string.IsNullOrWhiteSpace(NewAccountUrl))
        {
            StatusMessage = "请输入对标账号主页链接或 Sec-UID / ID";
            return;
        }

        var account = new SpiderAccount
        {
            Platform = NewAccountPlatform,
            UrlOrId = NewAccountUrl.Trim(),
            Name = string.IsNullOrWhiteSpace(NewAccountName) ? "对标账号" : NewAccountName.Trim(),
            Enabled = true
        };

        Accounts.Add(account);
        NewAccountUrl = string.Empty;
        NewAccountName = string.Empty;
        OnPropertyChanged(nameof(AccountCount));

        await SaveConfigAsync().ConfigureAwait(false);
        StatusMessage = $"已添加账号：{account.Name} ({account.Platform})";
    }

    [RelayCommand]
    public async Task DeleteAccountAsync(SpiderAccount? target)
    {
        var acc = target ?? SelectedAccount;
        if (acc != null && Accounts.Remove(acc))
        {
            OnPropertyChanged(nameof(AccountCount));
            await SaveConfigAsync().ConfigureAwait(false);
            StatusMessage = $"已移除账号：{acc.Name}";
        }
    }

    /// <summary>批量导入：支持每行「主页链接 / 分享短链 / Sec-UID」，链接自动识别平台。</summary>
    [RelayCommand]
    public async Task ImportAccountsAsync()
    {
        var lines = BulkAccountText
            .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (lines.Length == 0)
        {
            StatusMessage = "请先粘贴账号链接，每行一个。";
            return;
        }

        var known = new HashSet<string>(Accounts.Select(a => a.UrlOrId.Trim()), StringComparer.OrdinalIgnoreCase);
        var added = 0;
        var skipped = 0;

        foreach (var line in lines)
        {
            var (platform, target, name) = ParseBulkAccountLine(line, NewAccountPlatform);
            if (string.IsNullOrWhiteSpace(target) || !known.Add(target))
            {
                skipped++;
                continue;
            }

            Accounts.Add(new SpiderAccount
            {
                Platform = platform,
                UrlOrId = target,
                Name = string.IsNullOrWhiteSpace(name) ? "对标账号" : name,
                Enabled = true
            });
            added++;
        }

        BulkAccountText = string.Empty;
        OnPropertyChanged(nameof(AccountCount));
        await SaveConfigAsync().ConfigureAwait(false);

        StatusMessage = skipped > 0
            ? $"已导入 {added} 个账号，跳过 {skipped} 行（重复或空白）。"
            : $"已导入 {added} 个账号。";
    }

    internal static (string Platform, string Target, string Name) ParseBulkAccountLine(string line, string defaultPlatform)
    {
        var urls = VideoUrlExtractor.ExtractUrls(line);
        if (urls.Count > 0)
        {
            var url = urls[0];
            var name = line
                .Replace(url, string.Empty, StringComparison.Ordinal)
                .Trim(' ', '\t', ',', '，', ';', '；', '|');
            return (DetectPlatform(url, defaultPlatform), url, name);
        }

        var tokens = line
            .Split([' ', '\t'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (tokens.Length <= 1)
        {
            return (defaultPlatform, line.Trim(), string.Empty);
        }

        return (defaultPlatform, tokens[^1], string.Join(' ', tokens[..^1]));
    }

    private static string DetectPlatform(string url, string defaultPlatform)
    {
        if (url.Contains("kuaishou", StringComparison.OrdinalIgnoreCase) ||
            url.Contains("kwai", StringComparison.OrdinalIgnoreCase))
        {
            return "kuaishou";
        }

        if (url.Contains("douyin", StringComparison.OrdinalIgnoreCase) ||
            url.Contains("iesdouyin", StringComparison.OrdinalIgnoreCase))
        {
            return "douyin";
        }

        return defaultPlatform;
    }

    [RelayCommand]
    public async Task StartCrawlAsync()
    {
        if (IsRunning) return;

        var enabledAccounts = Accounts.Where(a => a.Enabled).ToList();
        if (enabledAccounts.Count == 0)
        {
            StatusMessage = "请至少勾选一个启用的对标账号！";
            return;
        }

        IsRunning = true;
        SelectedTabIndex = 1; // 自动切到日志查看
        StatusMessage = "爬虫正在启动与抓取，请稍候...";
        AppendLog($"[{DateTime.Now:HH:mm:ss}] === 开始执行多账号带货爬取与共性保留分析 ===");
        AppendLog($"[*] 启用账号数: {enabledAccounts.Count}，时间范围: 近 {TimeDays} 天，保留门槛: 跨账号 >= {MinAccountCount}");

        _crawlCts = new CancellationTokenSource();
        var token = _crawlCts.Token;

        try
        {
            var config = BuildCurrentConfig();
            var result = await _spiderService.RunCrawlAsync(
                config,
                onLogMessage: msg => _dispatcher.Invoke(() => AppendLog(msg)),
                ct: token
            ).ConfigureAwait(false);

            _dispatcher.Invoke(() =>
            {
                if (result.Success)
                {
                    ApplyResult(result);
                    LastResultText = DescribeResult(result);
                    StatusMessage = result.Message;
                    AppendLog($"[{DateTime.Now:HH:mm:ss}] [✓] {result.Message}");
                    if (!string.IsNullOrWhiteSpace(result.ExportedExcelPath))
                    {
                        AppendLog($"[{DateTime.Now:HH:mm:ss}] [✓] 报表：{result.ExportedExcelPath}");
                    }
                    if (RetainedProducts.Count > 0)
                    {
                        SelectedTabIndex = 0; // 爬取完成自动切回结果表格
                    }
                }
                else
                {
                    StatusMessage = result.Message;
                    AppendLog($"[{DateTime.Now:HH:mm:ss}] [!] {result.Message}");
                }
            });
        }
        catch (OperationCanceledException)
        {
            _dispatcher.Invoke(() =>
            {
                StatusMessage = "爬取任务已取消。";
                AppendLog($"[{DateTime.Now:HH:mm:ss}] [!] 任务已被手动停止。");
            });
        }
        catch (Exception ex)
        {
            _dispatcher.Invoke(() =>
            {
                StatusMessage = $"执行出错：{ex.Message}";
                AppendLog($"[{DateTime.Now:HH:mm:ss}] [-] 异常：{ex}");
            });
        }
        finally
        {
            _dispatcher.Invoke(() => IsRunning = false);
        }
    }

    [RelayCommand]
    public void CancelCrawl()
    {
        if (IsRunning && _crawlCts != null)
        {
            StatusMessage = "正在取消爬虫任务...";
            _crawlCts.Cancel();
        }
    }

    [RelayCommand]
    public async Task LoginDouyinAsync()
    {
        AppendLog($"[{DateTime.Now:HH:mm:ss}] 唤起抖音登录窗口...");
        await _spiderService.LaunchLoginAsync("douyin", msg => _dispatcher.Invoke(() => AppendLog(msg))).ConfigureAwait(false);
    }

    [RelayCommand]
    public async Task LoginKuaishouAsync()
    {
        AppendLog($"[{DateTime.Now:HH:mm:ss}] 唤起快手登录窗口...");
        await _spiderService.LaunchLoginAsync("kuaishou", msg => _dispatcher.Invoke(() => AppendLog(msg))).ConfigureAwait(false);
    }

    [RelayCommand]
    public async Task LaunchStandaloneGuiAsync()
    {
        StatusMessage = "正在唤起独立图形界面...";
        var ok = await _spiderService.LaunchStandaloneGuiAsync().ConfigureAwait(false);
        StatusMessage = ok
            ? "已启动独立爬虫界面"
            : "安装包未包含独立图形界面（需要 PySide6），请直接使用当前「选品爬虫」页面。";
    }

    [RelayCommand]
    public void OpenReport()
    {
        var path = LastReportPath;
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            StatusMessage = "暂无可打开的报表，请先完成一次爬取。";
            return;
        }

        try
        {
            _folderLauncher.OpenFile(path);
        }
        catch (Exception ex)
        {
            StatusMessage = $"打开报表失败：{ex.Message}";
        }
    }

    [RelayCommand]
    public void OpenDataDirectory()
    {
        if (string.IsNullOrWhiteSpace(DataDirectory))
        {
            StatusMessage = "尚未解析到数据目录，请先「重新检测」运行环境。";
            return;
        }

        try
        {
            _folderLauncher.Open(DataDirectory);
        }
        catch (Exception ex)
        {
            StatusMessage = $"打开数据目录失败：{ex.Message}";
        }
    }

    [RelayCommand]
    public void OpenSelectedVideo() =>
        OpenLink(SelectedProductItem?.VideoUrl, "该明细没有可打开的视频链接。");

    [RelayCommand]
    public void OpenSelectedSampleVideo() =>
        OpenLink(SelectedProduct?.SampleVideoUrl, "请先选中一款爆品，且该爆品没有示例视频链接。");

    [RelayCommand]
    public void OpenSelectedProductLink() =>
        OpenLink(SelectedProductItem?.DetailUrl, "该明细没有可打开的商品链接。");

    private void OpenLink(string? url, string emptyMessage)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            StatusMessage = emptyMessage;
            return;
        }

        try
        {
            _folderLauncher.OpenFile(url);
        }
        catch (Exception ex)
        {
            StatusMessage = $"打开链接失败：{ex.Message}";
        }
    }

    [RelayCommand]
    public void SendSelectedVideosToDownloads()
    {
        if (SelectedProduct == null)
        {
            StatusMessage = "请先在结果列表中选择一款商品。";
            return;
        }

        var urls = new HashSet<string>();
        if (!string.IsNullOrWhiteSpace(SelectedProduct.SampleVideoUrl))
        {
            urls.Add(SelectedProduct.SampleVideoUrl);
        }
        if (SelectedProduct.Items != null)
        {
            foreach (var it in SelectedProduct.Items)
            {
                if (!string.IsNullOrWhiteSpace(it.VideoUrl))
                {
                    urls.Add(it.VideoUrl);
                }
            }
        }

        if (urls.Count == 0)
        {
            StatusMessage = "该商品暂无有效的关联视频链接。";
            return;
        }

        var text = string.Join(Environment.NewLine, urls);
        _downloadViewModel.UrlInput = text;
        _downloadViewModel.ParseUrlsCommand.Execute(null);

        StatusMessage = $"已将 {urls.Count} 条视频链接注入下载模块！";
        _navigateToModule?.Invoke(WorkspaceModule.Downloads);
    }

    [RelayCommand]
    public void SendAllVideosToDownloads()
    {
        if (RetainedProducts.Count == 0)
        {
            StatusMessage = "当前没有筛选出的商品结果。";
            return;
        }

        var urls = new HashSet<string>();
        foreach (var p in RetainedProducts)
        {
            if (!string.IsNullOrWhiteSpace(p.SampleVideoUrl))
            {
                urls.Add(p.SampleVideoUrl);
            }
            if (p.Items != null)
            {
                foreach (var it in p.Items)
                {
                    if (!string.IsNullOrWhiteSpace(it.VideoUrl))
                    {
                        urls.Add(it.VideoUrl);
                    }
                }
            }
        }

        if (urls.Count == 0)
        {
            StatusMessage = "未收集到可下载的视频链接。";
            return;
        }

        var text = string.Join(Environment.NewLine, urls);
        _downloadViewModel.UrlInput = text;
        _downloadViewModel.ParseUrlsCommand.Execute(null);

        StatusMessage = $"已将全部爆品的 {urls.Count} 条视频链接注入下载模块！";
        _navigateToModule?.Invoke(WorkspaceModule.Downloads);
    }

    [RelayCommand]
    public void ClearLog()
    {
        LogText = string.Empty;
    }

    private void AppendLog(string message)
    {
        var sb = new StringBuilder(LogText);
        if (sb.Length > 200000)
        {
            sb.Remove(0, 50000);
        }
        sb.AppendLine(message);
        LogText = sb.ToString();
    }

    public void Dispose()
    {
        _crawlCts?.Cancel();
        _crawlCts?.Dispose();
        _crawlCts = null;
    }
}
