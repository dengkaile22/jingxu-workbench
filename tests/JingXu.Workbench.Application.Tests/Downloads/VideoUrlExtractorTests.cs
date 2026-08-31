using JingXu.Workbench.Application.Downloads;

namespace JingXu.Workbench.Application.Tests.Downloads;

public sealed class VideoUrlExtractorTests
{
    [Fact]
    public void ExtractUrls_Extracts_Clean_Urls_From_Mixed_Share_Text()
    {
        var input = """
            7.12 05/11 v@x.xy nK:/ 听说这里有好看的视频 https://v.douyin.com/iABCxyz/ 复制此链接，打开Douyin搜索
            https://v26-default.365yg.com/video/tos/cn/sample.mp4
            【快手】https://v.kuaishou.com/123456 点击查看
            """;

        var urls = VideoUrlExtractor.ExtractUrls(input);

        Assert.Equal(3, urls.Count);
        Assert.Equal("https://v.douyin.com/iABCxyz/", urls[0]);
        Assert.Equal("https://v26-default.365yg.com/video/tos/cn/sample.mp4", urls[1]);
        Assert.Equal("https://v.kuaishou.com/123456", urls[2]);
    }

    [Fact]
    public void ExtractUrls_Returns_Empty_When_No_Valid_Urls()
    {
        var input = "这是一段没有链接的纯文本说明。";
        var urls = VideoUrlExtractor.ExtractUrls(input);
        Assert.Empty(urls);
    }
}
