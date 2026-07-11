namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>编译后的 FFmpeg 命令（可执行文件 + 独立参数列表）。</summary>
public sealed record FfmpegCommand(string Executable, IReadOnlyList<string> Arguments)
{
    /// <summary>估算 Windows 命令行长度（保守预算，含可执行文件路径）。</summary>
    public int EstimatedCommandLineLength =>
        Executable.Length + Arguments.Sum(a => a.Length + 1);
}
