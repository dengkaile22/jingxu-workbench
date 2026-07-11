using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Subtitles;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class SubtitleRemovalFilterCompilerTests
{
    private static SubtitleRemovalPlan Manual(SubtitleRemovalMode mode) =>
        mode == SubtitleRemovalMode.CropAndReframe
            ? new(mode, new NormalizedRect(0, 0.75, 1, 0.25), 1920, 1080)
            : new(mode, new NormalizedRect(0.1, 0.7, 0.8, 0.2), 1920, 1080);

    [Theory]
    [InlineData(SubtitleRemovalMode.Blur, "gblur")]
    [InlineData(SubtitleRemovalMode.Delogo, "delogo")]
    [InlineData(SubtitleRemovalMode.CropAndReframe, "crop=")]
    public void Manual_removal_compiles_selected_mode(SubtitleRemovalMode mode, string token) =>
        Assert.Contains(token, SubtitleRemovalFilterCompiler.Compile(Manual(mode)));
}

public sealed class SubtitleBurnInFilterCompilerTests
{
    [Fact]
    public void Old_subtitle_removal_precedes_new_ass_burn_in()
    {
        var plan = new SubtitleBurnInPlan(
            @"C:\素材\video.mp4",
            @"C:\out\成片.mp4",
            @"C:\temp\subs.ass",
            SubtitleFileFormat.Ass,
            1920,
            1080,
            new SubtitleRemovalPlan(
                SubtitleRemovalMode.Delogo,
                new NormalizedRect(0, 0.75, 1, 0.25),
                1920,
                1080));

        var graph = SubtitleBurnInFilterCompiler.Compile(plan);
        Assert.True(graph.IndexOf("delogo", StringComparison.Ordinal) < graph.IndexOf("ass=", StringComparison.Ordinal));
    }

    [Fact]
    public void Windows_path_is_escaped_for_subtitles_filter()
    {
        var plan = new SubtitleBurnInPlan(
            @"C:\素材\video.mp4",
            @"C:\out\成片.mp4",
            @"C:\字幕\test.ass",
            SubtitleFileFormat.Ass,
            1920,
            1080);
        var graph = SubtitleBurnInFilterCompiler.Compile(plan);
        Assert.Contains("C\\:/", graph, StringComparison.Ordinal);
    }
}
