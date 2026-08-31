using System.Net;
using System.Net.Http;
using System.Text.RegularExpressions;
using JingXu.Workbench.Application.Abstractions;

namespace JingXu.Workbench.Infrastructure.Downloads;

public sealed class SmartVideoUrlResolver : IVideoUrlResolver
{
    private static readonly HttpClient Client = CreateClient();

    private const string MobileUserAgent =
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1";

    private const string DesktopUserAgent =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

    private static readonly Regex DouyinVideoIdRegex = new(
        @"/(?:video|share/video|note)/(\d+)",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex VideoTagRegex = new(
        @"<video[^>]+src=[""']([^""']+)[""']",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex OgVideoRegex = new(
        @"<meta[^>]+property=[""']og:video(?:[:\w]+)?[""'][^>]+content=[""']([^""']+)[""']",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex KuaishouPlayUrlRegex = new(
        @"""(?:srcNoMark|playUrl|videoUrl)""\s*:\s*""([^""]+)""",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static HttpClient CreateClient()
    {
        var handler = new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate | DecompressionMethods.Brotli,
            AllowAutoRedirect = false
        };

        return new HttpClient(handler)
        {
            Timeout = TimeSpan.FromSeconds(15)
        };
    }

    public async Task<ResolvedVideoInfo> ResolveAsync(string inputUrl, CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(inputUrl);
        cancellationToken.ThrowIfCancellationRequested();

        if (IsDirectMediaUrl(inputUrl))
        {
            return new ResolvedVideoInfo(inputUrl, null, IsDirectMedia: true);
        }

        try
        {
            if (IsDouyinUrl(inputUrl))
            {
                var douyinResult = await ResolveDouyinUrlAsync(inputUrl, cancellationToken).ConfigureAwait(false);
                if (douyinResult is not null)
                {
                    return douyinResult;
                }
            }

            if (IsKuaishouUrl(inputUrl))
            {
                var kuaishouResult = await ResolveKuaishouUrlAsync(inputUrl, cancellationToken).ConfigureAwait(false);
                if (kuaishouResult is not null)
                {
                    return kuaishouResult;
                }
            }

            // 通用网页重定向与 HTML 视频标签解析
            var genericResult = await ResolveGenericPageAsync(inputUrl, cancellationToken).ConfigureAwait(false);
            if (genericResult is not null)
            {
                return genericResult;
            }
        }
        catch (Exception)
        {
            // 解析失败时降级直接使用原始 URL
        }

        return new ResolvedVideoInfo(inputUrl, null, IsDirectMedia: false);
    }

    private static async Task<ResolvedVideoInfo?> ResolveDouyinUrlAsync(string url, CancellationToken ct)
    {
        // 1. 跟随短链重定向，获取完整视频页面 URL
        var currentUrl = url;
        for (var i = 0; i < 5; i++)
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, currentUrl);
            req.Headers.UserAgent.ParseAdd(MobileUserAgent);
            req.Headers.Referrer = new Uri("https://www.douyin.com/");

            using var resp = await Client.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            if (resp.StatusCode is HttpStatusCode.Moved or HttpStatusCode.Redirect or HttpStatusCode.SeeOther or HttpStatusCode.TemporaryRedirect or (HttpStatusCode)308)
            {
                var location = resp.Headers.Location;
                if (location is not null)
                {
                    currentUrl = location.IsAbsoluteUri ? location.AbsoluteUri : new Uri(new Uri(currentUrl), location).AbsoluteUri;
                    continue;
                }
            }

            break;
        }

        // 2. 从重定向后的 URL 中提取视频 ID
        var match = DouyinVideoIdRegex.Match(currentUrl);
        if (!match.Success)
        {
            return null;
        }

        var videoId = match.Groups[1].Value;

        // 3. 请求官方无水印播放接口获取重定向真实 CDN 流
        var playApiUrl = $"https://www.iesdouyin.com/aweme/v1/play/?video_id={videoId}&ratio=1080p&line=0";
        using var playReq = new HttpRequestMessage(HttpMethod.Get, playApiUrl);
        playReq.Headers.UserAgent.ParseAdd(MobileUserAgent);
        playReq.Headers.Referrer = new Uri("https://www.douyin.com/");

        using var playResp = await Client.SendAsync(playReq, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        if (playResp.StatusCode is HttpStatusCode.Moved or HttpStatusCode.Redirect or HttpStatusCode.SeeOther or HttpStatusCode.TemporaryRedirect or (HttpStatusCode)308)
        {
            var streamLocation = playResp.Headers.Location;
            if (streamLocation is not null)
            {
                var directUrl = streamLocation.IsAbsoluteUri
                    ? streamLocation.AbsoluteUri
                    : new Uri(new Uri(playApiUrl), streamLocation).AbsoluteUri;
                return new ResolvedVideoInfo(directUrl, $"douyin_{videoId}", IsDirectMedia: true);
            }
        }

        return null;
    }

    private static async Task<ResolvedVideoInfo?> ResolveKuaishouUrlAsync(string url, CancellationToken ct)
    {
        var currentUrl = url;
        for (var i = 0; i < 5; i++)
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, currentUrl);
            req.Headers.UserAgent.ParseAdd(MobileUserAgent);

            using var resp = await Client.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            if (resp.StatusCode is HttpStatusCode.Moved or HttpStatusCode.Redirect or HttpStatusCode.SeeOther or HttpStatusCode.TemporaryRedirect or (HttpStatusCode)308)
            {
                var location = resp.Headers.Location;
                if (location is not null)
                {
                    currentUrl = location.IsAbsoluteUri ? location.AbsoluteUri : new Uri(new Uri(currentUrl), location).AbsoluteUri;
                    continue;
                }
            }

            if (resp.IsSuccessStatusCode)
            {
                var html = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
                var match = KuaishouPlayUrlRegex.Match(html);
                if (match.Success)
                {
                    var playUrl = match.Groups[1].Value.Replace("\\u002F", "/", StringComparison.Ordinal).Replace("\\/", "/", StringComparison.Ordinal);
                    return new ResolvedVideoInfo(playUrl, null, IsDirectMedia: true);
                }
            }

            break;
        }

        return null;
    }

