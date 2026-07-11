using Microsoft.Win32;

namespace JingXu.Workbench.Bootstrap;

/// <summary>WPF 字幕实验室文件选择器。</summary>
public sealed class WpfSubtitleLabFilePicker : ISubtitleLabFilePicker
{
    public string? PickVideoFile()
    {
        var dialog = new OpenFileDialog
        {
            Title = "选择视频",
            Filter = "视频文件|*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v|所有文件|*.*",
            Multiselect = false
        };
        return dialog.ShowDialog() == true ? dialog.FileName : null;
    }

    public string? PickSubtitleFile()
    {
        var dialog = new OpenFileDialog
        {
            Title = "导入字幕",
            Filter = "字幕文件|*.srt;*.ass;*.ssa|所有文件|*.*",
            Multiselect = false
        };
        return dialog.ShowDialog() == true ? dialog.FileName : null;
    }

    public string? PickExportSubtitlePath(string suggestedFileName)
    {
        var dialog = new SaveFileDialog
        {
            Title = "导出 SRT",
            Filter = "SRT 字幕|*.srt|ASS 字幕|*.ass",
            FileName = suggestedFileName
        };
        return dialog.ShowDialog() == true ? dialog.FileName : null;
    }

    public string? PickExportVideoPath(string suggestedFileName)
    {
        var dialog = new SaveFileDialog
        {
            Title = "选择烧录输出",
            Filter = "MP4 视频|*.mp4",
            FileName = suggestedFileName
        };
        return dialog.ShowDialog() == true ? dialog.FileName : null;
    }
}
