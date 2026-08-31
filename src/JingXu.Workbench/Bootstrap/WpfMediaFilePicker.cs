using Microsoft.Win32;

namespace JingXu.Workbench.Bootstrap;

/// <summary>使用 WPF 标准文件对话框选择视频素材。</summary>
public sealed class WpfMediaFilePicker : IMediaFilePicker
{
    public IReadOnlyList<string>? PickVideoFiles(string? dialogTitle = null)
    {
        var dialog = new OpenFileDialog
        {
            Title = string.IsNullOrWhiteSpace(dialogTitle) ? "选择视频素材" : dialogTitle,
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

    public string? PickImageFile()
    {
        var dialog = new OpenFileDialog
        {
            Title = "选择图片（贴纸 / PNG 遮罩）",
            Filter = "图像文件|*.png;*.jpg;*.jpeg;*.webp;*.bmp|PNG 图像|*.png|所有文件|*.*",
            Multiselect = false,
            CheckFileExists = true
        };

        var owner = System.Windows.Application.Current?.MainWindow;
        var accepted = owner is null
            ? dialog.ShowDialog() == true
            : dialog.ShowDialog(owner) == true;

        return accepted ? dialog.FileName : null;
    }

    public IReadOnlyList<string>? PickImageFiles(string? dialogTitle = null)
    {
        var dialog = new OpenFileDialog
        {
            Title = string.IsNullOrWhiteSpace(dialogTitle) ? "选择图片素材" : dialogTitle,
            Filter = "PNG/GIF 贴纸|*.png;*.gif|所有图片|*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp|所有文件|*.*",
            Multiselect = true,
            CheckFileExists = true
        };

        var owner = System.Windows.Application.Current?.MainWindow;
        var accepted = owner is null
            ? dialog.ShowDialog() == true
            : dialog.ShowDialog(owner) == true;

        return accepted ? dialog.FileNames : null;
    }

    public IReadOnlyList<string>? PickAudioFiles(string? dialogTitle = null)
    {
        var dialog = new OpenFileDialog
        {
            Title = string.IsNullOrWhiteSpace(dialogTitle) ? "选择音频文件" : dialogTitle,
            Filter = "音频文件|*.mp3;*.wav;*.m4a;*.aac;*.flac;*.ogg|所有文件|*.*",
            Multiselect = true,
            CheckFileExists = true
        };

        var owner = System.Windows.Application.Current?.MainWindow;
        var accepted = owner is null
            ? dialog.ShowDialog() == true
            : dialog.ShowDialog(owner) == true;

        return accepted ? dialog.FileNames : null;
    }
}
