using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Spider;
using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.Infrastructure.Spider;

/// <summary>
/// 基于本地 Python 与 cli.py 的选品爬虫服务实现。
/// 批处理进程统一走 <see cref="IExternalProcessRunner"/>（参数列表 + Job Object 树终止）；
/// 配置、浏览器登录态、报表与源码分别落在数据目录 runtime 布局中，不写入安装目录。
/// </summary>
public sealed class PythonSpiderService : ISpiderService
{
    private const string PortableSpiderFolderName = "爬虫抖音和快手";
    private const string SourceSpiderFolderName = "JingXu.Spider";
    private const string SourceFolderName = "src";
    private const string PublishedSpiderFolderName = "spider";
    private const string RuntimeFolderName = "runtime";
    private const string CliFileName = "cli.py";
    private const int SearchDepth = 6;

    private static readonly TimeSpan VersionProbeTimeout = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan DependencyProbeTimeout = TimeSpan.FromSeconds(30);
    private static readonly string[] RequiredModules = ["DrissionPage", "requests", "openpyxl", "tabulate"];

    private const string DependencyProbeScript = """
        import importlib.util as u
        mods = ["DrissionPage", "requests", "openpyxl", "tabulate"]
        missing = [m for m in mods if u.find_spec(m) is None]
        print("OK" if not missing else "MISSING:" + ",".join(missing))
        """;

