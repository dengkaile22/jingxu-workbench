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
    private readonly List<MediaAsset> _assets = [];
    private IReadOnlyList<CompositionPlan> _executablePlans = [];

    public CompositionViewModel(
        IMediaProbe probe,
        RenderCoordinator coordinator,
        IMediaFilePicker filePicker,
        IOutputFolderPicker outputFolderPicker,
        IUiDispatcher uiDispatcher,
        OverlayWorkbenchState? overlayState = null,
        OverlayLibraryService? overlayLibraryService = null)
    {
        _probe = probe;
        _coordinator = coordinator;
        _filePicker = filePicker;
        _outputFolderPicker = outputFolderPicker;
        _uiDispatcher = uiDispatcher;
        _overlayState = overlayState;
        _overlayLibraryService = overlayLibraryService;
        if (_overlayState is not null)
        {
            EnableOverlayOnOutput = _overlayState.IsEnabled;
            UseRandomOverlayLibrary = _overlayState.UseRandomLibrarySource;
            _overlayState.Changed += OnOverlayStateChanged;
        }

        OutputDirectory = RenderRequestFactory.DefaultOutputDirectory;
        OutputFileNamePrefix = "混剪成片";
        RandomSeed = Environment.TickCount;
        RefreshOverlayStatus();
        RefreshPreview();
    }

    public override WorkspaceModule ModuleKind => WorkspaceModule.Composition;

    public override string Title => "批量混剪";

    public ObservableCollection<MaterialRowViewModel> Materials { get; } = [];

    public ObservableCollection<PreviewPlanRowViewModel> PreviewPlans { get; } = [];

    [ObservableProperty]
    private MaterialRowViewModel? _selectedMaterial;

    public int MaterialCount => Materials.Count;

    public bool HasMaterials => MaterialCount > 0;

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
    private bool _enableVariationEffects;

    [ObservableProperty]
    private bool _enableBgm;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasBgmPath))]
    private string _bgmPath = string.Empty;

    [ObservableProperty]
    private int _originalVolumePercent = 100;

    [ObservableProperty]
    private int _bgmVolumePercent = 18;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(OverlayStatusLabel))]
    [NotifyPropertyChangedFor(nameof(IsOverlaySectionEnabled))]
    private bool _enableOverlayOnOutput;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(UnifiedAspectPreviewDescription))]
    [NotifyPropertyChangedFor(nameof(IsCustomAspectPreset))]
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

    partial void OnEnableOverlayOnOutputChanged(bool value)
    {
        if (_overlayState is not null && _overlayState.IsEnabled != value)
        {
            _overlayState.SetEnabled(value);
        }

        RefreshOverlayStatus();
    }

    partial void OnUseRandomOverlayLibraryChanged(bool value)
    {
        if (_overlayState is not null && _overlayState.UseRandomLibrarySource != value)
        {
            _overlayState.SetUseRandomLibrarySource(value);
        }

        RefreshOverlayStatus();
    }

    partial void OnEnableUnifiedAspectChanged(bool value) => RefreshUnifiedAspectPreview();

    partial void OnAspectPresetChanged(OutputCanvasPreset value)
    {
        OnPropertyChanged(nameof(IsCustomAspectPreset));
        RefreshUnifiedAspectPreview();
    }

    partial void OnCustomAspectWidthChanged(int value) => RefreshUnifiedAspectPreview();

    partial void OnCustomAspectHeightChanged(int value) => RefreshUnifiedAspectPreview();

    partial void OnClipFitModeChanged(AspectFitMode value) => RefreshUnifiedAspectPreview();

    partial void OnOverlayFitModeChanged(OverlayFitMode value) => RefreshUnifiedAspectPreview();

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
        SelectedMaterial ??= Materials.FirstOrDefault(m => m.HasValidAsset);
        RefreshUnifiedAspectPreview();
        RefreshPreview();
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
        }
    }

    [RelayCommand]
    private void ClearBgm()
    {
        BgmPath = string.Empty;
        EnableBgm = false;
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

        var effectTemplate = EnableVariationEffects ? EffectTemplates.StandardVariation() : null;
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

        var overlayLayersPerPlan = _executablePlans
            .Select(plan => _overlayState is null
                ? Array.Empty<OverlayLayer>()
                : OverlayEnqueueResolver.ResolveForPlan(_overlayState, libraryEntries, plan))
            .ToArray();

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

        var requests = RenderRequestFactory.CreateForPlans(
            _executablePlans,
            OutputDirectory,
            OutputFileNamePrefix,
            RenderProfile.Balanced,
            aspectResult.Value!,
            overlayLayersPerPlan,
            sharedOverlayLayers: null,
            effectTemplate,
            bgm);

        var jobs = requests
            .Select(RenderJob.CreateQueued)
            .ToArray();

        await _coordinator.EnqueueAsync(jobs, CancellationToken.None).ConfigureAwait(true);
        var hints = new List<string>();
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
