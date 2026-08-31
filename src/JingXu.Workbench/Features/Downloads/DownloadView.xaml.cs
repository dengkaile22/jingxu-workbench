using System.Windows;
using Microsoft.Win32;
using JingXu.Workbench.Features.Downloads;

namespace JingXu.Workbench.Features.Downloads;

public partial class DownloadView : System.Windows.Controls.UserControl
{
    public DownloadView()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is DownloadViewModel oldVm)
        {
            oldVm.SaveDirectoryChanged -= OnBrowseSaveDirectory;
        }

        if (e.NewValue is DownloadViewModel newVm)
        {
            newVm.SaveDirectoryChanged += OnBrowseSaveDirectory;
        }
    }

    private void OnBrowseSaveDirectory(object? sender, EventArgs e)
    {
        if (DataContext is not DownloadViewModel vm)
        {
            return;
        }

        var dialog = new OpenFolderDialog
        {
            FolderName = vm.SaveDirectory
        };

        if (dialog.ShowDialog() == true)
        {
            vm.SaveDirectory = dialog.FolderName;
        }
    }
}
