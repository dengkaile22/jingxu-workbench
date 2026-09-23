# 批量链接下载模块实现计划

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（`src/JingXu.Workbench.Py`），文中 `.cs`/`.xaml` 路径仅作历史记录。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将字幕实验室模块替换为批量链接下载模块

**Architecture:** 三层架构：Application 层定义 `IVideoDownloader` 接口，Infrastructure 层用 `HttpClient` 实现，Presentation 层用 MVVM 绑定下载列表和进度

**Tech Stack:** .NET 10 WPF · CommunityToolkit.Mvvm · HttpClient

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `Application/Abstractions/IVideoDownloader.cs` | 下载接口 + 进度 DTO |
| 新建 | `Application/Downloads/DownloadItem.cs` | 下载项记录 + 状态枚举 |
| 新建 | `Infrastructure/Downloads/HttpClientVideoDownloader.cs` | HttpClient 流式下载 |
| 新建 | `Features/Downloads/DownloadViewModel.cs` | 下载模块 VM |
| 新建 | `Features/Downloads/DownloadView.xaml` | 下载模块视图 |
| 新建 | `Features/Downloads/DownloadView.xaml.cs` | 代码后置 |
| 修改 | `Features/Shell/WorkspaceModule.cs` | Subtitles → Downloads |
| 修改 | `Features/Shell/ShellViewModel.cs` | 替换依赖 |
| 修改 | `ShellWindow.xaml` | 替换 DataTemplate / 标签 / 图标 |
| 修改 | `Bootstrap/AppCompositionRoot.cs` | DI 注入 |
| 修改 | `Themes/Controls.xaml` | 下载进度条样式 |

---

### Task 1: Application 层接口和模型

**Files:**
- Create: `src/JingXu.Workbench.Application/Abstractions/IVideoDownloader.cs`
- Create: `src/JingXu.Workbench.Application/Downloads/DownloadItem.cs`

- [ ] **Step 1: Create IVideoDownloader.cs**

```csharp
namespace JingXu.Workbench.Application.Abstractions;

public record DownloadProgress(
    long BytesReceived,
    long? TotalBytes,
    double BytesPerSecond,
    double Percent);

public interface IVideoDownloader
{
    Task DownloadAsync(
        string url,
        string outputPath,
        IProgress<DownloadProgress> progress,
        CancellationToken cancellationToken);
}
```

- [ ] **Step 2: Create DownloadItem.cs**

```csharp
namespace JingXu.Workbench.Application.Downloads;

public enum DownloadItemState
{
    Pending,
    Downloading,
    Completed,
    Failed,
    Cancelled
}

public sealed record DownloadItem(
    Guid Id,
    string Url,
    int Index,
    string FileName,
    string OutputPath,
    DownloadItemState State,
    double ProgressPercent,
    double BytesPerSecond,
    long BytesReceived,
    long? TotalBytes,
    string? ErrorMessage)
{
    public static DownloadItem Create(string url, int index, string outputPath)
    {
        var fileName = $"{index}.mp4";
        return new DownloadItem(
            Guid.NewGuid(),
            url,
            index,
            fileName,
            outputPath,
            DownloadItemState.Pending,
            0, 0, 0, null, null);
    }

    public DownloadItem WithProgress(double percent, double speed, long received, long? total) =>
        this with
        {
            State = DownloadItemState.Downloading,
            ProgressPercent = percent,
            BytesPerSecond = speed,
            BytesReceived = received,
            TotalBytes = total
        };

    public DownloadItem Complete() =>
        this with { State = DownloadItemState.Completed, ProgressPercent = 100 };

    public DownloadItem Fail(string error) =>
        this with { State = DownloadItemState.Failed, ErrorMessage = error };

    public DownloadItem Cancel() =>
        this with { State = DownloadItemState.Cancelled };
}
```

- [ ] **Step 3: Commit**

```bash
git add src/JingXu.Workbench.Application/Abstractions/IVideoDownloader.cs src/JingXu.Workbench.Application/Downloads/DownloadItem.cs
git commit -m "feat: add video downloader interface and model"
```

---

### Task 2: Infrastructure 层 HttpClient 下载器

