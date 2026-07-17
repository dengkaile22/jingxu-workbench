using System.Collections.ObjectModel;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Stickers;
using JingXu.Workbench.Features.Shell;

namespace JingXu.Workbench.Features.Stickers;

public sealed partial class StickerEditorViewModel : WorkspaceModuleViewModel
{
    private readonly StickerLibraryService _libraryService;
    private readonly IMediaFilePicker _filePicker;
    private readonly IUiDispatcher _uiDispatcher;
    private readonly IStickerLibraryClearConfirmation _clearConfirmation;

    public StickerEditorViewModel(
        StickerLibraryService libraryService,
        IMediaFilePicker filePicker,
        IUiDispatcher uiDispatcher,
        IStickerLibraryClearConfirmation? clearConfirmation = null)
    {
        _libraryService = libraryService;
        _filePicker = filePicker;
        _uiDispatcher = uiDispatcher;
        _clearConfirmation = clearConfirmation ?? new WpfStickerLibraryClearConfirmation();

        Tracks.CollectionChanged += (_, _) =>
        {
            OnPropertyChanged(nameof(HasTracks));
            if (SelectedTrack is null || !Tracks.Contains(SelectedTrack))
            {
                SelectedTrack = Tracks.FirstOrDefault();
            }
        };
        LibraryEntries.CollectionChanged += (_, _) =>
        {
            OnPropertyChanged(nameof(HasLibraryEntries));
            ClearStickerLibraryCommand.NotifyCanExecuteChanged();
        };
    }

    public override string Title => "贴纸轨道";

    public override WorkspaceModule ModuleKind => WorkspaceModule.Stickers;

    [ObservableProperty]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    private bool _hasStatusMessage;

    [ObservableProperty]
    private StickerTrackRowViewModel? _selectedTrack;

    [ObservableProperty]
    private bool _useRandomStickerLibrary;

    [ObservableProperty]
    private StickerAspectMode _selectedAspectMode = StickerAspectMode.FollowComposition;

    private int _compositionCanvasWidth = 1080;
    private int _compositionCanvasHeight = 1920;

    /// <summary>
    /// 供 XAML ComboBox 绑定；避免 ObjectDataProvider 跨程序集解析 Domain 枚举失败。
    /// </summary>
    public static IReadOnlyList<StickerAspectMode> AspectModeOptions { get; } = Enum.GetValues<StickerAspectMode>();

    /// <summary>
    /// 供贴纸轨道「固定比例」ComboBox 绑定（DataTemplate 内用 x:Static）。
    /// </summary>
    public static IReadOnlyList<FixedAspectRatio> FixedAspectRatioOptions { get; } = Enum.GetValues<FixedAspectRatio>();

    public ObservableCollection<StickerTrackRowViewModel> Tracks { get; } = [];

    public ObservableCollection<StickerLibraryEntryRowViewModel> LibraryEntries { get; } = [];

    public bool HasLibraryEntries => LibraryEntries.Count > 0;

    public bool HasTracks => Tracks.Count > 0;

    public bool HasSelectedTrack => SelectedTrack is not null;

    public int PreviewCanvasWidth => GetEffectiveCanvasSize().Width;

    public int PreviewCanvasHeight => GetEffectiveCanvasSize().Height;

    public string AspectModeDisplayName => SelectedAspectMode.GetDisplayName();

    /// <summary>
    /// 同步混剪页统一画幅，使「跟随混剪画幅」预览与成片一致，避免贴纸落点被裁切。
    /// </summary>
    public void SyncCompositionCanvas(int width, int height)
    {
        var w = width > 0 ? width : 1080;
        var h = height > 0 ? height : 1920;
        if (_compositionCanvasWidth == w && _compositionCanvasHeight == h)
        {
            return;
        }

        _compositionCanvasWidth = w;
        _compositionCanvasHeight = h;
        if (SelectedAspectMode == StickerAspectMode.FollowComposition)
        {
            OnPropertyChanged(nameof(PreviewCanvasWidth));
            OnPropertyChanged(nameof(PreviewCanvasHeight));
        }
    }

