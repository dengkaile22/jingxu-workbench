using System.Windows;
using System.Windows.Controls;
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
        }
    }

    private void OnViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName is nameof(GateMonitorViewModel.PreviewVideoPath)
            && DataContext is GateMonitorViewModel vm
            && vm.HasVideoPlayback
            && !string.IsNullOrWhiteSpace(vm.PreviewVideoPath))
        {
            Dispatcher.BeginInvoke(() => PreviewPlayer.Play(), DispatcherPriority.Loaded);
        }
    }

    private void PreviewPlayer_OnMediaOpened(object sender, RoutedEventArgs e) => PreviewPlayer.Play();

    private void PreviewPlayer_OnMediaFailed(object sender, ExceptionRoutedEventArgs e)
    {
        if (DataContext is GateMonitorViewModel vm)
        {
            _ = vm.ReportPlaybackFailedCommand.ExecuteAsync(null);
        }
    }
}