**Files:**
- Create: `src/JingXu.Workbench.Infrastructure/Downloads/HttpClientVideoDownloader.cs`

- [ ] **Step 1: Create HttpClientVideoDownloader.cs**

```csharp
using JingXu.Workbench.Application.Abstractions;

namespace JingXu.Workbench.Infrastructure.Downloads;

public sealed class HttpClientVideoDownloader : IVideoDownloader
{
    private static readonly HttpClient Client = new()
    {
        Timeout = TimeSpan.FromMinutes(30)
    };

    public async Task DownloadAsync(
        string url,
        string outputPath,
        IProgress<DownloadProgress> progress,
        CancellationToken cancellationToken)
    {
        using var response = await Client.GetAsync(
            url,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken).ConfigureAwait(false);

        response.EnsureSuccessStatusCode();

        var totalBytes = response.Content.Headers.ContentLength;
        var totalBytesValue = totalBytes.HasValue ? totalBytes.Value : -1L;

        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);

        await using var contentStream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        await using var fileStream = new FileStream(
            outputPath, FileMode.Create, FileAccess.Write, FileShare.None, 81920, useAsync: true);

        var buffer = new byte[81920];
        var totalRead = 0L;
        var lastReport = DateTime.UtcNow;
        var lastRead = 0L;

        while (true)
        {
            var bytesRead = await contentStream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (bytesRead == 0)
            {
                break;
            }

            await fileStream.WriteAsync(buffer.AsMemory(0, bytesRead), cancellationToken).ConfigureAwait(false);
            totalRead += bytesRead;

            var now = DateTime.UtcNow;
            var elapsed = (now - lastReport).TotalSeconds;
            if (elapsed >= 0.2)
            {
                var speed = (totalRead - lastRead) / Math.Max(elapsed, 0.001);
                var percent = totalBytesValue > 0
                    ? Math.Clamp((double)totalRead / totalBytesValue * 100.0, 0, 100)
                    : 0;
                progress.Report(new DownloadProgress(totalRead, totalBytes, speed, percent));
                lastReport = now;
                lastRead = totalRead;
            }
        }

        progress.Report(new DownloadProgress(totalRead, totalBytes, 0, 100));
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add src/JingXu.Workbench.Infrastructure/Downloads/HttpClientVideoDownloader.cs
git commit -m "feat: implement HttpClient video downloader"
```

---

### Task 3: 下载模块 ViewModel

**Files:**
- Create: `src/JingXu.Workbench/Features/Downloads/DownloadViewModel.cs`

- [ ] **Step 1: Create DownloadViewModel.cs**

