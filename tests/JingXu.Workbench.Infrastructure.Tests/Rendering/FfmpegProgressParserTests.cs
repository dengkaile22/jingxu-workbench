using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class FfmpegProgressParserTests
{
    [Fact]
    public void Parses_machine_readable_progress_block()
    {
        var progress = FfmpegProgressParser.Parse("out_time_us=1500000\nspeed=0.75x\nprogress=continue\n");
        Assert.Equal(TimeSpan.FromMilliseconds(1500), progress.Position);
        Assert.Equal(0.75, progress.Speed);
    }

    [Fact]
    public void Continue_status_is_reported()
    {
        var progress = FfmpegProgressParser.Parse("out_time_us=1500000\nspeed=0.75x\nprogress=continue\n");
        Assert.Equal(FfmpegProgressStatus.Continue, progress.Status);
    }

    [Fact]
    public void End_status_is_reported()
    {
        var progress = FfmpegProgressParser.Parse("out_time_us=4000000\nspeed=2.0x\nprogress=end\n");
        Assert.Equal(FfmpegProgressStatus.End, progress.Status);
    }

    [Fact]
    public void Parses_full_block_with_optional_fields()
    {
        const string block =
            "frame=120\n" +
            "fps=30.0\n" +
            "stream_0_0_q=28.0\n" +
            "bitrate=1500.2kbits/s\n" +
            "total_size=524288\n" +
            "out_time_us=4000000\n" +
            "out_time=00:00:04.000000\n" +
            "dup_frames=0\n" +
            "drop_frames=0\n" +
            "speed=2x\n" +
            "progress=continue\n";

        var progress = FfmpegProgressParser.Parse(block);

        Assert.Equal(120, progress.Frame);
        Assert.Equal(30.0, progress.Fps);
        Assert.Equal(524288, progress.TotalSizeBytes);
        Assert.Equal(TimeSpan.FromSeconds(4), progress.Position);
        Assert.Equal(2.0, progress.Speed);
    }

    [Fact]
    public void Not_available_values_degrade_gracefully()
    {
        var progress = FfmpegProgressParser.Parse("frame=N/A\nout_time_us=N/A\nspeed=N/A\nprogress=continue\n");
        Assert.Equal(TimeSpan.Zero, progress.Position);
        Assert.Equal(0d, progress.Speed);
        Assert.Null(progress.Frame);
    }

    [Fact]
    public void Handles_carriage_returns_and_blank_lines()
    {
        var progress = FfmpegProgressParser.Parse("\r\nout_time_us=1500000\r\nspeed=0.75x\r\n\r\nprogress=continue\r\n");
        Assert.Equal(TimeSpan.FromMilliseconds(1500), progress.Position);
        Assert.Equal(0.75, progress.Speed);
    }
}
