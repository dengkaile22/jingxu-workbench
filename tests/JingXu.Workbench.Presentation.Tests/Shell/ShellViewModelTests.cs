using System;
using System.Linq;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Features.Shell;

using JingXu.Workbench.Presentation.Tests.Composition;

namespace JingXu.Workbench.Presentation.Tests.Shell;

public sealed class ShellViewModelTests
{
    [Fact]
    public void Navigation_changes_module_and_preserves_module_instance()
    {
        var shell = ShellViewModelTestFactory.Create();

        shell.NavigateCommand.Execute(WorkspaceModule.Queue);
        var queue = shell.CurrentModule;

        shell.NavigateCommand.Execute(WorkspaceModule.Settings);
        Assert.NotSame(queue, shell.CurrentModule);

        // 再次导航回队列应返回同一缓存实例（保留模块状态）。
        shell.NavigateCommand.Execute(WorkspaceModule.Queue);
        Assert.Same(queue, shell.CurrentModule);
    }

    [Fact]
    public void Navigating_to_disabled_module_is_ignored()
    {
        var shell = ShellViewModelTestFactory.Create();
        shell.NavigateCommand.Execute(WorkspaceModule.Settings);
        var current = shell.CurrentModule;

        shell.NavigateCommand.Execute((WorkspaceModule)999);

        Assert.Same(current, shell.CurrentModule);
        Assert.Equal(WorkspaceModule.Settings, shell.CurrentModule.ModuleKind);
    }

    [Fact]
    public void Default_current_module_is_an_enabled_module()
    {
        var shell = ShellViewModelTestFactory.Create();
        var tab = shell.Modules.Single(m => m.ModuleKind == shell.CurrentModule.ModuleKind);
        Assert.True(tab.IsEnabled);
        Assert.Equal(WorkspaceModule.Composition, shell.CurrentModule.ModuleKind);
    }

    [Fact]
    public void Rail_lists_all_five_modules_with_composition_queue_and_settings_enabled()
    {
        var shell = ShellViewModelTestFactory.Create();

        Assert.Equal(
            [
                WorkspaceModule.Composition, WorkspaceModule.Overlays, WorkspaceModule.Subtitles,
                WorkspaceModule.Queue, WorkspaceModule.Settings
            ],
            shell.Modules.Select(m => m.ModuleKind));

        var enabled = shell.Modules.Where(m => m.IsEnabled).Select(m => m.ModuleKind).ToArray();
        Assert.Equal(
            [
                WorkspaceModule.Composition, WorkspaceModule.Overlays, WorkspaceModule.Subtitles,
                WorkspaceModule.Queue, WorkspaceModule.Settings
            ],
            enabled);
    }

    [Fact]
    public void Navigation_to_overlays_preserves_module_instance()
    {
        var shell = ShellViewModelTestFactory.Create();
        shell.NavigateCommand.Execute(WorkspaceModule.Overlays);
        var overlays = shell.CurrentModule;
        shell.NavigateCommand.Execute(WorkspaceModule.Composition);
        shell.NavigateCommand.Execute(WorkspaceModule.Overlays);
        Assert.Same(overlays, shell.CurrentModule);
        Assert.Same(shell.OverlayModule, shell.CurrentModule);
    }

    [Fact]
    public void Every_rail_tab_has_label_icon_and_automation_name()
    {
        var shell = ShellViewModelTestFactory.Create();
        Assert.All(shell.Modules, tab =>
        {
            Assert.False(string.IsNullOrWhiteSpace(tab.Label));
            Assert.False(string.IsNullOrWhiteSpace(tab.IconKey));
            Assert.False(string.IsNullOrWhiteSpace(tab.AutomationName));
        });
    }

    [Fact]
    public void Selected_module_property_drives_navigation_for_enabled_modules()
    {
        var shell = ShellViewModelTestFactory.Create();
        shell.SelectedModule = WorkspaceModule.Settings;
        Assert.Equal(WorkspaceModule.Settings, shell.CurrentModule.ModuleKind);
    }

    [Fact]
    public void Toggle_commands_flip_collapse_state()
    {
        var shell = ShellViewModelTestFactory.Create();

        Assert.True(shell.IsQueueExpanded);
        shell.ToggleQueueCommand.Execute(null);
        Assert.False(shell.IsQueueExpanded);

        Assert.True(shell.IsInspectorExpanded);
        shell.ToggleInspectorCommand.Execute(null);
        Assert.False(shell.IsInspectorExpanded);
    }

    [Fact]
    public async Task Import_auto_selects_first_valid_material_for_monitor_preview()
    {
        var shell = ShellViewModelTestFactory.Create();
        var vm = shell.CompositionModule;

        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        Assert.NotNull(vm.SelectedMaterial);
        Assert.Equal("商品_片段_1.mp4", vm.SelectedMaterial!.FileName);
        Assert.Contains("商品_片段_1.mp4", shell.Monitor.MonitorCaption);
        Assert.False(shell.Monitor.IsIdle);
    }

    [Fact]
    public async Task Selecting_material_updates_monitor_caption()
    {
        var shell = ShellViewModelTestFactory.Create();
        var vm = shell.CompositionModule;
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.SelectMaterialCommand.Execute(vm.Materials[2]);

        Assert.Equal(vm.Materials[2], vm.SelectedMaterial);
        Assert.Contains("商品_片段_3.mp4", shell.Monitor.MonitorCaption);
    }

    [Fact]
    public void Open_data_directory_command_invokes_launcher_with_data_directory()
    {
        var shell = ShellViewModelTestFactory.Create(out var launcher);
        shell.OpenDataDirectoryCommand.Execute(null);
        Assert.Single(launcher.Opened);
        Assert.Equal(shell.DataDirectory, launcher.Opened[0]);
    }

    [Fact]
    public void Every_status_exposes_text_icon_and_automation_name()
    {
        foreach (var state in Enum.GetValues<JobState>())
        {
            var status = StatusPresentation.For(state);
            Assert.False(string.IsNullOrWhiteSpace(status.Text));
            Assert.False(string.IsNullOrWhiteSpace(status.IconKey));
            Assert.False(string.IsNullOrWhiteSpace(status.AutomationName));
        }
    }

    [Fact]
    public void Every_status_exposes_fill_and_text_brush_keys()
    {
        foreach (var state in Enum.GetValues<JobState>())
        {
            var status = StatusPresentation.For(state);
            Assert.False(string.IsNullOrWhiteSpace(status.FillKey));
            Assert.False(string.IsNullOrWhiteSpace(status.TextKey));
        }
    }
}