```csharp
using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Downloads;
using JingXu.Workbench.Features.Shell;

namespace JingXu.Workbench.Features.Downloads;

public sealed partial class DownloadViewModel : WorkspaceModuleViewModel
{
    private readonly IVideoDownloader _downloader;
    private readonly SemaphoreSlim _gate = new(5, 5);
    private CancellationTokenSource? _batchCts;

    public override WorkspaceModule ModuleKind => WorkspaceModule.Downloads;
    public override string Title => "批量下载";

    public DownloadViewModel(IVideoDownloader downloader)
    {
        _downloader = downloader;
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
            StatusText = "请先粘贴视频链接";
            return;
        }

        var urls = UrlInput
            .Split(['\n', '\r'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(u => Uri.TryCreate(u, UriKind.Absolute, out _))
            .ToList();

        if (urls.Count == 0)
        {
            StatusText = "未识别到有效链接";
            return;
        }

        var startIndex = Items.Count > 0 ? Items.Max(i => i.Index) + 1 : 1;
        foreach (var url in urls)
        {
            Items.Add(DownloadItem.Create(url, startIndex++, SaveDirectory));
        }

        StatusText = $"已解析 {urls.Count} 个链接，共 {Items.Count} 项";
        UrlInput = string.Empty;
        DownloadCommand.NotifyCanExecuteChanged();
    }

    private bool CanDownload() => Items.Any(i => i.State == DownloadItemState.Pending);

    [RelayCommand(CanExecute = nameof(CanDownload))]
    private async Task DownloadAsync()
    {
        _batchCts = new CancellationTokenSource();
        var pending = Items.Where(i => i.State == DownloadItemState.Pending).ToList();
        StatusText = $"开始下载 {pending.Count} 个文件";

        var tasks = pending.Select(item => DownloadOneAsync(item, _batchCts.Token));
        await Task.WhenAll(tasks).ConfigureAwait(false);

        var completed = Items.Count(i => i.State == DownloadItemState.Completed);
        var failed = Items.Count(i => i.State == DownloadItemState.Failed);
        StatusText = $"下载完成：成功 {completed}，失败 {failed}，共 {Items.Count} 项";
        DownloadCommand.NotifyCanExecuteChanged();
    }

    private async Task DownloadOneAsync(DownloadItem item, CancellationToken batchCt)
    {
        await _gate.WaitAsync(batchCt).ConfigureAwait(false);
        try
        {
            var index = Items.IndexOf(item);
            var outputPath = Path.Combine(SaveDirectory, item.FileName);
            outputPath = ResolveUniquePath(outputPath);

            var progress = new Progress<DownloadProgress>(p =>
            {
                if (index >= 0 && index < Items.Count)
                {
                    Items[index] = item.WithProgress(p.Percent, p.BytesPerSecond, p.BytesReceived, p.TotalBytes);
                }
            });

            await _downloader.DownloadAsync(item.Url, outputPath, progress, batchCt).ConfigureAwait(false);

            if (index >= 0 && index < Items.Count)
            {
                Items[index] = item.Complete();
            }
        }
        catch (OperationCanceledException)
        {
            if (index >= 0 && index < Items.Count)
            {
                Items[index] = item.Cancel();
            }
        }
        catch (Exception ex)
        {
            if (index >= 0 && index < Items.Count)
            {
                Items[index] = item.Fail(ex.Message);
            }
        }
        finally
        {
            _gate.Release();
        }

        int index;
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
        // 由 View 代码后置调用 FolderBrowserDialog
        SaveDirectoryChanged?.Invoke(this, EventArgs.Empty);
    }

    public event EventHandler? SaveDirectoryChanged;

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
```

**Note:** Fix the `index` variable capture — it's declared outside the try block but also needs to be captured in progress. Let me rewrite with the proper pattern:

- [ ] **Step 1 (revised): Create DownloadViewModel.cs**

```csharp
using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Downloads;
using JingXu.Workbench.Features.Shell;

namespace JingXu.Workbench.Features.Downloads;

public sealed partial class DownloadViewModel : WorkspaceModuleViewModel
{
    private readonly IVideoDownloader _downloader;
    private readonly SemaphoreSlim _gate = new(5, 5);
    private CancellationTokenSource? _batchCts;

    public override WorkspaceModule ModuleKind => WorkspaceModule.Downloads;
    public override string Title => "批量下载";

    public DownloadViewModel(IVideoDownloader downloader)
    {
        _downloader = downloader;
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
            StatusText = "请先粘贴视频链接";
            return;
        }

        var urls = UrlInput
            .Split(['\n', '\r'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(u => Uri.TryCreate(u, UriKind.Absolute, out _))
            .ToList();

        if (urls.Count == 0)
        {
            StatusText = "未识别到有效链接";
            return;
        }

        var startIndex = Items.Count > 0 ? Items.Max(i => i.Index) + 1 : 1;
        foreach (var url in urls)
        {
            Items.Add(DownloadItem.Create(url, startIndex++, SaveDirectory));
        }

        StatusText = $"已解析 {urls.Count} 个链接，共 {Items.Count} 项";
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

        var completed = Items.Count(i => i.State == DownloadItemState.Completed);
        var failed = Items.Count(i => i.State == DownloadItemState.Failed);
        StatusText = $"下载完成：成功 {completed}，失败 {failed}，共 {Items.Count} 项";
        DownloadCommand.NotifyCanExecuteChanged();
    }

    private async Task DownloadOneAsync(DownloadItem item, CancellationToken batchCt)
    {
        await _gate.WaitAsync(batchCt).ConfigureAwait(false);
        try
        {
            var outputPath = Path.Combine(SaveDirectory, item.FileName);
            outputPath = ResolveUniquePath(outputPath);

            var progress = new Progress<DownloadProgress>(p =>
            {
                var idx = FindItemIndex(item.Id);
                if (idx >= 0)
                {
                    Items[idx] = item.WithProgress(p.Percent, p.BytesPerSecond, p.BytesReceived, p.TotalBytes);
                }
            });

            await _downloader.DownloadAsync(item.Url, outputPath, progress, batchCt).ConfigureAwait(false);

            var idx = FindItemIndex(item.Id);
            if (idx >= 0)
            {
                Items[idx] = item.Complete();
            }
        }
        catch (OperationCanceledException)
        {
            var idx = FindItemIndex(item.Id);
            if (idx >= 0)
            {
                Items[idx] = item.Cancel();
            }
        }
        catch (Exception ex)
        {
            var idx = FindItemIndex(item.Id);
            if (idx >= 0)
            {
                Items[idx] = item.Fail(ex.Message);
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    private int FindItemIndex(Guid id)
    {
        for (var i = 0; i < Items.Count; i++)
        {
            if (Items[i].Id == id)
            {
                return i;
            }
        }

        return -1;
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
```

