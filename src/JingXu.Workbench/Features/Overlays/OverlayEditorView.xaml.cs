using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace JingXu.Workbench.Features.Overlays;

public partial class OverlayEditorView : UserControl
{
    private Point? _dragLast;
    private bool _isDragging;
    private PreviewHitZone _activeZone = PreviewHitZone.None;
    private Point? _sourceCropDragLast;
    private bool _isSourceCropDragging;
    private PreviewHitZone _activeSourceCropZone = PreviewHitZone.None;

    public OverlayEditorView()
    {
        InitializeComponent();
    }

    private OverlayEditorViewModel? ViewModel => DataContext as OverlayEditorViewModel;

    private void MaskPreviewFrame_OnMouseLeftButtonDown(object sender, MouseButtonEventArgs e) =>
        BeginDrag(e);

    private void MaskPreviewCanvas_OnMouseLeftButtonDown(object sender, MouseButtonEventArgs e) =>
        BeginDrag(e);

    private void BeginDrag(MouseButtonEventArgs e)
    {
        if (ViewModel is null || !ViewModel.HasSelected)
        {
            return;
        }

        var pos = e.GetPosition(MaskPreviewCanvas);
        _activeZone = ViewModel.HitTestPreview(pos.X, pos.Y);
        if (_activeZone is PreviewHitZone.None)
        {
            // 点在框外时仍允许从画布开始，默认按命中框中心平移附近处理
            _activeZone = PreviewHitZone.Move;
        }

        _dragLast = pos;
        _isDragging = true;
        MaskPreviewCanvas.Cursor = ToCursor(_activeZone);
        MaskPreviewCanvas.CaptureMouse();
        e.Handled = true;
    }

    private void MaskPreviewCanvas_OnMouseMove(object sender, MouseEventArgs e)
    {
        if (ViewModel is null)
        {
            return;
        }

        var current = e.GetPosition(MaskPreviewCanvas);
        if (!_isDragging)
        {
            var zone = ViewModel.HitTestPreview(current.X, current.Y);
            MaskPreviewCanvas.Cursor = ToCursor(zone);
            return;
        }

        if (_dragLast is null)
        {
            return;
        }

        var dx = current.X - _dragLast.Value.X;
        var dy = current.Y - _dragLast.Value.Y;
        if (Math.Abs(dx) < 0.01 && Math.Abs(dy) < 0.01)
        {
            return;
        }

        ViewModel.ApplyPreviewDragDelta(_activeZone, dx, dy);
        _dragLast = current;
        e.Handled = true;
    }

    private void MaskPreviewCanvas_OnMouseLeftButtonUp(object sender, MouseButtonEventArgs e) =>
        EndDrag();

    private void MaskPreviewCanvas_OnLostMouseCapture(object sender, MouseEventArgs e) =>
        EndDrag();

    private void EndDrag()
    {
        if (!_isDragging)
        {
            return;
        }

        _isDragging = false;
        _dragLast = null;
        _activeZone = PreviewHitZone.None;
        if (MaskPreviewCanvas.IsMouseCaptured)
        {
            MaskPreviewCanvas.ReleaseMouseCapture();
        }

        MaskPreviewCanvas.Cursor = Cursors.Arrow;
    }

    private void SourceCropPreviewFrame_OnMouseLeftButtonDown(object sender, MouseButtonEventArgs e) =>
        BeginSourceCropDrag(e);

    private void SourceCropPreviewCanvas_OnMouseLeftButtonDown(object sender, MouseButtonEventArgs e) =>
        BeginSourceCropDrag(e);

    private void BeginSourceCropDrag(MouseButtonEventArgs e)
    {
        if (ViewModel is null || !ViewModel.HasSelected)
        {
            return;
        }

        var pos = e.GetPosition(SourceCropPreviewCanvas);
        _activeSourceCropZone = ViewModel.HitTestSourceCrop(pos.X, pos.Y);
        if (_activeSourceCropZone is PreviewHitZone.None)
        {
            _activeSourceCropZone = PreviewHitZone.Move;
        }

        _sourceCropDragLast = pos;
        _isSourceCropDragging = true;
        SourceCropPreviewCanvas.Cursor = ToCursor(_activeSourceCropZone);
        SourceCropPreviewCanvas.CaptureMouse();
        e.Handled = true;
    }

    private void SourceCropPreviewCanvas_OnMouseMove(object sender, MouseEventArgs e)
    {
        if (ViewModel is null)
        {
            return;
        }

        var current = e.GetPosition(SourceCropPreviewCanvas);
        if (!_isSourceCropDragging)
        {
            SourceCropPreviewCanvas.Cursor = ToCursor(ViewModel.HitTestSourceCrop(current.X, current.Y));
            return;
        }

        if (_sourceCropDragLast is null)
        {
            return;
        }

        var dx = current.X - _sourceCropDragLast.Value.X;
        var dy = current.Y - _sourceCropDragLast.Value.Y;
        if (Math.Abs(dx) < 0.01 && Math.Abs(dy) < 0.01)
        {
            return;
        }

        ViewModel.ApplySourceCropDragDelta(_activeSourceCropZone, dx, dy);
        _sourceCropDragLast = current;
        e.Handled = true;
    }

    private void SourceCropPreviewCanvas_OnMouseLeftButtonUp(object sender, MouseButtonEventArgs e) =>
        EndSourceCropDrag();

    private void SourceCropPreviewCanvas_OnLostMouseCapture(object sender, MouseEventArgs e) =>
        EndSourceCropDrag();

    private void EndSourceCropDrag()
    {
        if (!_isSourceCropDragging)
        {
            return;
        }

        _isSourceCropDragging = false;
        _sourceCropDragLast = null;
        _activeSourceCropZone = PreviewHitZone.None;
        if (SourceCropPreviewCanvas.IsMouseCaptured)
        {
            SourceCropPreviewCanvas.ReleaseMouseCapture();
        }

        SourceCropPreviewCanvas.Cursor = Cursors.Arrow;
    }

    private static Cursor ToCursor(PreviewHitZone zone) =>
        zone switch
        {
            PreviewHitZone.North or PreviewHitZone.South => Cursors.SizeNS,
            PreviewHitZone.East or PreviewHitZone.West => Cursors.SizeWE,
            PreviewHitZone.NorthEast or PreviewHitZone.SouthWest => Cursors.SizeNESW,
            PreviewHitZone.NorthWest or PreviewHitZone.SouthEast => Cursors.SizeNWSE,
            PreviewHitZone.Move => Cursors.SizeAll,
            _ => Cursors.Arrow
        };
}