    private static async Task<ResolvedVideoInfo?> ResolveGenericPageAsync(string url, CancellationToken ct)
    {
        var currentUrl = url;
        for (var i = 0; i < 5; i++)
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, currentUrl);
            req.Headers.UserAgent.ParseAdd(DesktopUserAgent);

            using var resp = await Client.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            if (resp.StatusCode is HttpStatusCode.Moved or HttpStatusCode.Redirect or HttpStatusCode.SeeOther or HttpStatusCode.TemporaryRedirect or (HttpStatusCode)308)
            {
                var location = resp.Headers.Location;
                if (location is not null)
                {
                    currentUrl = location.IsAbsoluteUri ? location.AbsoluteUri : new Uri(new Uri(currentUrl), location).AbsoluteUri;
                    continue;
                }
            }

            var contentType = resp.Content.Headers.ContentType?.MediaType?.ToLowerInvariant() ?? string.Empty;
            if (contentType.StartsWith("video/", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(contentType, "application/octet-stream", StringComparison.OrdinalIgnoreCase) ||
                IsDirectMediaUrl(currentUrl))
            {
                return new ResolvedVideoInfo(currentUrl, null, IsDirectMedia: true);
            }

            if (contentType.Contains("html", StringComparison.OrdinalIgnoreCase))
            {
                var html = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
                var videoMatch = VideoTagRegex.Match(html);
                if (videoMatch.Success)
                {
                    var src = videoMatch.Groups[1].Value;
                    var absUrl = Uri.TryCreate(new Uri(currentUrl), src, out var u) ? u.AbsoluteUri : src;
                    return new ResolvedVideoInfo(absUrl, null, IsDirectMedia: true);
                }

                var ogMatch = OgVideoRegex.Match(html);
                if (ogMatch.Success)
                {
                    var src = ogMatch.Groups[1].Value;
                    var absUrl = Uri.TryCreate(new Uri(currentUrl), src, out var u) ? u.AbsoluteUri : src;
                    return new ResolvedVideoInfo(absUrl, null, IsDirectMedia: true);
                }
            }

            break;
        }

        return null;
    }

    private static bool IsDirectMediaUrl(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            return false;
        }

        var path = uri.AbsolutePath;
        if (path.EndsWith(".mp4", StringComparison.OrdinalIgnoreCase) ||
            path.EndsWith(".mov", StringComparison.OrdinalIgnoreCase) ||
            path.EndsWith(".m4v", StringComparison.OrdinalIgnoreCase) ||
            path.EndsWith(".webm", StringComparison.OrdinalIgnoreCase) ||
            path.EndsWith(".mkv", StringComparison.OrdinalIgnoreCase) ||
            path.EndsWith(".flv", StringComparison.OrdinalIgnoreCase) ||
            path.EndsWith(".ts", StringComparison.OrdinalIgnoreCase) ||
            path.EndsWith(".m3u8", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        var host = uri.Host;
        if ((host.Contains("douyinvod", StringComparison.OrdinalIgnoreCase) ||
             host.Contains("365yg.com", StringComparison.OrdinalIgnoreCase) ||
             host.Contains("bytecdn", StringComparison.OrdinalIgnoreCase)) &&
            path.Contains("/video/tos/", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return false;
    }

    private static bool IsDouyinUrl(string url)
    {
        return Uri.TryCreate(url, UriKind.Absolute, out var uri) &&
               (uri.Host.Contains("douyin.com", StringComparison.OrdinalIgnoreCase) ||
                uri.Host.Contains("iesdouyin.com", StringComparison.OrdinalIgnoreCase) ||
                uri.Host.Contains("amemv.com", StringComparison.OrdinalIgnoreCase));
    }

    private static bool IsKuaishouUrl(string url)
    {
        return Uri.TryCreate(url, UriKind.Absolute, out var uri) &&
               (uri.Host.Contains("kuaishou.com", StringComparison.OrdinalIgnoreCase) ||
                uri.Host.Contains("kwai.com", StringComparison.OrdinalIgnoreCase) ||
                uri.Host.Contains("gifshow.com", StringComparison.OrdinalIgnoreCase));
    }
}