- [ ] **Step 2: Commit**

```bash
git add src/JingXu.Workbench/Features/Downloads/DownloadViewModel.cs
git commit -m "feat: add download viewmodel with concurrent download logic"
```

---

### Task 4: 添加下载进度条转换器和图标资源

**Files:**
- Modify: `src/JingXu.Workbench/Themes/Converters/DownloadProgressToVisibilityConverter.cs`
- Modify: `src/JingXu.Workbench/App.xaml` — 注册转换器

- [ ] **Step 1: 创建转换器**

Create `src/JingXu.Workbench/Themes/Converters/DownloadProgressToVisibilityConverter.cs`:

```csharp
using System.Globalization;
using System.Windows;

namespace JingXu.Workbench.Themes.Converters;

public sealed class DownloadProgressToVisibilityConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) =>
        value is double d and > 0 ? Visibility.Visible : Visibility.Collapsed;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
```

- [ ] **Step 2: 在 App.xaml 中注册转换器**

在 `<Application.Resources>` 中添加该转换器（在现有 MergedDictionaries 之后）：

```xml
<Application.Resources>
    <ResourceDictionary>
        <ResourceDictionary.MergedDictionaries>
            <ResourceDictionary Source="Themes/Colors.xaml" />
            <ResourceDictionary Source="Themes/Typography.xaml" />
            <ResourceDictionary Source="Themes/Metrics.xaml" />
            <ResourceDictionary Source="Themes/Animations/Motion.xaml" />
            <ResourceDictionary Source="Themes/Controls.xaml" />
        </ResourceDictionary.MergedDictionaries>
        <converters:DownloadProgressToVisibilityConverter x:Key="DownloadProgressToVis" />
    </ResourceDictionary>
</Application.Resources>
```

Add the XML namespace to App.xaml if missing:
```xml
xmlns:converters="clr-namespace:JingXu.Workbench.Themes.Converters"
```

- [ ] **Step 3: Commit**

```bash
git add src/JingXu.Workbench/Themes/Converters/DownloadProgressToVisibilityConverter.cs src/JingXu.Workbench/App.xaml
git commit -m "feat: add download progress converter"
```

---

### Task 5: 下载模块 View (XAML + Code-behind)

**Files:**
- Create: `src/JingXu.Workbench/Features/Downloads/DownloadView.xaml`
- Create: `src/JingXu.Workbench/Features/Downloads/DownloadView.xaml.cs`

- [ ] **Step 2: Create DownloadView.xaml.cs**

