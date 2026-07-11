using JingXu.Workbench.Infrastructure.Subtitles;

namespace JingXu.Workbench.Infrastructure.Tests.Subtitles;

public sealed class TesseractTsvParserTests
{
    [Fact]
    public void Tsv_words_are_grouped_by_frame_block_paragraph_and_line()
    {
        var tsv = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Subtitles", "Fixtures", "chi-eng.tsv"));
        var lines = TesseractTsvParser.Parse(tsv, 1920, 1080);
        Assert.Equal("紫色梅果味", lines[0].Text);
        Assert.True(lines[0].Bounds.Height > 0);
    }
}
