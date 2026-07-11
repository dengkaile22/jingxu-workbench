using Microsoft.Win32;

namespace JingXu.Workbench.Bootstrap;

/// <summary>使用 WPF 标准文件对话框选择视频素材。</summary>
public sealed class WpfMediaFilePicker : IMediaFilePicker
{
    public IReadOnlyList<string>? PickVideoFiles()
    {
        var dialog = new OpenFileDialog
        {
            Title = "选择蒙版视频素材",
            Filter = "视频文件|*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v|所有文件|*.*",
            Multiselect = true,
            CheckFileExists = true
        };

        var owner = System.Windows.Application.Current?.MainWindow;
        var accepted = owner is null
            ? dialog.ShowDialog() == true
            : dialog.ShowDialog(owner) == true;

        return accepted ? dialog.FileNames : null;
    }

    public string? PickAudioFile()
    {
        var dialog = new OpenFileDialog
        {
            Title = "选择背景音乐",
            Filter = "音频文件|*.mp3;*.wav;*.m4a;*.aac;*.flac;*.ogg|所有文件|*.*",
            Multiselect = false,
            CheckFileExists = true
        };

        return dialog.ShowDialog() == true
            ? dialog.FileName
            : null;
    }
}
