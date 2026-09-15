namespace JingXu.Workbench.Infrastructure.Rendering;

using JingXu.Workbench.Domain.Rendering;

/// <summary>FFmpeg 最终 H.264 视频编码器。</summary>
public enum VideoEncoderKind
{
    Libx264,
    H264Nvenc,
    H264Qsv,
    H264Amf
}

/// <summary>一次渲染实际采用的编码器及其用户可见说明。</summary>
public sealed record VideoEncoderSelection(
    VideoEncoderKind Kind,
    string DisplayName,
    string? Notice = null,
    bool IsFallback = false)
{
    public static VideoEncoderSelection Cpu(string? notice = null, bool isFallback = false) =>
        new(VideoEncoderKind.Libx264, "CPU（libx264）", notice, isFallback);
}

/// <summary>按任务策略选择实际可用的最终视频编码器。</summary>
public interface IVideoEncoderSelector
{
    Task<VideoEncoderSelection> SelectAsync(
        string ffmpegExecutable,
        VideoProcessingMode mode,
        CancellationToken cancellationToken);

    /// <summary>
    /// 正式 GPU 编码已证明该编码器不可用时，本会话内跳过它，后续任务改探下一候选或 CPU。
    /// </summary>
    void RememberHardwareFailure(string ffmpegExecutable, VideoEncoderKind kind)
    {
    }

    /// <summary>清空某 FFmpeg 路径上的探测缓存与跳过名单（设置页刷新诊断）。</summary>
    void ResetProbe(string ffmpegExecutable)
    {
    }
}
