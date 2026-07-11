using CommunityToolkit.Mvvm.ComponentModel;

namespace JingXu.Workbench.Features.Shell;

/// <summary>
/// 所有工作台模块视图模型的基类。壳层通过缓存的模块实例在中央工作区之间切换，
/// 切换时保留实例状态。
/// </summary>
public abstract class WorkspaceModuleViewModel : ObservableObject
{
    /// <summary>该视图模型对应的模块标识。</summary>
    public abstract WorkspaceModule ModuleKind { get; }

    /// <summary>模块的中文标题，显示在中央工作区顶部。</summary>
    public abstract string Title { get; }
}
