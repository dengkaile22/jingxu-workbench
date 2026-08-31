using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Infrastructure.Media;

/// <summary>测试/无 FFmpeg 场景下的空实现：不生成真实帧。</summary>
public sealed class NullMediaFrameExtractor : IMediaFrameExtractor
{
    public Task<Result<string>> ExtractFirstFrameAsync(
        string videoPath,
        string outputJpegPath,
        CancellationToken cancellationToken) =>
        Task.FromResult(Result<string>.Failure("当前环境未配置帧抽取器。"));

    public Task<Result<string>> ExtractOverlayCompositePreviewAsync(
        OverlayCompositePreviewRequest request,
        CancellationToken cancellationToken) =>
        Task.FromResult(Result<string>.Failure("当前环境未配置帧抽取器。"));
}