    private static readonly string[] SpiderRelativePaths =
    [
        Path.Combine(RuntimeFolderName, PublishedSpiderFolderName),
        Path.Combine(SourceFolderName, SourceSpiderFolderName),
        PortableSpiderFolderName
    ];

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = true
    };

    private static readonly Encoding Utf8NoBom = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

    private readonly string _appRoot;
    private readonly IExternalProcessRunner _runner;
    private readonly Func<string, string?>? _pathResolver;
    private readonly string _dataDirectory;

    public PythonSpiderService(
        IExternalProcessRunner runner,
        string? appRoot = null,
        Func<string, string?>? pathResolver = null,
        string? dataDirectory = null)
    {
        ArgumentNullException.ThrowIfNull(runner);

        _runner = runner;
        _appRoot = (appRoot ?? AppContext.BaseDirectory)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        _pathResolver = pathResolver;
        _dataDirectory = string.IsNullOrWhiteSpace(dataDirectory)
            ? WorkbenchDataPaths.GetSpiderDirectory()
            : Path.GetFullPath(dataDirectory);
    }

    /// <summary>爬虫配置、报表与浏览器登录态的数据目录。</summary>
    public string DataDirectory => _dataDirectory;

    /// <summary>爬虫配置文件路径（应用侧读写，不再写回源码目录）。</summary>
    public string ConfigPath => Path.Combine(_dataDirectory, "config.json");

    /// <summary>Excel/JSON 报表导出目录。</summary>
    public string ExportDirectory => Path.Combine(_dataDirectory, "exports");

    /// <summary>浏览器登录态持久化目录（含 Cookie，敏感）。</summary>
    public string ProfileDirectory => Path.Combine(_dataDirectory, "browser_profile");

    /// <summary>最近一次结果快照路径。</summary>
    public string LastResultPath => Path.Combine(_dataDirectory, "last_result.json");

    /// <summary>
    /// 解析爬虫源码目录：应用内置 <c>runtime/spider</c> → 源码树 <c>src/JingXu.Spider</c> →
    /// 旧版便携目录 <c>爬虫抖音和快手</c> → 开发仓上层目录 → 当前工作目录；全部失败时返回内置候选路径。
    /// </summary>
    public string ResolveSpiderDirectory()
    {
        foreach (var root in EnumerateSearchRoots())
        {
            foreach (var relativePath in SpiderRelativePaths)
            {
                var candidate = Path.Combine(root, relativePath);
                if (IsSpiderDirectory(candidate))
                {
                    return candidate;
                }
            }
        }

        return Path.Combine(_appRoot, RuntimeFolderName, PublishedSpiderFolderName);
    }

    /// <summary>解析 Python 解释器：内置嵌入式 <c>runtime/python</c> → 用户 PATH → 裸文件名回退。</summary>
    public (string Path, bool IsBundled) ResolvePythonExecutable()
    {
        foreach (var root in EnumerateSearchRoots())
        {
            var bundled = Path.Combine(root, RuntimeFolderName, "python", "python.exe");
            if (File.Exists(bundled))
            {
                return (bundled, true);
            }
        }

        if (_pathResolver is not null)
        {
            var onPath = _pathResolver("python.exe") ?? _pathResolver("python");
            if (!string.IsNullOrWhiteSpace(onPath) && File.Exists(onPath))
            {
                return (onPath, false);
            }
        }

        var pathEnvironment = Environment.GetEnvironmentVariable("PATH");
        if (!string.IsNullOrWhiteSpace(pathEnvironment))
        {
            foreach (var part in pathEnvironment.Split(';', StringSplitOptions.RemoveEmptyEntries))
            {
                try
                {
                    var candidate = Path.Combine(part.Trim(), "python.exe");
                    if (File.Exists(candidate))
                    {
                        return (candidate, false);
                    }
                }
                catch (ArgumentException)
                {
                    // 忽略 PATH 中的非法路径片段。
                }
            }
        }

        return ("python", false);
    }

    public async Task<SpiderConfig> LoadConfigAsync(CancellationToken ct = default)
    {
        var path = ConfigPath;
        if (!File.Exists(path))
        {
            return new SpiderConfig { ExportDir = ExportDirectory };
        }

        try
        {
            var json = await File.ReadAllTextAsync(path, Encoding.UTF8, ct).ConfigureAwait(false);
            var config = JsonSerializer.Deserialize<SpiderConfig>(json, JsonOptions);
            return config ?? new SpiderConfig { ExportDir = ExportDirectory };
        }
        catch (Exception ex)
        {
            Trace.TraceWarning($"读取爬虫配置失败：{ex.Message}");
            return new SpiderConfig { ExportDir = ExportDirectory };
        }
    }

    public async Task SaveConfigAsync(SpiderConfig config, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(config);

        Directory.CreateDirectory(_dataDirectory);
        var json = JsonSerializer.Serialize(config, JsonOptions);
        await File.WriteAllTextAsync(ConfigPath, json, Utf8NoBom, ct).ConfigureAwait(false);
    }

    public async Task<SpiderEnvironmentStatus> CheckEnvironmentAsync(CancellationToken ct = default)
    {
        var spiderDirectory = ResolveSpiderDirectory();
        var (pythonPath, isBundled) = ResolvePythonExecutable();

        var status = new SpiderEnvironmentStatus
        {
            PythonPath = pythonPath,
            IsBundledPython = isBundled,
            SpiderDirectory = spiderDirectory,
            ConfigPath = ConfigPath,
            DataDirectory = _dataDirectory,
            MissingPackages = RequiredModules
        };

        if (!IsSpiderDirectory(spiderDirectory))
        {
            status.Message = $"未找到选品爬虫源码目录（缺少 {CliFileName}）：{spiderDirectory}";
            return status;
        }

        var versionResult = await TryRunAsync(pythonPath, ["--version"], VersionProbeTimeout, ct).ConfigureAwait(false);
        var versionText = versionResult is null
            ? null
            : FirstNonEmptyLine(versionResult.StandardOutput, versionResult.StandardError);

        if (versionResult is null || versionResult.ExitCode != 0 || string.IsNullOrWhiteSpace(versionText))
        {
            status.Message = isBundled
                ? "内置 Python 无法启动；请重新运行 scripts/Resolve-SpiderRuntime.ps1 构建内置环境。"
                : "未检测到可用的 Python。可运行 scripts/Resolve-SpiderRuntime.ps1 构建随包环境，或安装 Python 3.8 以上版本。";
            return status;
        }

        status.PythonAvailable = true;
        status.PythonVersion = versionText;

        var probeResult = await TryRunAsync(
            pythonPath,
            ["-c", DependencyProbeScript],
            DependencyProbeTimeout,
            ct).ConfigureAwait(false);

        var probeText = probeResult?.StandardOutput.Trim();
        if (probeResult is not null
            && probeResult.ExitCode == 0
            && string.Equals(probeText, "OK", StringComparison.Ordinal))
        {
            status.DependenciesInstalled = true;
            status.MissingPackages = [];
            status.Message = isBundled
                ? $"内置爬虫运行环境已就绪（{versionText}），无需本机安装 Python。"
                : $"已使用系统 Python（{versionText}），依赖完整。";
            return status;
        }

        var missing = ParseMissingPackages(probeText);
        status.MissingPackages = missing.Length > 0 ? missing : RequiredModules;
        status.Message = isBundled
            ? $"内置 Python 缺少依赖：{string.Join("、", status.MissingPackages)}；请运行 scripts/Resolve-SpiderRuntime.ps1 重新构建内置环境。"
            : $"系统 Python 缺少依赖：{string.Join("、", status.MissingPackages)}；请在爬虫目录执行 python -m pip install -r requirements.txt。";
        return status;
    }

    public async Task<SpiderRunResult> RunCrawlAsync(
        SpiderConfig config,
        Action<string>? onLogMessage = null,
        CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(config);

        var spiderDirectory = ResolveSpiderDirectory();
        if (!IsSpiderDirectory(spiderDirectory))
        {
            return Failure($"未找到选品爬虫源码目录（{spiderDirectory}）。请重新安装或运行 scripts/Resolve-SpiderRuntime.ps1。");
        }

        var (pythonPath, isBundled) = ResolvePythonExecutable();
        Directory.CreateDirectory(_dataDirectory);
        Directory.CreateDirectory(ExportDirectory);

        // 配置由应用侧统一落盘，Python 侧只读；导出目录固定指向数据目录。
        config.ExportDir = ExportDirectory;
        await SaveConfigAsync(config, ct).ConfigureAwait(false);

        var jsonPath = Path.Combine(WorkbenchDataPaths.GetTempDirectory(), $"jingxu-spider-{Guid.NewGuid():N}.json");

        try
        {
            var arguments = BuildCrawlArguments(config, spiderDirectory, jsonPath);
            var environment = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["PYTHONUNBUFFERED"] = "1",
                ["PYTHONUTF8"] = "1",
                ["PYTHONIOENCODING"] = "utf-8"
            };

            onLogMessage?.Invoke($"[*] 爬虫引擎：{pythonPath}{(isBundled ? "（内置）" : string.Empty)}");
            onLogMessage?.Invoke($"[*] 工作目录：{spiderDirectory}");

            var request = ProcessRequest.Create(
                pythonPath,
                arguments,
                workingDirectory: spiderDirectory,
                environmentOverrides: environment,
                outputEncoding: Encoding.UTF8);

            var progress = onLogMessage is null ? null : new Progress<string>(onLogMessage);
            var result = await _runner.RunAsync(request, progress, ct).ConfigureAwait(false);

            if (result.ExitCode != 0)
            {
                return Failure(BuildFailureMessage(result));
            }

            var runResult = ParseRunResult(jsonPath);
            if (runResult.Success)
            {
                runResult.SavedAt = DateTimeOffset.Now;
                try
                {
                    await SaveLastResultAsync(runResult, ct).ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    onLogMessage?.Invoke($"[-] 结果快照保存失败：{ex.Message}");
                }
            }

            return runResult;
        }
        catch (OperationCanceledException)
        {
            return Failure("爬虫任务已由用户取消。");
        }
        catch (InvalidOperationException ex)
        {
            return Failure($"爬虫启动失败：{ex.Message}");
        }
        finally
        {
            TryDeleteFile(jsonPath);
        }
    }

    public Task LaunchLoginAsync(
        string platform,
        Action<string>? onLogMessage = null,
        CancellationToken ct = default)
    {
        var spiderDirectory = ResolveSpiderDirectory();
        if (!IsSpiderDirectory(spiderDirectory))
        {
            onLogMessage?.Invoke($"[-] 未找到选品爬虫源码目录：{spiderDirectory}");
            return Task.CompletedTask;
        }

        var (pythonPath, _) = ResolvePythonExecutable();
        var arguments = new StringBuilder()
            .Append(Quote(Path.Combine(spiderDirectory, CliFileName)))
            .Append(" --login ").Append(platform)
            .Append(" --profile-dir ").Append(Quote(ProfileDirectory))
            .ToString();

        onLogMessage?.Invoke($"[*] 启动浏览器扫码登录：{platform}（登录态保存到 {ProfileDirectory}）");

        try
        {
            // 扫码登录为交互式流程：保留可见控制台窗口，且不纳入批处理进程管理。
            Process.Start(new ProcessStartInfo
            {
                FileName = pythonPath,
                Arguments = arguments,
                WorkingDirectory = spiderDirectory,
                UseShellExecute = true
            });
        }
        catch (Exception ex)
        {
            onLogMessage?.Invoke($"[-] 唤起扫码登录失败：{ex.Message}");
        }

        return Task.CompletedTask;
    }

    public Task<bool> LaunchStandaloneGuiAsync(CancellationToken ct = default)
    {
        var spiderDirectory = ResolveSpiderDirectory();
        var runPy = Path.Combine(spiderDirectory, "run.py");
        if (!File.Exists(runPy))
        {
            Trace.TraceInformation("独立爬虫图形界面未随包分发，请使用应用内「选品爬虫」页面。");
            return Task.FromResult(false);
        }

        try
        {
            var (pythonPath, _) = ResolvePythonExecutable();
            Process.Start(new ProcessStartInfo
            {
                FileName = pythonPath,
                Arguments = Quote(runPy),
                WorkingDirectory = spiderDirectory,
                UseShellExecute = true
            });
            return Task.FromResult(true);
        }
        catch (Exception ex)
        {
            Trace.TraceError($"启动独立爬虫图形界面失败：{ex.Message}");
            return Task.FromResult(false);
        }
    }

    private List<string> BuildCrawlArguments(SpiderConfig config, string spiderDirectory, string jsonPath)
    {
        var arguments = new List<string>
        {
            Path.Combine(spiderDirectory, CliFileName),
            "--config", ConfigPath,
            "--json-out", jsonPath,
            "--profile-dir", ProfileDirectory,
            "--export-dir", ExportDirectory
        };

        var mode = string.IsNullOrWhiteSpace(config.TimeConfig.Mode) ? "days" : config.TimeConfig.Mode;
        arguments.Add("--time-mode");
        arguments.Add(mode);

        if (string.Equals(mode, "days", StringComparison.OrdinalIgnoreCase))
        {
            arguments.Add("--days");
            arguments.Add(Math.Max(1, config.TimeConfig.Days).ToString(CultureInfo.InvariantCulture));
        }
        else if (string.Equals(mode, "range", StringComparison.OrdinalIgnoreCase))
        {
            if (!string.IsNullOrWhiteSpace(config.TimeConfig.StartDate))
            {
                arguments.Add("--start-date");
                arguments.Add(config.TimeConfig.StartDate);
            }

            if (!string.IsNullOrWhiteSpace(config.TimeConfig.EndDate))
            {
                arguments.Add("--end-date");
                arguments.Add(config.TimeConfig.EndDate);
            }
        }

        if (config.Headless)
        {
            arguments.Add("--headless");
        }

        arguments.Add("--min-accounts");
        arguments.Add(Math.Max(1, config.FilterConfig.MinAccountCount).ToString(CultureInfo.InvariantCulture));

        arguments.Add("--min-occurrences");
        arguments.Add(Math.Max(0, config.FilterConfig.MinTotalOccurrences).ToString(CultureInfo.InvariantCulture));

        if (!string.IsNullOrWhiteSpace(config.FilterConfig.FilterBy))
        {
            arguments.Add("--filter-by");
            arguments.Add(config.FilterConfig.FilterBy);
        }

        arguments.Add("--fuzzy-threshold");
        arguments.Add(config.FilterConfig.FuzzyThreshold.ToString("0.###", CultureInfo.InvariantCulture));

        arguments.Add("--max-scrolls");
        arguments.Add(Math.Max(1, config.MaxScrollsPerAccount).ToString(CultureInfo.InvariantCulture));

        return arguments;
    }

    private static SpiderRunResult ParseRunResult(string jsonPath)
    {
        if (!File.Exists(jsonPath))
        {
            return new SpiderRunResult
            {
                Success = true,
                Message = "爬取完成，但未生成结构化数据文件。"
            };
        }

        using var stream = File.OpenRead(jsonPath);
        var document = JsonNode.Parse(stream);

        var retainedProducts = new List<SpiderProductResult>();
        var items = new List<SpiderVideoItem>();

        if (document?["retained_products"] is JsonArray retainedArray)
        {
            foreach (var node in retainedArray)
            {
                if (node is null)
                {
                    continue;
                }

                var product = JsonSerializer.Deserialize<SpiderProductResult>(node.ToJsonString(), JsonOptions);
                if (product is not null)
                {
                    retainedProducts.Add(product);
                }
            }
        }

        if (document?["all_items"] is JsonArray itemsArray)
        {
            foreach (var node in itemsArray)
            {
                if (node is null)
                {
                    continue;
                }

                var item = JsonSerializer.Deserialize<SpiderVideoItem>(node.ToJsonString(), JsonOptions);
                if (item is not null)
                {
                    items.Add(item);
                }
            }
        }

        LinkItems(retainedProducts, items);

        return new SpiderRunResult
        {
            Success = true,
            Message = $"爬取完成，共获得 {retainedProducts.Count} 款跨账号爆品与 {items.Count} 条明细。",
            ExportedExcelPath = ReadExcelPath(document),
            RetainedProducts = retainedProducts,
            AllItems = items
        };
    }

    private static void LinkItems(List<SpiderProductResult> retainedProducts, List<SpiderVideoItem> items)
    {
        foreach (var product in retainedProducts)
        {
            product.Items = items
                .Where(item =>
                    string.Equals(item.CleanedName, product.CleanedName, StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(item.ProductName, product.ProductName, StringComparison.OrdinalIgnoreCase))
                .ToList();
        }
    }

    public async Task SaveLastResultAsync(SpiderRunResult result, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(result);

        var snapshot = new ResultSnapshot
        {
            SavedAt = (result.SavedAt ?? DateTimeOffset.Now).ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture),
            ExcelPath = result.ExportedExcelPath ?? string.Empty,
            RetainedProducts = [.. result.RetainedProducts],
            AllItems = [.. result.AllItems]
        };

        Directory.CreateDirectory(_dataDirectory);
        var json = JsonSerializer.Serialize(snapshot, JsonOptions);
        await File.WriteAllTextAsync(LastResultPath, json, Utf8NoBom, ct).ConfigureAwait(false);
    }

    public async Task<SpiderRunResult?> LoadLastResultAsync(CancellationToken ct = default)
    {
        if (!File.Exists(LastResultPath))
        {
            return null;
        }

        try
        {
            var json = await File.ReadAllTextAsync(LastResultPath, Encoding.UTF8, ct).ConfigureAwait(false);
            var snapshot = JsonSerializer.Deserialize<ResultSnapshot>(json, JsonOptions);
            if (snapshot is null)
            {
                return null;
            }

            var retainedProducts = snapshot.RetainedProducts;
            var items = snapshot.AllItems;
            LinkItems(retainedProducts, items);

            var excelPath = !string.IsNullOrWhiteSpace(snapshot.ExcelPath) && File.Exists(snapshot.ExcelPath)
                ? snapshot.ExcelPath
                : null;

            return new SpiderRunResult
            {
                Success = true,
                Message = $"已恢复上次结果（{snapshot.SavedAt}）。",
                SavedAt = DateTimeOffset.TryParse(
                    snapshot.SavedAt,
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.None,
                    out var savedAt)
                    ? savedAt
                    : null,
                ExportedExcelPath = excelPath,
                RetainedProducts = retainedProducts,
                AllItems = items
            };
        }
        catch (Exception ex)
        {
            Trace.TraceWarning($"读取爬虫结果快照失败：{ex.Message}");
            return null;
        }
    }

    private sealed class ResultSnapshot
    {
        [JsonPropertyName("saved_at")]
        public string SavedAt { get; set; } = string.Empty;

        [JsonPropertyName("excel_path")]
        public string ExcelPath { get; set; } = string.Empty;

        [JsonPropertyName("retained_products")]
        public List<SpiderProductResult> RetainedProducts { get; set; } = [];

        [JsonPropertyName("all_items")]
        public List<SpiderVideoItem> AllItems { get; set; } = [];
    }

    private static string? ReadExcelPath(JsonNode? document)
    {
        if (document?["excel_path"] is JsonValue value && value.TryGetValue<string>(out var path)
            && !string.IsNullOrWhiteSpace(path) && File.Exists(path))
        {
            return path;
        }

        return null;
    }

    private async Task<IProcessResult?> TryRunAsync(
        string executable,
        IReadOnlyList<string> arguments,
        TimeSpan timeout,
        CancellationToken ct)
    {
        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeoutCts.CancelAfter(timeout);

        try
        {
            var request = ProcessRequest.Create(executable, arguments, outputEncoding: Encoding.UTF8);
            return await _runner.RunAsync(request, progress: null, timeoutCts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            return null;
        }
        catch (InvalidOperationException)
        {
            return null;
        }
    }

    private IEnumerable<string> EnumerateSearchRoots()
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var directory = _appRoot;

        for (var depth = 0; depth <= SearchDepth && !string.IsNullOrWhiteSpace(directory); depth++)
        {
            if (seen.Add(directory))
            {
                yield return directory;
            }

            var parent = Path.GetDirectoryName(directory);
            if (string.IsNullOrWhiteSpace(parent) || string.Equals(parent, directory, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }

            directory = parent;
        }

        var currentDirectory = Directory.GetCurrentDirectory();
        if (!string.IsNullOrWhiteSpace(currentDirectory) && seen.Add(currentDirectory))
        {
            yield return currentDirectory;
        }
    }

    private static bool IsSpiderDirectory(string directory) =>
        !string.IsNullOrWhiteSpace(directory) && File.Exists(Path.Combine(directory, CliFileName));

    private static string? FirstNonEmptyLine(string? primary, string? fallback)
    {
        var text = string.IsNullOrWhiteSpace(primary) ? fallback : primary;
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        using var reader = new StringReader(text);
        return reader.ReadLine()?.Trim();
    }

    private static string[] ParseMissingPackages(string? probeText)
    {
        const string marker = "MISSING:";
        if (string.IsNullOrWhiteSpace(probeText))
        {
            return [];
        }

        var index = probeText.IndexOf(marker, StringComparison.Ordinal);
        if (index < 0)
        {
            return [];
        }

        return probeText[(index + marker.Length)..]
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    }

    private static string BuildFailureMessage(IProcessResult result)
    {
        var detail = result.StandardError?.Trim();
        if (string.IsNullOrWhiteSpace(detail))
        {
            detail = LastNonEmptyLine(result.StandardOutput);
        }

        if (detail is { Length: > 600 })
        {
            detail = detail[^600..];
        }

        var message = $"爬虫执行退出，退出码 {result.ExitCode}。";
        return string.IsNullOrWhiteSpace(detail) ? message : $"{message} {detail}";
    }

    private static string? LastNonEmptyLine(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        return text
            .Split('\n')
            .Select(line => line.Trim())
            .LastOrDefault(line => line.Length > 0);
    }

    private static SpiderRunResult Failure(string message) => new() { Success = false, Message = message };

    private static string Quote(string value) => $"\"{value}\"";

    private static void TryDeleteFile(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // 临时文件清理失败不影响结果返回。
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
