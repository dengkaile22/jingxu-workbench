using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Media;

namespace JingXu.Workbench.Infrastructure.Tests.Media;

public sealed class FfprobeJsonParserTests
{
    private static string Fixture(string name) =>
        Path.Combine(AppContext.BaseDirectory, "Media", "Fixtures", name);

    [Fact]
    public void Parses_duration_fractional_frame_rate_rotation_and_audio()
    {
        var json = File.ReadAllText(Fixture("ffprobe-rotated-with-audio.json"));
        var info = FfprobeJsonParser.Parse(json);
        Assert.Equal(TimeSpan.FromMilliseconds(23040), info.Duration);
        Assert.Equal(1080, info.Width);
        Assert.Equal(1920, info.Height);
        Assert.Equal(29.97m, info.FrameRate);
        Assert.Equal(90, info.RotationDegrees);
        Assert.True(info.HasAudio);
        Assert.Equal("h264", info.VideoCodec);
        Assert.Equal("aac", info.AudioCodec);
    }

    [Fact]
    public void Prefers_format_duration_when_stream_duration_is_absent()
    {
        const string json = """
            {
              "streams": [
                {
                  "codec_type": "video",
                  "codec_name": "h264",
                  "width": 1280,
                  "height": 720,
                  "avg_frame_rate": "30/1"
                }
              ],
              "format": { "duration": "12.500000" }
            }
            """;

        var info = FfprobeJsonParser.Parse(json);

        Assert.Equal(TimeSpan.FromMilliseconds(12500), info.Duration);
    }

    [Fact]
    public void Normalizes_rotation_to_quarter_turns()
    {
        const string json = """
            {
              "streams": [
                {
                  "codec_type": "video",
                  "codec_name": "h264",
                  "width": 720,
                  "height": 1280,
                  "avg_frame_rate": "25/1",
                  "tags": { "rotate": "450" }
                }
              ],
              "format": { "duration": "1.000000" }
            }
            """;

        var info = FfprobeJsonParser.Parse(json);

        Assert.Equal(90, info.RotationDegrees);
    }

    [Fact]
    public void Parses_rotation_from_side_data_when_tags_absent()
    {
        const string json = """
            {
              "streams": [
                {
                  "codec_type": "video",
                  "codec_name": "h264",
                  "width": 1080,
                  "height": 1920,
                  "avg_frame_rate": "24/1",
                  "side_data_list": [
                    { "rotation": -90 }
                  ]
                }
              ],
              "format": { "duration": "2.000000" }
            }
            """;

        var info = FfprobeJsonParser.Parse(json);

        Assert.Equal(270, info.RotationDegrees);
    }

    [Fact]
    public void Reports_no_audio_when_audio_stream_missing()
    {
        const string json = """
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
              "format": { "duration": "3.000000" }
            }
            """;

        var info = FfprobeJsonParser.Parse(json);

        Assert.False(info.HasAudio);
        Assert.Null(info.AudioCodec);
    }

    [Fact]
    public void Rejects_json_without_video_stream()
    {
        const string json = """
            {
              "streams": [
                { "codec_type": "audio", "codec_name": "aac" }
              ],
              "format": { "duration": "1.000000" }
            }
            """;

        var ex = Assert.Throws<MediaProbeException>(() => FfprobeJsonParser.Parse(json));
        Assert.Contains("视频流", ex.Message);
    }
}
