namespace JingXu.Workbench.Application.Projects;

/// <summary>集中解析本地数据根目录；自动化验证可使用独立目录，不接触用户素材库。</summary>
public static class WorkbenchDataPaths
{
    public static string GetTempDirectory()
    {
        var configured = Environment.GetEnvironmentVariable("JINGXU_TEMP_DIRECTORY");
        return !string.IsNullOrWhiteSpace(configured) && Path.IsPathFullyQualified(configured)
            ? Path.GetFullPath(configured)
            : Path.GetTempPath();
    }

    public static string GetDataDirectory()
    {
        var configured = Environment.GetEnvironmentVariable("JINGXU_DATA_DIRECTORY");
        return !string.IsNullOrWhiteSpace(configured) && Path.IsPathFullyQualified(configured)
            ? Path.GetFullPath(configured)
            : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "JingXu");
    }

    /// <summary>选品爬虫配置、报表导出与浏览器登录态的独立子目录。</summary>
    public static string GetSpiderDirectory() => Path.Combine(GetDataDirectory(), "Spider");
}
