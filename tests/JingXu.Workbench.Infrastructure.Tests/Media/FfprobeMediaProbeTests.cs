using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;
using JingXu.Workbench.Infrastructure.Tests.Runtime;

namespace JingXu.Workbench.Infrastructure.Tests.Media;

public sealed class FfprobeMediaProbeTests
{
    [Fact]
    public async Task Throws_chinese_error_when_ffprobe_is_missing()
    {
        using var layout = RuntimeLayout.Create();
        var probe = CreateProbe(layout, new FakeRunner(exitCode: 0, stderr: string.Empty));

        var ex = await Assert.ThrowsAsync<MediaProbeException>(() =>
            probe.ProbeAsync(@"C:\素材\测试.mp4", default));

        Assert.Equal(@"C:\素材\测试.mp4", ex.MediaPath);
        Assert.Contains("FFprobe", ex.Message);
    }

    [Fact]
    public async Task Throws_chinese_error_when_ffprobe_exits_nonzero()
    {
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffprobe.exe");
        var probe = CreateProbe(layout, new FakeRunner(exitCode: 1, stderr: "Invalid data found"));

        var ex = await Assert.ThrowsAsync<MediaProbeException>(() =>
            probe.ProbeAsync(@"C:\素材\损坏.mp4", default));

        Assert.Equal(@"C:\素材\损坏.mp4", ex.MediaPath);
        Assert.Contains("Invalid data found", ex.StderrSummary);
        Assert.Contains("探测失败", ex.Message);
    }

    [Fact]
    public async Task Uses_argument_list_without_shell_concatenation()
    {
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffprobe.exe");
        var runner = new RecordingRunner(exitCode: 0, stdout: MinimalProbeJson());
        var probe = CreateProbe(layout, runner);

        await probe.ProbeAsync(@"C:\测试 文件\clip.mp4", default);

        var request = Assert.Single(runner.Requests);
        Assert.Equal(layout.BundledFfprobe, request.Executable);
        Assert.Equal("-v", request.Arguments[0]);
        Assert.Equal("error", request.Arguments[1]);
        Assert.Contains(@"-show_entries", request.Arguments);
        Assert.Equal(@"C:\测试 文件\clip.mp4", request.Arguments[^1]);
        Assert.DoesNotContain(request.Arguments, x => x.Contains("cmd.exe", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public async Task Probes_zhaoyu_mask_with_chinese_spaces_and_parentheses_when_runtime_available()
    {
        const string maskPath =
            @"C:\Users\dengkaile\OneDrive\Desktop\project2026071001\test-assets\赵雨蒙版\赵雨 (8).mp4";
        if (!File.Exists(maskPath))
        {
            Assert.Skip("未找到赵雨蒙版测试素材。");
        }

        var ffprobePath = FindOnSystemPath("ffprobe");
        if (ffprobePath is null)
        {
            Assert.Skip("本机未找到 FFprobe，跳过真实媒体探测集成测试。");
            return;
        }

        using var layout = RuntimeLayout.Create();
        layout.RegisterExistingExecutable("ffprobe", ffprobePath);
        var probe = CreateProbe(layout, new ExternalProcessRunner());

        var info = await probe.ProbeAsync(maskPath, default);

        Assert.True(info.Duration > TimeSpan.FromSeconds(160));
        Assert.Equal(1080, info.Width);
        Assert.Equal(1920, info.Height);
        Assert.Equal("h264", info.VideoCodec);
        Assert.True(info.HasAudio);
    }

    [Fact]
    public async Task Probes_real_rotated_lavfi_clip_when_runtime_available()
    {
        var ffprobePath = FindOnSystemPath("ffprobe");
        var ffmpegPath = FindOnSystemPath("ffmpeg");
        if (ffprobePath is null || ffmpegPath is null)
        {
            Assert.Skip("本机未找到 FFprobe/FFmpeg，跳过真实媒体探测集成测试。");
            return;
        }

        using var layout = RuntimeLayout.Create();
        layout.RegisterExistingExecutable("ffprobe", ffprobePath);
        layout.RegisterExistingExecutable("ffmpeg", ffmpegPath);
        var resolver = new RuntimeResolver(layout.AppRoot, layout.PathLookup);

        var tempDir = Path.Combine(Path.GetTempPath(), "jingxu-probe-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);
        var mediaPath = Path.Combine(tempDir, "rotated.mp4");

        try
        {
            await GenerateRotatedClipAsync(ffmpegPath, mediaPath);

            var probe = new FfprobeMediaProbe(
                new ExternalProcessRunner(),
                resolver);

            var info = await probe.ProbeAsync(mediaPath, default);

            Assert.True(info.Duration > TimeSpan.Zero);
            Assert.Equal(1080, info.Width);
            Assert.Equal(1920, info.Height);
            Assert.Equal("h264", info.VideoCodec);
        }
        finally
        {
            try { Directory.Delete(tempDir, recursive: true); }
            catch (IOException) { }
        }
    }

    private static string? FindOnSystemPath(string tool)
    {
        var name = RuntimeLayout.ExecutableName(tool);
        var pathEnv = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathEnv))
        {
            return null;
        }

        foreach (var dir in pathEnv.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            var candidate = Path.Combine(dir.Trim(), name);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private static FfprobeMediaProbe CreateProbe(RuntimeLayout layout, IExternalProcessRunner runner) =>
        new(runner, new RuntimeResolver(layout.AppRoot, layout.PathLookup));

    private static string MinimalProbeJson() =>
        """
        {
          "streams": [
            {
              "codec_type": "video",
              "codec_name": "h264",
              "width": 640,
              "height": 360,
              "avg_frame_rate": "24/1"
            }
          ],
          "format": { "duration": "1.000000" }
        }
        """;

    private static async Task GenerateRotatedClipAsync(string ffmpegPath, string outputPath)
    {
        var request = ProcessRequest.Create(
            ffmpegPath,
            [
                "-y",
                "-f", "lavfi",
                "-i", "testsrc=duration=1:size=1080x1920:rate=30",
                "-c:v", "libx264",
                "-t", "1",
                "-metadata:s:v:0", "rotate=90",
                outputPath
            ]);

        var result = await new ExternalProcessRunner().RunAsync(request, null, default);
        if (result.ExitCode != 0)
        {
            throw new InvalidOperationException(
                $"生成测试媒体失败：{result.StandardError.Trim()}");
        }
    }

    private sealed class FakeRunner(int exitCode, string stderr) : IExternalProcessRunner
    {
        public Task<IProcessResult> RunAsync(
            IProcessRequest request,
            IProgress<string>? progress,
            CancellationToken cancellationToken) =>
            Task.FromResult<IProcessResult>(new ProcessResult(exitCode, string.Empty, stderr));
    }

    private sealed class RecordingRunner(int exitCode, string stdout) : IExternalProcessRunner
    {
        public List<IProcessRequest> Requests { get; } = [];

        public Task<IProcessResult> RunAsync(
            IProcessRequest request,
            IProgress<string>? progress,
            CancellationToken cancellationToken)
        {
            Requests.Add(request);
            return Task.FromResult<IProcessResult>(new ProcessResult(exitCode, stdout, string.Empty));
        }
    }
}
