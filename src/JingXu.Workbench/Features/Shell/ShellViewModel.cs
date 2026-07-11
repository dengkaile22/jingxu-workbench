using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Features.Composition;
using JingXu.Workbench.Features.Overlays;
using JingXu.Workbench.Features.Queue;
using JingXu.Workbench.Features.Settings;
using JingXu.Workbench.Features.Subtitles;
using System.ComponentModel;

namespace JingXu.Workbench.Features.Shell;

/// <summary>
/// 工作台壳层视图模型。负责模块导航（预创建并缓存模块实例，切换时保留实例状态）、
/// 标题栏信息、中央取景井预览、素材栏与检查器的展示，以及队列/检查器的折叠。
/// </summary>
public sealed partial class ShellViewModel : ObservableObject
{
    private readonly Dictionary<WorkspaceModule, WorkspaceModuleViewModel> _content;
    private readonly IFolderLauncher _folderLauncher;
    private readonly string _dataDirectory;

    public ShellViewModel(
        CompositionViewModel composition,
        OverlayEditorViewModel overlays,
        SubtitleLabViewModel subtitles,
        RenderQueueViewModel queue,
        SettingsViewModel settings,
        IFolderLauncher folderLauncher,
        IMediaFrameExtractor frameExtractor,
        IUiDispatcher uiDispatcher)
    {
        _folderLauncher = folderLauncher;
        _dataDirectory = settings.DataDirectory;
        QueueModule = queue;
        CompositionModule = composition;
        OverlayModule = overlays;
        Monitor = new GateMonitorViewModel(frameExtractor, uiDispatcher);

        // 预创建并缓存模块实例；导航在实例之间切换，不重建，保留各模块状态。
        _content = new Dictionary<WorkspaceModule, WorkspaceModuleViewModel>
        {
            [WorkspaceModule.Composition] = composition,
            [WorkspaceModule.Overlays] = overlays,
            [WorkspaceModule.Subtitles] = subtitles,
            [WorkspaceModule.Queue] = queue,
            [WorkspaceModule.Settings] = settings
        };

        // 左侧导航栏：全部五个条目按设计顺序排列。
        Modules =
        [
            new ShellModuleTab(WorkspaceModule.Composition, "混剪", "Icon.Module.Composition", "切换到批量混剪模块", isEnabled: true),
            new ShellModuleTab(WorkspaceModule.Overlays, "蒙版", "Icon.Module.Overlays", "切换到蒙版模板模块", isEnabled: true),
            new ShellModuleTab(WorkspaceModule.Subtitles, "字幕", "Icon.Module.Subtitles", "切换到字幕处理模块", isEnabled: true),
            new ShellModuleTab(WorkspaceModule.Queue, "队列", "Icon.Module.Queue", "切换到任务队列模块", isEnabled: true),
            new ShellModuleTab(WorkspaceModule.Settings, "设置", "Icon.Module.Settings", "切换到设置模块", isEnabled: true)
        ];

        // 默认进入混剪模块，便于导入 → 编排 → 入队主流程。
        _currentModule = composition;
        composition.PropertyChanged += OnCompositionPropertyChanged;
    }

    private void OnCompositionPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is nameof(CompositionViewModel.MaterialCount)
            or nameof(CompositionViewModel.HasMaterials)
            or nameof(CompositionViewModel.ImportGeneration))
        {
            OnPropertyChanged(nameof(MaterialCount));
            OnPropertyChanged(nameof(HasMaterials));
        }

        if (e.PropertyName is nameof(CompositionViewModel.SelectedMaterial)
            or nameof(CompositionViewModel.ImportGeneration))
        {
            var material = CompositionModule.SelectedMaterial
                ?? CompositionModule.Materials.FirstOrDefault(m => m.HasValidAsset);
            _ = Monitor.LoadFromMaterialAsync(material);
        }
    }

    /// <summary>中央取景井监视器。</summary>
    public GateMonitorViewModel Monitor { get; }

    /// <summary>左侧模块导航栏条目。</summary>
    public IReadOnlyList<ShellModuleTab> Modules { get; }

    /// <summary>任务队列模块实例。供底部持久队列条绑定其状态概览。</summary>
    public RenderQueueViewModel QueueModule { get; }

    /// <summary>批量混剪模块实例。供素材栏计数与混剪工作区共享状态。</summary>
    public CompositionViewModel CompositionModule { get; }

    /// <summary>蒙版模板模块实例。</summary>
    public OverlayEditorViewModel OverlayModule { get; }

    /// <summary>当前激活的模块内容视图模型。</summary>
    [ObservableProperty]
    private WorkspaceModuleViewModel _currentModule;

    /// <summary>
    /// 供导航列表双向绑定的当前模块标识。设置时执行导航；
    /// 导航到未启用模块时被忽略，属性回落到当前实际模块。
    /// </summary>
    public WorkspaceModule SelectedModule
    {
        get => CurrentModule.ModuleKind;
        set => Navigate(value);
    }

    partial void OnCurrentModuleChanged(WorkspaceModuleViewModel value) =>
        OnPropertyChanged(nameof(SelectedModule));

    /// <summary>
    /// 导航到指定模块。仅当该模块已启用且存在缓存实例时切换；否则为 no-op。
    /// </summary>
    [RelayCommand]
    private void Navigate(WorkspaceModule target)
    {
        var tab = Modules.FirstOrDefault(t => t.ModuleKind == target);
        if (tab is null || !tab.IsEnabled)
        {
            return;
        }

        if (_content.TryGetValue(target, out var content))
        {
            CurrentModule = content;
        }
    }

    /// <summary>在资源管理器中打开本地数据目录（检查器底部主操作）。</summary>
    [RelayCommand]
    private void OpenDataDirectory() => _folderLauncher.Open(_dataDirectory);

    // ── 标题栏 ────────────────────────────────────────────────────────────
    public string Wordmark { get; } = "镜序";

    public string ProductLine { get; } = "JINGXU · 光学编排台";

    public string ProjectName { get; } = "未打开项目";

    public string SaveStateText { get; } = "—";

    public string OfflineText { get; } = "离线";

    // ── 素材栏 ────────────────────────────────────────────────────────────
    public string MaterialTitle { get; } = "素材";

    public int MaterialCount => CompositionModule.MaterialCount;

    public bool HasMaterials => CompositionModule.HasMaterials;

    public string MaterialEmptyHint { get; } = "暂无素材。拖放视频到此处，或在混剪模块中导入以添加素材。";

    // ── 检查器 ────────────────────────────────────────────────────────────
    public string InspectorTitle { get; } = "属性";

    public string OutputRuleText { get; } =
        "输出规则：单一来源任务默认输出到源目录下的「分镜输出」；多来源任务输出到项目目录下的「分镜输出」。可按项目或任务自定义目录。";

    public string DataDirectory => _dataDirectory;

    // ── 折叠状态 ──────────────────────────────────────────────────────────
    [ObservableProperty]
    private bool _isQueueExpanded = true;

    [ObservableProperty]
    private bool _isInspectorExpanded = true;

    [RelayCommand]
    private void ToggleQueue() => IsQueueExpanded = !IsQueueExpanded;

    [RelayCommand]
    private void ToggleInspector() => IsInspectorExpanded = !IsInspectorExpanded;
}
