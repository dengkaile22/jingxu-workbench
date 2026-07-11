using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class AudioFilterCompilerTests
{
    [Fact]
    public void Bgm_defaults_keep_original_and_loop_with_fade()
    {
        var graph = AudioFilterCompiler.Compile(AudioPlans.WithBgm(durationSeconds: 10));
        Assert.Contains("aloop", graph, StringComparison.Ordinal);
        Assert.Contains("volume=0.18", graph, StringComparison.Ordinal);
        Assert.Contains("afade=t=out:st=9:d=1", graph, StringComparison.Ordinal);
        Assert.Contains("amix=duration=first", graph, StringComparison.Ordinal);
    }

    [Fact]
    public void Without_bgm_passthrough_main_audio()
    {
        var graph = AudioFilterCompiler.Compile(AudioPlans.WithoutBgm());
        Assert.Contains("[aout_raw]anull[aout]", graph, StringComparison.Ordinal);
        Assert.DoesNotContain("amix", graph, StringComparison.Ordinal);
    }

    [Fact]
    public void Silent_main_with_bgm_uses_anullsrc()
    {
        var graph = AudioFilterCompiler.Compile(AudioPlans.WithBgmOnly(durationSeconds: 8));
        Assert.Contains("anullsrc", graph, StringComparison.Ordinal);
        Assert.Contains("amix", graph, StringComparison.Ordinal);
    }

    [Fact]
    public void Custom_volumes_are_reflected_in_graph()
    {
        var bgm = BgmMixPlan.Create(@"C:\bgm.mp3", originalVolume: 0.8, bgmVolume: 0.25, fadeOutSeconds: 2).Value!;
        var graph = AudioFilterCompiler.Compile(new AudioMixCompileRequest(
            MainAudioLabel: "aout_raw",
            OutputDuration: TimeSpan.FromSeconds(12),
            BgmInputIndex: 2,
            Bgm: bgm,
            MainHasAudio: true));

        Assert.Contains("volume=0.8", graph, StringComparison.Ordinal);
        Assert.Contains("volume=0.25", graph, StringComparison.Ordinal);
        Assert.Contains("afade=t=out:st=10:d=2", graph, StringComparison.Ordinal);
    }
}

internal static class AudioPlans
{
    public static AudioMixCompileRequest WithBgm(double durationSeconds) =>
        new(
            MainAudioLabel: "aout_raw",
            OutputDuration: TimeSpan.FromSeconds(durationSeconds),
            BgmInputIndex: 1,
            Bgm: BgmMixPlan.Create(@"C:\bgm.mp3").Value,
            MainHasAudio: true);

    public static AudioMixCompileRequest WithoutBgm() =>
        new(
            MainAudioLabel: "aout_raw",
            OutputDuration: TimeSpan.FromSeconds(10),
            BgmInputIndex: null,
            Bgm: null,
            MainHasAudio: true);

    public static AudioMixCompileRequest WithBgmOnly(double durationSeconds) =>
        new(
            MainAudioLabel: "aout_raw",
            OutputDuration: TimeSpan.FromSeconds(durationSeconds),
            BgmInputIndex: 0,
            Bgm: BgmMixPlan.Create(@"C:\bgm.mp3").Value,
            MainHasAudio: false);
}
