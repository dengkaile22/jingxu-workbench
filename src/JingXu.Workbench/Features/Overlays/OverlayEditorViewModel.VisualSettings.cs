using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Features.Overlays;

public sealed partial class OverlayEditorViewModel
{
    private readonly object _libraryEntriesSync = new();
    private readonly HashSet<Guid> _selectedLibraryEntryIds = [];
    private double _opacityPercent = (1 - OverlayLayer.GhostOverlayOpacity) * 100;

    [ObservableProperty]
    private OverlayFitMode _fit = OverlayFitMode.FillCrop;

    /// <summary>
    /// 供界面显示的百分比透明度（0=完全不透明，100=完全透明）。
    /// 领域层仍使用 0 到 1 的不透明度。
    /// </summary>
    public double OpacityPercent
    {
        get => _opacityPercent;
        set
        {
            var clamped = Math.Round(Math.Clamp(value, 0, 100), 2);
            if (!SetProperty(ref _opacityPercent, clamped))
            {
                return;
            }

            Opacity = 1 - clamped / 100;
        }
    }


    public int SelectedLibraryEntryCount
    {
        get
        {
            lock (_libraryEntriesSync)
            {
                return _selectedLibraryEntryIds.Count;
            }
        }
    }

    public bool HasSelectedLibraryEntries => SelectedLibraryEntryCount > 0;

    public string FitInteractionHint => Fit switch
    {
        OverlayFitMode.FillCrop => "填满裁切：优先填满输出叠层框，可能裁掉源素材边缘。",
        OverlayFitMode.Contain => "完整适配：完整保留源素材，可能留黑边。",
        OverlayFitMode.Stretch => "拉伸：填满输出叠层框，但会改变源素材比例。",
        OverlayFitMode.MatchCanvasCrop => "裁成画幅再覆盖：先按成片画幅裁源素材，自动上下偏移仅在未手动取景时生效。",
        _ => string.Empty
    };

    partial void OnFitChanged(OverlayFitMode value)
    {
        OnPropertyChanged(nameof(FitInteractionHint));
        OnMaskFieldChanged();
    }

    private void SynchronizeOpacityPercent(double opacity) =>
        SetProperty(ref _opacityPercent, Math.Round(Math.Clamp(1 - opacity, 0, 1) * 100, 2), nameof(OpacityPercent));

    [RelayCommand(CanExecute = nameof(CanMutateSelected))]
    private void ApplyFitPreset(string? preset)
    {
        if (Selected is null)
        {
            return;
        }

        var parsed = preset?.Trim() switch
        {
            "FillCrop" => OverlayFitMode.FillCrop,
            "Contain" => OverlayFitMode.Contain,
            "Stretch" => OverlayFitMode.Stretch,
            "MatchCanvasCrop" => OverlayFitMode.MatchCanvasCrop,
            _ => (OverlayFitMode?)null
        };
        if (parsed is null)
        {
            StatusMessage = "请选择有效的蒙版适配方式。";
            return;
        }

        Fit = parsed.Value;
        StatusMessage = $"已应用适配方式：{parsed.Value}。";
    }

    [RelayCommand(CanExecute = nameof(CanApplyCurrentVisualSettingsToAllLayers))]
    private void ApplyCurrentVisualSettingsToAllLayers()
    {
        if (!TryBuildUpdatedLayer(out var layer, out var error))
        {
            StatusMessage = error ?? "请先确认当前蒙版参数有效。";
            return;
        }

        var settings = layer.ToVisualSettings();
        var updated = _workbenchState.Layers
            .Select(current => current.WithVisualSettings(settings) with
            {
                StartClipIndex = layer.StartClipIndex
            })
            .ToArray();
        _workbenchState.ReplaceAll(updated);

        StatusMessage =
            $"已将当前参数（含起始片段 {layer.StartClipIndex}）应用到其余 " +
            $"{Math.Max(0, updated.Length - 1)} 条蒙版轨道（共 {updated.Length} 条）。";
        InvalidateEffectPreview();
    }

    private bool CanApplyCurrentVisualSettingsToAllLayers() =>
        Selected is not null && Layers.Count > 1;

    /// <summary>只将当前起始片段同步到全部轨道，不覆盖位置、尺寸等其他参数。</summary>
    [RelayCommand(CanExecute = nameof(CanApplyStartClipIndexToAllLayers))]
    private void ApplyStartClipIndexToAllLayers()
    {
        if (Selected is null)
        {
            StatusMessage = "请先选中一条蒙版轨道。";
            return;
        }

        if (StartClipIndex < 1)
        {
            StatusMessage = "起始片段必须大于或等于 1。";
            return;
        }

        var updated = _workbenchState.Layers
            .Select(layer => layer with { StartClipIndex = StartClipIndex })
            .ToArray();
        _workbenchState.ReplaceAll(updated);

        StatusMessage = $"已将起始片段 {StartClipIndex} 统一应用到全部 {updated.Length} 条蒙版轨道，其他参数保持不变。";
        InvalidateEffectPreview();
    }

    private bool CanApplyStartClipIndexToAllLayers() =>
        Selected is not null && Layers.Count > 1;

    private void OnLibraryEntryRowPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (sender is not OverlayLibraryEntryRowViewModel row ||
            e.PropertyName != nameof(OverlayLibraryEntryRowViewModel.IsSelectedForBatchApply))
        {
            return;
        }

        lock (_libraryEntriesSync)
        {
            if (row.IsSelectedForBatchApply)
            {
                _selectedLibraryEntryIds.Add(row.Id);
            }
            else
            {
                _selectedLibraryEntryIds.Remove(row.Id);
            }

            OnPropertyChanged(nameof(SelectedLibraryEntryCount));
            OnPropertyChanged(nameof(HasSelectedLibraryEntries));
        }
    }

    private OverlayLibraryEntryRowViewModel CreateLibraryEntryRow(OverlayLibraryEntry entry)
    {
        var row = new OverlayLibraryEntryRowViewModel(
            entry,
            _selectedLibraryEntryIds.Contains(entry.Id));
        row.PropertyChanged += OnLibraryEntryRowPropertyChanged;
        return row;
    }

    private void ClearLibraryEntryRows()
    {
        foreach (var row in LibraryEntries.ToArray())
        {
            row.PropertyChanged -= OnLibraryEntryRowPropertyChanged;
        }

        LibraryEntries.Clear();
    }

    private void PreserveLibrarySelection(OverlayLibraryDocument document)
    {
        _selectedLibraryEntryIds.IntersectWith(document.Entries.Select(entry => entry.Id));
        OnPropertyChanged(nameof(SelectedLibraryEntryCount));
        OnPropertyChanged(nameof(HasSelectedLibraryEntries));
    }
}
