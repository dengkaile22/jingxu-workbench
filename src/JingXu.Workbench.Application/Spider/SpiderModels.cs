using System.Text.Json.Serialization;

namespace JingXu.Workbench.Application.Spider;

/// <summary>
/// 对标账号模型
/// </summary>
public sealed class SpiderAccount
{
    [JsonPropertyName("platform")]
    public string Platform { get; set; } = "douyin";

    [JsonPropertyName("url_or_id")]
    public string UrlOrId { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; } = true;

    [JsonPropertyName("sec_uid")]
    public string SecUid { get; set; } = string.Empty;

    [JsonPropertyName("user_id")]
    public string UserId { get; set; } = string.Empty;

    [JsonIgnore]
    public string Status { get; set; } = "就绪";
}

/// <summary>
/// 时间范围过滤配置
/// </summary>
public sealed class SpiderTimeConfig
{
    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "days";

    [JsonPropertyName("days")]
    public int Days { get; set; } = 7;

    [JsonPropertyName("start_date")]
    public string StartDate { get; set; } = string.Empty;

    [JsonPropertyName("end_date")]
    public string EndDate { get; set; } = string.Empty;
}

/// <summary>
/// 跨账号共性爆品保留规则配置
/// </summary>
public sealed class SpiderFilterConfig
{
    [JsonPropertyName("min_account_count")]
    public int MinAccountCount { get; set; } = 2;

    [JsonPropertyName("min_total_occurrences")]
    public int MinTotalOccurrences { get; set; } = 1;

    [JsonPropertyName("filter_by")]
    public string FilterBy { get; set; } = "accounts";

    [JsonPropertyName("enable_fuzzy_cluster")]
    public bool EnableFuzzyCluster { get; set; } = true;

    [JsonPropertyName("fuzzy_threshold")]
    public double FuzzyThreshold { get; set; } = 0.75;
}

/// <summary>
/// 爬虫总配置文件模型 (对应 config.json)
/// </summary>
public sealed class SpiderConfig
{
    [JsonPropertyName("accounts")]
    public List<SpiderAccount> Accounts { get; set; } = [];

    [JsonPropertyName("time_config")]
    public SpiderTimeConfig TimeConfig { get; set; } = new();

    [JsonPropertyName("filter_config")]
    public SpiderFilterConfig FilterConfig { get; set; } = new();

    [JsonPropertyName("headless")]
    public bool Headless { get; set; }

    [JsonPropertyName("max_scrolls_per_account")]
    public int MaxScrollsPerAccount { get; set; } = 25;

    [JsonPropertyName("export_dir")]
    public string ExportDir { get; set; } = string.Empty;
}

/// <summary>
/// 单条抓取到的带货视频与商品项
/// </summary>
public sealed class SpiderVideoItem
{
    [JsonPropertyName("平台")]
    public string Platform { get; set; } = string.Empty;

    [JsonPropertyName("账号名称")]
    public string AccountName { get; set; } = string.Empty;

    [JsonPropertyName("账号ID")]
    public string AccountId { get; set; } = string.Empty;

    [JsonPropertyName("视频ID")]
    public string VideoId { get; set; } = string.Empty;

    [JsonPropertyName("视频标题")]
    public string VideoTitle { get; set; } = string.Empty;

    [JsonPropertyName("视频链接")]
    public string VideoUrl { get; set; } = string.Empty;

    [JsonPropertyName("发布时间")]
    public string PublishTime { get; set; } = string.Empty;

    [JsonPropertyName("商品ID")]
    public string ProductId { get; set; } = string.Empty;

    [JsonPropertyName("商品原始名称")]
    public string ProductName { get; set; } = string.Empty;

    [JsonPropertyName("清洗后名称")]
    public string CleanedName { get; set; } = string.Empty;

    [JsonPropertyName("售价")]
    public string Price { get; set; } = string.Empty;

    [JsonPropertyName("商品链接")]
    public string DetailUrl { get; set; } = string.Empty;
}

/// <summary>
/// 跨账号保留的共同带货爆品
/// </summary>
public sealed class SpiderProductResult
{
    [JsonPropertyName("商品名称")]
    public string ProductName { get; set; } = string.Empty;

    [JsonPropertyName("清洗名称")]
    public string CleanedName { get; set; } = string.Empty;

    [JsonPropertyName("涉及平台")]
    public string Platform { get; set; } = string.Empty;

    [JsonPropertyName("带货账号数")]
    public int AccountCount { get; set; }

    [JsonPropertyName("带货视频数")]
    public int VideoCount { get; set; }

    [JsonPropertyName("对标账号明细")]
    public string AccountsDetail { get; set; } = string.Empty;

    [JsonPropertyName("参考价格")]
    public string PriceRange { get; set; } = string.Empty;

    [JsonPropertyName("示例视频链接")]
    public string SampleVideoUrl { get; set; } = string.Empty;

    [JsonIgnore]
    public List<SpiderVideoItem> Items { get; set; } = [];
}

/// <summary>
/// 爬虫运行结果汇总
/// </summary>
public sealed class SpiderRunResult
{
    public bool Success { get; set; }
    public string Message { get; set; } = string.Empty;
    public string? ExportedExcelPath { get; set; }
    public string? ExportedJsonPath { get; set; }

    /// <summary>结果完成时间（恢复历史快照时来自快照）。</summary>
    public DateTimeOffset? SavedAt { get; set; }

    public IReadOnlyList<SpiderProductResult> RetainedProducts { get; set; } = [];
    public IReadOnlyList<SpiderVideoItem> AllItems { get; set; } = [];
}

/// <summary>
/// 爬虫本地运行环境状态
/// </summary>
public sealed class SpiderEnvironmentStatus
{
    public bool PythonAvailable { get; set; }

    /// <summary>是否使用随包分发的内置嵌入式 Python。</summary>
    public bool IsBundledPython { get; set; }

    public string? PythonPath { get; set; }
    public string? PythonVersion { get; set; }
    public string? SpiderDirectory { get; set; }
    public string? ConfigPath { get; set; }
    public string? DataDirectory { get; set; }
    public bool DependenciesInstalled { get; set; }

    /// <summary>缺失的 Python 依赖模块名。</summary>
    public IReadOnlyList<string> MissingPackages { get; set; } = [];

    public string Message { get; set; } = string.Empty;
}
