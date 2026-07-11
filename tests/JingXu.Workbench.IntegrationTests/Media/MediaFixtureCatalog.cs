namespace JingXu.Workbench.IntegrationTests.Media;

/// <summary>六段 lavfi 夹具的序号、颜色与音频频率定义。</summary>
internal static class MediaFixtureCatalog
{
    public const string CustomSequenceExpression = "264513";

    public static readonly int[] CustomSequenceOrder = [2, 6, 4, 5, 1, 3];

    public static readonly IReadOnlyDictionary<int, MediaFixtureSegment> Segments =
        new Dictionary<int, MediaFixtureSegment>
        {
            [1] = new("red", 200, (255, 0, 0)),
            [2] = new("green", 300, (0, 255, 0)),
            [3] = new("blue", 400, (0, 0, 255)),
            [4] = new("yellow", 500, (255, 255, 0)),
            [5] = new("magenta", 600, (255, 0, 255)),
            [6] = new("cyan", 700, (0, 255, 255))
        };

    public static string ClipFileName(int sequenceIndex) => $"{sequenceIndex}.mp4";

    public static MediaFixtureSegment SegmentFor(int sequenceIndex) =>
        Segments.TryGetValue(sequenceIndex, out var segment)
            ? segment
            : throw new ArgumentOutOfRangeException(nameof(sequenceIndex), $"未知序号 {sequenceIndex}。");
}

internal readonly record struct MediaFixtureSegment(
    string LavfiColor,
    int FrequencyHz,
    (int R, int G, int B) CenterRgb);

internal readonly record struct Rgb24(byte R, byte G, byte B)
{
    public bool IsCloseTo((int R, int G, int B) expected, int tolerance = 80) =>
        Math.Abs(R - expected.R) <= tolerance
        && Math.Abs(G - expected.G) <= tolerance
        && Math.Abs(B - expected.B) <= tolerance;

    public bool IsCloseTo(Rgb24 other, int tolerance = 80) =>
        IsCloseTo((other.R, other.G, other.B), tolerance);

    public static int ClosestSegmentIndex(Rgb24 pixel)
    {
        var bestIndex = 1;
        var bestDistance = double.MaxValue;

        foreach (var (index, segment) in MediaFixtureCatalog.Segments)
        {
            var distance = ColorDistance(pixel, segment.CenterRgb);
            if (distance < bestDistance)
            {
                bestDistance = distance;
                bestIndex = index;
            }
        }

        return bestIndex;
    }

    private static double ColorDistance(Rgb24 pixel, (int R, int G, int B) expected) =>
        Math.Sqrt(
            Math.Pow(pixel.R - expected.R, 2)
            + Math.Pow(pixel.G - expected.G, 2)
            + Math.Pow(pixel.B - expected.B, 2));
}
