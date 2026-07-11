using System.Collections.Generic;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Presentation.Tests.Composition;
using JingXu.Workbench.Presentation.Tests.Infrastructure;

namespace JingXu.Workbench.Presentation.Tests.Shell;

/// <summary>
/// 构建用于测试的 <see cref="ShellViewModel"/>，注入不产生副作用的目录启动器。
/// </summary>
public static class ShellViewModelTestFactory
{
    public static ShellViewModel Create() =>
        new AppCompositionRoot(
            new RecordingFolderLauncher(),
            mediaProbe: FakeMediaProbe.ForSixClips(),
            uiDispatcher: new DirectUiDispatcher()).CreateShell();

    public static ShellViewModel Create(out RecordingFolderLauncher launcher)
    {
        launcher = new RecordingFolderLauncher();
        return new AppCompositionRoot(
            launcher,
            mediaProbe: FakeMediaProbe.ForSixClips(),
            uiDispatcher: new DirectUiDispatcher()).CreateShell();
    }
}

/// <summary>记录被请求打开的目录，不触碰文件系统或资源管理器。</summary>
public sealed class RecordingFolderLauncher : IFolderLauncher
{
    public List<string> Opened { get; } = [];

    public void Open(string directoryPath) => Opened.Add(directoryPath);
}
