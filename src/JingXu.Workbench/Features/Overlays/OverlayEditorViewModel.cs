using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Infrastructure.Persistence;

namespace JingXu.Workbench.Features.Overlays;

/// <summary>蒙版工作台视图模型：导入蒙版视频素材、编辑叠加参数、同步素材库。</summary>
public sealed partial class OverlayEditorViewModel : WorkspaceModuleViewModel
{
    public const string MaskVideoDialogTitle = "选择蒙版视频素材";
    public const double MinNormalizedSize = 0.05;

    private readonly IMediaFilePicker _filePicker;
    private readonly IMediaProbe _mediaProbe;
    private readonly IUiDispatcher _uiDispatcher;
    private readonly OverlayLibraryService _libraryService;
    private readonly OverlayWorkbenchState _workbenchState;
    private readonly OverlayLayersService _layersService;
    private readonly IMediaFrameExtractor? _frameExtractor;
    private long _saveGeneration;
    private int _layerCounter;
    private bool _isLoadingSelection;
    private bool _isRefreshingState;
    private bool _isLoadingLayers;
    private int _previewGeneration;

    public OverlayEditorViewModel(
        IMediaFilePicker filePicker,
        OverlayWorkbenchState workbenchState,
        IMediaProbe mediaProbe,
        IUiDispatcher uiDispatcher,
        OverlayLayersService layersService,
        OverlayLibraryService? libraryService = null,
        IMediaFrameExtractor? frameExtractor = null)
    {
        _filePicker = filePicker ?? throw new ArgumentNullException(nameof(filePicker));
        _workbenchState = workbenchState ?? throw new ArgumentNullException(nameof(workbenchState));
        _mediaProbe = mediaProbe ?? throw new ArgumentNullException(nameof(mediaProbe));
        _uiDispatcher = uiDispatcher ?? throw new ArgumentNullException(nameof(uiDispatcher));
        _layersService = layersService ?? throw new ArgumentNullException(nameof(layersService));
        _libraryService = libraryService ?? new OverlayLibraryService(
            new AtomicJsonStore<OverlayLibraryDocument>(OverlayLibraryDocument.CurrentSchemaVersion));
        _frameExtractor = frameExtractor;
        _workbenchState.Changed += OnWorkbenchStateChanged;
        RefreshFromState();
        _ = EnsureLayersLoadedAsync();
        _ = RefreshLibraryCountAsync();
    }

    public override WorkspaceModule ModuleKind => WorkspaceModule.Overlays;

    public override string Title => "蒙版模板";

