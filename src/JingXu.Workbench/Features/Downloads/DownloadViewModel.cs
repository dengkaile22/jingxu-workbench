using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Net.Http;
using System.Text;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Downloads;
using JingXu.Workbench.Features.Shell;

namespace JingXu.Workbench.Features.Downloads;

public sealed partial class DownloadViewModel : WorkspaceModuleViewModel, IDisposable
{
    private readonly IVideoDownloader _downloader;
    private readonly IVideoUrlResolver _urlResolver;
    private readonly IUiDispatcher _dispatcher;
    private readonly SemaphoreSlim _gate = new(5, 5);
    private CancellationTokenSource? _batchCts;

    public override WorkspaceModule ModuleKind => WorkspaceModule.Downloads;
    public override string Title => "批量下载";

    public DownloadViewModel(
        IVideoDownloader downloader,
        IVideoUrlResolver urlResolver,
        IUiDispatcher dispatcher)
    {
        _downloader = downloader;
        _urlResolver = urlResolver;
        _dispatcher = dispatcher;
    }

    [ObservableProperty]
    private string _urlInput = string.Empty;

    [ObservableProperty]
    private string _saveDirectory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");

    [ObservableProperty]
    private string _statusText = "粘贴链接后点击解析";

    public ObservableCollection<DownloadItem> Items { get; } = [];

    [RelayCommand]
    private void ParseUrls()
    {
        if (string.IsNullOrWhiteSpace(UrlInput))
        {
            StatusText = "请先粘贴视频链接或分享文本";
            return;
        }

        var urls = VideoUrlExtractor.ExtractUrls(UrlInput);
        if (urls.Count == 0)
        {
            StatusText = "未识别到有效链接，请检查输入的文本";
            return;
        }

        var startIndex = Items.Count > 0 ? Items.Max(i => i.Index) + 1 : 1;
        foreach (var url in urls)
        {
            Items.Add(DownloadItem.Create(url, startIndex++, SaveDirectory));
        }

        StatusText = $"已提取 {urls.Count} 个有效链接，当前列表共 {Items.Count} 项";
        UrlInput = string.Empty;
        DownloadCommand.NotifyCanExecuteChanged();
    }

    private bool CanDownload() => Items.Any(i => i.State == DownloadItemState.Pending);

    [RelayCommand(CanExecute = nameof(CanDownload))]
    private async Task DownloadAsync()
    {
        _batchCts = new CancellationTokenSource();
        var token = _batchCts.Token;
        var pending = Items.Where(i => i.State == DownloadItemState.Pending).ToList();
        StatusText = $"开始下载 {pending.Count} 个文件";

        var tasks = pending.Select(item => DownloadOneAsync(item, token));
        await Task.WhenAll(tasks).ConfigureAwait(false);

        _dispatcher.Invoke(() =>
        {
            var completed = Items.Count(i => i.State == DownloadItemState.Completed);
            var failed = Items.Count(i => i.State == DownloadItemState.Failed);
            StatusText = $"下载完成：成功 {completed}，失败 {failed}，共 {Items.Count} 项";
            DownloadCommand.NotifyCanExecuteChanged();
        });
    }

