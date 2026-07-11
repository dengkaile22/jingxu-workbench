using JingXu.Workbench.Infrastructure.Subtitles;

namespace JingXu.Workbench.Infrastructure.Tests.Subtitles;

public sealed class SrtSubtitleCodecTests
{
    [Fact]
    public void Srt_round_trip_preserves_multiline_chinese_and_milliseconds()
    {
        var source = "1\r\n00:00:01,250 --> 00:00:03,500\r\n第一行\r\nsecond line\r\n";
        var codec = new SrtSubtitleCodec();
        var decoded = codec.Read(source, "sample.srt");
        static string Normalize(string value) =>
            value.Replace("\r\n", "\n").Replace('\r', '\n').TrimEnd('\n');
        Assert.Equal(Normalize(source), Normalize(codec.Write(decoded)));
    }
}
