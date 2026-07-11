using JingXu.Workbench.Infrastructure.Bootstrap;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class HardCutIntegrationTests
{
    [Fact]
    public async Task Lavfi_hard_cut_output_duration_matches_segment_sum()
    {
        var ffmpegPath = FfmpegRuntimeProbe.FindFfmpeg();
        if (ffmpegPath is null || FfmpegRuntimeProbe.FindFfprobe() is null)
        {
            Assert.Skip("本机未找到 FFmpeg/FFprobe，跳过 lavfi 硬切集成测试。");
            return;
        }

        var tempDir = Path.Combine(Path.GetTempPath(), "jingxu-hardcut-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);
        var appRoot = Path.Combine(tempDir, "app");
        Directory.CreateDirectory(appRoot);

        var clipA = Path.Combine(tempDir, "a.mp4");
        var clipB = Path.Combine(tempDir, "b.mp4");
        var output = Path.Combine(tempDir, "merged.mp4");

        try
        {
            await LavfiMediaFactory.GenerateColorClipAsync(ffmpegPath, clipA, "red", TimeSpan.FromSeconds(1));
            await LavfiMediaFactory.GenerateColorClipAsync(ffmpegPath, clipB, "blue", TimeSpan.FromSeconds(1));
            await LavfiMediaFactory.ConcatHardCutAsync(ffmpegPath, [clipA, clipB], output);

            var probe = RenderInfrastructure.CreateMediaProbe(appRoot);
            var info = await probe.ProbeAsync(output, default);

            Assert.InRange(info.Duration.TotalMilliseconds, 1800, 2200);
            Assert.Equal(320, info.Width);
            Assert.Equal(240, info.Height);
        }
        finally
        {
            try { Directory.Delete(tempDir, recursive: true); }
            catch (IOException) { }
        }
    }

    [Fact]
    public async Task Lavfi_clip_probe_reports_expected_dimensions()
    {
        var ffmpegPath = FfmpegRuntimeProbe.FindFfmpeg();
        if (ffmpegPath is null || FfmpegRuntimeProbe.FindFfprobe() is null)
        {
            Assert.Skip("本机未找到 FFmpeg/FFprobe，跳过 lavfi 探测集成测试。");
            return;
        }

        var tempDir = Path.Combine(Path.GetTempPath(), "jingxu-lavfi-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);
        var appRoot = Path.Combine(tempDir, "app");
        Directory.CreateDirectory(appRoot);
        var clip = Path.Combine(tempDir, "green.mp4");

        try
        {
            await LavfiMediaFactory.GenerateColorClipAsync(
                ffmpegPath,
                clip,
                "0x00FF00",
                TimeSpan.FromMilliseconds(900));

            var probe = RenderInfrastructure.CreateMediaProbe(appRoot);
            var info = await probe.ProbeAsync(clip, default);

            Assert.InRange(info.Duration.TotalMilliseconds, 700, 1100);
            Assert.Equal("h264", info.VideoCodec);
            Assert.Equal(320, info.Width);
            Assert.Equal(240, info.Height);
        }
        finally
        {
            try { Directory.Delete(tempDir, recursive: true); }
            catch (IOException) { }
        }
    }
}
