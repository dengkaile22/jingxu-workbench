using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Application.Abstractions;

/// <summary>
/// 媒体文件元数据探测抽象。实现方负责调用 FFprobe 并填充 <see cref="MediaInfo"/>。
/// </summary>
public interface IMediaProbe
{
    /// <summary>
    /// 探测指定媒体文件的元信息。
    /// </summary>
    /// <param name="absolutePath">媒体文件绝对路径。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>探测得到的不可变元信息。</returns>
    /// <exception cref="MediaProbeException">探测失败（进程非零退出、输出无法解析等）。</exception>
    Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken);
}

/// <summary>
/// 媒体探测失败时抛出，包含素材路径与 stderr 摘要。
/// </summary>
public sealed class MediaProbeException : Exception
{
    public MediaProbeException(string mediaPath, string message, string? stderrSummary = null, Exception? innerException = null)
        : base(message, innerException)
    {
        MediaPath = mediaPath;
        StderrSummary = stderrSummary;
    }

    /// <summary>被探测的媒体绝对路径。</summary>
    public string MediaPath { get; }

    /// <summary>FFprobe 标准错误的有界摘要，可为空。</summary>
    public string? StderrSummary { get; }
}