    private async Task DownloadOneAsync(DownloadItem item, CancellationToken batchCt)
    {
        await _gate.WaitAsync(batchCt).ConfigureAwait(false);
        try
        {
            var downloadUrl = item.Url;
            try
            {
                var resolved = await _urlResolver.ResolveAsync(item.Url, batchCt).ConfigureAwait(false);
                if (!string.IsNullOrWhiteSpace(resolved.DirectMediaUrl))
                {
                    downloadUrl = resolved.DirectMediaUrl;
                }
            }
            catch (Exception)
            {
                // 解析降级使用原链接
            }

            var outputPath = Path.Combine(SaveDirectory, item.FileName);
            outputPath = ResolveUniquePath(outputPath);

            var progress = new Progress<DownloadProgress>(p =>
            {
                UpdateItem(item.Id, i => i.WithProgress(p.Percent, p.BytesPerSecond, p.BytesReceived, p.TotalBytes));
            });

            await _downloader.DownloadAsync(downloadUrl, outputPath, progress, batchCt).ConfigureAwait(false);

            UpdateItem(item.Id, i => i.Complete());
        }
        catch (OperationCanceledException)
        {
            UpdateItem(item.Id, i => i.Cancel());
        }
        catch (HttpRequestException httpEx)
        {
            LogDownloadError(item.Url, httpEx);
            var friendlyMsg = httpEx.StatusCode switch
            {
                System.Net.HttpStatusCode.Forbidden => "403 禁止访问（直链签名已过期或防盗链拦截）",
                System.Net.HttpStatusCode.NotFound => "404 资源未找到（视频文件不存在或链接失效）",
                System.Net.HttpStatusCode.Unauthorized => "401 未授权（需要访问凭证）",
                System.Net.HttpStatusCode.TooManyRequests => "429 请求过于频繁（已被平台限流）",
                System.Net.HttpStatusCode.ServiceUnavailable => "503 服务不可用（源服务器繁忙）",
                _ => $"网络请求失败: {httpEx.Message}"
            };
            UpdateItem(item.Id, i => i.Fail(friendlyMsg));
        }
        catch (Exception ex)
        {
            LogDownloadError(item.Url, ex);
            var msg = ex.Message;
            if (msg.Contains("403", StringComparison.OrdinalIgnoreCase))
            {
                msg = "403 禁止访问（直链签名已过期或防盗链拦截）";
            }
            UpdateItem(item.Id, i => i.Fail(msg));
        }
        finally
        {
            _gate.Release();
        }
    }

    private void UpdateItem(Guid id, Func<DownloadItem, DownloadItem> transform)
    {
        if (_dispatcher.CheckAccess())
        {
            ApplyItemUpdate(id, transform);
        }
        else
        {
            _dispatcher.Invoke(() => ApplyItemUpdate(id, transform));
        }
    }

    private void ApplyItemUpdate(Guid id, Func<DownloadItem, DownloadItem> transform)
    {
        for (var i = 0; i < Items.Count; i++)
        {
            if (Items[i].Id == id)
            {
                Items[i] = transform(Items[i]);
                return;
            }
        }
    }

    [RelayCommand]
    private void CancelAll()
    {
        _batchCts?.Cancel();
        StatusText = "已暂停所有下载";
    }

    [RelayCommand]
    private void ClearList()
    {
        _batchCts?.Cancel();
        Items.Clear();
        StatusText = "列表已清空";
        DownloadCommand.NotifyCanExecuteChanged();
    }

    [RelayCommand]
    private void BrowseSaveDirectory()
    {
        SaveDirectoryChanged?.Invoke(this, EventArgs.Empty);
    }

    public event EventHandler? SaveDirectoryChanged;

    public void Dispose()
    {
        _batchCts?.Cancel();
        _batchCts?.Dispose();
        _gate.Dispose();
    }

    private static void LogDownloadError(string url, Exception ex)
    {
        try
        {
            var logDir = Path.Combine(
                JingXu.Workbench.Application.Projects.WorkbenchDataPaths.GetDataDirectory(), "logs");
            Directory.CreateDirectory(logDir);
            var logPath = Path.Combine(logDir, $"download-{DateTime.Now:yyyyMMdd}.log");
            var msg = $"[{DateTime.Now:O}] 下载失败: {url}\r\n{ex.GetBaseException().GetType().Name}: {ex.GetBaseException().Message}\r\n{ex.GetBaseException().StackTrace}\r\n\r\n";
            File.AppendAllText(logPath, msg, Encoding.UTF8);
        }
        catch
        {
        }
    }

    private static string ResolveUniquePath(string path)
    {
        if (!File.Exists(path))
        {
            return path;
        }

        var dir = Path.GetDirectoryName(path)!;
        var name = Path.GetFileNameWithoutExtension(path);
        var ext = Path.GetExtension(path);
        for (var i = 1; i < 100; i++)
        {
            var candidate = Path.Combine(dir, $"{name}_{i}{ext}");
            if (!File.Exists(candidate))
            {
                return candidate;
            }
        }

        return path;
    }
}
