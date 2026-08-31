using System.Globalization;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>音频混音编译请求。</summary>
public sealed record AudioMixCompileRequest(
    string MainAudioLabel,
    TimeSpan OutputDuration,
    int? BgmInputIndex,
    BgmMixPlan? Bgm,
    bool MainHasAudio,
    string OutputLabel = "aout");

/// <summary>将主音轨与 BGM / 蒙版音轨编译为 FFmpeg 音频滤镜链。</summary>
public static class AudioFilterCompiler
{
    /// <summary>编译 BGM 混音滤镜后缀；无 BGM 时直通主音轨。</summary>
    public static string Compile(AudioMixCompileRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        var outputLabel = string.IsNullOrWhiteSpace(request.OutputLabel) ? "aout" : request.OutputLabel;

        if (request.Bgm is null || request.BgmInputIndex is null)
        {
            return $"[{request.MainAudioLabel}]anull[{outputLabel}]";
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
            $"[{bgmInput}:a]aloop=loop=-1,atrim=duration={durationSeconds},asetpts=PTS-STARTPTS,volume={FormatDecimal(bgm.BgmVolume)},afade=t=out:st={FormatSeconds(TimeSpan.FromSeconds(fadeStart))}:d={FormatDecimal(bgm.FadeOutSeconds)}[{bgmLabel}];");
        builder.Append(CultureInfo.InvariantCulture,
            $"[{mainLabel}][{bgmLabel}]amix=duration=first:inputs=2:dropout_transition=0[{outputLabel}]");

        return builder.ToString();
    }

    /// <summary>将需混入的蒙版音轨叠加到主音轨（按蒙版起始时间延迟并对齐成片时长）。</summary>
    public static string CompileOverlayMix(
        string mainAudioLabel,
        IReadOnlyList<(int InputIndex, TimeSpan Start, TimeSpan ActiveDuration)> mixLayers,
        TimeSpan planDuration,
        string outputLabel = "aout")
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(mainAudioLabel);
        ArgumentNullException.ThrowIfNull(mixLayers);
        if (mixLayers.Count == 0)
        {
            return $"[{mainAudioLabel}]anull[{outputLabel}]";
        }

        var builder = new System.Text.StringBuilder();
        var planSeconds = FormatSeconds(planDuration);
        var mixInputs = new System.Text.StringBuilder($"[{mainAudioLabel}]");

        for (var i = 0; i < mixLayers.Count; i++)
        {
            var (inputIndex, start, active) = mixLayers[i];
            var label = $"ova{i}";
            var delayMs = Math.Max(0, (int)Math.Round(start.TotalMilliseconds));
            var activeSeconds = FormatSeconds(active);
            builder.Append(CultureInfo.InvariantCulture,
                $"[{inputIndex}:a]aformat=sample_rates=48000:channel_layouts=stereo,aresample=48000," +
                $"aloop=loop=-1,atrim=duration={activeSeconds},asetpts=PTS-STARTPTS," +
                $"adelay={delayMs}:all=1,apad=whole_dur={planSeconds}[{label}];");
            mixInputs.Append(CultureInfo.InvariantCulture, $"[{label}]");
        }

        var inputCount = mixLayers.Count + 1;
        builder.Append(CultureInfo.InvariantCulture,
            $"{mixInputs}amix=duration=first:inputs={inputCount}:dropout_transition=0[{outputLabel}]");
        return builder.ToString();
    }

    private static string FormatDecimal(double value) =>
        value.ToString("0.######", CultureInfo.InvariantCulture);

    private static string FormatSeconds(TimeSpan duration) =>
        duration.TotalSeconds.ToString("0.######", CultureInfo.InvariantCulture);
}
