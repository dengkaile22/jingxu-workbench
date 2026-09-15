using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Tests.Runtime;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class RenderFailureMessageTests
{
    [Fact]
    public async Task Memory_failure_reports_actionable_cause_instead_of_prefixed_output_statistics()
    {
        var message = await FailAsync(-12, """
            [Parsed_overlay_18 @ 123] Cannot allocate memory
            [fc#0 @ 456] Task finished with error code: -12 (Cannot allocate memory)
            [out#0/mp4 @ 789] video:233031KiB audio:1757KiB subtitle:0KiB muxing overhead:0.050305%
            Conversion failed!
            """);

        Assert.Contains("内存申请失败", message, StringComparison.Ordinal);
        Assert.Contains("退出码 -12", message, StringComparison.Ordinal);
        Assert.Contains("降低输出分辨率", message, StringComparison.Ordinal);
        Assert.Contains("Parsed_overlay_18", message, StringComparison.Ordinal);
        Assert.DoesNotContain("video:233031", message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Specific_filter_error_takes_precedence_over_trailing_warning_and_statistics()
    {
        var message = await FailAsync(-22, """
            [Parsed_geq_2 @ 123] Invalid argument: missing closing parenthesis
            [swscaler @ 456] deprecated pixel format used, make sure you did set range correctly
            [out#0/mp4 @ 789] video:0KiB audio:0KiB muxing overhead:unknown
            [fc#0 @ 456] Terminating thread with return code -22
            Conversion failed!
            """);

        Assert.Contains("missing closing parenthesis", message, StringComparison.Ordinal);
        Assert.DoesNotContain("deprecated pixel format", message, StringComparison.Ordinal);
        Assert.DoesNotContain("video:0", message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Memory_exit_without_a_specific_log_line_still_explains_the_failure()
    {
        var message = await FailAsync(-12,
            "[out#0/mp4 @ 789] video:233031KiB audio:1757KiB muxing overhead:0.050305%");

        Assert.Contains("内存申请失败", message, StringComparison.Ordinal);
        Assert.DoesNotContain("muxing overhead", message, StringComparison.Ordinal);
    }

    private static async Task<string> FailAsync(int exitCode, string stderr)
    {
        using var directory = new TemporaryDirectory();
        using var layout = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var input = directory.File("input.mp4", "fixture");
        var executor = RenderExecutorFactory.Create(layout, new FakeProcessRunner(exitCode, stderr));
        var job = RenderJob.CreateQueued(TestJobs.RequestFor([input], directory.Root));
        var result = await executor.ExecuteAsync(job, null, default);
        Assert.False(result.IsSuccess);
        return result.FailureInfo!.Message;
    }
}
