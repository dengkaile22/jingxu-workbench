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
    public async Task Finished_render_preserves_a_subtitle_still_leased_by_another_job()
    {
        using var dir = new TemporaryDirectory();
        var input = dir.File("clip.mp4", "clip");
        var output = Path.Combine(dir.Root, "subtitle.mp4");
        var subtitle = Path.Combine(JingXu.Workbench.Application.Projects.WorkbenchDataPaths.GetTempDirectory(),
            "jingxu-subtitle-burn", Guid.NewGuid().ToString("N") + ".ass");
        Directory.CreateDirectory(Path.GetDirectoryName(subtitle)!);
        File.WriteAllText(subtitle, "[Script Info]\nScriptType: v4.00+");
        using var resource = JingXu.Workbench.Application.Projects.TempResourceLease.Acquire(subtitle);
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new ScriptingProcessRunner
        {
            OnRun = (_, staging, _) =>
            {
                File.WriteAllText(Path.Combine(staging, "output.mp4"), "rendered");
                return new ProcessResult(0, string.Empty, string.Empty);
            }
        };
        var request = TestJobs.RequestFor([input], dir.Root) with
        {
            OutputPath = output,
            SubtitleBurn = new JingXu.Workbench.Domain.Subtitles.SubtitleBurnInPlan(input, output, subtitle,
                JingXu.Workbench.Domain.Subtitles.SubtitleFileFormat.Ass, 1080, 1920)
        };
        try
        {
            var result = await RenderExecutorFactory.Create(layout, runner, new FixedProbe(TimeSpan.FromSeconds(2)))
                .ExecuteAsync(RenderJob.CreateQueued(request), null, default);
            Assert.True(result.IsSuccess, result.FailureInfo?.Message);
            Assert.True(File.Exists(subtitle), "另一任务仍持有字幕时，当前任务结束不能删除共享字幕。");
        }
        finally { if (File.Exists(subtitle)) { File.Delete(subtitle); } }
    }

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
        Assert.False(Directory.Exists(TestJobs.StagingPath(output, job.Id)));
    }

    [Fact]
    public async Task Successful_render_moves_output_and_removes_staging()
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
        Assert.False(Directory.Exists(TestJobs.StagingPath(output, job.Id)));
        var renderRequest = Assert.Single(
            runner.Requests,
            request => request.WorkingDirectory is not null);
        Assert.DoesNotContain(
            renderRequest.Arguments,
            x => x.Contains("cmd.exe", StringComparison.OrdinalIgnoreCase));
        Assert.Equal(ExternalProcessPriority.BelowNormal, renderRequest.Priority);
    }

    [Fact]
    public async Task Successful_render_materializes_short_input_aliases_in_staging()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");

        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        string? seenAliasPath = null;
        var runner = new ScriptingProcessRunner
        {
            OnRun = (request, stagingRoot, _) =>
            {
                Assert.Contains("i0.mp4", request.Arguments);
                Assert.DoesNotContain(request.Arguments, a => a.Equals(clip, StringComparison.OrdinalIgnoreCase));
                seenAliasPath = Path.Combine(stagingRoot, "i0.mp4");
                Assert.True(File.Exists(seenAliasPath), "staging 应物化短路径别名");
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
        Assert.NotNull(seenAliasPath);
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
        Assert.False(Directory.Exists(TestJobs.StagingPath(output, job.Id)));
        var diagnosticLog = Path.Combine(dir.Root, ".jingxu-logs", job.Id.ToString("N"), "render.log");
        Assert.True(File.Exists(diagnosticLog), "失败后应保留完整诊断日志，同时回收媒体暂存。");
        Assert.Contains("Invalid data found", File.ReadAllText(diagnosticLog), StringComparison.Ordinal);
        Assert.Contains(diagnosticLog, result.FailureInfo.Message, StringComparison.Ordinal);
        Assert.False(File.Exists(output));
    }

    [Fact]
    public async Task Hardware_initialization_failure_retries_once_with_cpu()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new SequencedRenderRunner(
            new ProcessResult(
                1,
                string.Empty,
                "[h264_qsv] Error initializing an internal MFX session"),
            new ProcessResult(0, "progress=end\n", string.Empty));
        var selector = FixedEncoderSelector.Qsv();
        var executor = RenderExecutorFactory.Create(
            layout,
            runner,
            selector,
            new FixedProbe(TimeSpan.FromSeconds(2)));
        var request = TestJobs.RequestFor([clip], dir.Root) with
        {
            OutputPath = output,
            ProcessingMode = VideoProcessingMode.Gpu
        };

        var result = await executor.ExecuteAsync(
            RenderJob.CreateQueued(request),
            progress: null,
            default);

        Assert.True(result.IsSuccess);
        Assert.Equal(2, runner.Requests.Count);
        Assert.Contains("h264_qsv", runner.Requests[0].Arguments);
        Assert.Contains("libx264", runner.Requests[1].Arguments);
        Assert.Contains("已自动改用 CPU", result.Notice, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Nvenc_opening_encoder_failure_retries_once_with_cpu()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new SequencedRenderRunner(
            new ProcessResult(
                1,
                string.Empty,
                "[h264_nvenc @ 000] Driver does not support the required nvenc API version.\nError while opening encoder for output stream #0:0"),
            new ProcessResult(0, "progress=end\n", string.Empty));
        var selector = new RecordingEncoderSelector(new VideoEncoderSelection(
            VideoEncoderKind.H264Nvenc,
            "NVIDIA GPU（NVENC）",
            "使用 NVIDIA GPU（NVENC）完成。"));
        var executor = RenderExecutorFactory.Create(
            layout,
            runner,
            selector,
            new FixedProbe(TimeSpan.FromSeconds(2)));
        var request = TestJobs.RequestFor([clip], dir.Root) with
        {
            OutputPath = output,
            ProcessingMode = VideoProcessingMode.Gpu
        };

        var result = await executor.ExecuteAsync(
            RenderJob.CreateQueued(request),
            progress: null,
            default);

        Assert.True(result.IsSuccess);
        Assert.Equal(2, runner.Requests.Count);
        Assert.Contains("h264_nvenc", runner.Requests[0].Arguments);
        Assert.Contains("libx264", runner.Requests[1].Arguments);
        Assert.Equal([VideoEncoderKind.H264Nvenc], selector.RememberedFailures);
    }

    [Fact]
    public void Hardware_encoder_failure_detects_nvenc_session_and_ignores_filter_errors()
    {
        Assert.True(FfmpegRenderExecutor.IsHardwareEncoderFailure(
            VideoEncoderKind.H264Nvenc,
            "[h264_nvenc @ 0] OpenEncodeSessionEx failed: invalid param"));
        Assert.True(FfmpegRenderExecutor.IsHardwareEncoderFailure(
            VideoEncoderKind.H264Nvenc,
            "Cannot load nvcuda.dll"));
        Assert.False(FfmpegRenderExecutor.IsHardwareEncoderFailure(
            VideoEncoderKind.H264Qsv,
            "Error reinitializing filters!"));
        Assert.False(FfmpegRenderExecutor.IsHardwareEncoderFailure(
            VideoEncoderKind.Libx264,
            "[h264_nvenc] no capable devices found"));
    }

    [Fact]
    public async Task Filter_failure_does_not_retry_cpu()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new SequencedRenderRunner(
            new ProcessResult(1, string.Empty, "Error reinitializing filters!"));
        var executor = RenderExecutorFactory.Create(
            layout,
            runner,
            FixedEncoderSelector.Qsv(),
            new FixedProbe(TimeSpan.FromSeconds(2)));
        var request = TestJobs.RequestFor([clip], dir.Root) with
        {
            OutputPath = output,
            ProcessingMode = VideoProcessingMode.Gpu
        };

        var result = await executor.ExecuteAsync(
            RenderJob.CreateQueued(request),
            progress: null,
            default);

        Assert.False(result.IsSuccess);
        Assert.Single(runner.Requests);
    }

    [Fact]
    public async Task Cancellation_does_not_retry_cpu()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new CancellingRenderRunner();
        var executor = RenderExecutorFactory.Create(
            layout,
            runner,
            FixedEncoderSelector.Qsv(),
            new FixedProbe(TimeSpan.FromSeconds(2)));
        var request = TestJobs.RequestFor([clip], dir.Root) with
        {
            OutputPath = output,
            ProcessingMode = VideoProcessingMode.Gpu
        };

        var job = RenderJob.CreateQueued(request);
        var result = await executor.ExecuteAsync(
            job,
            progress: null,
            default);

        Assert.True(result.IsCancelled);
        Assert.Single(runner.Requests);
        Assert.False(Directory.Exists(TestJobs.StagingPath(output, job.Id)));
    }

    [Fact]
    public async Task Stream_copy_does_not_probe_or_use_hardware_encoder()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var runner = new SequencedRenderRunner(
            new ProcessResult(0, "progress=end\n", string.Empty));
        var selector = FixedEncoderSelector.Qsv();
        var executor = RenderExecutorFactory.Create(
            layout,
            runner,
            selector,
            new FixedProbe(TimeSpan.FromSeconds(2)));
        var request = TestJobs.RequestFor([clip], dir.Root) with
        {
            OutputPath = output,
            Profile = RenderProfile.Lossless,
            ProcessingMode = VideoProcessingMode.Gpu
        };

        var result = await executor.ExecuteAsync(
            RenderJob.CreateQueued(request),
            progress: null,
            default);

        Assert.True(result.IsSuccess);
        Assert.Equal(0, selector.CallCount);
        Assert.Contains("copy", Assert.Single(runner.Requests).Arguments);
    }

    [Fact]
    public async Task Failed_or_cancelled_render_does_not_leave_sibling_job_staging()
    {
        using var dir = new TemporaryDirectory();
        var clip = dir.File("clip.mp4", contents: "clip");
        var output = Path.Combine(dir.Root, "成片.mp4");
        var otherId = Guid.NewGuid();
        var otherStaging = TestJobs.StagingPath(output, otherId);
        Directory.CreateDirectory(otherStaging);
        File.WriteAllText(Path.Combine(otherStaging, "output.mp4"), "other-job");

        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var executor = RenderExecutorFactory.WithProcessExitCode(1, stderr: "Conversion failed!");
        var job = RenderJob.CreateQueued(TestJobs.RequestFor([clip], dir.Root) with { OutputPath = output });
        var result = await executor.ExecuteAsync(job, progress: null, default);

        Assert.False(result.IsSuccess);
        Assert.False(Directory.Exists(TestJobs.StagingPath(output, job.Id)));
        Assert.True(File.Exists(Path.Combine(otherStaging, "output.mp4")));
        Assert.Equal("other-job", File.ReadAllText(Path.Combine(otherStaging, "output.mp4")));
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

    public static string StagingPath(string outputPath, Guid jobId) =>
        Path.Combine(Path.GetDirectoryName(outputPath)!, ".jingxu-tmp", jobId.ToString("N"));
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

    public static FfmpegRenderExecutor Create(
        RuntimeLayout layout,
        IExternalProcessRunner runner,
        IVideoEncoderSelector selector,
        IMediaProbe probe) =>
        new(
            runner,
            probe,
            new RuntimeResolver(layout.AppRoot, layout.PathLookup),
            encoderSelector: selector,
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

internal sealed class FixedEncoderSelector(VideoEncoderSelection selection) : IVideoEncoderSelector
{
    public int CallCount { get; private set; }

    public static FixedEncoderSelector Qsv() =>
        new(new VideoEncoderSelection(
            VideoEncoderKind.H264Qsv,
            "Intel GPU（QSV）",
            "使用 Intel GPU（QSV）完成。"));

    public Task<VideoEncoderSelection> SelectAsync(
        string ffmpegExecutable,
        VideoProcessingMode mode,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        CallCount++;
        return Task.FromResult(selection);
    }
}

/// <summary>记录正式编码失败后被跳过的 GPU 编码器。</summary>
internal sealed class RecordingEncoderSelector(VideoEncoderSelection selection) : IVideoEncoderSelector
{
    public List<VideoEncoderKind> RememberedFailures { get; } = [];

    public Task<VideoEncoderSelection> SelectAsync(
        string ffmpegExecutable,
        VideoProcessingMode mode,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(selection);
    }

    public void RememberHardwareFailure(string ffmpegExecutable, VideoEncoderKind kind) =>
        RememberedFailures.Add(kind);
}

internal sealed class SequencedRenderRunner(params IProcessResult[] results) : IExternalProcessRunner
{
    private readonly Queue<IProcessResult> _results = new(results);

    public List<IProcessRequest> Requests { get; } = [];

    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        Requests.Add(request);
        var result = _results.Dequeue();
        if (result.ExitCode == 0)
        {
            var stagingRoot = request.WorkingDirectory
                ?? throw new InvalidOperationException("缺少 staging 工作目录。");
            File.WriteAllText(Path.Combine(stagingRoot, "output.mp4"), "rendered-bytes");
        }

        return Task.FromResult(result);
    }
}

internal sealed class CancellingRenderRunner : IExternalProcessRunner
{
    public List<IProcessRequest> Requests { get; } = [];

    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        Requests.Add(request);
        throw new OperationCanceledException(cancellationToken);
    }
}
