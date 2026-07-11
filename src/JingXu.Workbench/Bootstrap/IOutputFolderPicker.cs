namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// 选择本地输出目录。抽象出来以便视图模型可被单元测试。
/// </summary>
public interface IOutputFolderPicker
{
    /// <summary>弹出目录选择对话框；用户取消时返回 <c>null</c>。</summary>
    string? PickOutputFolder();
}
