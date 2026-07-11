namespace JingXu.Workbench.Features.Shell;

/// <summary>
/// 左侧模块导航栏的一个条目：图标 + 两字标签。未实现具体视图的模块
/// <see cref="IsEnabled"/> 为 <c>false</c>，导航项灰显不可点。
/// </summary>
public sealed class ShellModuleTab
{
    public ShellModuleTab(
        WorkspaceModule kind,
        string label,
        string iconKey,
        string automationName,
        bool isEnabled)
    {
        ModuleKind = kind;
        Label = label;
        IconKey = iconKey;
        AutomationName = automationName;
        IsEnabled = isEnabled;
    }

    /// <summary>模块标识。</summary>
    public WorkspaceModule ModuleKind { get; }

    /// <summary>两字中文标签，例如「混剪」「队列」。</summary>
    public string Label { get; }

    /// <summary>图标几何资源键。</summary>
    public string IconKey { get; }

    /// <summary>可访问名称，例如「切换到任务队列模块」。</summary>
    public string AutomationName { get; }

    /// <summary>是否可导航。未实现模块为 <c>false</c>。</summary>
    public bool IsEnabled { get; }
}
