using JingXu.Workbench.Infrastructure.Subtitles;

namespace JingXu.Workbench.Infrastructure.Tests.Subtitles;

public sealed class AssSubtitleCodecTests
{
    [Fact]
    public void Ass_round_trip_preserves_text_with_commas_and_newlines()
    {
        var cues = new[]
        {
            JingXu.Workbench.Domain.Subtitles.SubtitleCue.Create(
                TimeSpan.FromSeconds(1),
                TimeSpan.FromSeconds(3),
                "你好, world\n第二行")
        };
        var codec = new AssSubtitleCodec();
        var content = codec.Write(cues);
        var decoded = codec.Read(content, "sample.ass");
        Assert.Single(decoded);
        Assert.Equal("你好, world\n第二行", decoded[0].Text);
    }
}
