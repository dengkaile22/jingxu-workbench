using System.Globalization;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>音频混音编译请求。</summary>
public sealed record AudioMixCompileRequest(
    string MainAudioLabel,
    TimeSpan OutputDuration,
    int? BgmInputIndex,
    BgmMixPlan? Bgm,
    bool MainHasAudio);

/// <summary>将主音轨与 BGM 编译为 FFmpeg 音频滤镜链。</summary>
public static class AudioFilterCompiler
{
    /// <summary>编译音频滤镜后缀；无 BGM 时直通主音轨。</summary>
    public static string Compile(AudioMixCompileRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        if (request.Bgm is null || request.BgmInputIndex is null)
        {
            return $"[{request.MainAudioLabel}]anull[aout]";
        }

        var durationSeconds = FormatSeconds(request.OutputDuration);
        var fadeStart = Math.Max(0, request.OutputDuration.TotalSeconds - request.Bgm.FadeOutSeconds);
        var bgm = request.Bgm;
        var bgmInput = request.BgmInputIndex.Value;

        var mainLabel = "amain";
        var bgmLabel = "abgm";
        var builder = new System.Text.StringBuilder();

        if (request.MainHasAudio)
        {
            builder.Append(CultureInfo.InvariantCulture,
                $"[{request.MainAudioLabel}]volume={FormatDecimal(bgm.OriginalVolume)}[{mainLabel}];");
        }
        else
        {
            builder.Append(CultureInfo.InvariantCulture,
                $"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={durationSeconds},asetpts=PTS-STARTPTS,volume={FormatDecimal(bgm.OriginalVolume)}[{mainLabel}];");
        }

        builder.Append(CultureInfo.InvariantCulture,
            $"[{bgmInput}:a]aloop=loop=-1:size=2e+09,atrim=duration={durationSeconds},asetpts=PTS-STARTPTS,volume={FormatDecimal(bgm.BgmVolume)},afade=t=out:st={FormatSeconds(TimeSpan.FromSeconds(fadeStart))}:d={FormatDecimal(bgm.FadeOutSeconds)}[{bgmLabel}];");
        builder.Append(CultureInfo.InvariantCulture,
            $"[{mainLabel}][{bgmLabel}]amix=duration=first:inputs=2:dropout_transition=0[aout]");

        return builder.ToString();
    }

    private static string FormatDecimal(double value) =>
        value.ToString("0.######", CultureInfo.InvariantCulture);

    private static string FormatSeconds(TimeSpan duration) =>
        duration.TotalSeconds.ToString("0.######", CultureInfo.InvariantCulture);
}
