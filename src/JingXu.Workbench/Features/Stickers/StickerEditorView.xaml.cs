using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace JingXu.Workbench.Features.Stickers;

public sealed partial class StickerEditorView : UserControl
{
    private Point? _dragLast;
    private bool _isDragging;

    public StickerEditorView()
    {
        InitializeComponent();
        Loaded += OnLoaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (DataContext is StickerEditorViewModel vm)
        {
            vm.LoadLibraryCommand.Execute(null);
        }
    }

    private StickerEditorViewModel? ViewModel => DataContext as StickerEditorViewModel;

    private void PreviewCanvas_OnMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (ViewModel?.SelectedTrack is null)
        {
            return;
        }

        _dragLast = e.GetPosition(PreviewCanvas);
        _isDragging = true;
        PreviewCanvas.Cursor = Cursors.SizeAll;
        PreviewCanvas.CaptureMouse();
        e.Handled = true;
    }

    private void PreviewCanvas_OnMouseMove(object sender, MouseEventArgs e)
    {
        if (ViewModel?.SelectedTrack is null)
        {
            return;
        }

        var current = e.GetPosition(PreviewCanvas);
        if (!_isDragging || _dragLast is null)
        {
            return;
        }

        var dx = current.X - _dragLast.Value.X;
        var dy = current.Y - _dragLast.Value.Y;
        if (Math.Abs(dx) < 0.01 && Math.Abs(dy) < 0.01)
        {
            return;
        }

        ViewModel.ApplyPreviewDragDelta(dx, dy);
        _dragLast = current;
        e.Handled = true;
    }

    private void PreviewCanvas_OnMouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (!_isDragging)
        {
            return;
        }

        _isDragging = false;
        _dragLast = null;
        if (PreviewCanvas.IsMouseCaptured)
        {
            PreviewCanvas.ReleaseMouseCapture();
        }

        PreviewCanvas.Cursor = Cursors.Arrow;
    }
}
