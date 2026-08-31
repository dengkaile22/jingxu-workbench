using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using JingXu.Workbench.Application.Abstractions;

namespace JingXu.Workbench.Infrastructure.Downloads;

public sealed class HttpClientVideoDownloader : IVideoDownloader
{
    private static readonly HttpClient Client = CreateClient();

    private const string DesktopUserAgent =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

    private const string MobileUserAgent =
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1";

    private static HttpClient CreateClient()
    {
        var handler = new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate | DecompressionMethods.Brotli,
            AllowAutoRedirect = true
        };

        return new HttpClient(handler)
        {
            Timeout = TimeSpan.FromMinutes(30)
        };
    }

    public async Task DownloadAsync(
        string url,
        string outputPath,
        IProgress<DownloadProgress> progress,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(url);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);
        cancellationToken.ThrowIfCancellationRequested();

        var strategies = BuildDownloadStrategies(url);
        HttpResponseMessage? successfulResponse = null;
        HttpRequestException? lastHttpException = null;

        foreach (var strategy in strategies)
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var request = strategy.CreateRequest(url);
                var response = await Client.SendAsync(
                    request,
                    HttpCompletionOption.ResponseHeadersRead,
                    cancellationToken).ConfigureAwait(false);

                if (response.IsSuccessStatusCode)
                {
                    successfulResponse = response;
                    break;
                }

                var statusCode = response.StatusCode;
                response.Dispose();

                // 若遇到 403/401/429/503 等状态码，尝试下一个策略
                if (statusCode is HttpStatusCode.Forbidden or HttpStatusCode.Unauthorized or HttpStatusCode.TooManyRequests or HttpStatusCode.ServiceUnavailable)
                {
                    lastHttpException = new HttpRequestException(
                        $"HTTP {(int)statusCode} ({statusCode})",
                        inner: null,
                        statusCode);
                    await Task.Delay(100, cancellationToken).ConfigureAwait(false);
                    continue;
                }

                // 其他错误（如 404）直接抛出
                response.EnsureSuccessStatusCode();
            }
            catch (HttpRequestException ex) when (ex.StatusCode is HttpStatusCode.Forbidden or HttpStatusCode.Unauthorized)
            {
                lastHttpException = ex;
            }
        }

        if (successfulResponse is null)
        {
            if (lastHttpException is not null)
            {
                throw lastHttpException;
            }

            throw new HttpRequestException("无法获取视频流响应。");
        }

        using (successfulResponse)
        {
            successfulResponse.EnsureSuccessStatusCode();

            var totalBytes = successfulResponse.Content.Headers.ContentLength;
            var totalBytesValue = totalBytes.HasValue ? totalBytes.Value : -1L;

            var dir = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrWhiteSpace(dir))
            {
                Directory.CreateDirectory(dir);
            }

            await using var contentStream = await successfulResponse.Content
                .ReadAsStreamAsync(cancellationToken)
                .ConfigureAwait(false);
            await using var fileStream = new FileStream(
                outputPath, FileMode.Create, FileAccess.Write, FileShare.None, 81920, useAsync: true);

            var buffer = new byte[81920];
            var totalRead = 0L;
            var lastReport = DateTime.UtcNow;
            var lastRead = 0L;

            while (true)
            {
                var bytesRead = await contentStream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
                if (bytesRead == 0)
                {
                    break;
                }

                await fileStream.WriteAsync(buffer.AsMemory(0, bytesRead), cancellationToken).ConfigureAwait(false);
                totalRead += bytesRead;

                var now = DateTime.UtcNow;
                var elapsed = (now - lastReport).TotalSeconds;
                if (elapsed >= 0.2)
                {
                    var speed = (totalRead - lastRead) / Math.Max(elapsed, 0.001);
                    var percent = totalBytesValue > 0
                        ? Math.Clamp((double)totalRead / totalBytesValue * 100.0, 0, 100)
                        : 0;
                    progress.Report(new DownloadProgress(totalRead, totalBytes, speed, percent));
                    lastReport = now;
                    lastRead = totalRead;
                }
            }

            progress.Report(new DownloadProgress(totalRead, totalBytes, 0, 100));
        }
    }

    internal static IReadOnlyList<DownloadHeaderStrategy> BuildDownloadStrategies(string url)
    {
        var primaryReferer = ResolvePrimaryReferer(url);
        var host = TryGetHost(url);

        var list = new List<DownloadHeaderStrategy>();

        // 策略 1: 平台专属 Referer / 智能自适应
        list.Add(new DownloadHeaderStrategy(
            UserAgent: DesktopUserAgent,
            Referer: primaryReferer,
            IncludeRange: true));

        // 策略 2: 无 Referer 纯净模式（解决跨站防盗链）
        if (primaryReferer is not null)
        {
            list.Add(new DownloadHeaderStrategy(
                UserAgent: DesktopUserAgent,
                Referer: null,
                IncludeRange: true));
        }

        // 策略 3: 同源 Referer (https://host/)
        if (!string.IsNullOrWhiteSpace(host))
        {
            var originReferer = $"https://{host}/";
            if (!string.Equals(originReferer, primaryReferer, StringComparison.OrdinalIgnoreCase))
            {
                list.Add(new DownloadHeaderStrategy(
                    UserAgent: DesktopUserAgent,
                    Referer: originReferer,
                    IncludeRange: false));
            }
        }

        // 策略 4: 移动端 User-Agent
        list.Add(new DownloadHeaderStrategy(
            UserAgent: MobileUserAgent,
            Referer: primaryReferer,
            IncludeRange: true));

        return list;
    }

    internal static string? ResolvePrimaryReferer(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            return null;
        }

        var host = uri.Host.ToLowerInvariant();

        // 抖音 / 字节跳动系
        if (host.Contains("douyin") || host.Contains("amemv.com") || host.Contains("ixigua.com") ||
            host.Contains("365yg.com") || host.Contains("zijieapi") || host.Contains("toutiaocdn") ||
            host.Contains("snssdk") || host.Contains("bytedance") || host.Contains("bytecdn"))
        {
            return "https://www.douyin.com/";
        }

        // 快手系
        if (host.Contains("kuaishou") || host.Contains("kwai") || host.Contains("gifshow") || host.Contains("yximgs"))
        {
            return "https://www.kuaishou.com/";
        }

        // B站系
        if (host.Contains("bilibili") || host.Contains("bilivideo") || host.Contains("hdslb"))
        {
            return "https://www.bilibili.com/";
        }

        // 小红书系
        if (host.Contains("xiaohongshu") || host.Contains("xhscdn"))
        {
            return "https://www.xiaohongshu.com/";
        }

        // 微信视频号
        if (host.Contains("weixin.qq.com") || host.Contains("channels.weixin") || host.Contains("qpic.cn"))
        {
            return "https://channels.weixin.qq.com/";
        }

        // 其他通用直链（OSS、COS、普通自建 CDN 等）默认不带外站 Referer，防止防盗链拦截
        return null;
    }

    private static string? TryGetHost(string url)
    {
        return Uri.TryCreate(url, UriKind.Absolute, out var uri) ? uri.Host : null;
    }

    internal sealed record DownloadHeaderStrategy(
        string UserAgent,
        string? Referer,
        bool IncludeRange)
    {
        public HttpRequestMessage CreateRequest(string url)
        {
            var request = new HttpRequestMessage(HttpMethod.Get, url);

            request.Headers.UserAgent.ParseAdd(UserAgent);
            request.Headers.Accept.ParseAdd("*/*");
            request.Headers.AcceptLanguage.ParseAdd("zh-CN,zh;q=0.9,en;q=0.8");
            request.Headers.Connection.ParseAdd("keep-alive");

            if (!string.IsNullOrWhiteSpace(Referer))
            {
                request.Headers.Referrer = new Uri(Referer);
            }

            if (IncludeRange)
            {
                request.Headers.Range = new RangeHeaderValue(0, null);
            }

            return request;
        }
    }
}
