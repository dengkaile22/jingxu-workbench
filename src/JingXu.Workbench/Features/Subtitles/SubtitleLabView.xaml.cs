using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;

namespace JingXu.Workbench.Features.Subtitles;

public partial class SubtitleLabView
{
    private Point? _dragStart;
    private Rectangle? _dragRect;

    public SubtitleLabView()
    {
        InitializeComponent();
        PreviewHost.SizeChanged += (_, _) => RefreshPreviewLayout();
        Loaded += (_, _) => RefreshPreviewLayout();
        DataContextChanged += (_, _) => RefreshPreviewLayout();
    }

    private SubtitleLabViewModel? ViewModel => DataContext as SubtitleLabViewModel;

    private void RefreshPreviewLayout()
    {
        if (ViewModel is null || PreviewHost.ActualWidth <= 0 || PreviewHost.ActualHeight <= 0)
        {
            return;
        }

        var dpi = VisualTreeHelper.GetDpi(this);
        ViewModel.UpdatePreviewLayout(PreviewHost.ActualWidth, PreviewHost.ActualHeight, dpi.DpiScaleX);
    }

    private void PreviewHost_OnMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (ViewModel is null || !ViewModel.HasVideo)
        {
            return;
        }

        _dragStart = e.GetPosition(PreviewHost);
        PreviewHost.CaptureMouse();
        _dragRect = new Rectangle
        {
            Stroke = (Brush)FindResource("Status.Running.Text"),
            StrokeThickness = 1,
            Fill = new SolidColorBrush(Color.FromArgb(0x33, 0xC4, 0xA3, 0x5A))
        };
        Canvas.SetLeft(_dragRect, _dragStart.Value.X);
        Canvas.SetTop(_dragRect, _dragStart.Value.Y);
        if (PreviewHost.Child is Grid grid && grid.Children.OfType<Canvas>().FirstOrDefault() is Canvas canvas)
        {
            canvas.Children.Add(_dragRect);
        }
    }

    private void PreviewHost_OnMouseMove(object sender, MouseEventArgs e)
    {
        if (_dragStart is null || _dragRect is null)
        {
            return;
        }

        var current = e.GetPosition(PreviewHost);
        var x = Math.Min(_dragStart.Value.X, current.X);
        var y = Math.Min(_dragStart.Value.Y, current.Y);
        var w = Math.Abs(current.X - _dragStart.Value.X);
        var h = Math.Abs(current.Y - _dragStart.Value.Y);
        Canvas.SetLeft(_dragRect, x);
        Canvas.SetTop(_dragRect, y);
        _dragRect.Width = w;
        _dragRect.Height = h;
    }

    private void PreviewHost_OnMouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (_dragStart is null || ViewModel is null)
        {
            return;
        }

        PreviewHost.ReleaseMouseCapture();
        var end = e.GetPosition(PreviewHost);
        var x = Math.Min(_dragStart.Value.X, end.X);
        var y = Math.Min(_dragStart.Value.Y, end.Y);
        var w = Math.Abs(end.X - _dragStart.Value.X);
        var h = Math.Abs(end.Y - _dragStart.Value.Y);

        if (_dragRect is not null && PreviewHost.Child is Grid grid && grid.Children.OfType<Canvas>().FirstOrDefault() is Canvas canvas)
        {
            canvas.Children.Remove(_dragRect);
        }

        _dragRect = null;
        _dragStart = null;

        if (w >= 4 && h >= 4)
        {
            var dpi = VisualTreeHelper.GetDpi(this);
            ViewModel.ApplySelectionFromViewport(
                x,
                y,
                w,
                h,
                PreviewHost.ActualWidth,
                PreviewHost.ActualHeight,
                dpi.DpiScaleX);
            RefreshPreviewLayout();
        }
    }
}
