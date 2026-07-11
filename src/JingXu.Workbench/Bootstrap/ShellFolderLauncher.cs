using System.Diagnostics;
using System.IO;

namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// 使用 Windows 资源管理器打开目录的默认实现。
/// </summary>
public sealed class ShellFolderLauncher : IFolderLauncher
{
    public void Open(string directoryPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(directoryPath);
        Directory.CreateDirectory(directoryPath);
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = directoryPath,
            UseShellExecute = true
        });
    }
}
