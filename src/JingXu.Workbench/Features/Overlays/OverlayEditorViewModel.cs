using System.Collections.ObjectModel;
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

/// <summary>蒙版工作台视图模型。</summary>
public sealed partial class OverlayEditorViewModel : WorkspaceModuleViewModel
{
    private readonly IMediaFilePicker _filePicker;
    private readonly IMediaProbe _mediaProbe;
    private readonly IUiDispatcher _uiDispatcher;
    private readonly OverlayLibraryService _libraryService;
    private readonly OverlayWorkbenchState _workbenchState;
    private int _layerCounter;
    private bool _isLoadingSelection;
    private bool _isRefreshingState;

    public OverlayEditorViewModel(
        IMediaFilePicker filePicker,
        OverlayWorkbenchState workbenchState,
        IMediaProbe mediaProbe,
        IUiDispatcher uiDispatcher,
        OverlayLibraryService? libraryService = null)
    {
        _filePicker = filePicker ?? throw new ArgumentNullException(nameof(filePicker));
        _workbenchState = workbenchState ?? throw new ArgumentNullException(nameof(workbenchState));
        _mediaProbe = mediaProbe ?? throw new ArgumentNullException(nameof(mediaProbe));
        _uiDispatcher = uiDispatcher ?? throw new ArgumentNullException(nameof(uiDispatcher));
        _libraryService = libraryService ?? new OverlayLibraryService(
            new AtomicJsonStore<OverlayLibraryDocument>(OverlayLibraryDocument.CurrentSchemaVersion));
        _workbenchState.Changed += OnWorkbenchStateChanged;
        RefreshFromState();
    }

    public override WorkspaceModule ModuleKind => WorkspaceModule.Overlays;

    public override string Title => "蒙版模板";