    private (int Width, int Height) GetEffectiveCanvasSize()
    {
        if (SelectedTrack is not null && SelectedTrack.FixedAspectRatio != FixedAspectRatio.None)
        {
            var size = SelectedTrack.FixedAspectRatio.GetCanvasSize();
            if (size.Width > 0 && size.Height > 0)
            {
                return size;
            }
        }

        if (SelectedAspectMode == StickerAspectMode.FollowComposition)
        {
            return (_compositionCanvasWidth, _compositionCanvasHeight);
        }

        return SelectedAspectMode.GetCanvasSize();
    }

    partial void OnSelectedAspectModeChanged(StickerAspectMode value)
    {
        OnPropertyChanged(nameof(PreviewCanvasWidth));
        OnPropertyChanged(nameof(PreviewCanvasHeight));
        OnPropertyChanged(nameof(AspectModeDisplayName));
    }

    partial void OnStatusMessageChanged(string value) => HasStatusMessage = !string.IsNullOrWhiteSpace(value);

    partial void OnSelectedTrackChanged(StickerTrackRowViewModel? value)
    {
        AddStickerCommand.NotifyCanExecuteChanged();
        RemoveSelectedTrackCommand.NotifyCanExecuteChanged();
        OnPropertyChanged(nameof(HasSelectedTrack));
        OnPropertyChanged(nameof(PreviewCanvasWidth));
        OnPropertyChanged(nameof(PreviewCanvasHeight));
    }

    [RelayCommand]
    private async Task LoadLibraryAsync()
    {
        await EnsureLibraryLoadedAsync().ConfigureAwait(false);
    }

    /// <summary>确保入队前已从持久化素材库装载贴纸，而不是依赖用户是否打开过贴纸页面。</summary>
    public async Task EnsureLibraryLoadedAsync()
    {
        var document = await _libraryService.LoadAsync().ConfigureAwait(false);
        _uiDispatcher.Invoke(() => ApplyLibraryDocument(document));
    }

    [RelayCommand]
    private async Task ImportStickersAsync()
    {
        var paths = _filePicker.PickImageFiles("选择贴纸图片（PNG/GIF）");
        if (paths is null || paths.Count == 0)
        {
            return;
        }

        foreach (var path in paths)
        {
            var document = await _libraryService.RegisterAsync(path).ConfigureAwait(false);
            if (document.Entries.Count == 0)
            {
                continue;
            }

            var entry = document.Entries[^1];
            _uiDispatcher.Invoke(() =>
            {
                LibraryEntries.Insert(0, new StickerLibraryEntryRowViewModel(entry));
            });
        }

        StatusMessage = $"已导入 {paths.Count} 张贴纸到素材库。";
    }

