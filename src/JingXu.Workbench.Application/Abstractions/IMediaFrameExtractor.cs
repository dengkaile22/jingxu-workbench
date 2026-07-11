using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Application.Abstractions;

/// <summary>
/// 从视频素材抽取首帧静图，供取景井在 MediaElement 无法解码时降级预览。
/// </summary>
public interface IMediaFrameExtractor
{
    /// <summary>
    /// 抽取首帧并写入 JPEG 文件。
    /// </summary>
    /// <param name="videoPath">视频绝对路径。</param>
    /// <param name="outputJpegPath">输出 JPEG 绝对路径。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    Task<Result<string>> ExtractFirstFrameAsync(
        string videoPath,
        string outputJpegPath,
        CancellationToken cancellationToken);
}
