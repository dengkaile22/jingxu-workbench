namespace JingXu.Workbench.Infrastructure.Tests.Runtime;

/// <summary>
/// 运行时定位测试的临时目录布局辅助类。
/// 在临时根目录下按需创建可执行文件占位，并模拟 PATH 查找。
/// </summary>
internal sealed class RuntimeLayout : IDisposable
{
    private readonly Dictionary<string, string> _pathEntries = new(StringComparer.OrdinalIgnoreCase);

    private RuntimeLayout(string root) => Root = root;

    /// <summary>临时根目录。</summary>
    public string Root { get; }

    /// <summary>模拟的应用安装根目录（内部含 runtime/ffmpeg）。</summary>
    public string AppRoot => System.IO.Path.Combine(Root, "app");

    /// <summary>模拟的用户自定义运行时目录。</summary>
    public string UserPath => System.IO.Path.Combine(Root, "user");

    /// <summary>模拟的 PATH 目录。</summary>
    public string PathDirectory => System.IO.Path.Combine(Root, "path");

    /// <summary>期望的内置 ffmpeg 绝对路径。</summary>
    public string BundledFfmpeg => BundledExecutable("ffmpeg");

    /// <summary>期望的内置 ffprobe 绝对路径。</summary>
    public string BundledFfprobe => BundledExecutable("ffprobe");

    /// <summary>期望的用户目录 ffmpeg 绝对路径。</summary>
    public string UserFfmpeg => System.IO.Path.Combine(UserPath, ExecutableName("ffmpeg"));

    /// <summary>供 <c>RuntimeResolver</c> 使用的 PATH 查找委托。</summary>
    public Func<string, string?> PathLookup =>
        name => _pathEntries.TryGetValue(name, out var full) ? full : null;

    /// <summary>返回与当前平台匹配的可执行文件名。</summary>
    public static string ExecutableName(string tool) =>
        OperatingSystem.IsWindows() ? tool + ".exe" : tool;

    /// <summary>内置目录中指定工具的绝对路径。</summary>
    public string BundledExecutable(string tool) =>
        System.IO.Path.Combine(AppRoot, "runtime", "ffmpeg", ExecutableName(tool));

    /// <summary>创建一个空的临时布局。</summary>
    public static RuntimeLayout Create()
    {
        var root = System.IO.Path.Combine(
            System.IO.Path.GetTempPath(), "jingxu-runtime-" + Guid.NewGuid().ToString("N"));
        System.IO.Directory.CreateDirectory(root);
        return new RuntimeLayout(root);
    }

    /// <summary>创建布局并在根目录下写入给定的相对路径占位文件。</summary>
    public static RuntimeLayout WithExecutables(params string[] relativePaths)
    {
        var layout = Create();
        foreach (var relative in relativePaths)
        {
            layout.CreateFile(relative);
        }

        return layout;
    }

    /// <summary>在 PATH 目录下创建工具占位并注册到 PATH 查找。</summary>
    public RuntimeLayout AddPathExecutable(string tool)
    {
        System.IO.Directory.CreateDirectory(PathDirectory);
        var full = System.IO.Path.Combine(PathDirectory, ExecutableName(tool));
        System.IO.File.WriteAllText(full, string.Empty);
        _pathEntries[ExecutableName(tool)] = full;
        _pathEntries[tool] = full;
        return this;
    }

    /// <summary>将已有绝对路径注册为 PATH 查找结果（用于集成测试引用本机运行时）。</summary>
    public RuntimeLayout RegisterExistingExecutable(string tool, string fullPath)
    {
        _pathEntries[ExecutableName(tool)] = fullPath;
        _pathEntries[tool] = fullPath;
        return this;
    }

    public void Dispose()
    {
        try
        {
            if (System.IO.Directory.Exists(Root))
            {
                System.IO.Directory.Delete(Root, recursive: true);
            }
        }
        catch (System.IO.IOException)
        {
            // 清理失败不影响测试结论。
        }
    }

    private void CreateFile(string relative)
    {
        var normalized = relative.Replace('/', System.IO.Path.DirectorySeparatorChar);
        var full = System.IO.Path.Combine(Root, normalized);
        System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(full)!);
        System.IO.File.WriteAllText(full, string.Empty);
    }
}