```csharp
using System.Windows;
using System.Windows.Forms;
using JingXu.Workbench.Features.Downloads;

namespace JingXu.Workbench.Features.Downloads;

public partial class DownloadView : System.Windows.Controls.UserControl
{
    public DownloadView()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is DownloadViewModel oldVm)
        {
            oldVm.SaveDirectoryChanged -= OnBrowseSaveDirectory;
        }

        if (e.NewValue is DownloadViewModel newVm)
        {
            newVm.SaveDirectoryChanged += OnBrowseSaveDirectory;
        }
    }

    private void OnBrowseSaveDirectory(object? sender, EventArgs e)
    {
        if (DataContext is not DownloadViewModel vm)
        {
            return;
        }

        using var dialog = new FolderBrowserDialog();
        dialog.SelectedPath = vm.SaveDirectory;
        if (dialog.ShowDialog() == DialogResult.OK)
        {
            vm.SaveDirectory = dialog.SelectedPath;
        }
    }
}
```

- [ ] **Step 3: Build and fix any XAML compile errors**

Run: `dotnet build src/JingXu.Workbench/JingXu.Workbench.csproj`
Expected: Build succeeds with 0 errors

- [ ] **Step 4: Commit**

```bash
git add src/JingXu.Workbench/Features/Downloads/DownloadView.xaml src/JingXu.Workbench/Features/Downloads/DownloadView.xaml.cs
git commit -m "feat: add download view with progress display"
```

---

### Task 6: 修改 ShellViewModel 替换字幕模块

**Files:**
- Modify: `src/JingXu.Workbench/Features/Shell/WorkspaceModule.cs`
- Modify: `src/JingXu.Workbench/Features/Shell/ShellViewModel.cs`

- [ ] **Step 1: Modify WorkspaceModule.cs — Subtitles → Downloads**

```csharp
public enum WorkspaceModule
{
    Composition,
    Overlays,
    Downloads,   // was Subtitles
    Queue,
    Settings
}
```

- [ ] **Step 2: Modify ShellViewModel.cs — Replace SubtitleLabViewModel with DownloadViewModel**

```csharp
// 顶部 using — remove subtitles, add downloads
using JingXu.Workbench.Features.Downloads;   // new
// remove: using JingXu.Workbench.Features.Subtitles;

// 构造参数 — replace SubtitleLabViewModel with DownloadViewModel
public ShellViewModel(
    CompositionViewModel composition,
    OverlayEditorViewModel overlays,
    DownloadViewModel downloads,       // was SubtitleLabViewModel subtitles
    RenderQueueViewModel queue,
    SettingsViewModel settings,
    IFolderLauncher folderLauncher,
    IMediaFrameExtractor frameExtractor,
    IUiDispatcher uiDispatcher)
{
    // ...
    _content = new Dictionary<WorkspaceModule, WorkspaceModuleViewModel>
    {
        [WorkspaceModule.Composition] = composition,
        [WorkspaceModule.Overlays] = overlays,
        [WorkspaceModule.Downloads] = downloads,    // was Subtitles
        [WorkspaceModule.Queue] = queue,
        [WorkspaceModule.Settings] = settings
    };

    Modules =
    [
        new ShellModuleTab(WorkspaceModule.Composition, "混剪", "Icon.Module.Composition", "切换到批量混剪模块", isEnabled: true),
        new ShellModuleTab(WorkspaceModule.Overlays, "蒙版", "Icon.Module.Overlays", "切换到蒙版模板模块", isEnabled: true),
        new ShellModuleTab(WorkspaceModule.Downloads, "下载", "Icon.Module.Downloads", "切换到批量下载模块", isEnabled: true),
        new ShellModuleTab(WorkspaceModule.Queue, "队列", "Icon.Module.Queue", "切换到任务队列模块", isEnabled: true),
        new ShellModuleTab(WorkspaceModule.Settings, "设置", "Icon.Module.Settings", "切换到设置模块", isEnabled: true)
    ];
    // ...
}
```

- [ ] **Step 3: Commit**

```bash
git add src/JingXu.Workbench/Features/Shell/WorkspaceModule.cs src/JingXu.Workbench/Features/Shell/ShellViewModel.cs
git commit -m "refactor: replace subtitle module with download module in shell"
```

---

### Task 7: 修改 AppCompositionRoot 和 ShellWindow

**Files:**
- Modify: `src/JingXu.Workbench/Bootstrap/AppCompositionRoot.cs`
- Modify: `src/JingXu.Workbench/ShellWindow.xaml`

- [ ] **Step 1: Modify AppCompositionRoot.cs**

