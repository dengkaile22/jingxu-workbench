using System.Globalization;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>集中生成各厂商 H.264 编码器参数，保证质量档位映射一致。</summary>
public static class VideoEncoderArguments
{
    public static IReadOnlyList<string> Build(VideoEncoderKind encoder, RenderProfile profile)
    {
        ArgumentNullException.ThrowIfNull(profile);

        var quality = profile.Crf ?? RenderProfile.Balanced.Crf ?? 22;
        var qualityText = quality.ToString(CultureInfo.InvariantCulture);

        return encoder switch
        {
            VideoEncoderKind.Libx264 =>
            [
                "-c:v", "libx264",
                "-preset", profile.EncodePreset,
                "-threads", "0",
                "-crf", qualityText
            ],
            VideoEncoderKind.H264Nvenc =>
            [
                "-c:v", "h264_nvenc",
                "-preset", NvencPreset(profile.Quality),
                "-tune", "hq",
                "-rc", "vbr",
                "-b:v", "0",
                "-cq", qualityText
            ],
            VideoEncoderKind.H264Qsv =>
            [
                "-c:v", "h264_qsv",
                "-preset", QsvPreset(profile.Quality),
                "-global_quality", qualityText
            ],
            VideoEncoderKind.H264Amf =>
            [
                "-c:v", "h264_amf",
                "-quality", AmfQuality(profile.Quality),
                "-rc", "cqp",
                "-qp_i", qualityText,
                "-qp_p", qualityText,
                "-qp_b", qualityText
            ],
            _ => throw new ArgumentOutOfRangeException(nameof(encoder), encoder, "未知的视频编码器。")
        };
    }

    private static string NvencPreset(QualityPreset quality) =>
        quality switch
        {
            QualityPreset.High => "p6",
            QualityPreset.Balanced or QualityPreset.Lossless => "p5",
            QualityPreset.Small => "p4",
            QualityPreset.Fast => "p2",
            _ => "p5"
        };

    private static string QsvPreset(QualityPreset quality) =>
        quality switch
        {
            QualityPreset.High => "slow",
            QualityPreset.Balanced or QualityPreset.Lossless => "medium",
            QualityPreset.Small => "faster",
            QualityPreset.Fast => "veryfast",
            _ => "medium"
        };

    private static string AmfQuality(QualityPreset quality) =>
        quality switch
        {
            QualityPreset.High => "quality",
            QualityPreset.Balanced or QualityPreset.Lossless => "balanced",
            QualityPreset.Small or QualityPreset.Fast => "speed",
            _ => "balanced"
        };
}
