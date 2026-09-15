using System.Drawing;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Bootstrap;
using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.IntegrationTests.Media;

public sealed class FourScreenRenderTests
{
    [Theory]
    [InlineData(false, 0, false)]
    [InlineData(true, 48, false)]
    [InlineData(true, 256, true)]
    public async Task Four_colors_preserve_cells_seams_duration_and_selected_audio(bool feather, int pixels, bool withBgm)
    {
        var (ffmpeg, ffprobe) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpeg, ffprobe);
        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var colors = new[] { "red", "lime", "blue", "white" };
        var expectedColors = new[] { new Rgb24(255, 0, 0), new Rgb24(0, 255, 0), new Rgb24(0, 0, 255), new Rgb24(255, 255, 255) };
        var assets = new List<MediaAsset>();
        for (var index = 0; index < colors.Length; index++)
        {
            var path = Path.Combine(workspace.Root, $"color-{index}.mp4");
            await LavfiMediaFactory.GenerateToneClipAsync(ffmpeg, path, index + 1, colors[index],
                200 + index * 150, TimeSpan.FromSeconds(index == 0 ? 2 : 0.5));
            assets.Add(new MediaAsset(Guid.NewGuid(), path, index + 1, await probe.ProbeAsync(path, default)));
        }

        var plan = new CompositionPlan(
            [new PlannedClip(assets[0], TimeSpan.Zero, TimeSpan.FromSeconds(2)),
             new PlannedClip(assets[0], TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(2))],
            TimeSpan.FromSeconds(4), 42, TimeSpan.Zero);
        BgmMixPlan? bgm = null;
        if (withBgm)
        {
            var path = Path.Combine(workspace.Root, "background.m4a");
            await LavfiMediaFactory.GenerateBgmToneAsync(ffmpeg, path, 700, TimeSpan.FromSeconds(4));
            bgm = new BgmMixPlan(path, OriginalVolume: 0, BgmVolume: 1, FadeOutSeconds: 0);
        }

        var request = Assert.Single(RenderRequestFactory.CreateForPlans(
            [plan], workspace.Root, "rendered", RenderProfile.Balanced, OutputAspect.InheritFirst,
            bgm: bgm, fourScreen: new FourScreenEffectPlan(2, FourScreenSourceMode.RandomCurrentFolder, feather, pixels),
            fourScreenSourceAssets: assets));
        await RenderAsync(request, workspace);

        var info = await probe.ProbeAsync(request.OutputPath, default);
        Assert.Equal(320, info.Width);
        Assert.Equal(240, info.Height);
        Assert.InRange(info.Duration.TotalSeconds, 3.9, 4.15);
        Assert.True(info.HasAudio);
        var frequency = await MediaSampleAnalyzer.SampleDominantFrequencyAsync(ffmpeg, request.OutputPath,
            TimeSpan.FromSeconds(3), TimeSpan.FromSeconds(0.4));
        Assert.InRange(frequency, withBgm ? 688 : 188, withBgm ? 712 : 212);

        var beforePath = await ExtractFrameAsync(ffmpeg, request.OutputPath, workspace.Root, "before", "0.5");
        using (var before = new Bitmap(beforePath))
        {
            AssertPixel(before, 80, 60, expectedColors[0]);
            AssertPixel(before, 240, 180, expectedColors[0]);
        }

        // 采样主片后半段，已超过 0.5 秒辅助视频，能证明循环没有提前停止或出现黑格。
        var afterPath = await ExtractFrameAsync(ffmpeg, request.OutputPath, workspace.Root, "after", "3.5");
        using var after = new Bitmap(afterPath);
        var selection = request.FourScreen!.SelectionFor(1)!;
        var expectedByPosition = new Rgb24[4];
        foreach (var cell in selection.Cells)
        {
            var position = (int)cell.Position;
            var sourceIndex = assets.FindIndex(asset => asset.Path == cell.SourceAsset.Path);
            expectedByPosition[position] = expectedColors[sourceIndex];
            AssertPixel(after, position % 2 == 0 ? 80 : 240, position < 2 ? 60 : 180, expectedColors[sourceIndex]);
        }

