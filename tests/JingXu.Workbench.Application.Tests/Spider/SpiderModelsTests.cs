using System.Text.Json;
using JingXu.Workbench.Application.Spider;
using Xunit;

namespace JingXu.Workbench.Application.Tests.Spider;

public sealed class SpiderModelsTests
{
    [Fact]
    public void SpiderConfig_SerializesAndDeserializes_Correctly()
    {
        var config = new SpiderConfig
        {
            Accounts =
            [
                new SpiderAccount
                {
                    Platform = "douyin",
                    UrlOrId = "https://www.douyin.com/user/test123",
                    Name = "达人A",
                    Enabled = true
                },
                new SpiderAccount
                {
                    Platform = "kuaishou",
                    UrlOrId = "profile_999",
                    Name = "老铁B",
                    Enabled = false
                }
            ],
            TimeConfig = new SpiderTimeConfig
            {
                Mode = "days",
                Days = 15
            },
            FilterConfig = new SpiderFilterConfig
            {
                MinAccountCount = 3,
                MinTotalOccurrences = 2,
                EnableFuzzyCluster = true,
                FuzzyThreshold = 0.8
            },
            Headless = true,
            MaxScrollsPerAccount = 30,
            ExportDir = @"C:\export"
        };

        var json = JsonSerializer.Serialize(config);
        var restored = JsonSerializer.Deserialize<SpiderConfig>(json);

        Assert.NotNull(restored);
        Assert.Equal(2, restored.Accounts.Count);
        Assert.Equal("douyin", restored.Accounts[0].Platform);
        Assert.Equal("达人A", restored.Accounts[0].Name);
        Assert.True(restored.Accounts[0].Enabled);
        Assert.Equal(15, restored.TimeConfig.Days);
        Assert.Equal(3, restored.FilterConfig.MinAccountCount);
        Assert.True(restored.FilterConfig.EnableFuzzyCluster);
        Assert.True(restored.Headless);
    }

    [Fact]
    public void SpiderProductResult_DeserializesFromJsonExport_Correctly()
    {
        var jsonSample = """
        {
            "商品名称": "【官方正品】生姜防脱洗发水500ml",
            "清洗名称": "生姜防脱洗发水500ml",
            "涉及平台": "douyin",
            "带货账号数": 2,
            "带货视频数": 5,
            "对标账号明细": "达人A, 达人B",
            "参考价格": "¥39.9",
            "示例视频链接": "https://www.douyin.com/video/123456"
        }
        """;

        var result = JsonSerializer.Deserialize<SpiderProductResult>(jsonSample);

        Assert.NotNull(result);
        Assert.Equal("【官方正品】生姜防脱洗发水500ml", result.ProductName);
        Assert.Equal("生姜防脱洗发水500ml", result.CleanedName);
        Assert.Equal("douyin", result.Platform);
        Assert.Equal(2, result.AccountCount);
        Assert.Equal(5, result.VideoCount);
        Assert.Equal("¥39.9", result.PriceRange);
        Assert.Equal("https://www.douyin.com/video/123456", result.SampleVideoUrl);
    }
}
