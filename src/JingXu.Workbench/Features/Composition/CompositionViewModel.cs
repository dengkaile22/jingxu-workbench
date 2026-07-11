using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
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
using JingXu.Workbench.Features.Shell;

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
    private readonly List<MediaAsset> _assets = [];
    private IReadOnlyList<CompositionPlan> _executablePlans = [];
    private bool _outputDirectoryUserOverride;
    private bool _trackOutputDirectoryOverrides;
    private bool _suppressOutputDirectoryOverrideTracking;
    private EffectVariationTemplate _activeEffectTemplate = EffectTemplates.None;
    private Dictionary<string, StickerTemplateDto> _stickersByTemplateId =
        new(StringComparer.Ordinal);

    public CompositionViewModel(
        IMediaProbe probe,
        RenderCoordinator coordinator,
        IMediaFilePicker filePicker,
        IOutputFolderPicker outputFolderPicker,
        IUiDispatcher uiDispatcher,
        OverlayWorkbenchState? overlayState = null,
        OverlayLibraryService? overlayLibraryService = null,
        TemplateService? templateService = null)
    {
        _probe = probe;
        _coordinator = coordinator;
        _filePicker = filePicker;
        _outputFolderPicker = outputFolderPicker;
        _uiDispatcher = uiDispatcher;
        _overlayState = overlayState;
        _overlayLibraryService = overlayLibraryService;
        _templateService = templateService;
        if (_overlayState is not null)
        {
            EnableOverlayOnOutput = _overlayState.IsEnabled;
            UseRandomOverlayLibrary = _overlayState.UseRandomLibrarySource;
            _overlayState.Changed += OnOverlayStateChanged;
        }

        OutputDirectory = RenderRequestFactory.DefaultOutputDirectory;
        OutputFileNamePrefix = "混剪成片";
        RandomSeed = Environment.TickCount;
        SelectedQuality = QualityPreset.Balanced;
        StickerXPercent = 72;
        StickerYPercent = 78;
        StickerWidthPercent = 22;
        StickerHeightPercent = 16;
        StickerOpacityPercent = 100;
        NewTemplateName = string.Empty;
        RefreshOverlayStatus();
        RefreshQualityHint();
        RefreshPreview();
        _trackOutputDirectoryOverrides = true;
        _ = LoadEffectTemplatesAsync();
    }

    public override WorkspaceModule ModuleKind => WorkspaceModule.Composition;

    public override string Title => "批量混剪";

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
    private string _qualityHint = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    private bool _enableVariationEffects;

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

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasStickerPath))]
    [NotifyPropertyChangedFor(nameof(IsStickerSectionEnabled))]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
    private bool _enableSticker;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasStickerPath))]
    private string _stickerPath = string.Empty;

    [ObservableProperty]
    private double _stickerXPercent = 72;

    [ObservableProperty]
    private double _stickerYPercent = 78;

    [ObservableProperty]
    private double _stickerWidthPercent = 22;

    [ObservableProperty]
    private double _stickerHeightPercent = 16;

    [ObservableProperty]
    private int _stickerOpacityPercent = 100;

    [ObservableProperty]
    private string _newTemplateName = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(OverlayStatusLabel))]
    [NotifyPropertyChangedFor(nameof(IsOverlaySectionEnabled))]
    [NotifyPropertyChangedFor(nameof(QualityHint))]
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

    public bool HasStickerPath => !string.IsNullOrWhiteSpace(StickerPath);

    public bool IsStickerSectionEnabled => EnableSticker;

    public bool IsLosslessQuality => SelectedQuality == QualityPreset.Lossless;

    public bool IsRandomMode => Mode == CompositionMode.Random;

    public bool IsCustomMode => Mode == CompositionMode.CustomSequence;

    public bool CanPickImportFiles => !IsImporting;

    public bool HasValidationMessage => !string.IsNullOrWhiteSpace(ValidationMessage);

    public bool HasStatusMessage => !string.IsNullOrWhiteSpace(StatusMessage);

    partial void OnModeChanged(CompositionMode value)
    {
        OnPropertyChanged(nameof(IsRandomMode));
        OnPropertyChanged(nameof(IsCustomMode));
        RefreshPreview();
    }

    partial void OnSequenceExpressionChanged(string value) => RefreshPreview();

    partial void OnBatchCountChanged(int value) => RefreshPreview();

    partial void OnRandomSeedChanged(int value) => RefreshPreview();

    partial void OnSelectedQualityChanged(QualityPreset value) => RefreshQualityHint();

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
        }

        RefreshQualityHint();
    }

    partial void OnEnableBgmChanged(bool value) => RefreshQualityHint();

    partial void OnEnableStickerChanged(bool value) => RefreshQualityHint();

    partial void OnEnableOverlayOnOutputChanged(bool value)
    {
        if (_overlayState is not null && _overlayState.IsEnabled != value)
        {
            _overlayState.SetEnabled(value);
        }

        RefreshOverlayStatus();
        RefreshQualityHint();
    }

    partial void OnUseRandomOverlayLibraryChanged(bool value)
    {
        if (_overlayState is not null && _overlayState.UseRandomLibrarySource != value)
        {
            _overlayState.SetUseRandomLibrarySource(value);
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
        RefreshUnifiedAspectPreview();
    }

    partial void OnCustomAspectWidthChanged(int value) => RefreshUnifiedAspectPreview();

    partial void OnCustomAspectHeightChanged(int value) => RefreshUnifiedAspectPreview();

    partial void OnClipFitModeChanged(AspectFitMode value) => RefreshUnifiedAspectPreview();

    partial void OnOverlayFitModeChanged(OverlayFitMode value) => RefreshUnifiedAspectPreview();

    partial void OnSelectedEffectTemplateChanged(EffectVariationTemplate? value)
    {
        if (value is null)
        {
            return;
        }

        ApplyEffectTemplate(value, applySticker: true);
    }

    private void RefreshUnifiedAspectPreview()
    {
        var (firstWidth, firstHeight) = ResolveFirstClipDimensions();
        UnifiedAspectPreviewDescription = BuildUnifiedAspectPolicy().BuildPreviewDescription(firstWidth, firstHeight);
        EnqueueCommand.NotifyCanExecuteChanged();
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

        if (UseRandomOverlayLibrary != _overlayState.UseRandomLibrarySource)
        {
            UseRandomOverlayLibrary = _overlayState.UseRandomLibrarySource;
        }

        RefreshOverlayStatus();
        RefreshQualityHint();
    }

    private void RefreshOverlayStatus()
    {
        if (_overlayState is null || !_overlayState.IsEnabled)
        {
            OverlayStatusLabel = "已关闭 · 成片不含蒙版";
            return;
        }

        if (_overlayState.UseRandomLibrarySource)
        {
            OverlayStatusLabel = _overlayState.HasLayers
                ? $"已开启 · 将随机套用素材库蒙版到成片（保留 {_overlayState.Layers.Count} 层参数）"
                : "已开启 · 将从素材库随机选取蒙版并叠加到成片";
            return;
        }

        OverlayStatusLabel = _overlayState.HasLayers
            ? $"已开启 · 将 {_overlayState.Layers.Count} 层蒙版叠加到成片"
            : "已开启 · 请先在蒙版页配置层，或开启随机套用素材库";
    }

    private void RefreshQualityHint()
    {
        if (SelectedQuality != QualityPreset.Lossless)
        {
            QualityHint = SelectedQuality switch
            {
                QualityPreset.High => "高质量：默认 CRF 18、AAC 192 kbps。",
                QualityPreset.Balanced => "平衡：默认 CRF 22、AAC 160 kbps。",
                QualityPreset.Small => "小体积：默认 CRF 27、AAC 128 kbps。",
                _ => string.Empty
            };
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

        if (EnableSticker && HasStickerPath)
        {
            blockers.Add("贴纸");
        }

        if (EnableOverlayOnOutput)
        {
            blockers.Add("蒙版");
        }

        if (EnableBgm && HasBgmPath)
        {
            blockers.Add("BGM");
        }

        QualityHint = blockers.Count == 0
            ? "无损直拷：仅在无画幅变化、滤镜、贴纸、蒙版、字幕或音频混合，且流结构兼容时可用。"
            : $"已启用 {string.Join("、", blockers)}，将强制重新编码（无法无损直拷）。";
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
    private void PickStickerFile()
    {
        var picked = _filePicker.PickImageFile();
        if (!string.IsNullOrWhiteSpace(picked))
        {
            StickerPath = picked;
            EnableSticker = true;
            RefreshQualityHint();
        }
    }

    [RelayCommand]
    private void ClearSticker()
    {
        StickerPath = string.Empty;
        EnableSticker = false;
        RefreshQualityHint();
    }

    [RelayCommand]
    private async Task LoadEffectTemplatesAsync()
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

        ApplyEffectTemplate(SelectedEffectTemplate, applySticker: true);
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

        var id = "user-" + Guid.NewGuid().ToString("N")[..12];
        var baseTemplate = EnableVariationEffects
            ? (_activeEffectTemplate.Id == EffectTemplates.None.Id
                ? EffectTemplates.StandardVariation()
                : _activeEffectTemplate)
            : EffectTemplates.None;

        var created = EffectVariationTemplate.Create(
            id,
            name,
            baseTemplate.EnableMirror,
            baseTemplate.MinCropPercent,
            baseTemplate.MaxCropPercent,
            baseTemplate.MinBrightness,
            baseTemplate.MaxBrightness,
            baseTemplate.MinContrast,
            baseTemplate.MaxContrast,
            baseTemplate.MinSaturation,
            baseTemplate.MaxSaturation,
            baseTemplate.MinDenoise,
            baseTemplate.MaxDenoise,
            baseTemplate.EnableMetadataClearing);

        if (!created.IsSuccess)
        {
            ValidationMessage = created.Error ?? "无法创建效果模板。";
            return;
        }

        var stickerMap = new Dictionary<string, StickerTemplateDto>(
            _stickersByTemplateId,
            StringComparer.Ordinal);
        if (EnableSticker && !string.IsNullOrWhiteSpace(StickerPath))
        {
            stickerMap[id] = new StickerTemplateDto
            {
                Path = StickerPath.Trim(),
                X = StickerXPercent / 100.0,
                Y = StickerYPercent / 100.0,
                Width = StickerWidthPercent / 100.0,
                Height = StickerHeightPercent / 100.0,
                Opacity = StickerOpacityPercent / 100.0
            };
        }
        else
        {
            stickerMap.Remove(id);
        }

        var userTemplates = EffectTemplatesList
            .Where(t => t.Id is not ("none" or "standard-variation") && t.Id != id)
            .Append(created.Value!)
            .ToArray();

        var document = new EffectTemplateDocument
        {
            Templates =
            [
                EffectTemplates.None,
                EffectTemplates.StandardVariation(),
                .. userTemplates
            ],
            StickersByTemplateId = stickerMap
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
        _stickersByTemplateId = new Dictionary<string, StickerTemplateDto>(StringComparer.Ordinal);
        if (SelectedEffectTemplate is null)
        {
            SelectedEffectTemplate = EffectTemplates.None;
        }
    }

    private void ApplyTemplateDocument(EffectTemplateDocument document)
    {
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

        _stickersByTemplateId = document.StickersByTemplateId is { Count: > 0 } map
            ? new Dictionary<string, StickerTemplateDto>(map, StringComparer.Ordinal)
            : new Dictionary<string, StickerTemplateDto>(StringComparer.Ordinal);

        var preferredId = SelectedEffectTemplate?.Id;
        SelectedEffectTemplate = EffectTemplatesList.FirstOrDefault(t => t.Id == preferredId)
            ?? EffectTemplatesList[0];
    }

    private void ApplyEffectTemplate(EffectVariationTemplate template, bool applySticker)
    {
        _activeEffectTemplate = template;
        EnableVariationEffects = !IsEffectivelyNone(template);

        if (!applySticker)
        {
            RefreshQualityHint();
            return;
        }

        if (_stickersByTemplateId.TryGetValue(template.Id, out var sticker)
            && !string.IsNullOrWhiteSpace(sticker.Path))
        {
            EnableSticker = true;
            StickerPath = sticker.Path;
            StickerXPercent = Math.Round(sticker.X * 100, 2);
            StickerYPercent = Math.Round(sticker.Y * 100, 2);
            StickerWidthPercent = Math.Round(sticker.Width * 100, 2);
            StickerHeightPercent = Math.Round(sticker.Height * 100, 2);
            StickerOpacityPercent = (int)Math.Round(sticker.Opacity * 100);
        }

        RefreshQualityHint();
    }

    private static bool IsEffectivelyNone(EffectVariationTemplate template) =>
        template.Id == EffectTemplates.None.Id
        || (!template.EnableMirror
            && template.MaxCropPercent <= 0
            && !template.EnableMetadataClearing
            && Math.Abs(template.MinBrightness) < 0.0001
            && Math.Abs(template.MaxBrightness) < 0.0001
            && Math.Abs(template.MinContrast - 1) < 0.0001
            && Math.Abs(template.MaxContrast - 1) < 0.0001
            && Math.Abs(template.MinSaturation - 1) < 0.0001
            && Math.Abs(template.MaxSaturation - 1) < 0.0001
            && template.MaxDenoise <= 0);

    private ImageSticker? TryBuildSticker(out string? error)
    {
        error = null;
        if (!EnableSticker)
        {
            return null;
        }

        if (string.IsNullOrWhiteSpace(StickerPath))
        {
            error = "已启用贴纸但未选择图片文件。";
            return null;
        }

        var result = ImageSticker.Create(
            StickerPath,
            StickerXPercent / 100.0,
            StickerYPercent / 100.0,
            StickerWidthPercent / 100.0,
            StickerHeightPercent / 100.0,
            StickerOpacityPercent / 100.0);

        if (!result.IsSuccess)
        {
            error = result.Error ?? "贴纸参数无效。";
            return null;
        }

        return result.Value;
    }

    [RelayCommand(CanExecute = nameof(CanEnqueue))]
    private async Task EnqueueAsync()
    {
        if (_executablePlans.Count == 0)
        {
            return;
        }

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
                libraryEntries.Length);
            if (overlayValidation is not null)
            {
                ValidationMessage = overlayValidation;
                return;
            }
        }

        var effectTemplate = EnableVariationEffects
            ? (_activeEffectTemplate.Id == EffectTemplates.None.Id
                ? EffectTemplates.StandardVariation()
                : _activeEffectTemplate)
            : null;

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

        var sticker = TryBuildSticker(out var stickerError);
        if (stickerError is not null)
        {
            ValidationMessage = stickerError;
            return;
        }

        var overlayLayersPerPlan = new IReadOnlyList<OverlayLayer>[_executablePlans.Count];
        for (var i = 0; i < _executablePlans.Count; i++)
        {
            var plan = _executablePlans[i];
            var layers = _overlayState is null
                ? Array.Empty<OverlayLayer>()
                : OverlayEnqueueResolver.ResolveForPlan(_overlayState, libraryEntries, plan);

            if (layers.Count > 0 && _overlayState?.UseRandomLibrarySource == true)
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
        var requests = RenderRequestFactory.CreateForPlans(
            _executablePlans,
            OutputDirectory,
            OutputFileNamePrefix,
            profile,
            aspectResult.Value!,
            overlayLayersPerPlan,
            sharedOverlayLayers: null,
            effectTemplate,
            bgm,
            sticker);

        var jobs = requests
            .Select(RenderJob.CreateQueued)
            .ToArray();

        await _coordinator.EnqueueAsync(jobs, CancellationToken.None).ConfigureAwait(true);
        var hints = new List<string> { DescribeQuality(SelectedQuality) };
        if (_overlayState?.IsEnabled == true && overlayLayersPerPlan.Any(layers => layers.Count > 0))
        {
            var layerCount = overlayLayersPerPlan.Max(layers => layers.Count);
            var overlayHintText = _overlayState.UseRandomLibrarySource
                ? $"随机素材库蒙版（{layerCount} 层）"
                : $"{layerCount} 层蒙版";
            hints.Add(overlayHintText);
        }

        if (EnableVariationEffects)
        {
            hints.Add("差异化滤镜");
        }

        if (sticker is not null)
        {
            hints.Add("贴纸");
        }

        if (bgm is not null)
        {
            hints.Add("BGM 混音");
        }

        if (EnableUnifiedAspect)
        {
            hints.Add("统一比例");
        }

        var overlayHint = hints.Count > 0 ? $"（含 {string.Join("、", hints)}）" : string.Empty;
        StatusMessage = $"已将 {jobs.Length} 个任务加入队列{overlayHint}。";
    }

    private static string DescribeQuality(QualityPreset quality) =>
        quality switch
        {
            QualityPreset.Lossless => "无损直拷",
            QualityPreset.High => "高质量",
            QualityPreset.Balanced => "平衡",
            QualityPreset.Small => "小体积",
            _ => quality.ToString()
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
            RandomSeed);

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
}
