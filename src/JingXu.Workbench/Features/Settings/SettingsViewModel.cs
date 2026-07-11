using System.Collections.ObjectModel;
using System.IO;
using System.Reflection;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Infrastructure.Processes;
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

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(DataDirectoryStatusText))]
    private bool _dataDirectoryExists;

    [ObservableProperty]
    private bool _isRefreshingRuntimeStatus;

    /// <summary>数据目录状态的中文描述。</summary>
    public string DataDirectoryStatusText => DataDirectoryExists ? "已创建" : "尚未创建（首次保存项目时自动生成）";

    public SettingsViewModel()
        : this(CreateDefaultDiagnostics())
    {
    }

    internal SettingsViewModel(RuntimeDiagnosticService runtimeDiagnostics)
    {
        ArgumentNullException.ThrowIfNull(runtimeDiagnostics);
        _runtimeDiagnostics = runtimeDiagnostics;

        var version = Assembly.GetExecutingAssembly().GetName().Version;
        AppVersion = version is null ? "1.0.0" : $"{version.Major}.{version.Minor}.{version.Build}";

        DataDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JingXu");

        RuntimeSearchOrder =
        [
            new("1", "应用目录 runtime\\", "随包分发的 FFmpeg / FFprobe / Whisper / Tesseract 优先。"),
            new("2", "设置中指定的目录", "尚未指定自定义运行时目录。"),
            new("3", "系统 PATH", "回退到系统环境变量中的可执行文件。")
        ];

        RefreshDataDirectoryState();
        _ = RefreshRuntimeStatusAsync();
    }

    private void RefreshDataDirectoryState() =>
        DataDirectoryExists = Directory.Exists(DataDirectory);

    /// <summary>重新读取本地数据目录与运行时诊断状态。</summary>
    [RelayCommand]
    private async Task RefreshDiagnosticsAsync()
    {
        RefreshDataDirectoryState();
        await RefreshRuntimeStatusAsync().ConfigureAwait(true);
    }

    /// <summary>仅刷新运行时组件诊断。</summary>
    [RelayCommand]
    private async Task RefreshRuntimeStatusAsync()
    {
        if (IsRefreshingRuntimeStatus)
        {
            return;
        }

        IsRefreshingRuntimeStatus = true;
        try
        {
            var statuses = await _runtimeDiagnostics.DiagnoseAsync().ConfigureAwait(true);
            RuntimeStatuses.Clear();
            foreach (var status in statuses)
            {
                RuntimeStatuses.Add(status);
            }
        }
        finally
        {
            IsRefreshingRuntimeStatus = false;
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
