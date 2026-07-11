namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// 在系统文件管理器中打开目录。抽象出来以便视图模型可被单元测试。
/// </summary>
public interface IFolderLauncher
{
    /// <summary>在资源管理器中打开指定目录；目录不存在时先创建。</summary>
    void Open(string directoryPath);
}
