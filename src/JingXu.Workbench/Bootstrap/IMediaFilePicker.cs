namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// 选择本地媒体文件。抽象出来以便视图模型可被单元测试。
/// </summary>
public interface IMediaFilePicker
{
    /// <summary>弹出文件选择对话框；用户取消时返回 <c>null</c>。</summary>
    IReadOnlyList<string>? PickVideoFiles();

    /// <summary>选择单个音频文件；用户取消时返回 <c>null</c>。</summary>
    string? PickAudioFile();

    /// <summary>选择单个灰度/透明 PNG 遮罩图；用户取消时返回 <c>null</c>。</summary>
    string? PickImageFile();
}
