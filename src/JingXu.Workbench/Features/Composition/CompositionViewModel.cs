using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Common;
using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Domain.Stickers;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Infrastructure.Persistence;
using JingXu.Workbench.Features.Stickers;
using JingXu.Workbench.Features.Overlays;

namespace JingXu.Workbench.Features.Composition;

/// <summary>
/// 批量混剪模块视图模型：导入素材、随机/自定义编排预览、加入渲染队列。
/// </summary>
public sealed partial class CompositionViewModel : WorkspaceModuleViewModel
{
    private readonly IMediaProbe _probe;
    private readonly RenderCoordinator _coordinator;
    private readonly IMediaFilePicker _filePicker;
    private readonly IOutputFolderPicker _outputFolderPicker;
    private readonly IUiDispatcher _uiDispatcher;
    private readonly OverlayWorkbenchState? _overlayState;
    private readonly OverlayLibraryService? _overlayLibraryService;
    private readonly TemplateService? _templateService;
    private readonly IMediaFrameExtractor? _frameExtractor;
    private readonly SequenceTemplateService? _sequenceTemplateService;
    private readonly StickerEditorViewModel _stickerEditor;
    private readonly OverlayEditorViewModel? _overlayEditor;
    private readonly AudioLibraryService? _audioLibraryService;
    private readonly FileExistenceCache _fileExistenceCache;
    private readonly int _randomLibrarySelectionSeed;
    private readonly int _audioLibrarySeed = Random.Shared.Next();
    private long _nextRandomAudioSelectionOrdinal;
    private readonly List<MediaAsset> _assets = [];
    private readonly CompositionWorkspaceSlot[] _workspaces =
    [
        new("商品组 A"),
        new("商品组 B")
    ];
    private IReadOnlyList<CompositionPlan> _executablePlans = [];
    private bool _outputDirectoryUserOverride;
    private bool _trackOutputDirectoryOverrides;
    private bool _suppressOutputDirectoryOverrideTracking;
    private bool _suppressWorkspaceSwitch;
    private EffectVariationTemplate _activeEffectTemplate = EffectTemplates.None;
    private readonly Dictionary<string, EffectTemplateSettingsDto> _effectTemplateSettingsById =
        new(StringComparer.Ordinal);
    private const int OverlayPreviewDebounceMilliseconds = 150;
    private readonly object _overlayPreviewSync = new();
    private readonly string _overlayPreviewSessionId = Guid.NewGuid().ToString("N");
    private readonly Task _initialEffectTemplateLoadTask;
    private CancellationTokenSource? _overlayPreviewCancellation;
    private int _overlayPreviewGeneration;
    private long _nextRandomMaskSelectionOrdinal;
    private long _nextRandomStickerSelectionOrdinal;

    public CompositionViewModel(
        IMediaProbe probe,
        RenderCoordinator coordinator,
        IMediaFilePicker filePicker,
        IOutputFolderPicker outputFolderPicker,
        IUiDispatcher uiDispatcher,
        OverlayWorkbenchState? overlayState = null,
        OverlayLibraryService? overlayLibraryService = null,
        TemplateService? templateService = null,
        IMediaFrameExtractor? frameExtractor = null,
        SequenceTemplateService? sequenceTemplateService = null,
        StickerEditorViewModel? stickerEditor = null,
        OverlayEditorViewModel? overlayEditor = null,
        AudioLibraryService? audioLibraryService = null,
        FileExistenceCache? fileExistenceCache = null)
    {
        _probe = probe;
        _coordinator = coordinator;
        _randomLibrarySelectionSeed = Random.Shared.Next();
        _audioLibrarySeed = Random.Shared.Next();
        _nextRandomMaskSelectionOrdinal = coordinator.Jobs.Count;
        _nextRandomStickerSelectionOrdinal = coordinator.Jobs.Count;
        _nextRandomAudioSelectionOrdinal = coordinator.Jobs.Count;
        _filePicker = filePicker;
        _outputFolderPicker = outputFolderPicker;
        _uiDispatcher = uiDispatcher;
        _overlayState = overlayState;
        _overlayLibraryService = overlayLibraryService;
        _templateService = templateService;
        _frameExtractor = frameExtractor;
        _sequenceTemplateService = sequenceTemplateService;
        _audioLibraryService = audioLibraryService;
        _fileExistenceCache = fileExistenceCache ?? new FileExistenceCache();
        _stickerEditor = stickerEditor ?? new StickerEditorViewModel(
            new StickerLibraryService(new AtomicJsonStore<StickerLibraryDocument>(StickerLibraryDocument.CurrentSchemaVersion)),
            new StickerTracksService(new AtomicJsonStore<StickerTracksDocument>(StickerTracksDocument.CurrentSchemaVersion)),
            filePicker,
            uiDispatcher);
        _overlayEditor = overlayEditor;
        if (_overlayState is not null)
        {
            EnableOverlayOnOutput = _overlayState.IsEnabled;
            UseRandomOverlayLibrary = _overlayState.UseRandomLibrarySource;
            _overlayState.Changed += OnOverlayStateChanged;
        }

        if (_overlayEditor is not null)
        {
            UseRandomOverlayLibrary = _overlayEditor.UseRandomMaskLibrary;
            _overlayEditor.PropertyChanged += OnOverlayEditorPropertyChanged;
        }

        OutputDirectory = RenderRequestFactory.DefaultOutputDirectory;
        OutputFileNamePrefix = "混剪成片-A";
        RandomSeed = Environment.TickCount;
        SelectedQuality = QualityPreset.Balanced;
        VariationIntensityPercent = 100;
        VariationEnableMirror = true;
        VariationEnableRotate = true;
        VariationEnableCrop = true;
        VariationEnableColor = true;
        VariationEnableDenoise = false;
        NewTemplateName = string.Empty;
        ActiveWorkspaceIndex = 0;
        RefreshOverlayStatus();
        RefreshQualityHint();
        RefreshPreview();
        _trackOutputDirectoryOverrides = true;
        _initialEffectTemplateLoadTask = LoadEffectTemplatesCoreAsync();
        _ = LoadSequenceTemplatesAsync();
        _ = RefreshAudioLibraryCountAsync();
    }

    public override WorkspaceModule ModuleKind => WorkspaceModule.Composition;

    public override string Title => "批量混剪";

    public StickerEditorViewModel StickerEditor => _stickerEditor;

    public ObservableCollection<MaterialRowViewModel> Materials { get; } = [];

    public ObservableCollection<PreviewPlanRowViewModel> PreviewPlans { get; } = [];

    public ObservableCollection<EffectVariationTemplate> EffectTemplatesList { get; } = [];