    public ObservableCollection<OverlayLayerRowViewModel> Layers { get; } = [];

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RemoveSelectedCommand))]
    [NotifyCanExecuteChangedFor(nameof(RegisterToLibraryCommand))]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    [NotifyCanExecuteChangedFor(nameof(AddFreeCoverCommand))]
    [NotifyCanExecuteChangedFor(nameof(AddFullFrameCommand))]
    [NotifyCanExecuteChangedFor(nameof(AddShapeMaskCommand))]
    private OverlayLayerRowViewModel? _selected;

    [ObservableProperty]
    private string _previewSummary = "添加蒙版层后，将叠加到混剪成片中。";

    [ObservableProperty]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _boundsX;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _boundsY;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _boundsWidth = 1;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _boundsHeight = 0.48;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private double _opacity = 1;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private int _startClipIndex = 1;

    [ObservableProperty]
    private double _scale = OverlayLayer.DefaultScale;

    [ObservableProperty]
    private double _offsetX;

    [ObservableProperty]
    private double _offsetY;

    [ObservableProperty]
    private double _rotationDegrees;

    [ObservableProperty]
    private double _feather;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private ShapeKind _selectedShape = ShapeKind.Rectangle;

    [ObservableProperty]
    private string? _alphaPngPath;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyBoundsCommand))]
    private bool _mixOverlayAudio;

    [ObservableProperty]
    private int _libraryEntryCount;

    /// <summary>形状遮罩可选几何类型（含导入 PNG）。</summary>
    public IReadOnlyList<ShapeKind> AvailableShapes { get; } =
    [
        ShapeKind.Rectangle,
        ShapeKind.RoundedRectangle,
        ShapeKind.Ellipse,
        ShapeKind.ImportedPng
    ];

    public bool IsShapeMaskSelected => Selected?.Layer.Mode == OverlayMode.ShapeMask;

    public bool IsImportedPngShape => IsShapeMaskSelected && SelectedShape == ShapeKind.ImportedPng;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(AddFreeCoverCommand))]
    [NotifyCanExecuteChangedFor(nameof(AddFullFrameCommand))]
    [NotifyCanExecuteChangedFor(nameof(AddShapeMaskCommand))]
    private bool _isAddingLayer;

    public bool HasLayers => Layers.Count > 0;

    public bool HasSelected => Selected is not null;

    public bool HasStatusMessage => !string.IsNullOrWhiteSpace(StatusMessage);

    public const double PreviewCanvasWidth = 180;

    public const double PreviewCanvasHeight = 320;

    public double PreviewMaskLeft => BoundsX * PreviewCanvasWidth;

    public double PreviewMaskTop => BoundsY * PreviewCanvasHeight;

    public double PreviewMaskWidth => BoundsWidth * PreviewCanvasWidth * Scale;

    public double PreviewMaskHeight => BoundsHeight * PreviewCanvasHeight * Scale;

    public double PreviewMaskCenterX => PreviewMaskLeft + PreviewMaskWidth / 2 + OffsetX * PreviewCanvasWidth;

    public double PreviewMaskCenterY => PreviewMaskTop + PreviewMaskHeight / 2 + OffsetY * PreviewCanvasHeight;

    public double PreviewMaskRenderLeft => PreviewMaskCenterX - PreviewMaskWidth / 2;

    public double PreviewMaskRenderTop => PreviewMaskCenterY - PreviewMaskHeight / 2;

    partial void OnSelectedChanged(OverlayLayerRowViewModel? value)
    {
        OnPropertyChanged(nameof(HasSelected));
        OnPropertyChanged(nameof(IsShapeMaskSelected));
        OnPropertyChanged(nameof(IsImportedPngShape));
        if (value is null)
        {
            return;
        }

        _isLoadingSelection = true;
        BoundsX = value.Bounds.X;
        BoundsY = value.Bounds.Y;
        BoundsWidth = value.Bounds.Width;
        BoundsHeight = value.Bounds.Height;
        Opacity = value.Opacity;
        StartClipIndex = value.StartClipIndex;
        Scale = value.Layer.Scale;
        OffsetX = value.Layer.OffsetX;
        OffsetY = value.Layer.OffsetY;
        RotationDegrees = value.Layer.RotationDegrees;
        Feather = value.Layer.Feather;
        SelectedShape = value.Layer.Shape;
        AlphaPngPath = value.Layer.AlphaPngPath;
        MixOverlayAudio = value.Layer.AudioMode == OverlayAudioMode.Mix;
        _isLoadingSelection = false;
        NotifyPreviewChanged();
        OnPropertyChanged(nameof(IsShapeMaskSelected));
        OnPropertyChanged(nameof(IsImportedPngShape));
    }

    partial void OnBoundsXChanged(double value) => OnMaskFieldChanged();

    partial void OnBoundsYChanged(double value) => OnMaskFieldChanged();

    partial void OnBoundsWidthChanged(double value) => OnMaskFieldChanged();

    partial void OnBoundsHeightChanged(double value) => OnMaskFieldChanged();

    partial void OnOpacityChanged(double value) => OnMaskFieldChanged();

    partial void OnStartClipIndexChanged(int value) => OnMaskFieldChanged();

    partial void OnScaleChanged(double value) => OnMaskFieldChanged();

    partial void OnOffsetXChanged(double value) => OnMaskFieldChanged();

    partial void OnOffsetYChanged(double value) => OnMaskFieldChanged();

    partial void OnRotationDegreesChanged(double value) => OnMaskFieldChanged();

    partial void OnFeatherChanged(double value) => OnMaskFieldChanged();

    partial void OnSelectedShapeChanged(ShapeKind value)
    {
        OnPropertyChanged(nameof(IsImportedPngShape));
        OnMaskFieldChanged();
    }

    partial void OnAlphaPngPathChanged(string? value) => OnMaskFieldChanged();

    partial void OnMixOverlayAudioChanged(bool value) => OnMaskFieldChanged();

    private bool CanAddLayer() => !IsAddingLayer;

    [RelayCommand(CanExecute = nameof(CanAddLayer))]
    private async Task AddFreeCoverAsync() =>
        await AddLayerAsync(OverlayMode.FreeCover).ConfigureAwait(true);

    [RelayCommand(CanExecute = nameof(CanAddLayer))]
    private async Task AddFullFrameAsync() =>
        await AddLayerAsync(OverlayMode.FullFrameLowOpacity).ConfigureAwait(true);

    [RelayCommand(CanExecute = nameof(CanAddLayer))]
    private async Task AddShapeMaskAsync() =>
        await AddLayerAsync(OverlayMode.ShapeMask).ConfigureAwait(true);

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
        StatusMessage = $"已更新蒙版层「{Selected.DisplayName}」。";
    }

    [RelayCommand(CanExecute = nameof(CanMutateSelected))]
    private async Task RegisterToLibraryAsync()
    {
        if (Selected is null)
        {
            return;
        }

        try
        {
            await _libraryService.RegisterAsync(
                Selected.Layer.SourcePath,
                tags: [Selected.Layer.Mode.ToString()],
                cancellationToken: CancellationToken.None).ConfigureAwait(true);
            await RefreshLibraryCountAsync().ConfigureAwait(true);
            _uiDispatcher.Invoke(() => StatusMessage = $"已将「{Path.GetFileName(Selected.Layer.SourcePath)}」加入蒙版素材库。");
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() => StatusMessage = $"加入素材库失败：{ToChineseOverlayError(ex)}");
        }
    }

    [RelayCommand(CanExecute = nameof(CanMutateSelected))]
    private void PickAlphaPng()
    {
        if (Selected is null || Selected.Layer.Mode != OverlayMode.ShapeMask)
        {
            return;
        }

        var path = _filePicker.PickImageFile();
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        SelectedShape = ShapeKind.ImportedPng;
        AlphaPngPath = path;
        StatusMessage = $"已选择 PNG 遮罩：{Path.GetFileName(path)}";
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

        updated = Selected.Layer with
        {
            Bounds = bounds.Value,
            Opacity = Opacity,
            StartClipIndex = StartClipIndex,
            Scale = Scale,
            OffsetX = OffsetX,
            OffsetY = OffsetY,
            RotationDegrees = RotationDegrees,
            Feather = Feather,
            Shape = Selected.Layer.Mode == OverlayMode.ShapeMask ? SelectedShape : Selected.Layer.Shape,
            AlphaPngPath = Selected.Layer.Mode == OverlayMode.ShapeMask && SelectedShape == ShapeKind.ImportedPng
                ? AlphaPngPath
                : null,
            AudioMode = MixOverlayAudio ? OverlayAudioMode.Mix : OverlayAudioMode.Discard
        };

        return true;
    }

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
    }

    private async Task AddLayerAsync(OverlayMode mode)
    {
        _uiDispatcher.Invoke(() =>
        {
            IsAddingLayer = true;
            StatusMessage = string.Empty;
        });

        try
        {
            IReadOnlyList<string>? paths;
            try
            {
                paths = _uiDispatcher.Invoke(() => _filePicker.PickVideoFiles());
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

            var path = paths[0];
            if (string.IsNullOrWhiteSpace(path))
            {
                _uiDispatcher.Invoke(() => StatusMessage = "未选择有效的蒙版素材路径。");
                return;
            }

            if (!File.Exists(path))
            {
                _uiDispatcher.Invoke(() => StatusMessage = $"蒙版素材不存在或无法访问：{path}");
                return;
            }

            _uiDispatcher.Invoke(() => StatusMessage = "正在探测蒙版素材…");

            var info = await _mediaProbe.ProbeAsync(path, CancellationToken.None).ConfigureAwait(false);
            if (info.Duration <= TimeSpan.Zero)
            {
                _uiDispatcher.Invoke(() => StatusMessage = "蒙版素材时长无效（必须大于 0 秒）。");
                return;
            }

            _layerCounter++;
            var name = $"蒙版 {_layerCounter}";

            var layer = mode switch
            {
                OverlayMode.FreeCover => OverlayLayer.CreateScreenshotPreset(path, info.Duration) with { Name = name, ZIndex = _layerCounter - 1 },
                OverlayMode.FullFrameLowOpacity => OverlayLayer.CreateFullFramePreset(path, info.Duration) with { Name = name, ZIndex = _layerCounter - 1 },
                OverlayMode.ShapeMask => OverlayLayer.CreateShapeMask(path, info.Duration, new NormalizedRect(0.1, 0.1, 0.8, 0.4)) with { Name = name, ZIndex = _layerCounter - 1 },
                _ => throw new ArgumentOutOfRangeException(nameof(mode), mode, null)
            };

            _uiDispatcher.Invoke(() =>
            {
                _workbenchState.Add(layer);
                StatusMessage = $"已添加{ModeLabel(mode)}：{Path.GetFileName(path)}。";
            });
        }
        catch (MediaProbeException ex)
        {
            _uiDispatcher.Invoke(() => StatusMessage = $"蒙版素材探测失败：{ToChineseOverlayError(ex)}");
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() => StatusMessage = $"添加蒙版失败：{ToChineseOverlayError(ex)}");
        }
        finally
        {
            _uiDispatcher.Invoke(() => IsAddingLayer = false);
        }
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
    }

    private void RefreshFromState()
    {
        _isRefreshingState = true;
        try
        {
            Selected = null;
            Layers.Clear();
            foreach (var layer in _workbenchState.Layers)
            {
                Layers.Add(new OverlayLayerRowViewModel(layer));
            }

            OnPropertyChanged(nameof(HasLayers));
            Selected = Layers.LastOrDefault();
            PreviewSummary = Layers.Count switch
            {
                0 => "添加蒙版层后，在混剪模块入队时将自动叠加到成片。",
                1 => $"已配置 1 层蒙版（{Selected?.ModeLabel}），入队时启用重新编码。",
                _ => $"已配置 {Layers.Count} 层蒙版，按层级顺序叠加。"
            };
        }
        finally
        {
            _isRefreshingState = false;
        }
    }

    private async Task RefreshLibraryCountAsync()
    {
        var document = await _libraryService.LoadAsync(cancellationToken: CancellationToken.None).ConfigureAwait(false);
        _uiDispatcher.Invoke(() => LibraryEntryCount = document.Entries.Count);
    }

    private static string ModeLabel(OverlayMode mode) => mode switch
    {
        OverlayMode.FreeCover => "自由覆盖层",
        OverlayMode.FullFrameLowOpacity => "全屏低透明度覆盖",
        OverlayMode.ShapeMask => "形状遮罩",
        _ => mode.ToString()
    };

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
        SourceFileName = Path.GetFileName(layer.SourcePath);
        ModeLabel = layer.Mode switch
        {
            OverlayMode.FreeCover => "自由覆盖",
            OverlayMode.FullFrameLowOpacity => "全屏低透明",
            OverlayMode.ShapeMask => "形状遮罩",
            _ => layer.Mode.ToString()
        };
        BoundsText = $"{layer.Bounds.X:0.##},{layer.Bounds.Y:0.##} · {layer.Bounds.Width:0.##}×{layer.Bounds.Height:0.##}";
        TransformText = $"缩放 {layer.Scale:P0} · 旋转 {layer.RotationDegrees:0.#}° · 羽化 {layer.Feather:P0}";
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