    public ObservableCollection<OverlayLayerRowViewModel> Layers { get; } = [];

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RemoveSelectedCommand))]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    [NotifyCanExecuteChangedFor(nameof(ImportMaskMaterialsCommand))]
    [NotifyCanExecuteChangedFor(nameof(ApplyUnifiedSizeToAllCommand))]
    [NotifyCanExecuteChangedFor(nameof(ApplyMaskAspectPresetCommand))]
    [NotifyCanExecuteChangedFor(nameof(ResetSourceCropBoundsCommand))]
    [NotifyCanExecuteChangedFor(nameof(ApplyFitPresetCommand))]
    [NotifyCanExecuteChangedFor(nameof(ApplyCurrentVisualSettingsToAllLayersCommand))]
    [NotifyCanExecuteChangedFor(nameof(ApplyStartClipIndexToAllLayersCommand))]
    [NotifyCanExecuteChangedFor(nameof(RefreshEffectPreviewFromBaseVideoCommand))]
    [NotifyPropertyChangedFor(nameof(ApplyCurrentVisualSettingsToAllLayersHint))]
    private OverlayLayerRowViewModel? _selected;

    [ObservableProperty]
    private string _previewSummary = "导入蒙版视频后，默认放在上半红框区（中间实、向上渐淡）；在混剪页启用叠加后生效。";

    [ObservableProperty]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _boundsX = OverlayLayer.ImportedMaskBounds.X;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _boundsY = OverlayLayer.ImportedMaskBounds.Y;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _boundsWidth = OverlayLayer.ImportedMaskBounds.Width;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _boundsHeight = OverlayLayer.ImportedMaskBounds.Height;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _opacity = OverlayLayer.GhostOverlayOpacity;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private int _startClipIndex = 1;

    [ObservableProperty]
    private double _scale = OverlayLayer.GhostOverlayScale;

    [ObservableProperty]
    private double _offsetX;

    [ObservableProperty]
    private double _offsetY = OverlayLayer.GhostOverlayOffsetY;

    [ObservableProperty]
    private double _rotationDegrees;

    [ObservableProperty]
    private double _feather = OverlayLayer.GhostOverlayFeather;

    [ObservableProperty]
    private double _topFade = OverlayLayer.GhostOverlayTopFade;

    [ObservableProperty]
    private double _sourceCropY;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private bool _mixOverlayAudio;

    [ObservableProperty]
    private int _libraryEntryCount;

    [ObservableProperty]
    private int _libraryValidCount;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ImportMaskMaterialsCommand))]
    private bool _isImporting;

    [ObservableProperty]
    private string _maskAspectPreset = "自由";

    [ObservableProperty]
    private bool _lockMaskAspect;

    [ObservableProperty]
    private bool _useRandomMaskLibrary;

    public ObservableCollection<OverlayLibraryEntryRowViewModel> LibraryEntries { get; } = [];

    public bool HasLayers => Layers.Count > 0;

    public bool HasSelected => Selected is not null;

    public string ApplyCurrentVisualSettingsToAllLayersHint =>
        Selected is null
            ? "先在上方选中一条蒙版轨道，作为要复制的参数来源。"
            : Layers.Count < 2
                ? "至少需要 2 条蒙版轨道，导入第二条后按钮会自动亮起。"
                : $"将「{Selected.DisplayName}」当前参数（包含起始片段）同步到其余 {Layers.Count - 1} 条蒙版轨道。";

    public bool HasStatusMessage => !string.IsNullOrWhiteSpace(StatusMessage);

    public bool HasLibraryEntries => LibraryEntries.Count > 0;

    public string LibraryCountLabel =>
        LibraryValidCount == LibraryEntryCount
            ? $"素材库 {LibraryEntryCount} 条"
            : $"素材库 {LibraryValidCount}/{LibraryEntryCount} 条有效";

    public const double PreviewCanvasWidth = 216;

    public const double PreviewCanvasHeight = 384;

    public double PreviewMaskLeft => BoundsX * PreviewCanvasWidth;

    public double PreviewMaskTop => BoundsY * PreviewCanvasHeight;

    public double PreviewMaskWidth => BoundsWidth * PreviewCanvasWidth * Scale;

    public double PreviewMaskHeight => BoundsHeight * PreviewCanvasHeight * Scale;

    public double PreviewMaskCenterX => PreviewMaskLeft + PreviewMaskWidth / 2 + OffsetX * PreviewCanvasWidth;

    public double PreviewMaskCenterY => PreviewMaskTop + PreviewMaskHeight / 2 + OffsetY * PreviewCanvasHeight;

    public double PreviewMaskRenderLeft => PreviewMaskCenterX - PreviewMaskWidth / 2;

    public double PreviewMaskRenderTop => PreviewMaskCenterY - PreviewMaskHeight / 2;

    /// <summary>预览蓝框填充透明度（随叠层 Opacity 变化，便于判断盖住程度）。</summary>
    public double PreviewMaskFillOpacity => Opacity;

    /// <summary>
    /// 分割位置（归一化 0~1）：蒙版覆盖区底边 = BoundsY + BoundsHeight。
    /// 对齐剪映线性蒙版分割线；调节后只改高度，顶边 BoundsY 不变。
    /// </summary>
    public double SplitPosition
    {
        get => Math.Clamp(BoundsY + BoundsHeight, MinNormalizedSize, 1.0);
        set
        {
            var bottom = Math.Clamp(value, BoundsY + MinNormalizedSize, 1.0);
            var nextHeight = Math.Round(bottom - BoundsY, 4);
            if (Math.Abs(nextHeight - BoundsHeight) < 0.0001)
            {
                return;
            }

            BoundsHeight = nextHeight;
            OnPropertyChanged();
        }
    }

    /// <summary>预览说明：含透明度与是否可拖拽/改大小。</summary>
    public string PreviewInteractionHint =>
        HasSelected
            ? $"拖拽蓝框中心平移，拖边/角改大小；当前透明度 {Opacity:P0}（默认约 {OverlayLayer.GhostOverlayOpacity:P0}）。框内为蒙版首帧半透明示意。"
            : "选中一层后可在此预览并拖拽/缩放蒙版区域。";

    [ObservableProperty]
    private string? _selectedMaskThumbnailPath;

    [ObservableProperty]
    private string? _effectPreviewImagePath;

    [ObservableProperty]
    private string _effectPreviewHint = "请选择预览主片后，再刷新真实叠层静帧；这里不会用蒙版缩略图冒充合成预览。";

    public bool HasSelectedMaskThumbnail =>
        !string.IsNullOrWhiteSpace(SelectedMaskThumbnailPath) && File.Exists(SelectedMaskThumbnailPath);

    public bool HasEffectPreviewImage =>
        !string.IsNullOrWhiteSpace(EffectPreviewImagePath) && File.Exists(EffectPreviewImagePath);

    partial void OnSelectedChanged(OverlayLayerRowViewModel? value)
    {
        OnPropertyChanged(nameof(HasSelected));
        if (value is null)
        {
            InvalidateEffectPreview();
            return;
        }

        _isLoadingSelection = true;
        BoundsX = value.Bounds.X;
        BoundsY = value.Bounds.Y;
        BoundsWidth = value.Bounds.Width;
        BoundsHeight = value.Bounds.Height;
        Opacity = value.Opacity;
        Fit = value.Layer.Fit;
        StartClipIndex = value.StartClipIndex;
        Scale = value.Layer.Scale;
        OffsetX = value.Layer.OffsetX;
        OffsetY = value.Layer.OffsetY;
        RotationDegrees = value.Layer.RotationDegrees;
        Feather = value.Layer.Feather;
        TopFade = value.Layer.TopFade;
        SourceCropY = value.Layer.SourceCropY;
        LoadSourceCropBounds(value.Layer);
        MixOverlayAudio = value.Layer.AudioMode == OverlayAudioMode.Mix;
        _isLoadingSelection = false;
        NotifyPreviewChanged();
        InvalidateEffectPreview();
        _ = RefreshSelectedMaskPreviewAsync();
    }

    partial void OnBoundsXChanged(double value) => OnMaskFieldChanged();

    partial void OnBoundsYChanged(double value)
    {
        OnPropertyChanged(nameof(SplitPosition));
        OnMaskFieldChanged();
    }

    partial void OnBoundsWidthChanged(double value) => OnMaskFieldChanged();

    partial void OnBoundsHeightChanged(double value)
    {
        OnPropertyChanged(nameof(SplitPosition));
        OnMaskFieldChanged();
    }

    partial void OnOpacityChanged(double value)
    {
        SynchronizeOpacityPercent(value);
        OnMaskFieldChanged();
    }

    partial void OnStartClipIndexChanged(int value) => OnMaskFieldChanged();

    partial void OnScaleChanged(double value) => OnMaskFieldChanged();

    partial void OnOffsetXChanged(double value) => OnMaskFieldChanged();

    partial void OnOffsetYChanged(double value) => OnMaskFieldChanged();

    partial void OnRotationDegreesChanged(double value) => OnMaskFieldChanged();

    partial void OnFeatherChanged(double value) => OnMaskFieldChanged();

    partial void OnTopFadeChanged(double value) => OnMaskFieldChanged();

    partial void OnSourceCropYChanged(double value) => OnMaskFieldChanged();

    partial void OnMixOverlayAudioChanged(bool value) => OnMaskFieldChanged();

    private bool CanImportMaskMaterials() => !IsImporting;

    /// <summary>导入蒙版视频素材：多选文件 → 探测 → 加入列表并写入素材库。</summary>
    [RelayCommand(CanExecute = nameof(CanImportMaskMaterials))]
    private async Task ImportMaskMaterialsAsync()
    {
        _uiDispatcher.Invoke(() =>
        {
            IsImporting = true;
            StatusMessage = string.Empty;
        });

        try
        {
            IReadOnlyList<string>? paths;
            try
            {
                paths = _uiDispatcher.Invoke(() => _filePicker.PickVideoFiles(MaskVideoDialogTitle));
            }
            catch (Exception ex)
            {
                _uiDispatcher.Invoke(() => StatusMessage = $"无法打开文件选择对话框：{ToChineseOverlayError(ex)}");
                return;
            }

            if (paths is null || paths.Count == 0)
            {
                return;
            }

            await ImportPathsAsync(paths).ConfigureAwait(true);
        }
        finally
        {
            _uiDispatcher.Invoke(() => IsImporting = false);
        }
    }

    [RelayCommand]
    private void AddSelfGhost()
    {
        _layerCounter++;
        var name = $"自叠影 {_layerCounter}";
        // 时长用较长占位；入队时会按成片剩余时长截断，循环计数不影响自叠影画面。
        var layer = OverlayLayer.CreateSelfGhostPreset(TimeSpan.FromHours(1)) with
        {
            Name = name,
            ZIndex = _layerCounter - 1
        };
        AddLayerAndSelect(layer);
        StatusMessage = "已添加主片自叠影（渲染时把当前成片画面放大半透明叠回）。";
    }

    /// <summary>供测试与拖放等入口复用：按路径列表导入蒙版素材。</summary>
    internal async Task ImportPathsAsync(IReadOnlyList<string> paths)
    {
        ArgumentNullException.ThrowIfNull(paths);

        var successCount = 0;
        var failCount = 0;
        string? lastError = null;

        foreach (var rawPath in paths)
        {
            if (string.IsNullOrWhiteSpace(rawPath))
            {
                failCount++;
                lastError = "未选择有效的蒙版素材路径。";
                continue;
            }

            var path = rawPath;
            if (!File.Exists(path))
            {
                failCount++;
                lastError = $"蒙版素材不存在或无法访问：{path}";
                continue;
            }

            _uiDispatcher.Invoke(() => StatusMessage = $"正在探测蒙版素材…（{Path.GetFileName(path)}）");

            try
            {
                var info = await _mediaProbe.ProbeAsync(path, CancellationToken.None).ConfigureAwait(false);
                if (info.Duration <= TimeSpan.Zero)
                {
                    failCount++;
                    lastError = "蒙版素材时长无效（必须大于 0 秒）。";
                    continue;
                }

                _layerCounter++;
                var name = $"蒙版 {_layerCounter}";
                // 导入默认：上半红框 FreeCover + 中间→上垂直 alpha。
                var layer = OverlayLayer.CreateImportedMaskPreset(path, info.Duration) with
                {
                    Name = name,
                    ZIndex = _layerCounter - 1
                };

                string? thumbnailPath = null;
                try
                {
                    thumbnailPath = await EnsureThumbnailAsync(path).ConfigureAwait(false);
                }
                catch
                {
                    // 缩略图失败不阻断导入。
                }

                try
                {
                    await _libraryService.RegisterAsync(
                        path,
                        tags: ["UpperMask"],
                        thumbnailPath: thumbnailPath,
                        cancellationToken: CancellationToken.None).ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    // 入库失败不阻断加入工作台列表；状态里提示。
                    lastError = $"加入素材库失败：{ToChineseOverlayError(ex)}";
                }

                _uiDispatcher.Invoke(() => AddLayerAndSelect(layer));
                successCount++;
            }
            catch (MediaProbeException ex)
            {
                failCount++;
                lastError = $"蒙版素材探测失败：{ToChineseOverlayError(ex)}";
            }
            catch (Exception ex)
            {
                failCount++;
                lastError = $"导入蒙版失败：{ToChineseOverlayError(ex)}";
            }
        }

        await RefreshLibraryCountAsync().ConfigureAwait(true);

        _uiDispatcher.Invoke(() =>
        {
            if (successCount == 0 && failCount == 0)
            {
                return;
            }

            if (failCount == 0)
            {
                StatusMessage = successCount == 1
                    ? $"已导入 1 个蒙版素材。"
                    : $"已导入 {successCount} 个蒙版素材。";
                return;
            }

            StatusMessage = successCount == 0
                ? lastError ?? "导入蒙版失败。"
                : $"已导入 {successCount} 个，失败 {failCount} 个。" + (lastError is null ? string.Empty : $" 最近错误：{lastError}");
        });
    }

    [RelayCommand(CanExecute = nameof(CanMutateSelected))]
    private void RemoveSelected()
    {
        if (Selected is null)
        {
            return;
        }

        var name = Selected.DisplayName;
        _workbenchState.Remove(name);
        StatusMessage = $"已移除蒙版层「{name}」。";
    }

    [RelayCommand(CanExecute = nameof(CanMutateSelected))]
    private void ApplyBounds()
    {
        if (Selected is null)
        {
            return;
        }

        if (!TryBuildUpdatedLayer(out var updated, out var error))
        {
            StatusMessage = error!;
            return;
        }

        _workbenchState.Update(Selected.DisplayName, updated);
        InvalidateEffectPreview();
        StatusMessage = $"已更新蒙版层「{Selected.DisplayName}」。";
    }

    [RelayCommand]
    private async Task RefreshLibraryAsync() => await RefreshLibraryCountAsync().ConfigureAwait(true);

    private bool CanMutateSelected() => Selected is not null;

    private void OnMaskFieldChanged()
    {
        NotifyPreviewChanged();
        if (_isLoadingSelection || _isRefreshingState || Selected is null)
        {
            return;
        }

        if (!TryBuildUpdatedLayer(out var updated, out var error))
        {
            StatusMessage = error!;
            return;
        }

        _workbenchState.Update(Selected.DisplayName, updated);
        InvalidateEffectPreview();
        StatusMessage = string.Empty;
    }

    private bool TryBuildUpdatedLayer(out OverlayLayer updated, out string? error)
    {
        updated = Selected!.Layer;
        error = null;

        var bounds = NormalizedRect.Create(BoundsX, BoundsY, BoundsWidth, BoundsHeight);
        if (!bounds.IsSuccess)
        {
            error = bounds.Error;
            return false;
        }

        if (!TryBuildManualSourceCropBounds(out var sourceCropBounds, out error))
        {
            return false;
        }

        updated = BuildPreviewLayer(bounds.Value, sourceCropBounds);

        return true;
    }

    private OverlayLayer BuildPreviewLayer(NormalizedRect bounds)
    {
        var sourceCropBounds = TryBuildManualSourceCropBounds(out var manualSourceCropBounds, out _)
            ? manualSourceCropBounds
            : Selected!.Layer.SourceCropBounds;
        return BuildPreviewLayer(bounds, sourceCropBounds);
    }

    private OverlayLayer BuildPreviewLayer(NormalizedRect bounds, NormalizedRect? sourceCropBounds) =>
        Selected!.Layer with
        {
            Bounds = bounds,
            Opacity = Opacity,
            Fit = Fit,
            StartClipIndex = StartClipIndex,
            Scale = Scale,
            OffsetX = OffsetX,
            OffsetY = OffsetY,
            RotationDegrees = RotationDegrees,
            Feather = Feather,
            TopFade = TopFade,
            SourceCropY = SourceCropY,
            SourceCropBounds = sourceCropBounds,
            AudioMode = MixOverlayAudio ? OverlayAudioMode.Mix : OverlayAudioMode.Discard
        };

    private void NotifyPreviewChanged()
    {
        OnPropertyChanged(nameof(PreviewMaskLeft));
        OnPropertyChanged(nameof(PreviewMaskTop));
        OnPropertyChanged(nameof(PreviewMaskWidth));
        OnPropertyChanged(nameof(PreviewMaskHeight));
        OnPropertyChanged(nameof(PreviewMaskCenterX));
        OnPropertyChanged(nameof(PreviewMaskCenterY));
        OnPropertyChanged(nameof(PreviewMaskRenderLeft));
        OnPropertyChanged(nameof(PreviewMaskRenderTop));
        OnPropertyChanged(nameof(PreviewMaskFillOpacity));
        OnPropertyChanged(nameof(PreviewInteractionHint));
        OnPropertyChanged(nameof(SplitPosition));
        NotifyPreviewVisualEffectChanged();
    }

    private void OnWorkbenchStateChanged()
    {
        try
        {
            _uiDispatcher.Invoke(RefreshFromState);
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() => StatusMessage = $"刷新蒙版列表失败：{ToChineseOverlayError(ex)}");
        }

        if (!_isLoadingLayers)
        {
            EnqueueDebouncedLayerSave();
        }
    }

    private void RefreshFromState()
    {
        var previouslySelectedName = Selected?.DisplayName;
        _isRefreshingState = true;
        try
        {
            Selected = null;
            Layers.Clear();
            foreach (var layer in _workbenchState.Layers)
            {
                Layers.Add(new OverlayLayerRowViewModel(layer));
            }

            if (Layers.Count > 0)
            {
                _layerCounter = Math.Max(_layerCounter, Layers.Count);
            }

            OnPropertyChanged(nameof(HasLayers));
            Selected = Layers.FirstOrDefault(layer =>
                           string.Equals(layer.DisplayName, previouslySelectedName, StringComparison.Ordinal))
                       ?? Layers.LastOrDefault();
            OnPropertyChanged(nameof(ApplyCurrentVisualSettingsToAllLayersHint));
            ApplyCurrentVisualSettingsToAllLayersCommand.NotifyCanExecuteChanged();
            ApplyStartClipIndexToAllLayersCommand.NotifyCanExecuteChanged();
            PreviewSummary = Layers.Count switch
            {
                0 => "导入蒙版视频后，默认覆盖上半红框区（中间实、向上渐淡）；混剪页开启「启用蒙版叠加」即可渲染。",
                1 => "已导入 1 个蒙版素材，可调透明度/边界/变换；入队时启用重新编码。",
                _ => $"已导入 {Layers.Count} 个蒙版素材，按层级顺序叠加。"
            };
        }
        finally
        {
            _isRefreshingState = false;
        }
    }

    /// <summary>将新建层写入共享状态后，显式选中该层；普通刷新仍保留用户当前选择。</summary>
    private void AddLayerAndSelect(OverlayLayer layer)
    {
        _workbenchState.Add(layer);
        Selected = Layers.FirstOrDefault(row =>
            string.Equals(row.DisplayName, layer.Name, StringComparison.Ordinal));
    }

    /// <summary>从持久化 JSON 加载蒙版层轨道。</summary>
    public async Task EnsureLayersLoadedAsync()
    {
        OverlayLayersDocument document;
        try
        {
            document = await _layersService.LoadAsync().ConfigureAwait(false);
        }
        catch
        {
            return;
        }

        if (document.Layers.Count == 0)
        {
            return;
        }

        _isLoadingLayers = true;
        try
        {
            _uiDispatcher.Invoke(() =>
            {
                _workbenchState.ReplaceAll(document.Layers);
            });
        }
        finally
        {
            _isLoadingLayers = false;
        }
    }

    /// <summary>将当前蒙版层持久化到 JSON。</summary>
    private async Task SaveLayersAsync(long generation)
    {
        try
        {
            if (generation != Interlocked.Read(ref _saveGeneration))
            {
                return;
            }

            var layers = _workbenchState.CreateSnapshot();
            var document = new OverlayLayersDocument { Layers = layers };
            await _layersService.SaveAsync(document).ConfigureAwait(false);
        }
        catch
        {
        }
    }

    /// <summary>防抖保存：500ms 内不再触发新变更时落地。</summary>
    private void EnqueueDebouncedLayerSave()
    {
        var gen = Interlocked.Increment(ref _saveGeneration);
        _ = Task.Run(async () =>
        {
            await Task.Delay(500).ConfigureAwait(false);
            if (gen == Interlocked.Read(ref _saveGeneration))
            {
                await SaveLayersAsync(gen).ConfigureAwait(false);
            }
        });
    }

    private async Task RefreshLibraryCountAsync()
    {
        var document = await _libraryService.LoadAsync(cancellationToken: CancellationToken.None).ConfigureAwait(false);
        _uiDispatcher.Invoke(() => ApplyLibraryDocument(document));
    }

    private void ApplyLibraryDocument(OverlayLibraryDocument document)
    {
        lock (_libraryEntriesSync)
        {
            PreserveLibrarySelection(document);
            ClearLibraryEntryRows();
            var valid = 0;
            foreach (var entry in document.Entries
                         .OrderByDescending(e => e.LastUsedAt ?? DateTimeOffset.MinValue)
                         .ThenBy(e => e.FilePath, StringComparer.OrdinalIgnoreCase))
            {
                var resolvedThumb = entry.ThumbnailPath;
                if (string.IsNullOrWhiteSpace(resolvedThumb) || !File.Exists(resolvedThumb))
                {
                    var candidate = OverlayThumbnailStore.GetThumbnailPath(entry.FilePath);
                    if (File.Exists(candidate))
                    {
                        resolvedThumb = candidate;
                    }
                }

                var row = CreateLibraryEntryRow(
                    entry with { ThumbnailPath = resolvedThumb ?? entry.ThumbnailPath });
                if (row.FileExists)
                {
                    valid++;
                }

                LibraryEntries.Add(row);
                if (row.FileExists && !row.HasThumbnail && _frameExtractor is not null)
                {
                    _ = EnsureLibraryThumbnailAsync(row);
                }
            }

            LibraryEntryCount = document.Entries.Count;
            LibraryValidCount = valid;
            OnPropertyChanged(nameof(HasLibraryEntries));
            OnPropertyChanged(nameof(LibraryCountLabel));
            ClearLibraryEntriesCommand.NotifyCanExecuteChanged();
        }
    }

    private async Task EnsureLibraryThumbnailAsync(OverlayLibraryEntryRowViewModel row)
    {
        var thumb = await EnsureThumbnailAsync(row.FilePath).ConfigureAwait(false);
        if (thumb is null)
        {
            return;
        }

        OverlayLibraryEntry? updatedEntry = null;
        try
        {
            var result = await _libraryService.UpdateThumbnailIfEntryExistsAsync(
                    row.Id,
                    thumb,
                    cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            updatedEntry = result.Document.Entries.FirstOrDefault(entry => entry.Id == row.Id);
        }
        catch
        {
            return;
        }

        if (updatedEntry is null)
        {
            return;
        }

        _uiDispatcher.Invoke(() =>
        {
            lock (_libraryEntriesSync)
            {
                for (var i = 0; i < LibraryEntries.Count; i++)
                {
                    if (LibraryEntries[i].Id != row.Id)
                    {
                        continue;
                    }

                    LibraryEntries[i].PropertyChanged -= OnLibraryEntryRowPropertyChanged;
                    LibraryEntries[i] = CreateLibraryEntryRow(
                        updatedEntry);
                    break;
                }
            }
        });
    }

    /// <summary>清理素材库中路径失效的条目。</summary>
    [RelayCommand]
    private async Task PruneMissingLibraryEntriesAsync()
    {
        try
        {
            var (document, removed) = await _libraryService
                .PruneMissingAsync(cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplyLibraryDocument(document);
                StatusMessage = removed == 0
                    ? "素材库无失效条目。"
                    : $"已清理 {removed} 条失效素材库条目。";
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() => StatusMessage = $"清理素材库失败：{ToChineseOverlayError(ex)}");
        }
    }

    /// <summary>删除素材库中选中的单条条目（不删磁盘文件）。</summary>
    [RelayCommand]
    private async Task DeleteLibraryEntryAsync(OverlayLibraryEntryRowViewModel? entry)
    {
        if (entry is null)
        {
            return;
        }

        try
        {
            var (document, removed) = await _libraryService
                .DeleteEntryAsync(entry.Id, cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplyLibraryDocument(document);
                StatusMessage = removed
                    ? $"已从素材库删除「{entry.FileName}」。"
                    : "素材库中未找到该条目。";
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() => StatusMessage = $"删除素材库条目失败：{ToChineseOverlayError(ex)}");
        }
    }

    /// <summary>清空蒙版素材库全部条目（不删磁盘文件）。</summary>
    [RelayCommand(CanExecute = nameof(HasLibraryEntries))]
    private async Task ClearLibraryEntriesAsync()
    {
        try
        {
            var (document, removed) = await _libraryService
                .ClearAllAsync(cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplyLibraryDocument(document);
                StatusMessage = removed == 0
                    ? "素材库已为空。"
                    : $"已清空素材库（{removed} 条）；磁盘上的视频文件未删除。";
                ClearLibraryEntriesCommand.NotifyCanExecuteChanged();
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() => StatusMessage = $"清空素材库失败：{ToChineseOverlayError(ex)}");
        }
    }

    /// <summary>命中预览蓝框：边/角为缩放，内部为平移。</summary>
    public PreviewHitZone HitTestPreview(double canvasX, double canvasY)
    {
        if (!HasSelected)
        {
            return PreviewHitZone.None;
        }

        return PreviewHitTester.HitTest(
            canvasX,
            canvasY,
            PreviewMaskRenderLeft,
            PreviewMaskRenderTop,
            PreviewMaskWidth,
            PreviewMaskHeight);
    }

    /// <summary>拖拽预览区蒙版框：平移或按边/角调整 Bounds 宽高。</summary>
    public void ApplyPreviewDragDelta(PreviewHitZone zone, double deltaCanvasX, double deltaCanvasY)
    {
        if (!HasSelected || zone is PreviewHitZone.None)
        {
            return;
        }

        if (zone == PreviewHitZone.Move)
        {
            var bounds = PreviewRectangleManipulator.Move(
                new NormalizedRect(BoundsX, BoundsY, BoundsWidth, BoundsHeight),
                deltaCanvasX,
                deltaCanvasY,
                PreviewCanvasWidth,
                PreviewCanvasHeight);
            BoundsX = bounds.X;
            BoundsY = bounds.Y;
            return;
        }

        ApplyPreviewResize(zone, deltaCanvasX, deltaCanvasY);
    }

    /// <summary>兼容旧调用：默认按平移处理。</summary>
    public void ApplyPreviewDragDelta(double deltaCanvasX, double deltaCanvasY) =>
        ApplyPreviewDragDelta(PreviewHitZone.Move, deltaCanvasX, deltaCanvasY);

    /// <summary>按边/角拖拽调整归一化 Bounds（保持在画布内，最小边长 <see cref="MinNormalizedSize"/>）。</summary>
    public void ApplyPreviewResize(PreviewHitZone zone, double deltaCanvasX, double deltaCanvasY)
    {
        if (!HasSelected)
        {
            return;
        }

        var bounds = PreviewRectangleManipulator.Resize(
            new NormalizedRect(BoundsX, BoundsY, BoundsWidth, BoundsHeight),
            zone,
            deltaCanvasX,
            deltaCanvasY,
            PreviewCanvasWidth,
            PreviewCanvasHeight,
            MinNormalizedSize,
            Scale);
        BoundsX = bounds.X;
        BoundsY = bounds.Y;
        BoundsWidth = bounds.Width;
        BoundsHeight = bounds.Height;
    }

    /// <summary>用主片路径合成接近成片的叠层静帧预览（蒙版页可选手动刷新）。</summary>
    public async Task RefreshEffectPreviewAsync(string? baseVideoPath = null)
    {
        var selected = Selected;
        var effectiveBaseVideoPath = string.IsNullOrWhiteSpace(baseVideoPath)
            ? EffectPreviewBaseVideoPath
            : baseVideoPath;

        if (_frameExtractor is null || selected is null)
        {
            _uiDispatcher.Invoke(() => InvalidateEffectPreview("合成预览组件未就绪或未选中蒙版层。"));
            return;
        }

        var boundsResult = NormalizedRect.Create(BoundsX, BoundsY, BoundsWidth, BoundsHeight);
        var bounds = boundsResult.IsSuccess ? boundsResult.Value! : selected.Layer.Bounds;
        var previewLayer = BuildPreviewLayer(bounds);
        if (string.IsNullOrWhiteSpace(effectiveBaseVideoPath) || !File.Exists(effectiveBaseVideoPath))
        {
            _uiDispatcher.Invoke(() => InvalidateEffectPreview("请选择预览主片后，再刷新真实叠层静帧。"));
            return;
        }

        if (!previewLayer.IsSelfSource && !File.Exists(previewLayer.SourcePath))
        {
            _uiDispatcher.Invoke(() => InvalidateEffectPreview("蒙版素材不存在，无法生成合成预览。"));
            return;
        }

        var generation = Interlocked.Increment(ref _previewGeneration);
        var output = Path.Combine(
            Path.GetTempPath(),
            "JingXu",
            "overlay-preview",
            $"mask-composite-{generation}.jpg");

        var request = new OverlayCompositePreviewRequest(
            effectiveBaseVideoPath,
            previewLayer,
            output,
            (int)PreviewCanvasWidth,
            (int)PreviewCanvasHeight);

        var result = await _frameExtractor
            .ExtractOverlayCompositePreviewAsync(request, CancellationToken.None)
            .ConfigureAwait(false);

        if (generation != _previewGeneration)
        {
            return;
        }

        _uiDispatcher.Invoke(() =>
        {
            if (generation != _previewGeneration)
            {
                return;
            }

            if (result.IsSuccess)
            {
                EffectPreviewImagePath = result.Value;
                EffectPreviewHint = "真实合成静帧（主片首帧 + 当前蒙版层）；已通过与成片相同的叠层滤镜生成。";
            }
            else
            {
                EffectPreviewImagePath = null;
                EffectPreviewHint = $"合成预览失败，未显示蒙版缩略图。{result.Error}";
            }

            OnPropertyChanged(nameof(HasEffectPreviewImage));
        });
    }

    private async Task RefreshSelectedMaskPreviewAsync()
    {
        var selected = Selected;
        if (selected is null || selected.Layer.IsSelfSource || string.IsNullOrWhiteSpace(selected.Layer.SourcePath))
        {
            _uiDispatcher.Invoke(() =>
            {
                SelectedMaskThumbnailPath = null;
                OnPropertyChanged(nameof(HasSelectedMaskThumbnail));
            });
            return;
        }

        var thumb = await EnsureThumbnailAsync(selected.Layer.SourcePath).ConfigureAwait(false);
        _uiDispatcher.Invoke(() =>
        {
            if (!ReferenceEquals(Selected, selected))
            {
                return;
            }

            SelectedMaskThumbnailPath = thumb;
            OnPropertyChanged(nameof(HasSelectedMaskThumbnail));
        });
    }

    private async Task<string?> EnsureThumbnailAsync(string mediaPath)
    {
        if (_frameExtractor is null || !File.Exists(mediaPath))
        {
            return null;
        }

        var thumbPath = OverlayThumbnailStore.GetThumbnailPath(mediaPath);
        if (File.Exists(thumbPath) && new FileInfo(thumbPath).Length > 0)
        {
            return thumbPath;
        }

        var result = await _frameExtractor
            .ExtractFirstFrameAsync(mediaPath, thumbPath, CancellationToken.None)
            .ConfigureAwait(false);
        return result.IsSuccess ? result.Value : null;
    }

    /// <summary>将选中层的尺寸（宽高+缩放）统一应用到全部蒙版层。</summary>
    [RelayCommand(CanExecute = nameof(HasSelected))]
    private void ApplyUnifiedSizeToAll()
    {
        if (Selected is null)
        {
            StatusMessage = "请先选中一层并确认参数有效。";
            return;
        }

        if (!TryBuildUpdatedLayer(out var template, out var error) || template is null)
        {
            StatusMessage = error ?? "请先选中一层并确认参数有效。";
            return;
        }

        var updated = new List<OverlayLayer>();
        foreach (var layer in _workbenchState.Layers)
        {
            var bounds = NormalizedRect.Create(
                layer.Bounds.X,
                layer.Bounds.Y,
                template.Bounds.Width,
                template.Bounds.Height);
            if (!bounds.IsSuccess)
            {
                StatusMessage = bounds.Error ?? "统一尺寸时边界无效。";
                return;
            }

            updated.Add(layer with
            {
                Bounds = bounds.Value!,
                Scale = template.Scale
            });
        }

        _workbenchState.ReplaceAll(updated);
        StatusMessage = $"已将尺寸统一为 {template.Bounds.Width:0.##}×{template.Bounds.Height:0.##}、缩放 {template.Scale:P0}（共 {updated.Count} 层）。";
    }

    /// <summary>按预设比例调整选中层宽高（保持中心，宽度优先）。</summary>
    [RelayCommand(CanExecute = nameof(HasSelected))]
    private void ApplyMaskAspectPreset(string? preset)
    {
        if (Selected is null)
        {
            return;
        }

        var key = string.IsNullOrWhiteSpace(preset) ? MaskAspectPreset : preset.Trim();
        MaskAspectPreset = key;
        if (key is "自由" or "Free")
        {
            LockMaskAspect = false;
            StatusMessage = "已切换为自由比例。";
            return;
        }

        double ratio = key switch
        {
            "9:16" => 9.0 / 16.0,
            "16:9" => 16.0 / 9.0,
            "1:1" => 1.0,
            "4:5" => 4.0 / 5.0,
            "3:4" => 3.0 / 4.0,
            _ => 0
        };
        if (ratio <= 0)
        {
            StatusMessage = $"未知比例预设：{key}";
            return;
        }

        LockMaskAspect = true;
        var centerX = BoundsX + BoundsWidth / 2;
        var centerY = BoundsY + BoundsHeight / 2;
        var area = Math.Max(0.01, BoundsWidth * BoundsHeight);
        var newWidth = Math.Clamp(Math.Sqrt(area * ratio), 0.05, 1.0);
        var newHeight = Math.Clamp(newWidth / ratio, 0.05, 1.0);
        if (newWidth > 1)
        {
            newWidth = 1;
            newHeight = Math.Clamp(newWidth / ratio, 0.05, 1.0);
        }

        if (newHeight > 1)
        {
            newHeight = 1;
            newWidth = Math.Clamp(newHeight * ratio, 0.05, 1.0);
        }

        BoundsWidth = Math.Round(newWidth, 4);
        BoundsHeight = Math.Round(newHeight, 4);
        BoundsX = Math.Clamp(centerX - BoundsWidth / 2, 0, 1 - BoundsWidth);
        BoundsY = Math.Clamp(centerY - BoundsHeight / 2, 0, 1 - BoundsHeight);
        StatusMessage = $"已应用蒙版比例 {key}。";
        OnMaskFieldChanged();
    }

    public IReadOnlyList<OverlayLayer> BuildLayersForPlan(
        int seed,
        IReadOnlyList<OverlayLibraryEntry>? libraryEntries = null,
        long planOrdinal = 0)
    {
        var templates = _workbenchState.CreateSnapshot();
        if (!UseRandomMaskLibrary)
        {
            return templates;
        }

        var entries = libraryEntries;
        if (entries is null || entries.Count == 0)
        {
            entries = LoadLibraryEntriesAsync().GetAwaiter().GetResult();
        }

        if (entries.Count == 0)
        {
            return templates;
        }

        var entry = OverlaySourceSelector.SelectReplacement(entries, seed, planOrdinal);
        var template = Selected?.Layer is { IsSelfSource: false } selectedLayer
            ? selectedLayer
            : templates.FirstOrDefault(layer => !layer.IsSelfSource);
        if (template is null)
        {
            var layer = OverlayLayer.CreateImportedMaskPreset(
                entry.FilePath,
                TimeSpan.FromSeconds(OverlayEnqueueResolver.DefaultLibrarySourceDurationSeconds));
            return [entry.VisualSettings is null ? layer : layer.WithVisualSettings(entry.VisualSettings)];
        }

        // 随机模式只替换当前选中的一条外部蒙版，不把全部轨道继续叠加到同一条成片。
        return [template with { SourcePath = entry.FilePath }];
    }

    private async Task<IReadOnlyList<OverlayLibraryEntry>> LoadLibraryEntriesAsync()
    {
        try
        {
            var document = await _libraryService.LoadAsync(cancellationToken: CancellationToken.None).ConfigureAwait(false);
            return document.Entries;
        }
        catch
        {
            return [];
        }
    }

    private static string ToChineseOverlayError(Exception ex)
    {
        if (ex is MediaProbeException probeEx)
        {
            var detail = probeEx.Message;
            if (!string.IsNullOrWhiteSpace(probeEx.StderrSummary))
            {
                detail = $"{detail}（{probeEx.StderrSummary}）";
            }

            return detail;
        }

        var message = ex.GetBaseException().Message;
        return string.IsNullOrWhiteSpace(message) ? "未知错误，请查看 %LOCALAPPDATA%\\JingXu\\logs\\。" : message;
    }
}

