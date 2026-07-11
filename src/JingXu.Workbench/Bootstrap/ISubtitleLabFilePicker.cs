namespace JingXu.Workbench.Bootstrap;

/// <summary>字幕与视频文件选择器。</summary>
public interface ISubtitleLabFilePicker
{
    string? PickVideoFile();

    string? PickSubtitleFile();

    string? PickExportSubtitlePath(string suggestedFileName);

    string? PickExportVideoPath(string suggestedFileName);
}
