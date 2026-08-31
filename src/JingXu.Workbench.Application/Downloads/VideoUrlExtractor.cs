using System.Text.RegularExpressions;

namespace JingXu.Workbench.Application.Downloads;

public static class VideoUrlExtractor
{
    private static readonly Regex UrlRegex = new(
        @"https?://[a-zA-Z0-9\-\._~:/\?#\[\]@!\$&'\(\)\*\+,;=%]+",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    /// <summary>
    /// 从任意多行文本中提取所有合法的 HTTP/HTTPS 链接（支持提取混在文案中的分享短链与直链）。
    /// </summary>
    public static IReadOnlyList<string> ExtractUrls(string? rawText)
    {
        if (string.IsNullOrWhiteSpace(rawText))
        {
            return [];
        }

        var lines = rawText.Split(['\n', '\r'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var line in lines)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            var matches = UrlRegex.Matches(line);
            if (matches.Count > 0)
            {
                foreach (Match match in matches)
                {
                    var candidate = CleanUrl(match.Value);
                    if (Uri.TryCreate(candidate, UriKind.Absolute, out _) && seen.Add(candidate))
                    {
                        result.Add(candidate);
                    }
                }
            }
            else if (Uri.TryCreate(line, UriKind.Absolute, out _))
            {
                var candidate = CleanUrl(line);
                if (seen.Add(candidate))
                {
                    result.Add(candidate);
                }
            }
        }

        return result;
    }

    private static string CleanUrl(string url)
    {
        var cleaned = url.Trim();
        // 去除末尾常见标点
        cleaned = cleaned.TrimEnd('.', '。', ',', '，', '!', '！', '?', '？', ';', '；', ')', '）', ']', '】', '>', '》');
        return cleaned;
    }
}
