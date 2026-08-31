namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>
/// 将任意长度的输入路径映射为 staging 相对短名（如 <c>i0.mp4</c>），供 argv 使用。
/// 同一绝对路径只分配一次别名。
/// </summary>
internal sealed class FfmpegPathAliaser
{
    private readonly Dictionary<string, string> _absoluteToRelative = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<FfmpegInputAlias> _aliases = [];
    private int _nextIndex;

    /// <summary>已分配的别名列表（分配顺序）。</summary>
    public IReadOnlyList<FfmpegInputAlias> Aliases => _aliases;

    /// <summary>返回短相对路径；重复输入复用同一别名。</summary>
    public string Alias(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);

        var absolute = NormalizeAbsolute(path);
        if (_absoluteToRelative.TryGetValue(absolute, out var existing))
        {
            return existing;
        }

        var relative = $"i{_nextIndex++}{SanitizeExtension(path)}";
        _absoluteToRelative[absolute] = relative;
        _aliases.Add(new FfmpegInputAlias(relative, absolute));
        return relative;
    }

    /// <summary>将参数列表中紧跟 <c>-i</c> 的路径替换为短别名。</summary>
    public List<string> RewriteDashIArguments(IReadOnlyList<string> arguments)
    {
        ArgumentNullException.ThrowIfNull(arguments);
        var rewritten = new List<string>(arguments.Count);
        for (var index = 0; index < arguments.Count; index++)
        {
            if (index > 0 && arguments[index - 1] == "-i")
            {
                rewritten.Add(Alias(arguments[index]));
            }
            else
            {
                rewritten.Add(arguments[index]);
            }
        }

        return rewritten;
    }

    private static string NormalizeAbsolute(string path)
    {
        try
        {
            return Path.GetFullPath(path);
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return path;
        }
    }

    private static string SanitizeExtension(string path)
    {
        var extension = Path.GetExtension(path);
        if (string.IsNullOrEmpty(extension) ||
            extension.Length > 12 ||
            extension.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
        {
            return ".bin";
        }

        return extension.ToLowerInvariant();
    }
}
