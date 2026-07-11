using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Rendering;
using JingXu.Workbench.Infrastructure.Runtime;
using JingXu.Workbench.Infrastructure.Tests.Runtime;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class FfmpegRenderExecutorTests
{
    [Fact]
    public async Task Failed_render_never_replaces_existing_output()
    {
        using var dir = new TemporaryDirectory();
        var output = dir.File("成片.mp4", contents: "existing");
        var executor = RenderExecutorFactory.WithProcessExitCode(1);
        var result = await executor.ExecuteAsync(TestJobs.To(output), progress: null, default);
        Assert.False(result.IsSuccess);
        Assert.Equal("existing", File.ReadAllText(output));
        Assert.Empty(dir.Files("*.partial.*"));
    }

    [Fact]
    public async Task Missing_request_returns_chinese_failure()
    {
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var executor = RenderExecutorFactory.Create(layout, new FakeProcessRunner(exitCode: 0));
        var result = await executor.ExecuteAsync(RenderJob.CreateQueued(), progress: null, default);
        Assert.False(result.IsSuccess);
        Assert.Contains("请求快照", result.FailureInfo!.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Missing_ffmpeg_returns_actionable_message()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        using var layout = RuntimeLayout.Create();
        var executor = RenderExecutorFactory.Create(layout, new FakeProcessRunner(exitCode: 0));
        var request = TestJobs.RequestFor([clip], dir.Root);
        var job = RenderJob.CreateQueued(request with { OutputPath = Path.Combine(dir.Root, "out.mp4") });
        var result = await executor.ExecuteAsync(job, progress: null, default);
        Assert.False(result.IsSuccess);
        Assert.Contains("未找到 FFmpeg", result.FailureInfo!.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Cancellation_returns_cancelled_without_finalizing_output()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");
        dir.File("成片.mp4", contents: "existing");

        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        var executor = RenderExecutorFactory.Create(layout, new FakeProcessRunner(exitCode: 0));
        var job = RenderJob.CreateQueued(TestJobs.RequestFor([clip], dir.Root) with { OutputPath = output });
        var result = await executor.ExecuteAsync(job, progress: null, cts.Token);
        Assert.True(result.IsCancelled);
        Assert.Equal("existing", File.ReadAllText(output));
    }

    [Fact]
    public async Task Zero_byte_success_output_is_rejected()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");

        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new ScriptingProcessRunner
        {
            OnRun = (_, stagingRoot, _) =>
            {
                Directory.CreateDirectory(stagingRoot);
                File.WriteAllBytes(Path.Combine(stagingRoot, "output.mp4"), []);
                return new ProcessResult(0, string.Empty, string.Empty);
            }
        };

        var executor = RenderExecutorFactory.Create(
            layout,
            runner,
            probe: new FixedProbe(TimeSpan.FromSeconds(2)));

        var job = RenderJob.CreateQueued(TestJobs.RequestFor([clip], dir.Root) with { OutputPath = output });
        var result = await executor.ExecuteAsync(job, progress: null, default);
        Assert.False(result.IsSuccess);
        Assert.Contains("零字节", result.FailureInfo!.Message, StringComparison.Ordinal);
        Assert.False(File.Exists(output));
    }

    [Fact]
    public async Task Successful_render_moves_output_and_leaves_log_only_in_staging()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");

        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new ScriptingProcessRunner
        {
            OnRun = (_, stagingRoot, _) =>
            {
                Directory.CreateDirectory(stagingRoot);
                File.WriteAllText(Path.Combine(stagingRoot, "output.mp4"), "rendered-bytes");
                return new ProcessResult(0, "progress=continue\n", string.Empty);
            }
        };

        var executor = RenderExecutorFactory.Create(
            layout,
            runner,
            probe: new FixedProbe(TimeSpan.FromSeconds(2)));

        var job = RenderJob.CreateQueued(TestJobs.RequestFor([clip], dir.Root) with { OutputPath = output });
        var result = await executor.ExecuteAsync(job, progress: null, default);
        Assert.True(result.IsSuccess);
        Assert.Equal("rendered-bytes", File.ReadAllText(output));
        Assert.Single(runner.Requests);
        Assert.DoesNotContain(runner.Requests[0].Arguments, x => x.Contains("cmd.exe", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public async Task Process_failure_maps_chinese_message_with_exit_code()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");

        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var executor = RenderExecutorFactory.WithProcessExitCode(1, stderr: "Invalid data found when processing input");

        var job = RenderJob.CreateQueued(TestJobs.RequestFor([clip], dir.Root) with { OutputPath = output });
        var result = await executor.ExecuteAsync(job, progress: null, default);
        Assert.False(result.IsSuccess);
        Assert.Contains("退出码 1", result.FailureInfo!.Message, StringComparison.Ordinal);
        Assert.Contains("Invalid data found", result.FailureInfo.Message, StringComparison.Ordinal);
    }
}

internal static class TestJobs
{
    public static RenderJob To(string outputPath) =>
        RenderJob.CreateQueued(RequestFor([@"C:\media\1.mp4"], Path.GetDirectoryName(outputPath)!)
            with
        { OutputPath = outputPath });

    public static RenderRequest RequestFor(IReadOnlyList<string> clipPaths, string outputDirectory)
    {
        var clips = new List<PlannedClip>();
        var offset = TimeSpan.Zero;
        var index = 1;
        foreach (var path in clipPaths)
        {
            var asset = new MediaAsset(
                Guid.NewGuid(),
                path,
                index,
                new MediaInfo(TimeSpan.FromSeconds(2), 1080, 1920, 30m, "h264", "aac", true, 0));
            clips.Add(new PlannedClip(asset, offset, asset.Info.Duration));
            offset += asset.Info.Duration;
            index++;
        }

        var plan = new CompositionPlan(clips, offset, Seed: 0, TimeSpan.Zero);
        return new RenderRequest(
            plan,
            Path.Combine(outputDirectory, "成片.mp4"),
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            []);
    }
}

internal static class RenderExecutorFactory
{
    public static FfmpegRenderExecutor WithProcessExitCode(int exitCode, string stderr = "") =>
        Create(
            RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe"),
            new FakeProcessRunner(exitCode, stderr),
            probe: new FixedProbe(TimeSpan.FromSeconds(2)));

    public static FfmpegRenderExecutor Create(
        RuntimeLayout layout,
        IExternalProcessRunner runner,
        IMediaProbe? probe = null) =>
        new(
            runner,
            probe ?? new FixedProbe(TimeSpan.FromSeconds(2)),
            new RuntimeResolver(layout.AppRoot, layout.PathLookup),
            availableDiskBytes: _ => long.MaxValue);

    public static FfmpegRenderExecutor Create(
        RuntimeLayout layout,
        ScriptingProcessRunner runner,
        IMediaProbe probe) =>
        new(
            runner,
            probe,
            new RuntimeResolver(layout.AppRoot, layout.PathLookup),
            availableDiskBytes: _ => long.MaxValue);
}

internal sealed class TemporaryDirectory : IDisposable
{
    public TemporaryDirectory()
    {
        Root = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "jingxu-render-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Root);
    }

    public string Root { get; }

    public string File(string name, string contents)
    {
        var full = System.IO.Path.Combine(Root, name);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(full)!);
        System.IO.File.WriteAllText(full, contents);
        return full;
    }

    public IReadOnlyList<string> Files(string pattern) =>
        Directory.GetFiles(Root, pattern, SearchOption.AllDirectories).ToList();

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(Root))
            {
                Directory.Delete(Root, recursive: true);
            }
        }
        catch (IOException)
        {
        }
    }
}

internal sealed class FakeProcessRunner(int exitCode, string stderr = "") : IExternalProcessRunner
{
    public List<IProcessRequest> Requests { get; } = [];

    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        Requests.Add(request);
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult<IProcessResult>(new ProcessResult(exitCode, string.Empty, stderr));
    }
}

internal sealed class ScriptingProcessRunner : IExternalProcessRunner
{
    public required Func<IProcessRequest, string, CancellationToken, IProcessResult> OnRun { get; init; }

    public List<IProcessRequest> Requests { get; } = [];

    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        Requests.Add(request);
        var stagingRoot = request.WorkingDirectory ?? throw new InvalidOperationException("缺少 staging 工作目录。");
        return Task.FromResult(OnRun(request, stagingRoot, cancellationToken));
    }
}

internal sealed class FixedProbe(TimeSpan duration) : IMediaProbe
{
    public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
        Task.FromResult(new MediaInfo(duration, 1080, 1920, 30m, "h264", "aac", true, 0));
}
