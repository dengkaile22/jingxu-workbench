using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Features.Overlays;

public sealed partial class OverlayEditorViewModel
{
    public const double SourceCropPreviewCanvasWidth = PreviewCanvasWidth;

    public const double SourceCropPreviewCanvasHeight = PreviewCanvasHeight;

    private bool _isLoadingSourceCropBounds;
    private bool _hasManualSourceCropBounds;

    [ObservableProperty]
    private double _sourceCropBoundsX;

    [ObservableProperty]
    private double _sourceCropBoundsY;

    [ObservableProperty]
    private double _sourceCropBoundsWidth = 1;

    [ObservableProperty]
    private double _sourceCropBoundsHeight = 1;

    /// <summary>源素材取景是否已由用户手动指定；否则沿用渲染器的自动选取逻辑。</summary>
    public bool HasManualSourceCropBounds
    {
        get => _hasManualSourceCropBounds;
        private set
        {
            if (!SetProperty(ref _hasManualSourceCropBounds, value))
            {
                return;
            }

            OnPropertyChanged(nameof(SourceCropInteractionHint));
        }
    }

    public double SourceCropPreviewLeft => Math.Clamp(SourceCropBoundsX, 0, 1) * SourceCropPreviewCanvasWidth;

    public double SourceCropPreviewTop => Math.Clamp(SourceCropBoundsY, 0, 1) * SourceCropPreviewCanvasHeight;

    public double SourceCropPreviewWidth =>
        Math.Clamp(SourceCropBoundsWidth, MinNormalizedSize, 1) * SourceCropPreviewCanvasWidth;

    public double SourceCropPreviewHeight =>
        Math.Clamp(SourceCropBoundsHeight, MinNormalizedSize, 1) * SourceCropPreviewCanvasHeight;

    public string SourceCropInteractionHint => HasManualSourceCropBounds
        ? "当前使用手动源素材取景；它优先于自动上下选取偏移。"
        : "当前使用自动取景；拖动或调整下方白框后会切换为手动源素材取景。";

    partial void OnSourceCropBoundsXChanged(double value) => OnSourceCropBoundsFieldChanged();

    partial void OnSourceCropBoundsYChanged(double value) => OnSourceCropBoundsFieldChanged();

    partial void OnSourceCropBoundsWidthChanged(double value) => OnSourceCropBoundsFieldChanged();

    partial void OnSourceCropBoundsHeightChanged(double value) => OnSourceCropBoundsFieldChanged();

    private void LoadSourceCropBounds(OverlayLayer layer)
    {
        var sourceCrop = layer.SourceCropBounds ?? NormalizedRect.FullFrame;
        SetSourceCropBoundsFields(sourceCrop, layer.SourceCropBounds is not null, updateLayer: false);
    }

    private void OnSourceCropBoundsFieldChanged()
    {
        if (_isLoadingSourceCropBounds)
        {
            return;
        }

        if (!AreSourceCropBoundsFinite())
        {
            StatusMessage = NonFiniteSourceCropBoundsError;
            return;
        }

        HasManualSourceCropBounds = true;
        NotifySourceCropPreviewChanged();
        OnMaskFieldChanged();
    }

    private bool TryBuildManualSourceCropBounds(out NormalizedRect? sourceCropBounds, out string? error)
    {
        sourceCropBounds = null;
        error = null;
        if (!HasManualSourceCropBounds)
        {
            return true;
        }

        if (!AreSourceCropBoundsFinite())
        {
            error = NonFiniteSourceCropBoundsError;
            return false;
        }

        var result = NormalizedRect.Create(
            SourceCropBoundsX,
            SourceCropBoundsY,
            SourceCropBoundsWidth,
            SourceCropBoundsHeight);
        if (result.IsSuccess)
        {
            sourceCropBounds = result.Value;
            return true;
        }

        error = $"源素材取景无效：{result.Error}";
        return false;
    }

    private NormalizedRect GetEditableSourceCropBounds()
    {
        if (!AreSourceCropBoundsFinite())
        {
            return Selected?.Layer.SourceCropBounds ?? NormalizedRect.FullFrame;
        }

        var result = NormalizedRect.Create(
            SourceCropBoundsX,
            SourceCropBoundsY,
            SourceCropBoundsWidth,
            SourceCropBoundsHeight);
        return result.IsSuccess ? result.Value! : Selected?.Layer.SourceCropBounds ?? NormalizedRect.FullFrame;
    }