        if (feather)
        {
            AssertPixel(after, 160, 60, Average(expectedByPosition[0], expectedByPosition[1]), tolerance: 24);
            AssertPixel(after, 80, 120, Average(expectedByPosition[0], expectedByPosition[2]), tolerance: 24);
            AssertPixel(after, 160, 120, new Rgb24(127, 127, 127), tolerance: 24);
            // 相邻交点像素应连续，不应出现一条黑线或亮线。
            for (var y = 118; y <= 122; y++)
            {
                for (var x = 158; x <= 162; x++)
                {
                    AssertPixel(after, x, y, new Rgb24(127, 127, 127), tolerance: 30);
                }
            }
        }
    }

    [Theory]
    [InlineData(320, 240)]
    [InlineData(318, 238)]
    public async Task Current_source_duplicates_a_moving_pattern_into_four_synchronized_cells(int width, int height)
    {
        var (ffmpeg, ffprobe) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpeg, ffprobe);
        var source = Path.Combine(workspace.Root, "pattern.mp4");
        var generated = await new ExternalProcessRunner().RunAsync(ProcessRequest.Create(ffmpeg,
            ["-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", source]), null, default);
        Assert.Equal(0, generated.ExitCode);
        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var asset = new MediaAsset(Guid.NewGuid(), source, 1, await probe.ProbeAsync(source, default));
        var plan = new CompositionPlan([new PlannedClip(asset, TimeSpan.Zero, TimeSpan.FromSeconds(1))],
            TimeSpan.FromSeconds(1), 7, TimeSpan.Zero);
        var request = Assert.Single(RenderRequestFactory.CreateForPlans([plan], workspace.Root, "same-source",
            RenderProfile.Balanced, OutputAspect.Custom(width, height), fourScreen: new FourScreenEffectPlan(1, FeatherEnabled: false)));
        await RenderAsync(request, workspace);
        var info = await probe.ProbeAsync(request.OutputPath, default);
        Assert.Equal(width, info.Width);
        Assert.Equal(height, info.Height);
        Assert.InRange(info.Duration.TotalSeconds, 0.9, 1.15);
        var imagePath = await ExtractFrameAsync(ffmpeg, request.OutputPath, workspace.Root, "same-source", "0.7");
        using var frame = new Bitmap(imagePath);
        foreach (var (x, y) in new[] { (30, 25), (85, 65), (120, 90) })
        {
            // 比较小块均值，避免 H.264 和奇数格边界的色度相位让单个高频边缘像素偏移。
            var expected = PatchColor(frame, x, y);
            Assert.True(PatchColor(frame, x + width / 2, y).IsCloseTo(expected, 18));
            Assert.True(PatchColor(frame, x, y + height / 2).IsCloseTo(expected, 18));
            Assert.True(PatchColor(frame, x + width / 2, y + height / 2).IsCloseTo(expected, 18));
        }
    }

    [Fact]
    public async Task Feather_masks_and_repeated_short_sources_remain_valid_at_the_end_of_multiple_clips()
    {
        var (ffmpeg, ffprobe) = MediaIntegrationHarness.RequireFfmpeg();
        using var workspace = MediaIntegrationHarness.CreateWorkspace();
        MediaIntegrationHarness.InstallBundledRuntime(workspace, ffmpeg, ffprobe);
        var probe = RenderInfrastructure.CreateMediaProbe(workspace.AppRoot);
        var assets = new List<MediaAsset>();
        foreach (var item in new[] { (Color: "red", Rate: "30000/1001", Duration: "10"),
                                    (Color: "blue", Rate: "17", Duration: "0.5") })
        {
            var path = Path.Combine(workspace.Root, item.Color + ".mp4");
            var generated = await new ExternalProcessRunner().RunAsync(ProcessRequest.Create(ffmpeg,
                ["-y", "-f", "lavfi", "-i", $"color=c={item.Color}:size=320x240:rate={item.Rate}:duration={item.Duration}",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", path]), null, default);
            Assert.True(generated.ExitCode == 0, generated.StandardError);
            assets.Add(new MediaAsset(Guid.NewGuid(), path, assets.Count + 1, await probe.ProbeAsync(path, default)));
        }

        var plan = new CompositionPlan(
            [new PlannedClip(assets[0], TimeSpan.Zero, TimeSpan.FromSeconds(5)),
             new PlannedClip(assets[0], TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(5))],
            TimeSpan.FromSeconds(10), 42, TimeSpan.Zero);
        var request = Assert.Single(RenderRequestFactory.CreateForPlans(
            [plan], workspace.Root, "long-feather", RenderProfile.Balanced, OutputAspect.Custom(318, 238),
            fourScreen: new FourScreenEffectPlan(1, FourScreenSourceMode.RandomCurrentFolder, true, 48),
            fourScreenSourceAssets: assets));
        await RenderAsync(request, workspace);

        var info = await probe.ProbeAsync(request.OutputPath, default);
        Assert.Equal(318, info.Width);
        Assert.Equal(238, info.Height);
        Assert.InRange(info.Duration.TotalSeconds, 9.9, 10.15);
        Assert.InRange(info.FrameRate, 29.9m, 30.1m);
        foreach (var (clipIndex, timestamp) in new[] { (0, "4.8"), (1, "9.8") })
        {
            var imagePath = await ExtractFrameAsync(ffmpeg, request.OutputPath, workspace.Root, "tail-" + clipIndex, timestamp);
            using var frame = new Bitmap(imagePath);
            var expected = request.FourScreen!.SelectionFor(clipIndex)!.Cells.OrderBy(cell => cell.Position)
                .Select(cell => cell.SourceAsset.Path == assets[0].Path ? new Rgb24(255, 0, 0) : new Rgb24(0, 0, 255)).ToArray();
            for (var position = 0; position < 4; position++)
            {
                AssertPixel(frame, position % 2 == 0 ? 60 : 238, position < 2 ? 40 : 178, expected[position]);
            }

            AssertPixel(frame, 159, 40, Average(expected[0], expected[1]), tolerance: 24);
            AssertPixel(frame, 60, 119, Average(expected[0], expected[2]), tolerance: 24);
            AssertPixel(frame, 159, 119, Average(Average(expected[0], expected[1]), Average(expected[2], expected[3])), tolerance: 24);
        }
    }

    private static async Task RenderAsync(RenderRequest request, MediaWorkspace workspace)
    {
        var job = RenderJob.CreateQueued(request with { ProcessingMode = VideoProcessingMode.Cpu });
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var result = await MediaIntegrationHarness.CreateExecutor(workspace).ExecuteAsync(job, null, timeout.Token);
        var log = Path.Combine(workspace.Root, ".jingxu-logs", job.Id.ToString("N"), "render.log");
        Assert.True(result.IsSuccess, result.FailureInfo?.Message + Environment.NewLine + (File.Exists(log) ? await File.ReadAllTextAsync(log) : string.Empty));
        Assert.True(File.Exists(request.OutputPath));
        Assert.False(Directory.Exists(Path.Combine(workspace.Root, ".jingxu-tmp", job.Id.ToString("N"))));
    }

    private static async Task<string> ExtractFrameAsync(string ffmpeg, string video, string workspace, string name, string timestamp)
    {
        var path = Path.Combine(workspace, name + ".png");
        var result = await new ExternalProcessRunner().RunAsync(ProcessRequest.Create(ffmpeg,
            ["-y", "-ss", timestamp, "-i", video, "-frames:v", "1", path]), null, default);
        Assert.True(result.ExitCode == 0, result.StandardError);
        return path;
    }

    private static Rgb24 Pixel(Bitmap bitmap, int x, int y)
    {
        var color = bitmap.GetPixel(x, y);
        return new Rgb24(color.R, color.G, color.B);
    }

    private static void AssertPixel(Bitmap bitmap, int x, int y, Rgb24 expected, int tolerance = 18)
    {
        var actual = Pixel(bitmap, x, y);
        Assert.True(actual.IsCloseTo(expected, tolerance), $"像素 ({x},{y}) 预期 {expected}，实际 {actual}。");
    }

    private static Rgb24 Average(Rgb24 left, Rgb24 right) =>
        new((byte)((left.R + right.R) / 2), (byte)((left.G + right.G) / 2), (byte)((left.B + right.B) / 2));

    private static Rgb24 PatchColor(Bitmap bitmap, int centerX, int centerY)
    {
        var red = 0;
        var green = 0;
        var blue = 0;
        for (var y = centerY - 3; y <= centerY + 3; y++)
        {
            for (var x = centerX - 3; x <= centerX + 3; x++)
            {
                var pixel = bitmap.GetPixel(x, y);
                red += pixel.R;
                green += pixel.G;
                blue += pixel.B;
            }
        }

        return new Rgb24((byte)(red / 49), (byte)(green / 49), (byte)(blue / 49));
    }
}