在 `CreateShell()` 方法中，替换 SubtitleLabViewModel 的创建为 DownloadViewModel：

```csharp
// 在 CreateShell 方法中：

// 删除 SubtitleLabViewModel 的创建（约 3 行）
// 删除 SubtitleWorkflow 的创建（如果无其他地方引用）

// 添加 DownloadViewModel
var downloader = new HttpClientVideoDownloader();
var downloadVm = new DownloadViewModel(downloader);

// 传给 ShellViewModel 构造
return new ShellViewModel(
    composition,
    overlays,
    downloadVm,              // was subtitles
    queue,
    settings,
    folderLauncher,
    frameExtractor,
    uiDispatcher);
```

并添加 using：
```csharp
using JingXu.Workbench.Infrastructure.Downloads;
using JingXu.Workbench.Features.Downloads;
```

删除不再需要的 using：
```csharp
// 移除（如果不再引用）
// using JingXu.Workbench.Features.Subtitles;
// using JingXu.Workbench.Infrastructure.Subtitles;
```

- [ ] **Step 2: Modify ShellWindow.xaml**

删除字幕的 DataTemplate：
```xml
<!-- DELETE this block -->
<!-- <DataTemplate DataType="{x:Type subtitles:SubtitleLabViewModel}">
    <subtitles:SubtitleLabView />
</DataTemplate> -->
```

添加下载的 DataTemplate：
```xml
<DataTemplate DataType="{x:Type downloads:DownloadViewModel}">
    <downloads:DownloadView />
</DataTemplate>
```

更新 XML 命名空间：
```xml
xmlns:downloads="clr-namespace:JingXu.Workbench.Features.Downloads"
```

删除字幕的命名空间：
```xml
<!-- DELETE -->
<!-- xmlns:subtitles="clr-namespace:JingXu.Workbench.Features.Subtitles" -->
```

- [ ] **Step 3: Build to verify**

Run: `dotnet build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add src/JingXu.Workbench/Bootstrap/AppCompositionRoot.cs src/JingXu.Workbench/ShellWindow.xaml
git commit -m "refactor: wire download module in composition root and shell window"
```

---

### Task 8: 添加下载图标和进程条样式

**Files:**
- Modify: `src/JingXu.Workbench/ShellWindow.xaml`（添加图标资源）

- [ ] **Step 1: 添加下载图标几何资源**

```csharp
using System.Globalization;
using System.Windows;

namespace JingXu.Workbench.Themes.Converters;

public sealed class DownloadProgressToVisibilityConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) =>
        value is double d && d > 0 ? Visibility.Visible : Visibility.Collapsed;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
```

- [ ] **Step 2: 在 App.xaml 中注册转换器**

```xml
<!-- 在 App.xaml Application.Resources 中添加 -->
<ResourceDictionary>
    <ResourceDictionary.MergedDictionaries>
        <!-- existing dictionaries -->
    </ResourceDictionary.MergedDictionaries>
    <converters:DownloadProgressToVisibilityConverter x:Key="DownloadProgressToVis" />
</ResourceDictionary>
```

或者注册到 Themes/Converters 目录并合并。

- [ ] **Step 3: 添加下载图标资源**

在 ShellWindow.xaml 或资源字典中添加下载图标：

```xml
<!-- 下载箭头图标 Path -->
<PathGeometry x:Key="Icon.Module.Downloads">M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22A10,10 0 0,1 2,12A10,10 0 0,1 12,2M12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12A8,8 0 0,0 12,4M11,16V10H13V16H16L12,20L8,16H11Z</PathGeometry>
```

- [ ] **Step 4: Commit**

```bash
git add src/JingXu.Workbench/Themes/Converters/DownloadProgressToVisibilityConverter.cs
git commit -m "feat: add download progress converter and module icon"
```

---

### Task 9: 运行测试，验证编译和功能

- [ ] **Step 1: Build entire solution**

Run: `dotnet build`
Expected: Build succeeds, no errors

- [ ] **Step 2: Run all tests**

Run: `dotnet test`
Expected: All existing tests pass (Domain 128, Application 90, Infrastructure 127, Presentation 157)

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: replace subtitle lab with batch video download module"
```
