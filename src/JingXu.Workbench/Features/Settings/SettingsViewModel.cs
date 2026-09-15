using System.Collections.ObjectModel;
using System.IO;
using System.Reflection;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Features.Settings;

/// <summary>
/// 运行时搜索顺序中的一个条目（仅信息展示）。
/// </summary>
/// <param name="Order">序号，例如「1」。</param>
/// <param name="Location">位置说明。</param>
/// <param name="Detail">补充说明。</param>
public sealed record RuntimeSearchEntry(string Order, string Location, string Detail);

/// <summary>
/// 设置模块视图模型。展示离线声明、应用版本、本地数据目录，
/// 以及 FFmpeg / FFprobe / Whisper / Tesseract 的运行时诊断状态。
/// </summary>
public sealed partial class SettingsViewModel : WorkspaceModuleViewModel
{
    private readonly RuntimeDiagnosticService _runtimeDiagnostics;
    private readonly RenderCoordinator? _renderCoordinator;
    private readonly IVideoEncoderSelector? _encoderSelector;
    private readonly IVideoProcessingSelector? _processingSelector;

    public override WorkspaceModule ModuleKind => WorkspaceModule.Settings;

    public override string Title => "设置";

    /// <summary>应用版本号。</summary>
    public string AppVersion { get; }

    /// <summary>离线运行声明。</summary>
    public string OfflineStatement { get; } =
        "完全离线运行：不联网、不上传任何素材、音频、字幕或项目数据。";

    /// <summary>本地数据目录（项目、队列、设置的存放位置）。</summary>
    public string DataDirectory { get; }

    /// <summary>外部媒体运行时的解析顺序（应用目录 → 用户设置 → 系统 PATH）。</summary>
    public IReadOnlyList<RuntimeSearchEntry> RuntimeSearchOrder { get; }

    /// <summary>各运行时组件的诊断状态。</summary>
    public ObservableCollection<RuntimeComponentStatus> RuntimeStatuses { get; } = [];