    [RelayCommand]
    private async Task RemoveLibraryStickerAsync(StickerLibraryEntryRowViewModel? entry)
    {
        if (entry is null)
        {
            StatusMessage = "请选择要从贴纸素材库移除的贴纸。";
            return;
        }

        try
        {
            var document = await _libraryService.RemoveAsync(entry.Id).ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplyLibraryDocument(document);
                StatusMessage = $"已从贴纸素材库移除「{entry.FileName}」（不会删除原文件）。";
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
                StatusMessage = $"移除贴纸失败：{ex.GetBaseException().Message}");
        }
    }

    [RelayCommand(CanExecute = nameof(CanClearStickerLibrary))]
    private async Task ClearStickerLibraryAsync()
    {
        var entryCount = LibraryEntries.Count;
        if (entryCount == 0)
        {
            return;
        }

        if (!_clearConfirmation.ConfirmClear(entryCount))
        {
            StatusMessage = "已取消清空贴纸素材库。";
            return;
        }

        try
        {
            var (document, removed) = await _libraryService.ClearAllAsync().ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplyLibraryDocument(document);
                StatusMessage = removed == 0
                    ? "贴纸素材库已为空。"
                    : $"已清空贴纸素材库（{removed} 条）；电脑中的原文件未删除，当前贴纸轨道未改动。";
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
                StatusMessage = $"清空贴纸素材库失败：{ex.GetBaseException().Message}");
        }
    }

    private bool CanClearStickerLibrary() => HasLibraryEntries;

    [RelayCommand]
    private void AddSticker(StickerLibraryEntryRowViewModel? entry)
    {
        var path = entry?.FilePath ?? SelectedTrack?.SourcePath;
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            StatusMessage = "请先选择一张贴纸素材。";
            return;
        }

        var result = StickerTrack.Create(
            $"贴纸 {Tracks.Count + 1}",
            path,
            0.05,
            0.05,
            0.2,
            0.2,
            opacity: 1.0,
            rotationDegrees: 0.0,
            isEnabled: true);

        if (!result.IsSuccess || result.Value is null)
        {
            StatusMessage = result.Error ?? "创建贴纸轨道失败。";
            return;
        }

        var track = new StickerTrackRowViewModel(result.Value);
        track.AspectRatioChanged = OnTrackAspectRatioChanged;
        Tracks.Add(track);
        SelectedTrack = track;
        StatusMessage = $"已添加贴纸轨道：{track.Name}";
    }

    [RelayCommand(CanExecute = nameof(CanRemoveSelectedTrack))]
    private void RemoveSelectedTrack()
    {
        if (SelectedTrack is null)
        {
            return;
        }

        Tracks.Remove(SelectedTrack);
        SelectedTrack = Tracks.FirstOrDefault();
    }

    private bool CanRemoveSelectedTrack() => SelectedTrack is not null;

    private void OnTrackAspectRatioChanged()
    {
        OnPropertyChanged(nameof(PreviewCanvasWidth));
        OnPropertyChanged(nameof(PreviewCanvasHeight));
    }

    private void ApplyLibraryDocument(StickerLibraryDocument document)
    {
        LibraryEntries.Clear();
        foreach (var entry in document.Entries
                     .OrderByDescending(e => e.LastUsedAt ?? DateTimeOffset.MinValue)
                     .ThenBy(e => e.FilePath, StringComparer.OrdinalIgnoreCase))
        {
            LibraryEntries.Add(new StickerLibraryEntryRowViewModel(entry));
        }
    }

    public Result<IReadOnlyList<StickerTrack>> TryBuildTracks(bool enabledOnly = false)
    {
        var tracks = new List<StickerTrack>();
        foreach (var row in Tracks)
        {
            if (enabledOnly && !row.IsEnabled)
            {
                continue;
            }

            var result = row.TryToModel();
            if (!result.IsSuccess || result.Value is null)
            {
                return Result<IReadOnlyList<StickerTrack>>.Failure(
                    result.Error ?? $"贴纸轨道「{row.Name}」参数无效。");
            }

            tracks.Add(result.Value);
        }

        return Result<IReadOnlyList<StickerTrack>>.Success(tracks);
    }

    /// <summary>
    /// 为单个成片计划构建贴纸轨道；开启随机替换时，先将素材库洗牌，
    /// 再按全局成片序号分段取用，保留位置/大小/旋转/透明度。
    /// 一轮内优先不重复，并尽量让同一成片的多条贴纸使用不同素材。
    /// </summary>
    public Result<IReadOnlyList<StickerTrack>> TryBuildEnabledTracksForPlan(int seed, long planOrdinal = 0)
    {
        var tracksResult = TryBuildTracks(enabledOnly: true);
        if (!tracksResult.IsSuccess || tracksResult.Value is null)
        {
            return tracksResult;
        }

        var baseTracks = tracksResult.Value;
        if (!UseRandomStickerLibrary)
        {
            return Result<IReadOnlyList<StickerTrack>>.Success(baseTracks);
        }

        var sources = LibraryEntries
            .Select(e => e.FilePath)
            .Where(p => !string.IsNullOrWhiteSpace(p))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (sources.Length == 0)
        {
            return Result<IReadOnlyList<StickerTrack>>.Failure(
                "已开启贴纸随机替换，但贴纸素材库为空。请先导入贴纸素材。");
        }

        if (planOrdinal < 0)
        {
            return Result<IReadOnlyList<StickerTrack>>.Failure("成片序号无效，无法随机替换贴纸。");
        }

        var tracksPerPlan = Math.Max(1, baseTracks.Count);
        var randomized = baseTracks
            .Select((t, index) =>
            {
                var selectionOrdinal = planOrdinal * tracksPerPlan + index;
                var sourceIndex = DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
                    sources.Length,
                    seed,
                    selectionOrdinal,
                    branchIndex: 1);
                return t with { SourcePath = sources[sourceIndex] };
            })
            .ToArray();
        return Result<IReadOnlyList<StickerTrack>>.Success(randomized);
    }

    /// <summary>用模板快照替换当前全部贴纸轨道。</summary>
    public void ReplaceTracks(IEnumerable<StickerTrack> tracks)
    {
        ArgumentNullException.ThrowIfNull(tracks);

        Tracks.Clear();
        foreach (var model in tracks)
        {
            var row = new StickerTrackRowViewModel(model)
            {
                AspectRatioChanged = OnTrackAspectRatioChanged
            };
            Tracks.Add(row);
        }

        SelectedTrack = Tracks.FirstOrDefault();
    }

    /// <summary>
    /// 在预览画布上拖拽贴纸，更新选中轨道的 X/Y 百分比。
    /// </summary>
    public void ApplyPreviewDragDelta(double canvasDx, double canvasDy)
    {
        if (SelectedTrack is null)
        {
            return;
        }

        var (cw, ch) = GetEffectiveCanvasSize();
        if (cw <= 0 || ch <= 0)
        {
            return;
        }

        var percentDx = canvasDx / cw * 100.0;
        var percentDy = canvasDy / ch * 100.0;
        SelectedTrack.X = Math.Round(Math.Clamp(SelectedTrack.X + percentDx, 0, 100 - SelectedTrack.Width), 2);
        SelectedTrack.Y = Math.Round(Math.Clamp(SelectedTrack.Y + percentDy, 0, 100 - SelectedTrack.Height), 2);
    }

    /// <summary>
    /// 在预览画布上调整贴纸尺寸，更新选中轨道的宽高百分比。
    /// </summary>
    public void ApplyPreviewResizeDelta(double widthDeltaPercent, double heightDeltaPercent)
    {
        if (SelectedTrack is null)
        {
            return;
        }

        if (SelectedTrack.FixedAspectRatio != FixedAspectRatio.None)
        {
            var ratio = SelectedTrack.FixedAspectRatio.GetAspectRatio();
            if (ratio > 0)
            {
                var newWidth = Math.Round(Math.Clamp(SelectedTrack.Width + widthDeltaPercent, 1, 100 - SelectedTrack.X), 2);
                var newHeight = Math.Round(newWidth / ratio, 2);
                if (newHeight > 0 && newHeight <= 100 - SelectedTrack.Y)
                {
                    SelectedTrack.Width = newWidth;
                    SelectedTrack.Height = newHeight;
                }
                return;
            }
        }

        SelectedTrack.Width = Math.Round(Math.Clamp(SelectedTrack.Width + widthDeltaPercent, 1, 100 - SelectedTrack.X), 2);
        SelectedTrack.Height = Math.Round(Math.Clamp(SelectedTrack.Height + heightDeltaPercent, 1, 100 - SelectedTrack.Y), 2);
    }
}

