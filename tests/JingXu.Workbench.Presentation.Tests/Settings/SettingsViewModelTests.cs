using JingXu.Workbench.Features.Settings;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Presentation.Tests.Settings;

public sealed class SettingsViewModelTests
{
    [Fact]
    public async Task Runtime_check_reports_actionable_chinese_status()
    {
        var vm = SettingsViewModelFactory.WithMissing(RuntimeKind.Tesseract);
        await vm.RefreshRuntimeStatusCommand.ExecuteAsync(null);

        var tesseract = vm.RuntimeStatuses.Single(x => x.Kind == RuntimeKind.Tesseract);
        Assert.Contains("未找到 Tesseract", tesseract.Message, StringComparison.Ordinal);
        Assert.False(string.IsNullOrWhiteSpace(tesseract.SuggestedAction));
    }

    [Fact]
    public async Task Refresh_populates_all_manifest_components()
    {
        var vm = SettingsViewModelFactory.WithMissing(RuntimeKind.Ffmpeg);
        await vm.RefreshRuntimeStatusCommand.ExecuteAsync(null);

        Assert.Contains(vm.RuntimeStatuses, x => x.Kind == RuntimeKind.Ffmpeg);
        Assert.Contains(vm.RuntimeStatuses, x => x.Kind == RuntimeKind.Ffprobe);
        Assert.Contains(vm.RuntimeStatuses, x => x.Kind == RuntimeKind.Tesseract);
    }
}
