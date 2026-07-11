using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.Infrastructure.Runtime;

/// <summary>
/// 离线检测 FFmpeg、FFprobe、Whisper 与 Tesseract 是否可用，
/// 并返回中文状态与可操作的修复建议。
/// </summary>
public sealed class RuntimeDiagnosticService
{
    private readonly string _appRoot;
    private readonly RuntimeResolver _resolver;
    private readonly IExternalProcessRunner _runner;
    private readonly RuntimeManifest _manifest;
    private readonly string? _userRuntimeDirectory;

    public RuntimeDiagnosticService(
        string appRoot,
        RuntimeResolver resolver,
        IExternalProcessRunner runner,
        RuntimeManifest? manifest = null,
        string? userRuntimeDirectory = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(appRoot);
        ArgumentNullException.ThrowIfNull(resolver);
        ArgumentNullException.ThrowIfNull(runner);

        _appRoot = appRoot;
        _resolver = resolver;
        _runner = runner;
        _manifest = manifest ?? RuntimeManifest.Default;
        _userRuntimeDirectory = userRuntimeDirectory;
    }

    /// <summary>诊断全部清单组件。</summary>
    public async Task<IReadOnlyList<RuntimeComponentStatus>> DiagnoseAsync(
        CancellationToken cancellationToken = default)
    {
        var results = new List<RuntimeComponentStatus>(_manifest.Components.Count);

        foreach (var component in _manifest.Components)
        {
            results.Add(await DiagnoseComponentAsync(component, cancellationToken).ConfigureAwait(false));
        }

        return results;
    }

    private async Task<RuntimeComponentStatus> DiagnoseComponentAsync(
        RuntimeManifestComponent component,
        CancellationToken cancellationToken)
    {
        if (component.Kind == RuntimeKind.WhisperModel)
        {
            return DiagnoseModelFile(component);
        }

        RuntimeResolution? resolution = null;
        try
        {
            resolution = ResolveExecutable(component);
        }
        catch (RuntimeToolNotFoundException)
        {
            return Missing(component);
        }

        var versionSummary = await TryReadVersionAsync(
            resolution.Path,
            component.VersionArguments,
            cancellationToken).ConfigureAwait(false);

        var sourceText = DescribeSource(resolution.Source);
        var message = string.IsNullOrWhiteSpace(versionSummary)
            ? $"{component.DisplayName} 已就绪（{sourceText}）。"
            : $"{component.DisplayName} 已就绪（{sourceText}）：{versionSummary}";

        return new RuntimeComponentStatus(
            component.Kind,
            component.DisplayName,
            IsAvailable: true,
            component.Required,
            message,
            SuggestedAction: resolution.Path,
            resolution.Path,
            resolution.Source);
    }

    private RuntimeComponentStatus DiagnoseModelFile(RuntimeManifestComponent component)
    {
        var bundled = Path.Combine(_appRoot, "runtime", component.RelativePath.Replace('/', Path.DirectorySeparatorChar));
        if (File.Exists(bundled))
        {
            return new RuntimeComponentStatus(
                component.Kind,
                component.DisplayName,
                IsAvailable: true,
                component.Required,
                $"{component.DisplayName} 已就绪（应用目录）。",
                SuggestedAction: bundled,
                bundled,
                RuntimeSource.Bundled);
        }

        return new RuntimeComponentStatus(
            component.Kind,
            component.DisplayName,
            IsAvailable: false,
            component.Required,
            $"未找到 {component.DisplayName}。",
            "请将 ggml-base.bin 放入 runtime\\whisper\\models\\，或在设置中指定模型路径。",
            ResolvedPath: null,
            Source: null);
    }

    private RuntimeResolution ResolveExecutable(RuntimeManifestComponent component) =>
        component.Kind switch
        {
            RuntimeKind.Ffmpeg => _resolver.Resolve("ffmpeg", _userRuntimeDirectory),
            RuntimeKind.Ffprobe => _resolver.Resolve("ffprobe", _userRuntimeDirectory),
            RuntimeKind.WhisperCli => _resolver.ResolveRelative(component.RelativePath, "whisper-cli", _userRuntimeDirectory),
            RuntimeKind.Tesseract => _resolver.ResolveRelative(component.RelativePath, "tesseract", _userRuntimeDirectory),
            _ => throw new InvalidOperationException($"无法解析组件：{component.Kind}")
        };

    private static RuntimeComponentStatus Missing(RuntimeManifestComponent component)
    {
        var (message, action) = component.Kind switch
        {
            RuntimeKind.Ffmpeg => (
                "未找到 FFmpeg。",
                "请将 ffmpeg.exe 与 ffprobe.exe 放入 runtime\\ffmpeg\\，在设置中指定目录，或加入系统 PATH。"),
            RuntimeKind.Ffprobe => (
                "未找到 FFprobe。",
                "请将 ffprobe.exe 放入 runtime\\ffmpeg\\，在设置中指定目录，或加入系统 PATH。"),
            RuntimeKind.WhisperCli => (
                "未找到 Whisper.cpp。",
                "请将 whisper-cli.exe 放入 runtime\\whisper\\，在设置中指定目录，或加入系统 PATH。"),
            RuntimeKind.Tesseract => (
                "未找到 Tesseract OCR。",
                "请将 tesseract.exe 放入 runtime\\tesseract\\，在设置中指定目录，或加入系统 PATH。"),
            _ => (
                $"未找到 {component.DisplayName}。",
                "请检查 runtime 目录或在设置中指定路径。")
        };

        return new RuntimeComponentStatus(
            component.Kind,
            component.DisplayName,
            IsAvailable: false,
            component.Required,
            message,
            action,
            ResolvedPath: null,
            Source: null);
    }

    private async Task<string?> TryReadVersionAsync(
        string executablePath,
        IReadOnlyList<string>? versionArguments,
        CancellationToken cancellationToken)
    {
        if (versionArguments is null || versionArguments.Count == 0)
        {
            return null;
        }

        try
        {
            var request = ProcessRequest.Create(executablePath, versionArguments);
            var result = await _runner.RunAsync(request, progress: null, cancellationToken).ConfigureAwait(false);
            var text = string.IsNullOrWhiteSpace(result.StandardOutput)
                ? result.StandardError
                : result.StandardOutput;

            return SummarizeVersion(text);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static string? SummarizeVersion(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        using var reader = new StringReader(text);
        var firstLine = reader.ReadLine()?.Trim();
        return string.IsNullOrWhiteSpace(firstLine) ? null : firstLine;
    }

    private static string DescribeSource(RuntimeSource source) =>
        source switch
        {
            RuntimeSource.Bundled => "应用目录",
            RuntimeSource.User => "用户指定目录",
            RuntimeSource.Path => "系统 PATH",
            _ => source.ToString()
        };
}