    /// <summary>可选并发上限（1–4）；高并发适合升级后的多核 CPU / 多显卡电脑。</summary>
    public IReadOnlyList<int> ConcurrencyOptions { get; } = [1, 2, 3, 4];

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(DataDirectoryStatusText))]
    private bool _dataDirectoryExists;

    [ObservableProperty]
    private bool _isRefreshingRuntimeStatus;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ConcurrencyHint))]
    private int _maxRenderConcurrency = 2;

    [ObservableProperty]
    private string _concurrencyStatusMessage = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasCacheCleanupStatus))]
    private string _cacheCleanupStatusMessage = string.Empty;

    [ObservableProperty]
    private bool _isCleaningCache;

    /// <summary>数据目录状态的中文描述。</summary>
    public string DataDirectoryStatusText => DataDirectoryExists ? "已创建" : "尚未创建（首次保存项目时自动生成）";

    /// <summary>并发说明。</summary>
    public string ConcurrencyHint =>
        (MaxRenderConcurrency <= 1
            ? "串行渲染：一次只跑 1 个任务，适合 CPU 编码和低配置电脑。"
            : MaxRenderConcurrency <= 2
                ? "最多同时渲染 2 个任务；GPU 编码时也建议保持 2，避免显存争用。"
                : $"最多同时渲染 {MaxRenderConcurrency} 个任务；适合多核 CPU。GPU 编码时并发过高可能争用显存。")
        + " 高分辨率四屏任务自动逐个处理，减少内存和显存争用。";

    /// <summary>只读：本机探测到的 GPU 编码器，或回退 CPU 的说明。</summary>
    [ObservableProperty]
    private string _gpuEncoderStatus =
        "尚未检测。混剪页默认「自动」：有可用 GPU 时用硬件编码（NVENC → QSV → AMF），失败自动回退 CPU。点击下方「刷新诊断」可立即检测。";

    [ObservableProperty]
    private string _gpuProcessingStatus = "硬件解码与 GPU 缩放尚未检测。点击「刷新诊断」可检测当前设备。";

    /// <summary>GPU 能力的固定说明，避免做成复杂配置项。</summary>
    public string GpuEncoderHint { get; } =
        "自动模式优先硬件编码，在适合的缩小场景启用硬解与 GPU 缩放；GPU 模式可手动启用兼容主片硬解。同尺寸视频的硬解可能因帧回传而更慢。循环辅助素材、蒙版、贴纸与调色使用 CPU。硬件失败自动回退；无损直拷不走编码器。需要对应 NVIDIA / AMD / Intel 显卡驱动。";

    public bool HasConcurrencyStatus => !string.IsNullOrWhiteSpace(ConcurrencyStatusMessage);

    public bool HasCacheCleanupStatus => !string.IsNullOrWhiteSpace(CacheCleanupStatusMessage);

    public SettingsViewModel()
        : this(CreateDefaultDiagnostics(), renderCoordinator: null)
    {
    }

    internal SettingsViewModel(
        RuntimeDiagnosticService runtimeDiagnostics,
        RenderCoordinator? renderCoordinator = null,
        IVideoEncoderSelector? encoderSelector = null,
        IVideoProcessingSelector? processingSelector = null)
    {
        ArgumentNullException.ThrowIfNull(runtimeDiagnostics);
        _runtimeDiagnostics = runtimeDiagnostics;
        _renderCoordinator = renderCoordinator;
        _encoderSelector = encoderSelector;
        _processingSelector = processingSelector;

        var version = Assembly.GetExecutingAssembly().GetName().Version;
        AppVersion = version is null ? "1.0.0" : $"{version.Major}.{version.Minor}.{version.Build}";

        DataDirectory = WorkbenchDataPaths.GetDataDirectory();

        RuntimeSearchOrder =
        [
            new("1", "应用目录 runtime\\", "随包分发的 FFmpeg / FFprobe / Whisper / Tesseract 优先。"),
            new("2", "设置中指定的目录", "尚未指定自定义运行时目录。"),
            new("3", "系统 PATH", "回退到系统环境变量中的可执行文件。")
        ];

        if (_renderCoordinator is not null)
        {
            MaxRenderConcurrency = _renderCoordinator.MaxConcurrency;
        }

        RefreshDataDirectoryState();
        _ = RefreshRuntimeStatusAsync();
    }

    /// <summary>应用渲染并发上限（1–4）；进行中任务结束后生效。</summary>
    [RelayCommand]
    private async Task ApplyRenderConcurrencyAsync()
    {
        if (_renderCoordinator is null)
        {
            ConcurrencyStatusMessage = "渲染协调器未装配，无法调整并发。";
            OnPropertyChanged(nameof(HasConcurrencyStatus));
            return;
        }

        var value = Math.Clamp(MaxRenderConcurrency, 1, RenderCoordinator.SafeMaxConcurrency);
        MaxRenderConcurrency = value;
        await _renderCoordinator.SetMaxConcurrencyAsync(value, CancellationToken.None).ConfigureAwait(true);
        ConcurrencyStatusMessage = value == _renderCoordinator.MaxConcurrency
            ? $"已应用：同时最多 {value} 个渲染任务。"
            : $"已预约并发 {value}（当前活跃任务结束后生效；当前仍为 {_renderCoordinator.MaxConcurrency}）。";
        OnPropertyChanged(nameof(HasConcurrencyStatus));
    }

    /// <summary>清理工作台缓存与临时目录（已知 jingxu 临时目录、.jingxu-tmp 半成品、蒙版缩略图缓存）。不成片、不删库 JSON。</summary>
    [RelayCommand]
    private async Task ClearWorkbenchCacheAsync()
    {
        IsCleaningCache = true;
        CacheCleanupStatusMessage = "正在检查并清理失效临时文件…";
        OnPropertyChanged(nameof(HasCacheCleanupStatus));
        try
        {
            IReadOnlyList<Guid>? protectedIds = null;
            List<string>? extraRoots = null;
            List<string>? protectedFiles = null;
            if (_renderCoordinator is not null)
            {
                protectedIds = _renderCoordinator.InflightJobIds;
                extraRoots = [];
                protectedFiles = [];
                foreach (var job in _renderCoordinator.Jobs)
                {
                    var outputDir = Path.GetDirectoryName(job.Request?.OutputPath);
                    if (!string.IsNullOrWhiteSpace(outputDir))
                    {
                        extraRoots.Add(outputDir);
                    }

                    var subtitlePath = job.Request?.SubtitleBurn?.SubtitleFilePath;
                    if (job.State is JobState.Queued or JobState.Preparing or JobState.Running or JobState.Finalizing
                        && !string.IsNullOrWhiteSpace(subtitlePath))
                    {
                        protectedFiles.Add(subtitlePath);
                    }
                }
            }

            var result = await Task.Run(() => WorkbenchCacheCleanup.Cleanup(
                DataDirectory,
                extraSearchRoots: extraRoots,
                protectedJobIds: protectedIds,
                protectedFiles: protectedFiles,
                includeOverlayThumbCache: true)).ConfigureAwait(true);
            CacheCleanupStatusMessage = result.SummaryText;
        }
        catch (Exception ex)
        {
            CacheCleanupStatusMessage = $"清理失败：{ex.GetBaseException().Message}";
        }
        finally
        {
            IsCleaningCache = false;
        }

        RefreshDataDirectoryState();
        OnPropertyChanged(nameof(HasCacheCleanupStatus));
    }

    private void RefreshDataDirectoryState() =>
        DataDirectoryExists = Directory.Exists(DataDirectory);

    /// <summary>重新读取本地数据目录、运行时与 GPU 编码器诊断。</summary>
    [RelayCommand]
    private async Task RefreshDiagnosticsAsync()
    {
        RefreshDataDirectoryState();
        await RefreshRuntimeStatusAsync().ConfigureAwait(true);
        await RefreshGpuEncoderStatusAsync().ConfigureAwait(true);
    }

    /// <summary>根据当前 FFmpeg 探测可用的 NVENC/QSV/AMF，结果只读展示。</summary>
    private async Task RefreshGpuEncoderStatusAsync()
    {
        var ffmpeg = RuntimeStatuses.FirstOrDefault(status => status.Kind == RuntimeKind.Ffmpeg);
        if (ffmpeg is null || !ffmpeg.IsAvailable || string.IsNullOrWhiteSpace(ffmpeg.ResolvedPath))
        {
            GpuEncoderStatus = "未找到 FFmpeg，无法检测 GPU 编码器。渲染将使用 CPU（libx264）。";
            GpuProcessingStatus = "未找到 FFmpeg，无法检测硬件解码与 GPU 缩放。";
            return;
        }

        if (_encoderSelector is null)
        {
            GpuEncoderStatus = "GPU 编码器探测未装配。首次转码仍会自动探测，失败则回退 CPU。";
            GpuProcessingStatus = "GPU 处理能力探测未装配。";
            return;
        }

        try
        {
            _encoderSelector.ResetProbe(ffmpeg.ResolvedPath);
            var selection = await _encoderSelector
                .SelectAsync(ffmpeg.ResolvedPath, VideoProcessingMode.Auto, CancellationToken.None)
                .ConfigureAwait(true);
            GpuEncoderStatus = DescribeGpuSelection(selection);
            if (_processingSelector is null)
            {
                GpuProcessingStatus = "GPU 处理能力探测未装配；解码与缩放使用 CPU。";
            }
            else
            {
                GpuProcessingStatus = "正在实测硬件解码、缩放与帧回传…";
                _processingSelector.ResetProbe(ffmpeg.ResolvedPath);
                var processing = await _processingSelector.SelectAsync(ffmpeg.ResolvedPath,
                    VideoProcessingMode.Auto, selection.Kind, CancellationToken.None).ConfigureAwait(true);
                GpuProcessingStatus = processing.Description;
            }
        }
        catch (Exception ex)
        {
            GpuEncoderStatus = $"GPU 编码器检测失败：{ex.GetBaseException().Message}。渲染将回退 CPU（libx264）。";
            GpuProcessingStatus = "GPU 处理能力检测未完成；解码与缩放使用 CPU。";
        }
    }

    private static string DescribeGpuSelection(VideoEncoderSelection selection) =>
        selection.Kind switch
        {
            VideoEncoderKind.H264Nvenc =>
                "当前可用：NVIDIA GPU（NVENC / h264_nvenc）。混剪页选「自动」或「GPU」时将用它做最终编码。",
            VideoEncoderKind.H264Qsv =>
                "当前可用：Intel GPU（QSV / h264_qsv）。混剪页选「自动」或「GPU」时将用它做最终编码。",
            VideoEncoderKind.H264Amf =>
                "当前可用：AMD GPU（AMF / h264_amf）。混剪页选「自动」或「GPU」时将用它做最终编码。",
            _ =>
                "未检测到可用 GPU 编码器，渲染将使用 CPU（libx264）。请安装 NVIDIA / AMD / Intel 显卡驱动，并允许独显用于本程序。"
        };

    /// <summary>仅刷新运行时组件诊断。</summary>
    [RelayCommand]
    private async Task RefreshRuntimeStatusAsync()
    {
        IsRefreshingRuntimeStatus = true;
        var sync = SynchronizationContext.Current;
        try
        {
            var statuses = await _runtimeDiagnostics.DiagnoseAsync().ConfigureAwait(false);
            void Apply() => ReplaceRuntimeStatuses(statuses);
            if (sync is null)
            {
                Apply();
            }
            else
            {
                sync.Send(_ => Apply(), null);
            }
        }
        finally
        {
            void ClearFlag() => IsRefreshingRuntimeStatus = false;
            if (sync is null)
            {
                ClearFlag();
            }
            else
            {
                sync.Send(_ => ClearFlag(), null);
            }
        }
    }

    private void ReplaceRuntimeStatuses(IReadOnlyList<RuntimeComponentStatus> statuses)
    {
        RuntimeStatuses.Clear();
        foreach (var status in statuses)
        {
            RuntimeStatuses.Add(status);
        }
    }

    private static RuntimeDiagnosticService CreateDefaultDiagnostics()
    {
        var appRoot = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        return new RuntimeDiagnosticService(
            appRoot,
            new RuntimeResolver(appRoot, FindOnPath),
            new ExternalProcessRunner());
    }

    private static string? FindOnPath(string executableName)
    {
        var pathValue = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathValue))
        {
            return null;
        }

        foreach (var directory in pathValue.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(directory.Trim(), executableName);
                if (File.Exists(candidate))
                {
                    return candidate;
                }

                if (OperatingSystem.IsWindows())
                {
                    var withExe = candidate.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
                        ? candidate
                        : candidate + ".exe";
                    if (File.Exists(withExe))
                    {
                        return withExe;
                    }
                }
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        return null;
    }
}
