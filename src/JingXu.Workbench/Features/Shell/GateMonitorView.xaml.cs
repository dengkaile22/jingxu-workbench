using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace JingXu.Workbench.Features.Shell;

public partial class GateMonitorView : UserControl
{
    public GateMonitorView()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is GateMonitorViewModel oldVm)
        {
            oldVm.PropertyChanged -= OnViewModelPropertyChanged;
        }

        if (e.NewValue is GateMonitorViewModel newVm)
        {
            newVm.PropertyChanged += OnViewModelPropertyChanged;
            ApplyPreviewSources(newVm);
        }
    }

    private void OnViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (DataContext is not GateMonitorViewModel vm)
        {
            return;
        }

        if (e.PropertyName is nameof(GateMonitorViewModel.PreviewVideoPath)
            or nameof(GateMonitorViewModel.HasVideoPlayback)
            or nameof(GateMonitorViewModel.PreviewImagePath)
            or nameof(GateMonitorViewModel.HasStaticFrame))
        {
            ApplyPreviewSources(vm);
        }
    }

    private void ApplyPreviewSources(GateMonitorViewModel vm)
    {
        if (vm.HasVideoPlayback && !string.IsNullOrWhiteSpace(vm.PreviewVideoPath))
        {
            TrySetMediaSource(vm.PreviewVideoPath);
        }
        else
        {
            PreviewPlayer.Stop();
            PreviewPlayer.Source = null;
        }

        if (vm.HasStaticFrame && !string.IsNullOrWhiteSpace(vm.PreviewImagePath))
        {
            PreviewImage.Source = LoadBitmap(vm.PreviewImagePath);
        }
        else
        {
            PreviewImage.Source = null;
        }
    }

    private void TrySetMediaSource(string path)
    {
        try
        {
            var uri = new Uri(path, UriKind.Absolute);
            if (PreviewPlayer.Source != uri)
            {
                PreviewPlayer.Source = uri;
            }

            Dispatcher.BeginInvoke(() =>
            {
                try
                {
                    PreviewPlayer.Play();
                }
                catch
                {
                    // MediaFailed 会回退到首帧静图。
                }
            }, DispatcherPriority.Loaded);
        }
        catch
        {
            PreviewPlayer.Source = null;
            if (DataContext is GateMonitorViewModel vm)
            {
                _ = vm.ReportPlaybackFailedCommand.ExecuteAsync(null);
            }
        }
    }

    private static BitmapImage? LoadBitmap(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return null;
            }

            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.CreateOptions = BitmapCreateOptions.IgnoreImageCache;
            bitmap.UriSource = new Uri(path, UriKind.Absolute);
            bitmap.EndInit();
            bitmap.Freeze();
            return bitmap;
        }
        catch
        {
            return null;
        }
    }

    private void PreviewPlayer_OnMediaOpened(object sender, RoutedEventArgs e) => PreviewPlayer.Play();

    private void PreviewPlayer_OnMediaFailed(object sender, ExceptionRoutedEventArgs e)
    {
        PreviewPlayer.Source = null;
        if (DataContext is GateMonitorViewModel vm)
        {
            _ = vm.ReportPlaybackFailedCommand.ExecuteAsync(null);
        }
    }
}