    private bool AreSourceCropBoundsFinite() =>
        double.IsFinite(SourceCropBoundsX) &&
        double.IsFinite(SourceCropBoundsY) &&
        double.IsFinite(SourceCropBoundsWidth) &&
        double.IsFinite(SourceCropBoundsHeight);

    private const string NonFiniteSourceCropBoundsError =
        "源素材取景无效：X、Y、宽度和高度必须是有限数值。";

    private void SetSourceCropBoundsFields(
        NormalizedRect sourceCropBounds,
        bool hasManualSourceCropBounds,
        bool updateLayer)
    {
        _isLoadingSourceCropBounds = true;
        try
        {
            SourceCropBoundsX = sourceCropBounds.X;
            SourceCropBoundsY = sourceCropBounds.Y;
            SourceCropBoundsWidth = sourceCropBounds.Width;
            SourceCropBoundsHeight = sourceCropBounds.Height;
            HasManualSourceCropBounds = hasManualSourceCropBounds;
        }
        finally
        {
            _isLoadingSourceCropBounds = false;
        }

        NotifySourceCropPreviewChanged();
        if (updateLayer)
        {
            OnMaskFieldChanged();
        }
    }

    private void NotifySourceCropPreviewChanged()
    {
        OnPropertyChanged(nameof(SourceCropPreviewLeft));
        OnPropertyChanged(nameof(SourceCropPreviewTop));
        OnPropertyChanged(nameof(SourceCropPreviewWidth));
        OnPropertyChanged(nameof(SourceCropPreviewHeight));
        OnPropertyChanged(nameof(SourceCropInteractionHint));
    }

    /// <summary>命中源素材取景框：边/角为缩放，内部为平移。</summary>
    public PreviewHitZone HitTestSourceCrop(double canvasX, double canvasY)
    {
        if (!HasSelected)
        {
            return PreviewHitZone.None;
        }

        return PreviewHitTester.HitTest(
            canvasX,
            canvasY,
            SourceCropPreviewLeft,
            SourceCropPreviewTop,
            SourceCropPreviewWidth,
            SourceCropPreviewHeight);
    }

    /// <summary>拖动源素材取景框，不会改变蓝色输出叠层框。</summary>
    public void ApplySourceCropDragDelta(PreviewHitZone zone, double deltaCanvasX, double deltaCanvasY)
    {
        if (!HasSelected || zone is PreviewHitZone.None)
        {
            return;
        }

        var sourceCrop = GetEditableSourceCropBounds();
        if (zone == PreviewHitZone.Move)
        {
            sourceCrop = PreviewRectangleManipulator.Move(
                sourceCrop,
                deltaCanvasX,
                deltaCanvasY,
                SourceCropPreviewCanvasWidth,
                SourceCropPreviewCanvasHeight);
        }
        else
        {
            sourceCrop = PreviewRectangleManipulator.Resize(
                sourceCrop,
                zone,
                deltaCanvasX,
                deltaCanvasY,
                SourceCropPreviewCanvasWidth,
                SourceCropPreviewCanvasHeight,
                MinNormalizedSize);
        }

        SetSourceCropBoundsFields(sourceCrop, hasManualSourceCropBounds: true, updateLayer: true);
    }

    /// <summary>按边/角调整源素材取景框。</summary>
    public void ApplySourceCropResize(PreviewHitZone zone, double deltaCanvasX, double deltaCanvasY) =>
        ApplySourceCropDragDelta(zone, deltaCanvasX, deltaCanvasY);

    [RelayCommand(CanExecute = nameof(CanMutateSelected))]
    private void ResetSourceCropBounds()
    {
        if (Selected is null)
        {
            return;
        }

        SetSourceCropBoundsFields(
            NormalizedRect.FullFrame,
            hasManualSourceCropBounds: false,
            updateLayer: true);
        StatusMessage = "已恢复自动源素材取景；自动上下选取偏移仍会保留。";
    }
}