/// <summary>蒙版层列表行。</summary>
public sealed class OverlayLayerRowViewModel
{
    public OverlayLayerRowViewModel(OverlayLayer layer)
    {
        Layer = layer;
        DisplayName = layer.Name;
        SourceFileName = layer.IsSelfSource ? "主片自叠影" : Path.GetFileName(layer.SourcePath);
        // 列表不再展示三类模式名；导入素材统一标为「蒙版素材」。
        ModeLabel = layer.IsSelfSource ? "自叠影" : "蒙版素材";
        BoundsText = $"{layer.Bounds.X:0.##},{layer.Bounds.Y:0.##} · {layer.Bounds.Width:0.##}×{layer.Bounds.Height:0.##}";
        var fadeText = layer.TopFade > 0.000001 ? $" · 上向渐变 {layer.TopFade:0.##}" : string.Empty;
        var cropText = Math.Abs(layer.SourceCropY) > 0.000001 ? $" · 选取 {layer.SourceCropY:0.##}" : string.Empty;
        TransformText = $"缩放 {layer.Scale:P0} · 旋转 {layer.RotationDegrees:0.#}° · 羽化 {layer.Feather:P0}{fadeText}{cropText}";
        Opacity = layer.Opacity;
        StartClipIndex = layer.StartClipIndex;
        ZIndex = layer.ZIndex;
    }

