using System.Globalization;
using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Infrastructure.Subtitles;

/// <summary>Tesseract TSV 行。</summary>
public sealed record TesseractTextLine(
    int PageNumber,
    string Text,
    NormalizedRect Bounds,
    double Confidence);

/// <summary>解析 Tesseract level-5 word TSV 并按行分组。</summary>
public static class TesseractTsvParser
{
    public static IReadOnlyList<TesseractTextLine> Parse(string tsv, int frameWidth, int frameHeight)
    {
        ArgumentNullException.ThrowIfNull(tsv);
        var lines = tsv.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (lines.Length <= 1)
        {
            return [];
        }

        var header = lines[0].Split('\t');
        var index = header
            .Select((name, i) => (name, i))
            .ToDictionary(x => x.name, x => x.i, StringComparer.OrdinalIgnoreCase);

        var words = new List<(int Page, int Block, int Par, int Line, string Text, double Conf, int Left, int Top, int Width, int Height)>();
        foreach (var row in lines.Skip(1))
        {
            var cols = row.Split('\t');
            if (cols.Length < header.Length)
            {
                continue;
            }

            if (!int.TryParse(Get(cols, index, "level"), NumberStyles.Integer, CultureInfo.InvariantCulture, out var level) || level != 5)
            {
                continue;
            }

            var text = Get(cols, index, "text");
            if (string.IsNullOrWhiteSpace(text))
            {
                continue;
            }

            words.Add((
                int.Parse(Get(cols, index, "page_num"), CultureInfo.InvariantCulture),
                int.Parse(Get(cols, index, "block_num"), CultureInfo.InvariantCulture),
                int.Parse(Get(cols, index, "par_num"), CultureInfo.InvariantCulture),
                int.Parse(Get(cols, index, "line_num"), CultureInfo.InvariantCulture),
                text,
                double.Parse(Get(cols, index, "conf"), CultureInfo.InvariantCulture),
                int.Parse(Get(cols, index, "left"), CultureInfo.InvariantCulture),
                int.Parse(Get(cols, index, "top"), CultureInfo.InvariantCulture),
                int.Parse(Get(cols, index, "width"), CultureInfo.InvariantCulture),
                int.Parse(Get(cols, index, "height"), CultureInfo.InvariantCulture)));
        }

        return words
            .GroupBy(x => (x.Page, x.Block, x.Par, x.Line))
            .Select(group =>
            {
                var left = group.Min(x => x.Left);
                var top = group.Min(x => x.Top);
                var right = group.Max(x => x.Left + x.Width);
                var bottom = group.Max(x => x.Top + x.Height);
                var width = Math.Max(1, right - left);
                var height = Math.Max(1, bottom - top);
                var bounds = new NormalizedRect(
                    left / (double)frameWidth,
                    top / (double)frameHeight,
                    width / (double)frameWidth,
                    height / (double)frameHeight);
                var confidence = group.Average(x => x.Conf) / 100.0;
                return new TesseractTextLine(
                    group.Key.Page,
                    string.Concat(group.OrderBy(x => x.Left).Select(x => x.Text)),
                    bounds,
                    confidence);
            })
            .ToArray();
    }

    private static string Get(string[] cols, Dictionary<string, int> index, string name) =>
        cols[index[name]];
}
