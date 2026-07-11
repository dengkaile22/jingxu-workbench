using JingXu.Workbench.Infrastructure.Subtitles;

namespace JingXu.Workbench.Infrastructure.Tests.Subtitles;

public sealed class WhisperSrtParserTests
{
    [Fact]
    public void Parses_mixed_language_whisper_srt_without_logging_text()
    {
        const string content = """
            1
            00:00:00,000 --> 00:00:02,000
            今天 launch 新产品

            2
            00:00:02,000 --> 00:00:04,000
            Hello world

            """;
        var cues = WhisperSrtParser.Parse(content);
        Assert.Equal(2, cues.Count);
        Assert.Equal("今天 launch 新产品", cues[0].Text);
    }
}