public sealed partial class StickerTrackRowViewModel : ObservableObject
{
    private readonly StickerTrack _model;

    public StickerTrackRowViewModel(StickerTrack model)
    {
        _model = model;
        _name = model.Name;
        _sourcePath = model.SourcePath;
        _x = model.Bounds.X * 100;
        _y = model.Bounds.Y * 100;
        _width = model.Bounds.Width * 100;
        _height = model.Bounds.Height * 100;
        _stickerOpacity = model.Opacity * 100;
        _rotationDegrees = model.RotationDegrees;
        _isEnabled = model.IsEnabled;
        _fixedAspectRatio = model.FixedAspectRatio;
    }

    public Guid Id => _model.Id;

    public string FileName => System.IO.Path.GetFileName(SourcePath);

    [ObservableProperty]
    private string _name;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(FileName))]
    private string _sourcePath;

    [ObservableProperty]
    private double _x;

    [ObservableProperty]
    private double _y;

    [ObservableProperty]
    private double _width;

    [ObservableProperty]
    private double _height;

    [ObservableProperty]
    private double _stickerOpacity;

    [ObservableProperty]
    private double _rotationDegrees;

    [ObservableProperty]
    private bool _isEnabled;

    [ObservableProperty]
    private FixedAspectRatio _fixedAspectRatio;

    private bool _isConstraining;

    public Action? AspectRatioChanged { get; set; }

    partial void OnFixedAspectRatioChanged(FixedAspectRatio value)
    {
        // 预览画布会切到该比例；百分比宽高相等即可得到正确像素宽高比。
        if (value != FixedAspectRatio.None)
        {
            _isConstraining = true;
            try
            {
                var maxHeight = Math.Max(0.01, 100 - Y);
                Height = Math.Round(Math.Clamp(Width, 0.01, maxHeight), 2);
            }
            finally
            {
                _isConstraining = false;
            }
        }

        AspectRatioChanged?.Invoke();
    }

    partial void OnWidthChanged(double value)
    {
        if (_isConstraining || FixedAspectRatio == FixedAspectRatio.None)
        {
            return;
        }

        _isConstraining = true;
        try
        {
            var maxHeight = Math.Max(0.01, 100 - Y);
            Height = Math.Round(Math.Clamp(value, 0.01, maxHeight), 2);
        }
        finally
        {
            _isConstraining = false;
        }
    }

    partial void OnHeightChanged(double value)
    {
        if (_isConstraining || FixedAspectRatio == FixedAspectRatio.None)
        {
            return;
        }

        _isConstraining = true;
        try
        {
            var maxWidth = Math.Max(0.01, 100 - X);
            Width = Math.Round(Math.Clamp(value, 0.01, maxWidth), 2);
        }
        finally
        {
            _isConstraining = false;
        }
    }

    public Result<StickerTrack> TryToModel()
    {
        var displayName = string.IsNullOrWhiteSpace(Name) ? "未命名" : Name.Trim();
        if (string.IsNullOrWhiteSpace(Name))
        {
            return Result<StickerTrack>.Failure("贴纸轨道名称不能为空。");
        }

        if (string.IsNullOrWhiteSpace(SourcePath))
        {
            return Result<StickerTrack>.Failure($"贴纸轨道「{displayName}」的素材路径不能为空。");
        }

        if (!double.IsFinite(X)
            || !double.IsFinite(Y)
            || !double.IsFinite(Width)
            || !double.IsFinite(Height))
        {
            return Result<StickerTrack>.Failure($"贴纸轨道「{displayName}」的位置和尺寸必须是有效数字。");
        }

        var bounds = NormalizedRect.Create(X / 100.0, Y / 100.0, Width / 100.0, Height / 100.0);
        if (!bounds.IsSuccess)
        {
            var detail = (bounds.Error ?? "矩形范围无效。").Replace("蒙版", "贴纸", StringComparison.Ordinal);
            return Result<StickerTrack>.Failure($"贴纸轨道「{displayName}」参数无效：{detail}");
        }

        if (!double.IsFinite(StickerOpacity) || StickerOpacity is < 0 or > 100)
        {
            return Result<StickerTrack>.Failure($"贴纸轨道「{displayName}」透明度必须在 0% 到 100% 之间。");
        }

        if (!double.IsFinite(RotationDegrees))
        {
            return Result<StickerTrack>.Failure($"贴纸轨道「{displayName}」旋转角度必须是有效数字。");
        }

        return Result<StickerTrack>.Success(new StickerTrack(
            Id,
            displayName,
            SourcePath.Trim(),
            bounds.Value,
            StickerOpacity / 100.0,
            RotationDegrees,
            IsEnabled,
            FixedAspectRatio));
    }
}

public sealed partial class StickerLibraryEntryRowViewModel : ObservableObject
{
    private readonly StickerLibraryEntry _entry;

    public StickerLibraryEntryRowViewModel(StickerLibraryEntry entry)
    {
        _entry = entry;
    }

    public Guid Id => _entry.Id;

    public string FilePath => _entry.FilePath;

    public string FileName => _entry.FileName;

    public string? ThumbnailPath => _entry.ThumbnailPath;

    public bool HasThumbnail => !string.IsNullOrWhiteSpace(ThumbnailPath) && File.Exists(ThumbnailPath!);
}
