using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Bootstrap;

/// <summary>--self-test 模式的机器可读诊断结果。</summary>
public sealed record SelfTestReport(
    int SchemaVersion,
    bool Success,
    string AppRoot,
    bool ManifestValid,
    IReadOnlyList<string> ManifestIssues,
    IReadOnlyList<SelfTestComponentReport> Components,
    IReadOnlyList<string> MissingRequired);

/// <summary>单个运行时组件的自检条目。</summary>
public sealed record SelfTestComponentReport(
    string Kind,
    string DisplayName,
    bool Required,
    bool Available,
    string Message,
    string? ResolvedPath);

/// <summary>
/// 处理 <c>--self-test</c>：离线校验运行时清单与组件布局，输出 JSON 并返回进程退出码。
/// </summary>
public static class SelfTestRunner
{
    private const int SchemaVersion = 1;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false
    };

    /// <summary>执行自检并返回进程退出码（0=通过，1=失败）。</summary>
    public static int Run(string[] args) =>
        RunAsync(args, CancellationToken.None).GetAwaiter().GetResult();

    /// <summary>执行自检并返回进程退出码（0=通过，1=失败）。</summary>
    public static async Task<int> RunAsync(string[] args, CancellationToken cancellationToken)
    {
        if (!args.Contains("--self-test", StringComparer.Ordinal))
        {
            return 0;
        }

        var appRoot = AppContext.BaseDirectory.TrimEnd(System.IO.Path.DirectorySeparatorChar, System.IO.Path.AltDirectorySeparatorChar);
        var manifest = LoadManifest(appRoot);
        var manifestIssues = RuntimeManifestValidator.Validate(manifest);

        var diagnostics = new RuntimeDiagnosticService(
            appRoot,
            new RuntimeResolver(appRoot, ResolveFromPath),
            new ExternalProcessRunner(),
            manifest);

        // Run 在 WPF 启动线程同步等待；自检续体不能再排回被阻塞的 Dispatcher。
        var statuses = await diagnostics.DiagnoseAsync(cancellationToken).ConfigureAwait(false);
        var missingRequired = statuses
            .Where(status => status.IsRequired && !status.IsAvailable)
            .Select(status => status.DisplayName)
            .ToArray();

        var report = new SelfTestReport(
            SchemaVersion,
            manifestIssues.Count == 0 && missingRequired.Length == 0,
            appRoot,
            manifestIssues.Count == 0,
            manifestIssues,
            statuses.Select(ToComponentReport).ToArray(),
            missingRequired);

        Console.WriteLine(JsonSerializer.Serialize(report, JsonOptions));
        return report.Success ? 0 : 1;
    }

    private static RuntimeManifest LoadManifest(string appRoot)
    {
        var candidates = new[]
        {
            System.IO.Path.Combine(appRoot, "runtime-manifest.json"),
            System.IO.Path.Combine(appRoot, "build", "runtime-manifest.json"),
            System.IO.Path.GetFullPath(System.IO.Path.Combine(appRoot, "..", "..", "..", "..", "build", "runtime-manifest.json"))
        };

        foreach (var candidate in candidates)
        {
            if (System.IO.File.Exists(candidate))
            {
                return RuntimeManifest.LoadFromFile(candidate);
            }
        }

        return RuntimeManifest.Default;
    }

    private static SelfTestComponentReport ToComponentReport(RuntimeComponentStatus status) =>
        new(
            status.Kind.ToString(),
            status.DisplayName,
            status.IsRequired,
            status.IsAvailable,
            status.Message,
            status.ResolvedPath);

    private static string? ResolveFromPath(string executableName)
    {
        var pathValue = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathValue))
        {
            return null;
        }

        foreach (var directory in pathValue.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            var candidate = System.IO.Path.Combine(directory.Trim(), executableName);
            if (System.IO.File.Exists(candidate))
            {
                return candidate;
            }

            if (OperatingSystem.IsWindows())
            {
                var withExe = candidate.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
                    ? candidate
                    : candidate + ".exe";
                if (System.IO.File.Exists(withExe))
                {
                    return withExe;
                }
            }
        }

        return null;
    }
}