    [ObservableProperty]
    private MaterialRowViewModel? _selectedMaterial;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(SelectedTemplateDisplayName))]
    private EffectVariationTemplate? _selectedEffectTemplate;

    public int MaterialCount => Materials.Count;

    public bool HasMaterials => MaterialCount > 0;

    public string SelectedTemplateDisplayName =>
        SelectedEffectTemplate?.DisplayName ?? "（未选择）";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(MaterialCount))]
    [NotifyPropertyChangedFor(nameof(HasMaterials))]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    [NotifyCanExecuteChangedFor(nameof(ClearMaterialsCommand))]
    private int _importGeneration;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private CompositionMode _mode = CompositionMode.Random;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private string _sequenceExpression = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private int _batchCount = 1;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private int _randomSeed;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    [NotifyPropertyChangedFor(nameof(ClipsPerPlanHint))]
    private int? _clipsPerPlan;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    [NotifyPropertyChangedFor(nameof(HasValidationMessage))]
    private string _validationMessage = string.Empty;

    [ObservableProperty]
    private string _previewSummary = "导入素材后可在此预览拼接顺序与预计时长。";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanPickImportFiles))]
    private bool _isImporting;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasStatusMessage))]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private string _outputDirectory = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private string _outputFileNamePrefix = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    [NotifyPropertyChangedFor(nameof(IsLosslessQuality))]
    private QualityPreset _selectedQuality = QualityPreset.Balanced;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    private VideoProcessingMode _selectedProcessingMode = VideoProcessingMode.Auto;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    private OutputResolutionPreset _selectedOutputResolution = OutputResolutionPreset.Original;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    private OutputFrameRatePreset _selectedOutputFrameRate = OutputFrameRatePreset.Original;

    [ObservableProperty]
    private string _qualityHint = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    [NotifyPropertyChangedFor(nameof(IsDoubleScreenSettingsEnabled))]
    private bool _enableVariationEffects;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(VariationIntensityLabel))]
    [NotifyPropertyChangedFor(nameof(IsVariationIntensityEnabled))]
    [NotifyPropertyChangedFor(nameof(IsVariationItemSwitchesEnabled))]
    private int _variationIntensityPercent = 100;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsVariationItemSwitchesEnabled))]
    private bool _variationEnableMirror = true;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsVariationItemSwitchesEnabled))]
    private bool _variationEnableRotate = true;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsVariationItemSwitchesEnabled))]
    private bool _variationEnableCrop = true;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsVariationItemSwitchesEnabled))]
    private bool _variationEnableColor = true;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsVariationItemSwitchesEnabled))]
    private bool _variationEnableDenoise;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDoubleScreenStartEnabled))]
    [NotifyPropertyChangedFor(nameof(IsDoubleScreenSettingsEnabled))]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private bool _enableDoubleScreen;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private int _doubleScreenStartClipIndex = 1;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDoubleScreenRandomSettingsEnabled))]
    private bool _doubleScreenUseRandomCurrentFolder;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(DoubleScreenFeatherLabel))]
    private bool _doubleScreenFeatherEnabled = true;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(DoubleScreenFeatherLabel))]
    private int _doubleScreenFeatherPixels = DoubleScreenEffectPlan.DefaultFeatherPixels;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ActiveWorkspaceLabel))]
    [NotifyPropertyChangedFor(nameof(IsWorkspaceA))]
    [NotifyPropertyChangedFor(nameof(IsWorkspaceB))]
    private int _activeWorkspaceIndex;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    private bool _enableBgm;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasBgmPath))]
    private string _bgmPath = string.Empty;

    [ObservableProperty]
    private int _originalVolumePercent = 100;

    [ObservableProperty]
    private int _bgmVolumePercent = 18;

    // ── 音频库 ────────────────────────────────────────────────────────────

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    [NotifyPropertyChangedFor(nameof(AudioLibrarySwitchHint))]
    private bool _enableAudioLibrary;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(AudioLibrarySwitchHint))]
    private int _audioLibraryEntryCount;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsAudioFixedVolumeSectionVisible))]
    [NotifyPropertyChangedFor(nameof(AudioVolumeSummary))]
    private bool _enableAudioFixedVolume;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsAudioRandomVolumeSectionVisible))]
    [NotifyPropertyChangedFor(nameof(AudioVolumeSummary))]
    private bool _enableAudioRandomVolume;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(AudioVolumeSummary))]
    private double _audioFixedVolumePercent;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(AudioVolumeSummary))]
    private double _audioVolumeMinPercent = -50;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(AudioVolumeSummary))]
    private double _audioVolumeMaxPercent = 50;

    public string AudioLibrarySwitchHint =>
        EnableAudioLibrary
            ? $"已启用音频库（库内 {AudioLibraryEntryCount} 条，每个任务随机选取）"
            : "未启用音频库，将使用右侧单文件 BGM（如有）";

    public bool HasAudioLibrary => AudioLibraryEntryCount > 0;

    public bool IsAudioFixedVolumeSectionVisible => EnableAudioLibrary && EnableAudioFixedVolume;

    public bool IsAudioRandomVolumeSectionVisible => EnableAudioLibrary && EnableAudioRandomVolume;

    public string AudioVolumeSummary
    {
        get
        {
            if (!EnableAudioLibrary) return string.Empty;
            if (EnableAudioFixedVolume && EnableAudioRandomVolume)
                return $"音量：固定 {AudioFixedVolumePercent:+#;-#;0}%，随机 {AudioVolumeMinPercent:+#;-#;0}~{AudioVolumeMaxPercent:+#;-#;0}%；随机优先";
            if (EnableAudioFixedVolume)
                return $"音量：固定 {AudioFixedVolumePercent:+#;-#;0}%";
            if (EnableAudioRandomVolume)
                return $"音量：随机 {AudioVolumeMinPercent:+#;-#;0}~{AudioVolumeMaxPercent:+#;-#;0}%";
            return "音量：默认 18%";
        }
    }

    partial void OnEnableAudioLibraryChanged(bool value)
    {
        RefreshQualityHint();
        OnPropertyChanged(nameof(AudioVolumeSummary));
    }

    partial void OnAudioLibraryEntryCountChanged(int value)
    {
        OnPropertyChanged(nameof(HasAudioLibrary));
        OnPropertyChanged(nameof(AudioLibrarySwitchHint));
    }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsMainVolumeSectionEnabled))]
    [NotifyPropertyChangedFor(nameof(HasMainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainVolumeRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainVolumeRangeHint))]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    private bool _enableMainClipVolumeBoost;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsMainVolumeFixedMode))]
    [NotifyPropertyChangedFor(nameof(IsMainVolumeRandomMode))]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainVolumeFixedLabel))]
    [NotifyPropertyChangedFor(nameof(MainVolumeRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainVolumeRangeHint))]
    private MainMaterialBoostMode _mainVolumeMode = MainMaterialBoostMode.Fixed;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainVolumeFixedLabel))]
    [NotifyPropertyChangedFor(nameof(MainVolumeRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainVolumeRangeHint))]
    private double _mainVolumeFixedPercent = 105;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainVolumeMinLabel))]
    [NotifyPropertyChangedFor(nameof(MainVolumeRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainVolumeRangeHint))]
    private double _mainVolumeMinPercent = 100;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainVolumeMaxLabel))]
    [NotifyPropertyChangedFor(nameof(MainVolumeRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainVolumeRangeHint))]
    private double _mainVolumeMaxPercent = 110;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsMainScaleSectionEnabled))]
    [NotifyPropertyChangedFor(nameof(HasMainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainScaleRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainScaleRangeHint))]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    private bool _enableMainClipScale;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsMainScaleFixedMode))]
    [NotifyPropertyChangedFor(nameof(IsMainScaleRandomMode))]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainScaleFixedLabel))]
    [NotifyPropertyChangedFor(nameof(MainScaleRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainScaleRangeHint))]
    private MainMaterialBoostMode _mainScaleMode = MainMaterialBoostMode.Fixed;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainScaleFixedLabel))]
    [NotifyPropertyChangedFor(nameof(MainScaleRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainScaleRangeHint))]
    private double _mainScaleFixedPercent = 105;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainScaleMinLabel))]
    [NotifyPropertyChangedFor(nameof(MainScaleRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainScaleRangeHint))]
    private double _mainScaleMinPercent = 100;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(MainMaterialBoostSummary))]
    [NotifyPropertyChangedFor(nameof(MainScaleMaxLabel))]
    [NotifyPropertyChangedFor(nameof(MainScaleRangeHint))]
    [NotifyPropertyChangedFor(nameof(HasMainScaleRangeHint))]
    private double _mainScaleMaxPercent = 110;

    [ObservableProperty]
    private string _newTemplateName = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(OverlayStatusLabel))]
    [NotifyPropertyChangedFor(nameof(IsOverlaySectionEnabled))]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    [NotifyPropertyChangedFor(nameof(OverlayEffectPreviewText))]
    [NotifyPropertyChangedFor(nameof(HasOverlayEffectPreview))]
    private bool _enableOverlayOnOutput;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(UnifiedAspectPreviewDescription))]
    [NotifyPropertyChangedFor(nameof(IsCustomAspectPreset))]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private bool _enableUnifiedAspect;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(UnifiedAspectPreviewDescription))]
    [NotifyPropertyChangedFor(nameof(IsCustomAspectPreset))]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private OutputCanvasPreset _aspectPreset = OutputCanvasPreset.Vertical9x16;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(UnifiedAspectPreviewDescription))]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private int _customAspectWidth = 1080;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(UnifiedAspectPreviewDescription))]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private int _customAspectHeight = 1920;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(UnifiedAspectPreviewDescription))]
    private AspectFitMode _clipFitMode = AspectFitMode.CenterCrop;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(UnifiedAspectPreviewDescription))]
    private OverlayFitMode _overlayFitMode = OverlayFitMode.FillCrop;

    [ObservableProperty]
    private string _unifiedAspectPreviewDescription =
        UnifiedAspectPolicy.Disabled.BuildPreviewDescription();

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(OverlayStatusLabel))]
    private bool _useRandomOverlayLibrary;

    [ObservableProperty]
    private string _overlayStatusLabel = "已关闭 · 成片不含蒙版";

    public bool IsOverlaySectionEnabled => EnableOverlayOnOutput;

    public bool IsCustomAspectPreset => AspectPreset == OutputCanvasPreset.Custom;

    public bool HasBgmPath => !string.IsNullOrWhiteSpace(BgmPath);

    public bool IsMainVolumeSectionEnabled => EnableMainClipVolumeBoost;

    public bool IsMainScaleSectionEnabled => EnableMainClipScale;

    public bool IsMainVolumeFixedMode => MainVolumeMode == MainMaterialBoostMode.Fixed;

    public bool IsMainVolumeRandomMode => MainVolumeMode == MainMaterialBoostMode.Random;

    public bool IsMainScaleFixedMode => MainScaleMode == MainMaterialBoostMode.Fixed;

    public bool IsMainScaleRandomMode => MainScaleMode == MainMaterialBoostMode.Random;

    /// <summary>任一主素材增强开关开启时，面板顶部展示本次设置摘要。</summary>
    public bool HasMainMaterialBoostSummary => EnableMainClipVolumeBoost || EnableMainClipScale;

    public string MainVolumeFixedLabel => $"{MainVolumeFixedPercent:0.#}%";

    public string MainVolumeMinLabel => $"{MainVolumeMinPercent:0.#}%";

    public string MainVolumeMaxLabel => $"{MainVolumeMaxPercent:0.#}%";

    public string MainScaleFixedLabel => $"{MainScaleFixedPercent:0.#}%";

    public string MainScaleMinLabel => $"{MainScaleMinPercent:0.#}%";

    public string MainScaleMaxLabel => $"{MainScaleMaxPercent:0.#}%";

    /// <summary>启用后常驻摘要：固定值或随机区间。</summary>
    public string MainMaterialBoostSummary
    {
        get
        {
            if (!HasMainMaterialBoostSummary)
            {
                return "未启用";
            }

            var parts = new List<string>();
            if (EnableMainClipVolumeBoost)
            {
                parts.Add(MainVolumeMode == MainMaterialBoostMode.Fixed
                    ? $"音量固定 {MainVolumeFixedPercent:0.#}%"
                    : $"音量随机 {MainVolumeMinPercent:0.#}–{MainVolumeMaxPercent:0.#}%");
            }

            if (EnableMainClipScale)
            {
                parts.Add(MainScaleMode == MainMaterialBoostMode.Fixed
                    ? $"缩放固定 {MainScaleFixedPercent:0.#}%"
                    : $"缩放随机 {MainScaleMinPercent:0.#}–{MainScaleMaxPercent:0.#}%");
            }

            return string.Join(" · ", parts);
        }
    }

    public bool HasMainVolumeRangeHint => !string.IsNullOrEmpty(MainVolumeRangeHint);

    public string MainVolumeRangeHint => BuildBoostRangeHint(
        EnableMainClipVolumeBoost,
        MainVolumeMode,
        MainVolumeFixedPercent,
        MainVolumeMinPercent,
        MainVolumeMaxPercent,
        "音量");

    public bool HasMainScaleRangeHint => !string.IsNullOrEmpty(MainScaleRangeHint);

    public string MainScaleRangeHint => BuildBoostRangeHint(
        EnableMainClipScale,
        MainScaleMode,
        MainScaleFixedPercent,
        MainScaleMinPercent,
        MainScaleMaxPercent,
        "缩放");

    private static string BuildBoostRangeHint(
        bool enabled,
        MainMaterialBoostMode mode,
        double fixedPercent,
        double minPercent,
        double maxPercent,
        string label)
    {
        if (!enabled)
        {
            return string.Empty;
        }

        const double min = MainMaterialBoostPlan.MinPercent;
        const double max = MainMaterialBoostPlan.MaxPercent;

        if (mode == MainMaterialBoostMode.Fixed)
        {
            return fixedPercent is < min or > max
                ? $"拼接主素材{label}固定值必须在 {min}%–{max}% 之间。"
                : string.Empty;
        }

        if (minPercent is < min or > max || maxPercent is < min or > max)
        {
            return $"拼接主素材{label}随机区间必须在 {min}%–{max}% 之间。";
        }

        return minPercent > maxPercent
            ? $"拼接主素材{label}随机下限不能大于上限。"
            : string.Empty;
    }

    public bool IsLosslessQuality => SelectedQuality == QualityPreset.Lossless;

    public bool IsRandomMode => Mode == CompositionMode.Random;

    public bool IsCustomMode => Mode == CompositionMode.CustomSequence;

    public string ClipsPerPlanHint =>
        ClipsPerPlan.HasValue
            ? $"每条成片从 {_assets.Count} 个素材中随机抽取 {ClipsPerPlan.Value} 个"
            : $"每条成片使用全部 {_assets.Count} 个素材";

    public bool CanPickImportFiles => !IsImporting;

    public bool HasValidationMessage => !string.IsNullOrWhiteSpace(ValidationMessage);

    public bool HasStatusMessage => !string.IsNullOrWhiteSpace(StatusMessage);

    public bool IsVariationIntensityEnabled => EnableVariationEffects;

    public bool IsVariationItemSwitchesEnabled => EnableVariationEffects;

    public bool IsDoubleScreenStartEnabled => EnableVariationEffects && EnableDoubleScreen;

    public bool IsDoubleScreenSettingsEnabled => IsDoubleScreenStartEnabled;

    public bool IsDoubleScreenRandomSettingsEnabled =>
        IsDoubleScreenSettingsEnabled && DoubleScreenUseRandomCurrentFolder;

    public string DoubleScreenFeatherLabel =>
        DoubleScreenFeatherEnabled ? $"{DoubleScreenFeatherPixels} 像素" : "关闭";

    public string VariationIntensityLabel => $"强度 {VariationIntensityPercent}%";

    /// <summary>蒙版叠层效果预览说明（几何/透明度，非实时视频帧）。</summary>
    public string OverlayEffectPreviewText
    {
        get
        {
            if (!EnableOverlayOnOutput || _overlayState is null)
            {
                return "蒙版覆盖已关闭：成片不含蒙版层。";
            }

            var layers = _overlayState.Layers;
            if (layers.Count == 0)
            {
                return UseRandomOverlayLibrary
                    ? "每条成片将从素材库随机替换 1 个蒙版；若未配置轨道，使用默认红框参数（可在「蒙版」页预览/调整）。"
                    : "尚未配置蒙版层。请到「蒙版」页导入素材，或开启随机替换素材库。";
            }

            var strongest = layers.Max(l => l.Opacity);
            var lines = layers
                .OrderBy(l => l.ZIndex)
                .Take(3)
                .Select(l =>
                    $"「{l.Name}」区域 {l.Bounds.X:0.##},{l.Bounds.Y:0.##} · {l.Bounds.Width:0.##}×{l.Bounds.Height:0.##} · 透明 {l.Opacity:P0}"
                    + (l.TopFade > 0 ? $" · 上向渐变 {l.TopFade:0.##}" : string.Empty));
            var more = layers.Count > 3 ? $"；另有 {layers.Count - 3} 层…" : string.Empty;
            var warn = strongest >= 0.4
                ? " ⚠ 透明度偏高，成片可能明显盖住商品主体，建议在「蒙版」页调低或上移。"
                : " 默认偏上半区，下半商品区通常更干净；可在「蒙版」页拖拽蓝框预览位置。";
            return $"叠层预览（{layers.Count} 层）：{string.Join("；", lines)}{more}。{warn}";
        }
    }

    public bool HasOverlayEffectPreview => EnableOverlayOnOutput;

    [ObservableProperty]
    private string? _overlayCompositePreviewPath;

    [ObservableProperty]
    private string _overlayCompositePreviewHint = "开启蒙版并导入主片/蒙版后，将自动生成接近成片的叠层静帧。";

    public bool HasOverlayCompositePreview =>
        !string.IsNullOrWhiteSpace(OverlayCompositePreviewPath) && File.Exists(OverlayCompositePreviewPath);

    public bool IsWorkspaceA => ActiveWorkspaceIndex == 0;

    public bool IsWorkspaceB => ActiveWorkspaceIndex == 1;

    public string ActiveWorkspaceLabel =>
        ActiveWorkspaceIndex is >= 0 and < 2
            ? _workspaces[ActiveWorkspaceIndex].DisplayName
            : "商品组";

    partial void OnModeChanged(CompositionMode value)
    {
        OnPropertyChanged(nameof(IsRandomMode));
        OnPropertyChanged(nameof(IsCustomMode));
        RefreshPreview();
    }

    partial void OnSequenceExpressionChanged(string value) => RefreshPreview();

    partial void OnBatchCountChanged(int value) => RefreshPreview();

    partial void OnRandomSeedChanged(int value) => RefreshPreview();

    partial void OnClipsPerPlanChanged(int? value) => RefreshPreview();

    partial void OnSelectedQualityChanged(QualityPreset value) => RefreshQualityHint();

    partial void OnSelectedProcessingModeChanged(VideoProcessingMode value) => RefreshQualityHint();

    partial void OnSelectedOutputResolutionChanged(OutputResolutionPreset value) => RefreshQualityHint();

    partial void OnSelectedOutputFrameRateChanged(OutputFrameRatePreset value) => RefreshQualityHint();

    partial void OnEnableVariationEffectsChanged(bool value)
    {
        if (value && _activeEffectTemplate.Id == EffectTemplates.None.Id)
        {
            _activeEffectTemplate = EffectTemplates.StandardVariation();
            if (SelectedEffectTemplate is null || SelectedEffectTemplate.Id == EffectTemplates.None.Id)
            {
                SelectedEffectTemplate = EffectTemplatesList.FirstOrDefault(t => t.Id == _activeEffectTemplate.Id)
                    ?? _activeEffectTemplate;
            }

            VariationEnableMirror = true;
            VariationEnableRotate = true;
            VariationEnableCrop = true;
            VariationEnableColor = true;
            VariationEnableDenoise = false;
        }

        OnPropertyChanged(nameof(IsVariationIntensityEnabled));
        OnPropertyChanged(nameof(IsVariationItemSwitchesEnabled));
        OnPropertyChanged(nameof(IsDoubleScreenStartEnabled));
        OnPropertyChanged(nameof(IsDoubleScreenSettingsEnabled));
        OnPropertyChanged(nameof(IsDoubleScreenRandomSettingsEnabled));
        RefreshQualityHint();
    }

    partial void OnEnableDoubleScreenChanged(bool value)
    {
        OnPropertyChanged(nameof(IsDoubleScreenStartEnabled));
        OnPropertyChanged(nameof(IsDoubleScreenSettingsEnabled));
        OnPropertyChanged(nameof(IsDoubleScreenRandomSettingsEnabled));
        RefreshQualityHint();
    }

    partial void OnDoubleScreenUseRandomCurrentFolderChanged(bool value) => RefreshQualityHint();

    partial void OnDoubleScreenFeatherEnabledChanged(bool value) => RefreshQualityHint();

    partial void OnDoubleScreenFeatherPixelsChanged(int value) => RefreshQualityHint();

    partial void OnActiveWorkspaceIndexChanged(int value)
    {
        if (_suppressWorkspaceSwitch)
        {
            return;
        }

        var clamped = value is 0 or 1 ? value : 0;
        if (clamped != value)
        {
            _suppressWorkspaceSwitch = true;
            ActiveWorkspaceIndex = clamped;
            _suppressWorkspaceSwitch = false;
        }

        // CommunityToolkit 在赋值后才调用此回调；需用字段外的「先前索引」不好拿，
        // 因此在 SwitchWorkspaceCommand 中显式切换。此处仅刷新标签。
        OnPropertyChanged(nameof(ActiveWorkspaceLabel));
        OnPropertyChanged(nameof(IsWorkspaceA));
        OnPropertyChanged(nameof(IsWorkspaceB));
    }

    /// <summary>切换商品工作组（各组素材/编排独立，可分别入队并行渲染）。</summary>
    [RelayCommand]
    private void SwitchWorkspace(object? parameter)
    {
        var target = parameter switch
        {
            int i => i,
            string s when int.TryParse(s, out var parsed) => parsed,
            _ => -1
        };
        if (target is not (0 or 1) || target == ActiveWorkspaceIndex)
        {
            return;
        }

        SaveActiveWorkspace();
        _suppressWorkspaceSwitch = true;
        ActiveWorkspaceIndex = target;
        _suppressWorkspaceSwitch = false;
        LoadWorkspace(target);
        OnPropertyChanged(nameof(ActiveWorkspaceLabel));
        OnPropertyChanged(nameof(IsWorkspaceA));
        OnPropertyChanged(nameof(IsWorkspaceB));
        StatusMessage = $"已切换到 {_workspaces[target].DisplayName}（素材 {_assets.Count} 个）。";
    }

    private void SaveActiveWorkspace()
    {
        var slot = _workspaces[ActiveWorkspaceIndex];
        slot.Assets = _assets.ToList();
        slot.MaterialRows = Materials.ToList();
        slot.Mode = Mode;
        slot.SequenceExpression = SequenceExpression;
        slot.BatchCount = BatchCount;
        slot.RandomSeed = RandomSeed;
        slot.ClipsPerPlan = ClipsPerPlan;
        slot.OutputDirectory = OutputDirectory;
        slot.OutputFileNamePrefix = OutputFileNamePrefix;
        slot.OutputDirectoryUserOverride = _outputDirectoryUserOverride;
    }

    private void LoadWorkspace(int index)
    {
        var slot = _workspaces[index];
        _assets.Clear();
        _assets.AddRange(slot.Assets);
        Materials.Clear();
        foreach (var row in slot.MaterialRows)
        {
            Materials.Add(row);
        }

        _suppressOutputDirectoryOverrideTracking = true;
        Mode = slot.Mode;
        SequenceExpression = slot.SequenceExpression;
        BatchCount = slot.BatchCount;
        RandomSeed = slot.RandomSeed;
        ClipsPerPlan = slot.ClipsPerPlan;
        OutputDirectory = string.IsNullOrWhiteSpace(slot.OutputDirectory)
            ? RenderRequestFactory.DefaultOutputDirectory
            : slot.OutputDirectory;
        OutputFileNamePrefix = string.IsNullOrWhiteSpace(slot.OutputFileNamePrefix)
            ? (index == 0 ? "混剪成片-A" : "混剪成片-B")
            : slot.OutputFileNamePrefix;
        _outputDirectoryUserOverride = slot.OutputDirectoryUserOverride;
        _suppressOutputDirectoryOverrideTracking = false;

        ImportGeneration++;
        SelectedMaterial = Materials.FirstOrDefault();
        RefreshPreview();
        RefreshUnifiedAspectPreview();
        ScheduleOverlayCompositePreview();
        OnPropertyChanged(nameof(MaterialCount));
        OnPropertyChanged(nameof(HasMaterials));
    }

    partial void OnEnableBgmChanged(bool value) => RefreshQualityHint();

    partial void OnEnableMainClipVolumeBoostChanged(bool value) => RefreshQualityHint();

    partial void OnEnableMainClipScaleChanged(bool value) => RefreshQualityHint();

    partial void OnEnableOverlayOnOutputChanged(bool value)
    {
        if (_overlayState is not null)
        {
            if (_overlayState.IsEnabled != value)
            {
                _overlayState.SetEnabled(value);
            }
        }
        else
        {
            ScheduleOverlayCompositePreview();
        }

        RefreshOverlayStatus();
        RefreshQualityHint();
    }

    partial void OnUseRandomOverlayLibraryChanged(bool value)
    {
        if (_overlayState is not null)
        {
            if (_overlayState.UseRandomLibrarySource != value)
            {
                _overlayState.SetUseRandomLibrarySource(value);
            }
        }
        else
        {
            ScheduleOverlayCompositePreview();
        }

        if (_overlayEditor is not null && _overlayEditor.UseRandomMaskLibrary != value)
        {
            _overlayEditor.UseRandomMaskLibrary = value;
        }

        RefreshOverlayStatus();
    }

    partial void OnEnableUnifiedAspectChanged(bool value)
    {
        RefreshUnifiedAspectPreview();
        RefreshQualityHint();
    }

    partial void OnAspectPresetChanged(OutputCanvasPreset value)
    {
        OnPropertyChanged(nameof(IsCustomAspectPreset));
        // 统一比例 3:4：默认「先裁成画幅再覆盖」，避免 9:16 蒙版直接 FillCrop 进上半区错位。
        if (value == OutputCanvasPreset.Portrait3x4 &&
            OverlayFitMode is OverlayFitMode.FillCrop)
        {
            OverlayFitMode = OverlayFitMode.MatchCanvasCrop;
        }

        RefreshUnifiedAspectPreview();
    }

    partial void OnCustomAspectWidthChanged(int value) => RefreshUnifiedAspectPreview();

    partial void OnCustomAspectHeightChanged(int value) => RefreshUnifiedAspectPreview();

    partial void OnClipFitModeChanged(AspectFitMode value) => RefreshUnifiedAspectPreview();

    partial void OnOverlayFitModeChanged(OverlayFitMode value) => RefreshUnifiedAspectPreview();

    partial void OnSelectedEffectTemplateChanged(EffectVariationTemplate? value)
    {
        EffectTemplateRenameName = value?.DisplayName ?? string.Empty;
        OnPropertyChanged(nameof(CanManageSelectedEffectTemplate));
        RenameSelectedEffectTemplateCommand.NotifyCanExecuteChanged();
        DeleteSelectedEffectTemplateCommand.NotifyCanExecuteChanged();

        if (value is null)
        {
            return;
        }

        ApplyEffectTemplate(value);
    }

    private void RefreshUnifiedAspectPreview()
    {
        var (firstWidth, firstHeight) = ResolveFirstClipDimensions();
        var policy = BuildUnifiedAspectPolicy();
        UnifiedAspectPreviewDescription = policy.BuildPreviewDescription(firstWidth, firstHeight);
        SyncStickerPreviewCanvas(policy, firstWidth, firstHeight);
        EnqueueCommand.NotifyCanExecuteChanged();
    }

    private void SyncStickerPreviewCanvas(
        UnifiedAspectPolicy policy,
        int? firstWidth,
        int? firstHeight)
    {
        var (width, height) = ResolveCompositionCanvasPixels(policy, firstWidth, firstHeight);
        _stickerEditor.SyncCompositionCanvas(width, height);
    }

    private static (int Width, int Height) ResolveCompositionCanvasPixels(
        UnifiedAspectPolicy policy,
        int? firstWidth,
        int? firstHeight)
    {
        if (!policy.IsEnabled)
        {
            return (
                firstWidth is > 0 ? firstWidth.Value : 1080,
                firstHeight is > 0 ? firstHeight.Value : 1920);
        }

        return policy.Preset switch
        {
            OutputCanvasPreset.Vertical9x16 => (1080, 1920),
            OutputCanvasPreset.Horizontal16x9 => (1920, 1080),
            OutputCanvasPreset.Square1x1 => (1080, 1080),
            OutputCanvasPreset.Portrait3x4 => (1080, 1440),
            OutputCanvasPreset.Custom when policy.CustomWidth is > 0 && policy.CustomHeight is > 0 =>
                (policy.CustomWidth.Value, policy.CustomHeight.Value),
            _ => (
                firstWidth is > 0 ? firstWidth.Value : 1080,
                firstHeight is > 0 ? firstHeight.Value : 1920)
        };
    }

    private (int? Width, int? Height) ResolveFirstClipDimensions()
    {
        if (_assets.Count == 0)
        {
            return (null, null);
        }

        var info = _assets[0].Info;
        return info.RotationDegrees is 90 or 270
            ? (info.Height, info.Width)
            : (info.Width, info.Height);
    }

    private UnifiedAspectPolicy BuildUnifiedAspectPolicy() =>
        new(
            EnableUnifiedAspect,
            AspectPreset,
            CustomAspectWidth,
            CustomAspectHeight,
            ClipFitMode,
            OverlayFitMode);

    private void OnOverlayStateChanged()
    {
        if (_overlayState is null)
        {
            return;
        }

        if (EnableOverlayOnOutput != _overlayState.IsEnabled)
        {
            EnableOverlayOnOutput = _overlayState.IsEnabled;
        }

        if (_overlayEditor is not null)
        {
            if (_overlayEditor.UseRandomMaskLibrary != _overlayState.UseRandomLibrarySource)
            {
                _overlayEditor.UseRandomMaskLibrary = _overlayState.UseRandomLibrarySource;
            }

            if (UseRandomOverlayLibrary != _overlayEditor.UseRandomMaskLibrary)
            {
                UseRandomOverlayLibrary = _overlayEditor.UseRandomMaskLibrary;
            }
        }
        else if (UseRandomOverlayLibrary != _overlayState.UseRandomLibrarySource)
        {
            UseRandomOverlayLibrary = _overlayState.UseRandomLibrarySource;
        }

        RefreshOverlayStatus();
        RefreshQualityHint();
        OnPropertyChanged(nameof(OverlayEffectPreviewText));
        OnPropertyChanged(nameof(HasOverlayEffectPreview));
        ScheduleOverlayCompositePreview();
    }

    private void OnOverlayEditorPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (_overlayEditor is null)
        {
            return;
        }

        if (e.PropertyName == nameof(OverlayEditorViewModel.UseRandomMaskLibrary))
        {
            if (UseRandomOverlayLibrary != _overlayEditor.UseRandomMaskLibrary)
            {
                UseRandomOverlayLibrary = _overlayEditor.UseRandomMaskLibrary;
            }
        }
    }

    private void RefreshOverlayStatus()
    {
        if (_overlayState is null || !_overlayState.IsEnabled)
        {
            OverlayStatusLabel = "已关闭 · 成片不含蒙版";
            OnPropertyChanged(nameof(OverlayEffectPreviewText));
            return;
        }

        var useRandomForStatus = _overlayEditor?.UseRandomMaskLibrary ?? _overlayState.UseRandomLibrarySource;
        if (useRandomForStatus)
        {
            OverlayStatusLabel = _overlayState.HasLayers
                ? "已开启 · 每条成片随机替换 1 个素材库蒙版（沿用蒙版页当前选中轨道参数）"
                : "已开启 · 每条成片从素材库随机选取 1 个蒙版";
            OnPropertyChanged(nameof(OverlayEffectPreviewText));
            return;
        }

        OverlayStatusLabel = _overlayState.HasLayers
            ? $"已开启 · 将 {_overlayState.Layers.Count} 层蒙版叠加到成片"
            : "已开启 · 请先在蒙版页配置层，或开启随机替换素材库";
        OnPropertyChanged(nameof(OverlayEffectPreviewText));
    }

    /// <summary>从导航切换时刷新音频库条目计数（公开方法，供壳层调用）。</summary>
    public async Task RefreshAudioLibraryCountFromNavigationAsync() =>
        await RefreshAudioLibraryCountAsync().ConfigureAwait(false);

    /// <summary>刷新音频库条目计数（后台加载）。</summary>
    private async Task RefreshAudioLibraryCountAsync()
    {
        if (_audioLibraryService is null)
        {
            return;
        }

        try
        {
            var doc = await _audioLibraryService
                .LoadAsync(cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() => AudioLibraryEntryCount = doc.Entries.Count);
        }
        catch
        {
            // 音频库计数刷新失败不应阻塞混剪页工作
        }
    }

    /// <summary>生成主片首帧 + 蒙版半透明叠层的静帧预览。</summary>
    public Task RefreshOverlayCompositePreviewAsync()
    {
        CancelScheduledOverlayCompositePreview();
        var generation = Interlocked.Increment(ref _overlayPreviewGeneration);
        return RefreshOverlayCompositePreviewCoreAsync(generation, CancellationToken.None);
    }

    private void ScheduleOverlayCompositePreview()
    {
        var generation = Interlocked.Increment(ref _overlayPreviewGeneration);
        var cancellation = new CancellationTokenSource();
        CancellationTokenSource? previous;
        lock (_overlayPreviewSync)
        {
            previous = _overlayPreviewCancellation;
            _overlayPreviewCancellation = cancellation;
            previous?.Cancel();
        }

        _ = RefreshOverlayCompositePreviewAfterDelayAsync(generation, cancellation);
    }

    private void CancelScheduledOverlayCompositePreview()
    {
        CancellationTokenSource? cancellation;
        lock (_overlayPreviewSync)
        {
            cancellation = _overlayPreviewCancellation;
            _overlayPreviewCancellation = null;
            cancellation?.Cancel();
        }
    }

    private async Task RefreshOverlayCompositePreviewAfterDelayAsync(
        int generation,
        CancellationTokenSource cancellation)
    {
        try
        {
            await Task.Delay(OverlayPreviewDebounceMilliseconds, cancellation.Token).ConfigureAwait(false);
            await RefreshOverlayCompositePreviewCoreAsync(generation, cancellation.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
        {
            // A newer overlay change superseded this preview request.
        }
        finally
        {
            lock (_overlayPreviewSync)
            {
                if (ReferenceEquals(_overlayPreviewCancellation, cancellation))
                {
                    _overlayPreviewCancellation = null;
                }
            }

            cancellation.Dispose();
        }
    }

    private async Task RefreshOverlayCompositePreviewCoreAsync(int generation, CancellationToken cancellationToken)
    {
        string? output = null;
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!EnableOverlayOnOutput || _frameExtractor is null || _overlayState is null)
            {
                ApplyOverlayCompositePreview(null, "开启「启用蒙版叠加」并导入主片/蒙版后可看合成静帧。", generation);
                return;
            }

            var baseAsset = _assets.FirstOrDefault(a => File.Exists(a.Path));
            var overlayLayer = _overlayState.Layers
                // ":self:" 不是外部文件；它会由预览/成片的主轨 split 提供，不能用 File.Exists 过滤掉。
                .Where(l => l.IsSelfSource || File.Exists(l.SourcePath))
                .OrderBy(l => l.ZIndex)
                .FirstOrDefault();

            if (baseAsset is null)
            {
                ApplyOverlayCompositePreview(null, "请先导入主片素材，再生成叠层静帧预览。", generation);
                return;
            }

            if (overlayLayer is null)
            {
                ApplyOverlayCompositePreview(null, "请先在「蒙版」页导入蒙版素材（或等待随机库在渲染时选取）。", generation);
                return;
            }

            output = Path.Combine(
                GetOverlayPreviewDirectory(),
                $"composition-composite-{_overlayPreviewSessionId}-{generation}.jpg");
            var request = new OverlayCompositePreviewRequest(
                baseAsset.Path,
                overlayLayer,
                output,
                216,
                384);

            var result = await _frameExtractor
                .ExtractOverlayCompositePreviewAsync(request, cancellationToken)
                .ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();

            if (result.IsSuccess)
            {
                ApplyOverlayCompositePreview(
                    result.Value,
                    "接近成片的叠层静帧（主片首帧 + 蒙版半透明）。默认蒙版偏弱，避免盖死商品；非实时视频。",
                    generation);
            }
            else
            {
                TryDeleteOverlayCompositePreview(output);
                ApplyOverlayCompositePreview(null, $"合成预览失败：{result.Error}", generation);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            TryDeleteOverlayCompositePreview(output);
        }
        catch (Exception ex)
        {
            TryDeleteOverlayCompositePreview(output);
            ApplyOverlayCompositePreview(null, $"合成预览失败：{ex.GetBaseException().Message}", generation);
        }
    }

    private void ApplyOverlayCompositePreview(string? path, string hint, int generation)
    {
        if (generation != Volatile.Read(ref _overlayPreviewGeneration))
        {
            TryDeleteOverlayCompositePreview(path);
            return;
        }

        _uiDispatcher.Invoke(() =>
        {
            if (generation != Volatile.Read(ref _overlayPreviewGeneration))
            {
                TryDeleteOverlayCompositePreview(path);
                return;
            }

            var previousPath = OverlayCompositePreviewPath;
            OverlayCompositePreviewPath = path;
            OverlayCompositePreviewHint = hint;
            OnPropertyChanged(nameof(HasOverlayCompositePreview));
            if (!string.Equals(previousPath, path, StringComparison.OrdinalIgnoreCase))
            {
                TryDeleteOverlayCompositePreview(previousPath);
            }
        });
    }

    private static string GetOverlayPreviewDirectory() =>
        Path.Combine(Path.GetTempPath(), "JingXu", "overlay-preview");

    private static void TryDeleteOverlayCompositePreview(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        try
        {
            var previewDirectory = Path.GetFullPath(GetOverlayPreviewDirectory())
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var fullPath = Path.GetFullPath(path);
            if (!fullPath.StartsWith(previewDirectory, StringComparison.OrdinalIgnoreCase) ||
                !Path.GetFileName(fullPath).StartsWith("composition-composite-", StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(Path.GetExtension(fullPath), ".jpg", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            if (File.Exists(fullPath))
            {
                File.Delete(fullPath);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
        {
            // A locked or already removed preview is safe to leave for cache cleanup.
        }
    }

    /// <summary>清空当前商品组内全部素材与预览计划，便于接着做下一商品（不影响另一组与已入队任务）。</summary>
    [RelayCommand(CanExecute = nameof(HasMaterials))]
    private void ClearMaterials()
    {
        _assets.Clear();
        Materials.Clear();
        SelectedMaterial = null;
        _executablePlans = [];
        PreviewPlans.Clear();
        ValidationMessage = string.Empty;
        ImportGeneration++;
        OnPropertyChanged(nameof(MaterialCount));
        OnPropertyChanged(nameof(HasMaterials));
        ClearMaterialsCommand.NotifyCanExecuteChanged();
        EnqueueCommand.NotifyCanExecuteChanged();
        RefreshPreview();
        RefreshUnifiedAspectPreview();
        ScheduleOverlayCompositePreview();
        StatusMessage = $"已清空 {ActiveWorkspaceLabel} 的素材，可导入下一商品或切换另一商品组。";
    }

    private void RefreshQualityHint()
    {
        var outputVideoSettings = BuildOutputVideoSettings();
        const string gpuScopeHint = "GPU 只加速最终编码；蒙版、羽化和贴纸仍由 CPU 计算。";
        var processingHint = DescribeProcessingMode(SelectedProcessingMode);
        if (SelectedQuality != QualityPreset.Lossless)
        {
            var qualityHint = SelectedQuality switch
            {
                QualityPreset.High => "高质量：CRF 18、AAC 192 kbps、x264 preset=fast。",
                QualityPreset.Balanced => "平衡（默认）：CRF 22、AAC 160 kbps、x264 preset=faster、-threads 0。",
                QualityPreset.Small => "小体积：CRF 27、AAC 128 kbps、x264 preset=veryfast。",
                QualityPreset.Fast => "快速预览：CRF 26、AAC 128 kbps、x264 preset=ultrafast（画质换速度）。",
                _ => string.Empty
            };
            QualityHint = outputVideoSettings.RequiresTranscode
                ? $"{qualityHint} 导出规格：{DescribeOutputVideoSettings(outputVideoSettings)}；将重新编码。{processingHint}。{gpuScopeHint}"
                : $"{qualityHint} {processingHint}。{gpuScopeHint}";
            return;
        }

        var blockers = new List<string>();
        if (EnableUnifiedAspect)
        {
            blockers.Add("统一比例");
        }

        if (EnableVariationEffects)
        {
            blockers.Add("差异化滤镜");
        }

        if (EnableOverlayOnOutput)
        {
            blockers.Add("蒙版");
        }

        if (EnableAudioLibrary && HasAudioLibrary)
        {
            blockers.Add("音频库");
        }
        else if (EnableBgm && HasBgmPath)
        {
            blockers.Add("BGM");
        }

        if (EnableMainClipVolumeBoost || EnableMainClipScale)
        {
            blockers.Add("主素材音量/缩放");
        }

        if (!outputVideoSettings.IsOriginalResolution)
        {
            blockers.Add($"导出分辨率 {DescribeOutputResolution(outputVideoSettings.Resolution)}");
        }

        if (!outputVideoSettings.IsOriginalFrameRate)
        {
            blockers.Add($"导出帧率 {DescribeOutputFrameRate(outputVideoSettings.FrameRate)}");
        }

        QualityHint = blockers.Count == 0
            ? $"无损直拷：仅在无画幅变化、滤镜、贴纸、蒙版、字幕或音频混合，且流结构兼容时可用。{processingHint}；直拷时不启用编码器。"
            : $"已启用 {string.Join("、", blockers)}，将强制重新编码（无法无损直拷）。{processingHint}。{gpuScopeHint}";
    }

    [RelayCommand]
    private async Task PickImportFilesAsync()
    {
        try
        {
            var paths = _filePicker.PickVideoFiles();
            if (paths is null || paths.Count == 0)
            {
                return;
            }

            await ImportFilesAsync(paths).ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            // 文件对话框或后续链路异常不得闪退。
            _uiDispatcher.Invoke(() => StatusMessage = $"导入失败：{ToChineseImportError(ex)}");
        }
    }

    [RelayCommand]
    private async Task ImportFilesAsync(IReadOnlyList<string>? paths)
    {
        if (paths is null || paths.Count == 0)
        {
            return;
        }

        _uiDispatcher.Invoke(() =>
        {
            IsImporting = true;
            StatusMessage = "正在探测素材…";
        });

        try
        {
            var outcomes = await CompositionOrchestrator.ImportAsync(_probe, paths, CancellationToken.None)
                .ConfigureAwait(false);

            _uiDispatcher.Invoke(() => ApplyImportOutcomes(paths.Count, outcomes));
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() => StatusMessage = $"导入失败：{ToChineseImportError(ex)}");
        }
        finally
        {
            _uiDispatcher.Invoke(() => IsImporting = false);
        }
    }

    private void ApplyImportOutcomes(int requestedCount, IReadOnlyList<MediaImportOutcome> outcomes)
    {
        var successCount = 0;
        foreach (var outcome in outcomes)
        {
            if (outcome.Asset is not null)
            {
                _assets.Add(outcome.Asset);
                successCount++;
            }

            Materials.Add(CreateMaterialRow(outcome));
        }

        ImportGeneration++;
        StatusMessage = successCount == requestedCount
            ? $"已导入 {requestedCount} 个文件。"
            : $"已处理 {requestedCount} 个文件，成功 {successCount} 个。";

        ApplyDefaultOutputDirectoryFromAssets();

        // 先选中再通知壳层；ListBox 可能在布局后清掉选中，故再投递一次恢复。
        var preferred = Materials.FirstOrDefault(m => m.HasValidAsset);
        SelectedMaterial = preferred;
        RefreshUnifiedAspectPreview();
        RefreshPreview();
        ScheduleOverlayCompositePreview();

        if (preferred is not null)
        {
            _uiDispatcher.Post(() =>
            {
                if (SelectedMaterial is null)
                {
                    SelectedMaterial = preferred;
                }
            });
        }
    }

    partial void OnOutputDirectoryChanged(string value)
    {
        if (_trackOutputDirectoryOverrides && !_suppressOutputDirectoryOverrideTracking)
        {
            _outputDirectoryUserOverride = true;
        }
    }

    private void ApplyDefaultOutputDirectoryFromAssets()
    {
        if (_outputDirectoryUserOverride || _assets.Count == 0)
        {
            return;
        }

        _suppressOutputDirectoryOverrideTracking = true;
        try
        {
            OutputDirectory = RenderRequestFactory.ResolveDefaultOutputDirectory(
                _assets.Select(a => a.Path));
        }
        finally
        {
            _suppressOutputDirectoryOverrideTracking = false;
        }
    }

    [RelayCommand]
    private void SelectMaterial(MaterialRowViewModel? material)
    {
        if (material is null || !material.HasValidAsset)
        {
            return;
        }

        SelectedMaterial = material;
    }

    partial void OnSelectedMaterialChanged(MaterialRowViewModel? value)
    {
        foreach (var row in Materials)
        {
            row.IsSelected = row == value;
        }
    }

    private static string ToChineseImportError(Exception ex)
    {
        var message = ex.GetBaseException().Message;
        return string.IsNullOrWhiteSpace(message) ? "未知错误，请查看日志。" : message;
    }

    [RelayCommand]
    private void PickOutputDirectory()
    {
        var picked = _outputFolderPicker.PickOutputFolder();
        if (!string.IsNullOrWhiteSpace(picked))
        {
            OutputDirectory = picked;
        }
    }

    [RelayCommand]
    private void PickBgmFile()
    {
        var picked = _filePicker.PickAudioFile();
        if (!string.IsNullOrWhiteSpace(picked))
        {
            BgmPath = picked;
            EnableBgm = true;
            RefreshQualityHint();
        }
    }

    [RelayCommand]
    private void ClearBgm()
    {
        BgmPath = string.Empty;
        EnableBgm = false;
        RefreshQualityHint();
    }

    [RelayCommand]
    private async Task LoadEffectTemplatesAsync()
    {
        await _initialEffectTemplateLoadTask.ConfigureAwait(false);
        await LoadEffectTemplatesCoreAsync().ConfigureAwait(false);
    }

    private async Task LoadEffectTemplatesCoreAsync()
    {
        if (_templateService is null)
        {
            SeedBuiltinTemplates();
            return;
        }

        try
        {
            var document = await _templateService.LoadAsync(cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() => ApplyTemplateDocument(document));
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
            {
                SeedBuiltinTemplates();
                StatusMessage = $"加载效果模板失败，已使用内置模板：{ex.GetBaseException().Message}";
            });
        }
    }

    [RelayCommand]
    private void ApplySelectedTemplate()
    {
        if (SelectedEffectTemplate is null)
        {
            return;
        }

        ApplyEffectTemplate(SelectedEffectTemplate);
        StatusMessage = $"已应用效果模板「{SelectedEffectTemplate.DisplayName}」。";
    }

    [RelayCommand]
    private async Task SaveEffectTemplateAsync()
    {
        var name = NewTemplateName.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            ValidationMessage = "请输入要保存的模板名称。";
            return;
        }

        if (_templateService is null)
        {
            ValidationMessage = "效果模板服务未装配。";
            return;
        }

        await _initialEffectTemplateLoadTask.ConfigureAwait(false);

        var id = "user-" + Guid.NewGuid().ToString("N")[..12];
        var baseTemplate = EnableVariationEffects
            ? (_activeEffectTemplate.Id == EffectTemplates.None.Id
                ? EffectTemplates.StandardVariation()
                : _activeEffectTemplate)
            : EffectTemplates.None;

        var created = EffectVariationTemplate.Create(
            id,
            name,
            baseTemplate.EnableMirror && VariationEnableMirror,
            VariationEnableCrop ? baseTemplate.MinCropPercent : 0,
            VariationEnableCrop ? baseTemplate.MaxCropPercent : 0,
            VariationEnableColor ? baseTemplate.MinBrightness : 0,
            VariationEnableColor ? baseTemplate.MaxBrightness : 0,
            VariationEnableColor ? baseTemplate.MinContrast : 1,
            VariationEnableColor ? baseTemplate.MaxContrast : 1,
            VariationEnableColor ? baseTemplate.MinSaturation : 1,
            VariationEnableColor ? baseTemplate.MaxSaturation : 1,
            VariationEnableDenoise ? baseTemplate.MinDenoise : 0,
            VariationEnableDenoise ? baseTemplate.MaxDenoise : 0,
            baseTemplate.EnableMetadataClearing,
            enableRotate: baseTemplate.EnableRotate && VariationEnableRotate,
            minRotationDegrees: VariationEnableRotate ? baseTemplate.MinRotationDegrees : 0,
            maxRotationDegrees: VariationEnableRotate ? baseTemplate.MaxRotationDegrees : 0);

        if (!created.IsSuccess)
        {
            ValidationMessage = created.Error ?? "无法创建效果模板。";
            return;
        }

        var stickerTracksResult = _stickerEditor.TryBuildTracks();
        if (!stickerTracksResult.IsSuccess || stickerTracksResult.Value is null)
        {
            ValidationMessage = stickerTracksResult.Error ?? "贴纸轨道参数无效。";
            return;
        }

        var userTemplates = EffectTemplatesList
            .Where(t => t.Id is not ("none" or "standard-variation") && t.Id != id)
            .Append(created.Value!)
            .ToArray();

        var settingsByTemplateId = new Dictionary<string, EffectTemplateSettingsDto>(
            _effectTemplateSettingsById,
            StringComparer.Ordinal)
        {
            [id] = CreateTemplateSettings(stickerTracksResult.Value)
        };

        var document = new EffectTemplateDocument
        {
            Templates =
            [
                EffectTemplates.None,
                EffectTemplates.StandardVariation(),
                .. userTemplates
            ],
            SettingsByTemplateId = settingsByTemplateId
        };

        try
        {
            await _templateService.SaveAsync(document, cancellationToken: CancellationToken.None)
                .ConfigureAwait(true);
            ApplyTemplateDocument(document);
            SelectedEffectTemplate = EffectTemplatesList.FirstOrDefault(t => t.Id == id);
            NewTemplateName = string.Empty;
            StatusMessage = $"已保存效果模板「{name}」。";
            ValidationMessage = string.Empty;
        }
        catch (Exception ex)
        {
            ValidationMessage = $"保存效果模板失败：{ex.GetBaseException().Message}";
        }
    }

    private void SeedBuiltinTemplates()
    {
        EffectTemplatesList.Clear();
        EffectTemplatesList.Add(EffectTemplates.None);
        EffectTemplatesList.Add(EffectTemplates.StandardVariation());
        if (SelectedEffectTemplate is null)
        {
            SelectedEffectTemplate = EffectTemplates.None;
        }
    }

    private void ApplyTemplateDocument(EffectTemplateDocument document)
    {
        _effectTemplateSettingsById.Clear();
        foreach (var (templateId, settings) in document.SettingsByTemplateId
                     ?? new Dictionary<string, EffectTemplateSettingsDto>(StringComparer.Ordinal))
        {
            if (!string.IsNullOrWhiteSpace(templateId) && settings is not null)
            {
                _effectTemplateSettingsById[templateId] = settings;
            }
        }

        foreach (var (templateId, sticker) in document.StickersByTemplateId
                     ?? new Dictionary<string, StickerTemplateDto>(StringComparer.Ordinal))
        {
            if (_effectTemplateSettingsById.ContainsKey(templateId) || sticker is null)
            {
                continue;
            }

            _effectTemplateSettingsById[templateId] = new EffectTemplateSettingsDto
            {
                StickerTracks =
                [
                    new StickerTrackTemplateDto
                    {
                        Name = "贴纸 1",
                        Path = sticker.Path,
                        X = sticker.X,
                        Y = sticker.Y,
                        Width = sticker.Width,
                        Height = sticker.Height,
                        Opacity = sticker.Opacity
                    }
                ]
            };
        }

        EffectTemplatesList.Clear();
        foreach (var template in document.Templates)
        {
            EffectTemplatesList.Add(template);
        }

        if (EffectTemplatesList.Count == 0)
        {
            SeedBuiltinTemplates();
            return;
        }

        var preferredId = SelectedEffectTemplate?.Id;
        SelectedEffectTemplate = EffectTemplatesList.FirstOrDefault(t => t.Id == preferredId)
            ?? EffectTemplatesList[0];
    }

    private void ApplyEffectTemplate(EffectVariationTemplate template)
    {
        _activeEffectTemplate = template;
        EnableVariationEffects = !IsEffectivelyNone(template);
        SyncVariationItemSwitchesFromTemplate(template);
        if (_effectTemplateSettingsById.TryGetValue(template.Id, out var settings))
        {
            VariationIntensityPercent = Math.Clamp(settings.VariationIntensityPercent, 1, 200);
            ApplyStickerTrackTemplate(settings.StickerTracks ?? []);
        }

        RefreshQualityHint();
    }

    private EffectTemplateSettingsDto CreateTemplateSettings(IReadOnlyList<StickerTrack> tracks) =>
        new()
        {
            VariationIntensityPercent = Math.Clamp(VariationIntensityPercent, 1, 200),
            StickerTracks = tracks.Select(track => new StickerTrackTemplateDto
            {
                Name = track.Name,
                Path = track.SourcePath,
                X = track.Bounds.X,
                Y = track.Bounds.Y,
                Width = track.Bounds.Width,
                Height = track.Bounds.Height,
                Opacity = track.Opacity,
                RotationDegrees = track.RotationDegrees,
                IsEnabled = track.IsEnabled,
                FixedAspectRatio = track.FixedAspectRatio
            }).ToArray()
        };

    private void ApplyStickerTrackTemplate(IReadOnlyList<StickerTrackTemplateDto> snapshots)
    {
        var tracks = new List<StickerTrack>(snapshots.Count);
        foreach (var snapshot in snapshots)
        {
            var created = StickerTrack.Create(
                string.IsNullOrWhiteSpace(snapshot.Name) ? $"贴纸 {tracks.Count + 1}" : snapshot.Name,
                snapshot.Path,
                snapshot.X,
                snapshot.Y,
                snapshot.Width,
                snapshot.Height,
                snapshot.Opacity,
                snapshot.RotationDegrees,
                snapshot.IsEnabled,
                snapshot.FixedAspectRatio);
            if (!created.IsSuccess || created.Value is null)
            {
                ValidationMessage = $"效果模板中的贴纸参数无效：{created.Error}";
                return;
            }

            tracks.Add(created.Value);
        }

        _stickerEditor.ReplaceTracks(tracks);
    }

    private void SyncVariationItemSwitchesFromTemplate(EffectVariationTemplate template)
    {
        VariationEnableMirror = template.EnableMirror;
        VariationEnableRotate = template.EnableRotate
            && (Math.Abs(template.MinRotationDegrees) > 0.0001
                || Math.Abs(template.MaxRotationDegrees) > 0.0001);
        VariationEnableCrop = template.MaxCropPercent > 0;
        VariationEnableColor =
            Math.Abs(template.MinBrightness) > 0.0001
            || Math.Abs(template.MaxBrightness) > 0.0001
            || Math.Abs(template.MinContrast - 1) > 0.0001
            || Math.Abs(template.MaxContrast - 1) > 0.0001
            || Math.Abs(template.MinSaturation - 1) > 0.0001
            || Math.Abs(template.MaxSaturation - 1) > 0.0001;
        VariationEnableDenoise = template.MaxDenoise > 0;
    }

    private static bool IsEffectivelyNone(EffectVariationTemplate template) =>
        template.Id == EffectTemplates.None.Id
        || (!template.EnableMirror
            && !template.EnableRotate
            && template.MaxCropPercent <= 0
            && !template.EnableMetadataClearing
            && Math.Abs(template.MinBrightness) < 0.0001
            && Math.Abs(template.MaxBrightness) < 0.0001
            && Math.Abs(template.MinContrast - 1) < 0.0001
            && Math.Abs(template.MaxContrast - 1) < 0.0001
            && Math.Abs(template.MinSaturation - 1) < 0.0001
            && Math.Abs(template.MaxSaturation - 1) < 0.0001
            && template.MaxDenoise <= 0);

    private List<ImageSticker> TryBuildStickersForPlan(
        CompositionPlan plan,
        long planOrdinal,
        out string? error)
    {
        error = null;
        var selectionSeed = _stickerEditor.UseRandomStickerLibrary
            ? _randomLibrarySelectionSeed
            : plan.Seed;
        var tracksResult = _stickerEditor.TryBuildEnabledTracksForPlan(selectionSeed, planOrdinal);
        if (!tracksResult.IsSuccess || tracksResult.Value is null)
        {
            error = tracksResult.Error ?? "贴纸轨道参数无效。";
            return [];
        }

        var tracks = tracksResult.Value;
        if (tracks.Count == 0)
        {
            return [];
        }

        var stickers = new List<ImageSticker>(tracks.Count);
        foreach (var track in tracks)
        {
            if (string.IsNullOrWhiteSpace(track.SourcePath) || !File.Exists(track.SourcePath))
            {
                error = $"贴纸文件不存在：{track.SourcePath}";
                return [];
            }

            var sticker = track.ToImageSticker();
            if (sticker is null)
            {
                error = $"贴纸参数无效：{track.Name}";
                return [];
            }

            stickers.Add(sticker);
        }

        return stickers;
    }

    [RelayCommand(CanExecute = nameof(CanEnqueue))]
    private async Task EnqueueAsync()
    {
        if (_executablePlans.Count == 0)
        {
            return;
        }

        ValidationMessage = string.Empty;
        StatusMessage = string.Empty;
        try
        {
            await EnqueueCoreAsync().ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            ValidationMessage = $"加入队列失败：{ex.GetBaseException().Message}";
        }
    }

    private async Task EnqueueCoreAsync()
    {
        var libraryEntries = Array.Empty<OverlayLibraryEntry>();
        if (_overlayState?.IsEnabled == true && _overlayLibraryService is not null)
        {
            var document = await _overlayLibraryService
                .LoadAsync(cancellationToken: CancellationToken.None)
                .ConfigureAwait(true);
            libraryEntries = document.Entries.ToArray();
        }

        if (_overlayState is not null)
        {
            var overlayValidation = OverlayEnqueueResolver.ValidateForEnqueue(
                _overlayState,
                libraryEntries.Length,
                libraryEntries);
            if (overlayValidation is not null)
            {
                ValidationMessage = overlayValidation;
                return;
            }
        }

        var effectTemplate = EnableVariationEffects
            ? ResolveActiveEffectTemplate()
            : null;

        DoubleScreenEffectPlan? doubleScreen = null;
        if (EnableVariationEffects && EnableDoubleScreen)
        {
            var doubleScreenResult = DoubleScreenEffectPlan.Create(
                DoubleScreenStartClipIndex,
                sourceMode: DoubleScreenUseRandomCurrentFolder
                    ? DoubleScreenSourceMode.RandomCurrentFolder
                    : DoubleScreenSourceMode.CurrentClip,
                placementMode: DoubleScreenPlacementMode.Random,
                featherEnabled: DoubleScreenFeatherEnabled,
                featherPixels: DoubleScreenFeatherPixels);
            var maximumStartIndex = _executablePlans.Count == 0
                ? 0
                : _executablePlans.Min(static plan => plan.Clips.Count);
            if (!doubleScreenResult.IsSuccess || DoubleScreenStartClipIndex > maximumStartIndex)
            {
                ValidationMessage = maximumStartIndex > 0
                    ? $"双屏起始视频必须在 1 到 {maximumStartIndex} 之间。"
                    : doubleScreenResult.Error ?? "双屏起始视频无效。";
                return;
            }

            doubleScreen = doubleScreenResult.Value;
        }

        // 单文件 BGM（音频库关闭时的后备）
        BgmMixPlan? bgm = null;
        if (EnableBgm && !string.IsNullOrWhiteSpace(BgmPath))
        {
            var bgmResult = BgmMixPlan.Create(
                BgmPath,
                originalVolume: OriginalVolumePercent / 100.0,
                bgmVolume: BgmVolumePercent / 100.0);
            if (!bgmResult.IsSuccess)
            {
                ValidationMessage = bgmResult.Error ?? "BGM 参数无效。";
                return;
            }

            bgm = bgmResult.Value;
        }

        // 音频库：优先于单文件 BGM
        var audioLibraryEntries = Array.Empty<AudioLibraryEntry>();
        if (EnableAudioLibrary && _audioLibraryService is not null)
        {
            // 入队前先清理失效文件，再加载有效条目
            var (doc, _) = await _audioLibraryService
                .PruneMissingAsync(cache: _fileExistenceCache, cancellationToken: CancellationToken.None)
                .ConfigureAwait(true);
            audioLibraryEntries = doc.Entries.ToArray();
            _uiDispatcher.Invoke(() => AudioLibraryEntryCount = doc.Entries.Count);
        }

        MainMaterialBoostPlan? mainBoost = null;
        if (EnableMainClipVolumeBoost || EnableMainClipScale)
        {
            var volumeMin = MainVolumeMode == MainMaterialBoostMode.Fixed
                ? MainVolumeFixedPercent
                : MainVolumeMinPercent;
            var volumeMax = MainVolumeMode == MainMaterialBoostMode.Fixed
                ? MainVolumeFixedPercent
                : MainVolumeMaxPercent;
            var scaleMin = MainScaleMode == MainMaterialBoostMode.Fixed
                ? MainScaleFixedPercent
                : MainScaleMinPercent;
            var scaleMax = MainScaleMode == MainMaterialBoostMode.Fixed
                ? MainScaleFixedPercent
                : MainScaleMaxPercent;

            var boostResult = MainMaterialBoostPlan.Create(
                EnableMainClipVolumeBoost,
                MainVolumeMode,
                volumeMin,
                volumeMax,
                EnableMainClipScale,
                MainScaleMode,
                scaleMin,
                scaleMax);
            if (!boostResult.IsSuccess)
            {
                ValidationMessage = boostResult.Error ?? "主素材音量/缩放参数无效。";
                return;
            }

            mainBoost = boostResult.Value;
        }

        if (_stickerEditor.UseRandomStickerLibrary)
        {
            await _stickerEditor.EnsureLibraryLoadedAsync().ConfigureAwait(true);
        }

        // 两类素材各自维护跨商品、跨多次入队的抽取序号，避免重新从第 0 个素材开始，
        // 同时不会因临时关闭另一类随机功能而跳过本素材库中的条目。
        var stickerSelectionStartOrdinal = _nextRandomStickerSelectionOrdinal;
        var maskSelectionStartOrdinal = _nextRandomMaskSelectionOrdinal;
        var useRandomMaskSelection = _overlayState?.IsEnabled == true
            && (_overlayEditor?.UseRandomMaskLibrary ?? _overlayState.UseRandomLibrarySource);

        var stickersPerPlan = new IReadOnlyList<ImageSticker>[_executablePlans.Count];
        for (var i = 0; i < _executablePlans.Count; i++)
        {
            var planStickers = TryBuildStickersForPlan(
                _executablePlans[i],
                stickerSelectionStartOrdinal + i,
                out var stickerError);
            if (stickerError is not null)
            {
                ValidationMessage = stickerError;
                return;
            }

            stickersPerPlan[i] = planStickers;
        }

        // 音频库：预生成每计划的独立 BGM
        var bgmPerPlan = new List<BgmMixPlan>(_executablePlans.Count);
        var useAudioLibrary = EnableAudioLibrary && audioLibraryEntries.Length > 0;
        if (useAudioLibrary)
        {
            var audioSeed = _audioLibrarySeed;
            for (var i = 0; i < _executablePlans.Count; i++)
            {
                var entry = AudioLibraryEntryResolver.Resolve(
                    audioLibraryEntries,
                    audioSeed,
                    _nextRandomAudioSelectionOrdinal + i,
                    _fileExistenceCache);

                if (entry is not null)
                {
                    var volMode = EnableAudioRandomVolume
                        ? AudioVolumeMode.RandomRange
                        : EnableAudioFixedVolume
                            ? AudioVolumeMode.Fixed
                            : AudioVolumeMode.Default;
                    var mixPlan = AudioLibraryEntryResolver.Materialize(
                        entry,
                        volMode,
                        AudioFixedVolumePercent,
                        AudioVolumeMinPercent,
                        AudioVolumeMaxPercent,
                        audioSeed,
                        _nextRandomAudioSelectionOrdinal + i);
                    bgmPerPlan.Add(mixPlan.ToBgmMixPlan());
                }
            }
        }

        var overlayLayersPerPlan = new IReadOnlyList<OverlayLayer>[_executablePlans.Count];
        for (var i = 0; i < _executablePlans.Count; i++)
        {
            var plan = _executablePlans[i];
            IReadOnlyList<OverlayLayer> layers;
            if (_overlayEditor is not null && _overlayState?.IsEnabled == true)
            {
                layers = _overlayEditor.BuildLayersForPlan(
                    _randomLibrarySelectionSeed,
                    libraryEntries,
                    planOrdinal: maskSelectionStartOrdinal + i);
            }
            else if (_overlayState is not null)
            {
                layers = OverlayEnqueueResolver.ResolveForPlan(
                    _overlayState,
                    libraryEntries,
                    plan,
                    planOrdinal: maskSelectionStartOrdinal + i,
                    randomSelectionSeed: _randomLibrarySelectionSeed);
            }
            else
            {
                layers = Array.Empty<OverlayLayer>();
            }

            var useRandom = _overlayEditor is not null
                ? _overlayEditor.UseRandomMaskLibrary
                : _overlayState?.UseRandomLibrarySource == true;
            if (layers.Count > 0 && useRandom)
            {
                layers = await OverlayEnqueueResolver
                    .ProbeSourceDurationsAsync(layers, _probe, CancellationToken.None)
                    .ConfigureAwait(true);
            }

            overlayLayersPerPlan[i] = layers;
        }

        var aspectPolicy = BuildUnifiedAspectPolicy();
        var aspectResult = aspectPolicy.ToOutputAspect();
        if (!aspectResult.IsSuccess)
        {
            ValidationMessage = aspectResult.Error ?? "画幅参数无效。";
            return;
        }

        if (aspectPolicy.IsEnabled)
        {
            overlayLayersPerPlan = overlayLayersPerPlan
                .Select(layers => aspectPolicy.ApplyOverlayFit(layers))
                .ToArray();
        }

        var profile = RenderProfile.For(SelectedQuality);
        var outputVideoSettings = BuildOutputVideoSettings();
        var reservedOutputPaths = _coordinator.Jobs
            .Where(j => j.State is JobState.Queued or JobState.Preparing or JobState.Running or JobState.Finalizing)
            .Select(j => j.Request?.OutputPath)
            .Where(static p => !string.IsNullOrWhiteSpace(p))
            .Cast<string>();
        var requests = RenderRequestFactory.CreateForPlans(
            _executablePlans,
            OutputDirectory,
            OutputFileNamePrefix,
            profile,
            aspectResult.Value!,
            overlayLayersPerPlan,
            sharedOverlayLayers: null,
            effectTemplate,
            bgm: useAudioLibrary ? null : bgm,
            stickers: [],
            mainBoost,
            outputVideoSettings,
            doubleScreen,
            reservedOutputPaths,
            stickersPerPlan,
            SelectedProcessingMode,
            bgmPerPlan: useAudioLibrary ? bgmPerPlan : null,
            doubleScreenSourceAssets: _assets);

        var jobs = requests
            .Select(RenderJob.CreateQueued)
            .ToArray();

        await _coordinator.EnqueueAsync(jobs, CancellationToken.None).ConfigureAwait(true);
        if (_stickerEditor.UseRandomStickerLibrary)
        {
            _nextRandomStickerSelectionOrdinal += jobs.LongLength;
        }

        if (useRandomMaskSelection)
        {
            _nextRandomMaskSelectionOrdinal += jobs.LongLength;
        }

        if (useAudioLibrary)
        {
            _nextRandomAudioSelectionOrdinal += jobs.LongLength;
        }

        var hints = new List<string>
        {
            DescribeQuality(SelectedQuality),
            DescribeProcessingMode(SelectedProcessingMode)
        };
        if (outputVideoSettings.RequiresTranscode)
        {
            hints.Add(DescribeOutputVideoSettings(outputVideoSettings));
        }
        if (_overlayState?.IsEnabled == true && overlayLayersPerPlan.Any(layers => layers.Count > 0))
        {
            var layerCount = overlayLayersPerPlan.Max(layers => layers.Count);
            var overlayHintText = (_overlayEditor?.UseRandomMaskLibrary ?? _overlayState?.UseRandomLibrarySource == true)
                ? "随机替换蒙版（每条成片 1 个）"
                : $"{layerCount} 层蒙版";
            hints.Add(overlayHintText);
        }

        if (EnableVariationEffects)
        {
            hints.Add($"差异化滤镜 {VariationIntensityPercent}%");
        }

        if (doubleScreen is not null)
        {
            var sourceHint = DoubleScreenUseRandomCurrentFolder
                ? "随机抽取当前素材文件夹素材并随机上下覆盖"
                : "当前视频上下双屏";
            var featherHint = DoubleScreenFeatherEnabled
                ? $"羽化 {DoubleScreenFeatherPixels}px"
                : "硬切";
            hints.Add($"双屏（第 {doubleScreen.StartClipIndex} 个视频起，{sourceHint}，{featherHint}）");
        }

        var totalStickerCount = stickersPerPlan.Sum(s => s.Count);
        if (totalStickerCount > 0)
        {
            var randomHint = _stickerEditor.UseRandomStickerLibrary ? " · 随机替换" : string.Empty;
            hints.Add($"贴纸({totalStickerCount}){randomHint}");
        }

        if (useAudioLibrary)
        {
            hints.Add("音频库随机");
        }
        else if (bgm is not null)
        {
            hints.Add("BGM 混音");
        }

        if (mainBoost is not null)
        {
            var parts = new List<string>();
            if (mainBoost.EnableVolume)
            {
                parts.Add(mainBoost.VolumeMode == MainMaterialBoostMode.Fixed
                    ? $"音量 {mainBoost.VolumeMinPercent:0.#}%"
                    : $"音量随机 {mainBoost.VolumeMinPercent:0.#}–{mainBoost.VolumeMaxPercent:0.#}%");
            }

            if (mainBoost.EnableScale)
            {
                parts.Add(mainBoost.ScaleMode == MainMaterialBoostMode.Fixed
                    ? $"缩放 {mainBoost.ScaleMinPercent:0.#}%"
                    : $"缩放随机 {mainBoost.ScaleMinPercent:0.#}–{mainBoost.ScaleMaxPercent:0.#}%");
            }

            hints.Add($"主素材 {string.Join("、", parts)}");
        }

        if (EnableUnifiedAspect)
        {
            hints.Add("统一比例");
        }

        var overlayHint = hints.Count > 0 ? $"（含 {string.Join("、", hints)}）" : string.Empty;
        StatusMessage =
            $"已将 {jobs.Length} 个任务加入队列{overlayHint}。界面未锁定，可「清理素材」后导入下一商品，或切换另一商品组继续入队。";
    }

    private static string DescribeQuality(QualityPreset quality) =>
        quality switch
        {
            QualityPreset.Lossless => "无损直拷",
            QualityPreset.High => "高质量",
            QualityPreset.Balanced => "平衡",
            QualityPreset.Small => "小体积",
            QualityPreset.Fast => "快速",
            _ => quality.ToString()
        };

    private static string DescribeProcessingMode(VideoProcessingMode mode) =>
        mode switch
        {
            VideoProcessingMode.Auto => "处理器：自动",
            VideoProcessingMode.Cpu => "处理器：CPU",
            VideoProcessingMode.Gpu => "处理器：GPU",
            _ => "处理器：自动"
        };

    private OutputVideoSettings BuildOutputVideoSettings() =>
        new(SelectedOutputResolution, SelectedOutputFrameRate);

    private static string DescribeOutputVideoSettings(OutputVideoSettings settings)
    {
        var parts = new List<string>();
        if (!settings.IsOriginalResolution)
        {
            parts.Add(DescribeOutputResolution(settings.Resolution));
        }

        if (!settings.IsOriginalFrameRate)
        {
            parts.Add(DescribeOutputFrameRate(settings.FrameRate));
        }

        return string.Join(" + ", parts);
    }

    private static string DescribeOutputResolution(OutputResolutionPreset preset) =>
        preset switch
        {
            OutputResolutionPreset.P480 => "480P",
            OutputResolutionPreset.P720 => "720P",
            OutputResolutionPreset.P1080 => "1080P",
            _ => "原画"
        };

    private static string DescribeOutputFrameRate(OutputFrameRatePreset preset) =>
        preset switch
        {
            OutputFrameRatePreset.Fps24 => "24 fps",
            OutputFrameRatePreset.Fps25 => "25 fps",
            OutputFrameRatePreset.Fps30 => "30 fps（手机兼容）",
            OutputFrameRatePreset.Fps50 => "50 fps",
            OutputFrameRatePreset.Fps60 => "60 fps",
            _ => "原帧率"
        };

    private bool CanEnqueue() =>
        _executablePlans.Count > 0
        && !string.IsNullOrWhiteSpace(OutputDirectory)
        && !string.IsNullOrWhiteSpace(OutputFileNamePrefix)
        && (!EnableUnifiedAspect
            || AspectPreset != OutputCanvasPreset.Custom
            || (CustomAspectWidth > 0 && CustomAspectHeight > 0));

    private void RefreshPreview()
    {
        PreviewPlans.Clear();
        var result = CompositionOrchestrator.BuildPreview(
            _assets,
            Mode,
            SequenceExpression,
            BatchCount,
            RandomSeed,
            ClipsPerPlan);

        ValidationMessage = result.ValidationMessage;
        _executablePlans = result.ExecutablePlans;

        foreach (var plan in result.Plans)
        {
            PreviewPlans.Add(new PreviewPlanRowViewModel(
                plan.PlanNumber,
                FormatSequence(plan.Sequence),
                plan.Duration,
                plan.Sequence.Count));
        }

        PreviewSummary = PreviewPlans.Count switch
        {
            0 => "当前无法生成预览，请检查素材与编排参数。",
            1 => IsCustomMode
                ? $"单条成片：预计时长 {PreviewPlans[0].DurationText}，共 {PreviewPlans[0].ClipCount} 段。"
                : $"预计成片时长 {PreviewPlans[0].DurationText}，共 {PreviewPlans[0].ClipCount} 段。",
            _ => IsCustomMode
                ? $"将生成 {PreviewPlans.Count} 条独立成片（每条表达式对应一条任务）。"
                : $"将生成 {PreviewPlans.Count} 条成片，每条 {PreviewPlans[0].ClipCount} 段。"
        };

        EnqueueCommand.NotifyCanExecuteChanged();
    }

    private static MaterialRowViewModel CreateMaterialRow(MediaImportOutcome outcome)
    {
        if (outcome.Asset is not null)
        {
            var asset = outcome.Asset;
            var resolution = $"{asset.Info.Width}×{asset.Info.Height}";
            return new MaterialRowViewModel(
                Path.GetFileName(asset.Path),
                asset.Path,
                asset.SequenceIndex?.ToString(CultureInfo.InvariantCulture),
                asset.Info.Duration,
                resolution,
                outcome.SequenceWarning,
                hasValidAsset: true,
                videoCodec: asset.Info.VideoCodec);
        }

        return new MaterialRowViewModel(
            Path.GetFileName(outcome.SourcePath),
            outcome.SourcePath,
            null,
            TimeSpan.Zero,
            "—",
            outcome.ProbeError ?? outcome.SequenceWarning ?? "导入失败。",
            hasValidAsset: false);
    }

    private static string FormatSequence(IReadOnlyList<int> sequence) =>
        string.Join(" → ", sequence);

    private EffectVariationTemplate ResolveActiveEffectTemplate()
    {
        var baseTemplate = _activeEffectTemplate.Id == EffectTemplates.None.Id
            ? EffectTemplates.StandardVariation()
            : _activeEffectTemplate;
        var scaled = baseTemplate.ScaleIntensity(VariationIntensityPercent / 100.0);
        return scaled with
        {
            EnableMirror = scaled.EnableMirror && VariationEnableMirror,
            EnableRotate = scaled.EnableRotate && VariationEnableRotate,
            MinCropPercent = VariationEnableCrop ? scaled.MinCropPercent : 0,
            MaxCropPercent = VariationEnableCrop ? scaled.MaxCropPercent : 0,
            MinBrightness = VariationEnableColor ? scaled.MinBrightness : 0,
            MaxBrightness = VariationEnableColor ? scaled.MaxBrightness : 0,
            MinContrast = VariationEnableColor ? scaled.MinContrast : 1,
            MaxContrast = VariationEnableColor ? scaled.MaxContrast : 1,
            MinSaturation = VariationEnableColor ? scaled.MinSaturation : 1,
            MaxSaturation = VariationEnableColor ? scaled.MaxSaturation : 1,
            MinDenoise = VariationEnableDenoise ? scaled.MinDenoise : 0,
            MaxDenoise = VariationEnableDenoise ? scaled.MaxDenoise : 0,
            MinRotationDegrees = VariationEnableRotate ? scaled.MinRotationDegrees : 0,
            MaxRotationDegrees = VariationEnableRotate ? scaled.MaxRotationDegrees : 0
        };
    }
}

/// <summary>混剪页商品工作组快照：两组素材可分别编排并入队并行渲染。</summary>
internal sealed class CompositionWorkspaceSlot
{
    public CompositionWorkspaceSlot(string displayName)
    {
        DisplayName = displayName;
    }

    public string DisplayName { get; }

    public List<MediaAsset> Assets { get; set; } = [];

    public List<MaterialRowViewModel> MaterialRows { get; set; } = [];

    public CompositionMode Mode { get; set; } = CompositionMode.Random;

    public string SequenceExpression { get; set; } = string.Empty;

    public int BatchCount { get; set; } = 1;

    public int RandomSeed { get; set; } = Environment.TickCount;

    public int? ClipsPerPlan { get; set; }

    public string OutputDirectory { get; set; } = string.Empty;

    public string OutputFileNamePrefix { get; set; } = string.Empty;

    public bool OutputDirectoryUserOverride { get; set; }
}
