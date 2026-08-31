using JingXu.Workbench.Infrastructure.Downloads;

namespace JingXu.Workbench.Infrastructure.Tests.Downloads;

public sealed class HttpClientVideoDownloaderTests
{
    [Theory]
    [InlineData("https://v26-default.365yg.com/video/tos/cn/xxx.mp4", "https://www.douyin.com/")]
    [InlineData("https://v3-web.douyinvod.com/xxx/mp4", "https://www.douyin.com/")]
    [InlineData("https://tx-v.kuaishou.com/bs2/xxx.mp4", "https://www.kuaishou.com/")]
    [InlineData("https://upos-sz-mirrorcos.bilivideo.com/upgcxcode/xxx.mp4", "https://www.bilibili.com/")]
    [InlineData("https://sns-video-bd.xhscdn.com/xxx.mp4", "https://www.xiaohongshu.com/")]
    [InlineData("https://my-bucket.oss-cn-hangzhou.aliyuncs.com/sample.mp4", null)]
    [InlineData("https://example.com/videos/direct.mp4", null)]
    public void ResolvePrimaryReferer_Matches_Expected_Platform(string url, string? expectedReferer)
    {
        var actual = HttpClientVideoDownloader.ResolvePrimaryReferer(url);
        Assert.Equal(expectedReferer, actual);
    }

    [Fact]
    public void BuildDownloadStrategies_Produces_Multiple_Fallback_Strategies()
    {
        var url = "https://v26-default.365yg.com/video/sample.mp4";
        var strategies = HttpClientVideoDownloader.BuildDownloadStrategies(url);

        Assert.NotEmpty(strategies);
        Assert.True(strategies.Count >= 3);

        // 包含无 Referer 纯净模式
        Assert.Contains(strategies, s => s.Referer is null);

        // 包含移动端 UA 模式
        Assert.Contains(strategies, s => s.UserAgent.Contains("iPhone") || s.UserAgent.Contains("Mobile"));
    }
}