    public OverlayLayer Layer { get; }

    /// <summary>列表展示名（勿用 <c>Name</c>，避免与 WPF <c>FrameworkElement.Name</c> 及 TwoWay 绑定冲突）。</summary>
    public string DisplayName { get; }

    public string SourceFileName { get; }

    public string ModeLabel { get; }

    public string BoundsText { get; }

    public string TransformText { get; }

    public NormalizedRect Bounds => Layer.Bounds;

    public double Opacity { get; }

    public int StartClipIndex { get; }

    public int ZIndex { get; }
}

/// <summary>蒙版素材库可视化行。</summary>
public sealed partial class OverlayLibraryEntryRowViewModel : ObservableObject
{
    public OverlayLibraryEntryRowViewModel(
        OverlayLibraryEntry entry,
        bool isSelectedForBatchApply = false)
    {
        Entry = entry;
        Id = entry.Id;
        FilePath = entry.FilePath;
        FileName = Path.GetFileName(entry.FilePath);
        FileExists = File.Exists(entry.FilePath);
        StatusLabel = FileExists ? "可用" : "缺失";
        TagsText = entry.Tags.Count == 0 ? "—" : string.Join(" · ", entry.Tags);
        LastUsedText = entry.LastUsedAt is null
            ? "尚未使用"
            : entry.LastUsedAt.Value.ToLocalTime().ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
        ThumbnailPath = !string.IsNullOrWhiteSpace(entry.ThumbnailPath) && File.Exists(entry.ThumbnailPath)
            ? entry.ThumbnailPath
            : null;
        _isSelectedForBatchApply = isSelectedForBatchApply;
    }

    public OverlayLibraryEntry Entry { get; }

    public Guid Id { get; }

    public string FilePath { get; }

    public string FileName { get; }

    public bool FileExists { get; }

    public string StatusLabel { get; }

    public string TagsText { get; }

    public string LastUsedText { get; }

    public string? ThumbnailPath { get; }

    public bool HasThumbnail => !string.IsNullOrWhiteSpace(ThumbnailPath);

    [ObservableProperty]
    private bool _isSelectedForBatchApply;
}
