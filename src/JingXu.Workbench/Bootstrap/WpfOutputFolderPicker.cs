using Microsoft.Win32;

namespace JingXu.Workbench.Bootstrap;

/// <summary>使用 WPF 标准目录对话框选择成片输出位置。</summary>
public sealed class WpfOutputFolderPicker : IOutputFolderPicker
{
    public string? PickOutputFolder()
    {
        var dialog = new OpenFolderDialog
        {
            Title = "选择成片输出目录",
            Multiselect = false
        };

        return dialog.ShowDialog() == true
            ? dialog.FolderName
            : null;
    }
}
