using System.Runtime.InteropServices;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>
/// 将编译期短路径别名物化到 staging：优先硬链接，其次符号链接，最后复制。
/// </summary>
internal static class StagingInputMaterializer
{
    public static void Materialize(string stagingRoot, IReadOnlyList<FfmpegInputAlias> aliases)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(stagingRoot);
        ArgumentNullException.ThrowIfNull(aliases);

        foreach (var alias in aliases)
        {
            var destination = Path.Combine(stagingRoot, alias.RelativePath);
            if (File.Exists(destination))
            {
                continue;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            LinkOrCopy(alias.AbsolutePath, destination);
        }
    }

    private static void LinkOrCopy(string source, string destination)
    {
        if (!File.Exists(source))
        {
            throw new FileNotFoundException($"找不到输入素材：{source}", source);
        }

        if (OperatingSystem.IsWindows() && TryCreateHardLink(destination, source))
        {
            return;
        }

        try
        {
            File.CreateSymbolicLink(destination, source);
            return;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or PlatformNotSupportedException)
        {
            // 无权限创建符号链接时回退复制。
        }

        File.Copy(source, destination, overwrite: true);
    }

    private static bool TryCreateHardLink(string destination, string source)
    {
        try
        {
            return CreateHardLink(destination, source, IntPtr.Zero);
        }
        catch (DllNotFoundException)
        {
            return false;
        }
        catch (EntryPointNotFoundException)
        {
            return false;
        }
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateHardLink(
        string lpFileName,
        string lpExistingFileName,
        IntPtr lpSecurityAttributes);
}
