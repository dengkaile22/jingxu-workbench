namespace JingXu.Workbench.Application.Spider;

/// <summary>
/// 选品爬虫服务抽象接口
/// </summary>
public interface ISpiderService
{
    /// <summary>
    /// 读取爬虫当前配置文件（包含对标账号、时间与保留规则）
    /// </summary>
    Task<SpiderConfig> LoadConfigAsync(CancellationToken ct = default);

    /// <summary>
    /// 保存爬虫配置文件
    /// </summary>
    Task SaveConfigAsync(SpiderConfig config, CancellationToken ct = default);

    /// <summary>
    /// 运行爬虫与共性保留分析任务
    /// </summary>
    Task<SpiderRunResult> RunCrawlAsync(
        SpiderConfig config,
        Action<string>? onLogMessage = null,
        CancellationToken ct = default);

    /// <summary>
    /// 保存最近一次成功结果快照，供重启后恢复爆品表格与报表入口
    /// </summary>
    Task SaveLastResultAsync(SpiderRunResult result, CancellationToken ct = default);

    /// <summary>
    /// 读取最近一次结果快照；没有快照时返回 <c>null</c>
    /// </summary>
    Task<SpiderRunResult?> LoadLastResultAsync(CancellationToken ct = default);

    /// <summary>
    /// 唤起浏览器完成指定平台的扫码登录并持久化 Cookie
    /// </summary>
    Task LaunchLoginAsync(
        string platform,
        Action<string>? onLogMessage = null,
        CancellationToken ct = default);

    /// <summary>
    /// 启动独立的桌面端爬虫完整图形界面
    /// </summary>
    Task<bool> LaunchStandaloneGuiAsync(CancellationToken ct = default);

    /// <summary>
    /// 检测本地 Python 环境与爬虫依赖库就绪状态
    /// </summary>
    Task<SpiderEnvironmentStatus> CheckEnvironmentAsync(CancellationToken ct = default);
}
