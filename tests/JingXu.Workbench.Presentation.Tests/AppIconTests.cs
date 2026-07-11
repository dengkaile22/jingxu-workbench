using System.IO;
using System.Runtime.CompilerServices;

namespace JingXu.Workbench.Presentation.Tests;

/// <summary>
/// 验证 WPF 项目声明了自定义应用图标（互锁取景框标记），而非发布默认可执行文件图标。
/// </summary>
public sealed class AppIconTests
{
    [Fact]
    public void Wpf_project_declares_custom_application_icon()
    {
        var projectPath = Path.Combine(RepositoryRoot(), "src", "JingXu.Workbench", "JingXu.Workbench.csproj");
        Assert.True(File.Exists(projectPath), $"未找到 WPF 项目文件：{projectPath}");

        var project = File.ReadAllText(projectPath);
        Assert.Contains("<ApplicationIcon>Assets\\AppIcon.ico</ApplicationIcon>", project);

        var iconPath = Path.Combine(RepositoryRoot(), "src", "JingXu.Workbench", "Assets", "AppIcon.ico");
        Assert.True(File.Exists(iconPath), $"未找到应用图标：{iconPath}");
        Assert.True(new FileInfo(iconPath).Length > 0, "应用图标为空文件。");
    }

    private static string RepositoryRoot([CallerFilePath] string thisFile = "")
    {
        // thisFile = <root>\tests\JingXu.Workbench.Presentation.Tests\AppIconTests.cs
        var projectDir = Path.GetDirectoryName(thisFile)!;
        return Directory.GetParent(projectDir)!.Parent!.FullName;
    }
}
