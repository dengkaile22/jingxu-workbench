namespace JingXu.Workbench.Infrastructure.Runtime;

/// <summary>运行时可执行文件的定位来源。</summary>
public enum RuntimeSource
{
    /// <summary>应用内置运行时目录。</summary>
    Bundled,

    /// <summary>用户指定目录。</summary>
    User,

    /// <summary>系统 PATH。</summary>
    Path
}

/// <summary>运行时定位结果。</summary>
public sealed record RuntimeResolution(string Tool, string Path, RuntimeSource Source);

/// <summary>未能定位运行时工具时抛出。</summary>
public sealed class RuntimeToolNotFoundException : Exception
{
    public RuntimeToolNotFoundException(string tool)
        : base($"未能定位运行时工具 \"{tool}\"。请确认已随应用打包，或在设置中指定其所在目录。") =>
        Tool = tool;

    public RuntimeToolNotFoundException()
    {
    }

    public RuntimeToolNotFoundException(string message, Exception innerException)
        : base(message, innerException)
    {
    }

    /// <summary>缺失的工具名。</summary>
    public string Tool { get; } = string.Empty;
}

/// <summary>
/// 按 应用内置目录 → 用户指定目录 → 系统 PATH 的顺序定位运行时可执行文件。
/// 内置目录固定为 <c>&lt;appRoot&gt;/runtime/ffmpeg</c>（ffmpeg 与 ffprobe 同处该目录）。
/// </summary>
public sealed class RuntimeResolver
{
    private const string RuntimeDirectoryName = "runtime";
    private const string BundleDirectoryName = "ffmpeg";

    private readonly string _appRoot;
    private readonly Func<string, string?> _pathLookup;

    /// <summary>创建定位器。</summary>
    /// <param name="appRoot">应用安装根目录（其下含 <c>runtime/ffmpeg</c>）。</param>
    /// <param name="pathLookup">PATH 查找委托：输入可执行文件名，返回绝对路径或 <c>null</c>。</param>
    public RuntimeResolver(string appRoot, Func<string, string?> pathLookup)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(appRoot);
        ArgumentNullException.ThrowIfNull(pathLookup);
        _appRoot = appRoot;
        _pathLookup = pathLookup;
    }

    /// <summary>定位指定工具（如 <c>ffmpeg</c>、<c>ffprobe</c>）。</summary>
    /// <param name="tool">工具名，不含扩展名。</param>
    /// <param name="userDirectory">用户指定目录，可为空。</param>
    /// <exception cref="RuntimeToolNotFoundException">全部来源均未找到时抛出。</exception>
    public RuntimeResolution Resolve(string tool, string? userDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(tool);

        var executable = OperatingSystem.IsWindows() ? tool + ".exe" : tool;

        var bundled = System.IO.Path.Combine(_appRoot, RuntimeDirectoryName, BundleDirectoryName, executable);
        if (System.IO.File.Exists(bundled))
        {
            return new RuntimeResolution(tool, bundled, RuntimeSource.Bundled);
        }

        if (!string.IsNullOrWhiteSpace(userDirectory))
        {
            var user = System.IO.Path.Combine(userDirectory, executable);
            if (System.IO.File.Exists(user))
            {
                return new RuntimeResolution(tool, user, RuntimeSource.User);
            }
        }

        var fromPath = _pathLookup(executable);
        if (!string.IsNullOrWhiteSpace(fromPath) && System.IO.File.Exists(fromPath))
        {
            return new RuntimeResolution(tool, fromPath, RuntimeSource.Path);
        }

        throw new RuntimeToolNotFoundException(tool);
    }

    /// <summary>
    /// 定位 <c>runtime/</c> 下任意相对路径的可执行文件（如 whisper、tesseract）。
    /// </summary>
    public RuntimeResolution ResolveRelative(string relativePath, string tool, string? userDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(relativePath);
        ArgumentException.ThrowIfNullOrWhiteSpace(tool);

        var bundled = System.IO.Path.Combine(_appRoot, RuntimeDirectoryName, relativePath);
        if (System.IO.File.Exists(bundled))
        {
            return new RuntimeResolution(tool, bundled, RuntimeSource.Bundled);
        }

        if (!string.IsNullOrWhiteSpace(userDirectory))
        {
            var fileName = System.IO.Path.GetFileName(relativePath);
            var user = System.IO.Path.Combine(userDirectory, fileName);
            if (System.IO.File.Exists(user))
            {
                return new RuntimeResolution(tool, user, RuntimeSource.User);
            }
        }

        var fromPath = _pathLookup(System.IO.Path.GetFileName(relativePath));
        if (!string.IsNullOrWhiteSpace(fromPath) && System.IO.File.Exists(fromPath))
        {
            return new RuntimeResolution(tool, fromPath, RuntimeSource.Path);
        }

        throw new RuntimeToolNotFoundException(tool);
    }
}
