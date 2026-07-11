using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Features.Settings;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Presentation.Tests.Settings;

public static class SettingsViewModelFactory
{
    public static SettingsViewModel WithMissing(RuntimeKind kind)
    {
        var tempRoot = Path.Combine(Path.GetTempPath(), "jingxu-settings-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempRoot);
        var appRoot = Path.Combine(tempRoot, "app");
        Directory.CreateDirectory(appRoot);

        var diagnostics = new RuntimeDiagnosticService(
            appRoot,
            new RuntimeResolver(appRoot, _ => null),
            new NoOpProcessRunner(),
            RuntimeManifest.Default);

        return new SettingsViewModel(diagnostics);
    }
}

internal sealed class NoOpProcessRunner : IExternalProcessRunner
{
    public Task<IProcessResult> RunAsync(
        IProcessRequest request,
        IProgress<string>? progress,
        CancellationToken cancellationToken) =>
        Task.FromResult<IProcessResult>(new ProcessResult(0, "test version", string.Empty));
}
