using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Features.Overlays;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Persistence;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;
using JingXu.Workbench.Presentation.Tests.Infrastructure;

namespace JingXu.Workbench.Presentation.Tests.Overlays;

public sealed class OverlayEditorViewModelTests
{
    [Fact]
    public async Task Import_mask_materials_adds_free_cover_layer_and_user_can_edit_bounds()
    {
        var maskPath = CreateTempMediaPath();
        var state = new OverlayWorkbenchState();
        var library = CreateTempLibrary();
        var vm = CreateViewModel(new FakeMediaFilePicker(maskPath), state, libraryService: library);

        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        Assert.Single(vm.Layers);
        Assert.Equal(OverlayMode.FreeCover, vm.Selected!.Layer.Mode);
        Assert.True(vm.LibraryEntryCount >= 1);

        vm.BoundsX = 0.1;
        vm.BoundsY = 0.1;
        vm.BoundsWidth = 0.8;
        vm.BoundsHeight = 0.4;
        vm.ApplyBoundsCommand.Execute(null);

        Assert.Equal(new NormalizedRect(0.1, 0.1, 0.8, 0.4), vm.Selected.Bounds);
    }

    [Fact]
    public async Task Import_multiple_mask_materials_adds_all_layers()
    {
        var pathA = CreateTempMediaPath();
        var pathB = CreateTempMediaPath();
        var state = new OverlayWorkbenchState();
        var library = CreateTempLibrary();
        var vm = CreateViewModel(new FakeMediaFilePicker([pathA, pathB]), state, libraryService: library);

        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        Assert.Equal(2, vm.Layers.Count);
        Assert.Equal(2, vm.LibraryEntryCount);
        Assert.Contains("已导入 2", vm.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public void Workbench_state_snapshot_is_shared_with_composition_enqueue()
    {
        var state = new OverlayWorkbenchState();
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2));
        state.Add(layer);

        var snapshot = state.CreateSnapshot();
        Assert.Single(snapshot);
        Assert.Equal(OverlayMode.FreeCover, snapshot[0].Mode);
    }

    [Fact]
    public async Task Remove_selected_clears_layer_from_state()
    {
        var maskPath = CreateTempMediaPath();
        var state = new OverlayWorkbenchState();
        var vm = CreateViewModel(new FakeMediaFilePicker(maskPath), state);
        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);
        vm.RemoveSelectedCommand.Execute(null);
        Assert.Empty(state.Layers);
    }

    [Fact]
    public void Shape_mask_layer_from_state_preserves_ellipse_when_editing_opacity()
    {
        var state = new OverlayWorkbenchState();
        var layer = OverlayLayer.CreateShapeMask(
            @"C:\mask.mp4",
            TimeSpan.FromSeconds(2),
            new NormalizedRect(0.1, 0.1, 0.8, 0.4)) with
        {
            Shape = ShapeKind.Ellipse,
            Name = "形状 1"
        };
        state.Add(layer);

        var vm = CreateViewModel(new FakeMediaFilePicker(@"C:\mask.mp4"), state);
        vm.Opacity = 0.5;

        Assert.Equal(ShapeKind.Ellipse, state.Layers.Single().Shape);
        Assert.Equal(0.5, state.Layers.Single().Opacity);
    }

    [Fact]
    public void Shape_mask_layer_from_state_preserves_imported_png_path()
    {
        var pngPath = Path.Combine(Path.GetTempPath(), $"mask-{Guid.NewGuid():N}.png");
        File.WriteAllBytes(pngPath, [0x89, 0x50, 0x4E, 0x47]);
        try
        {
            var state = new OverlayWorkbenchState();
            var layer = OverlayLayer.CreateShapeMask(
                @"C:\mask.mp4",
                TimeSpan.FromSeconds(2),
                new NormalizedRect(0.1, 0.1, 0.8, 0.4)) with
            {
                Shape = ShapeKind.ImportedPng,
                AlphaPngPath = pngPath,
                Name = "PNG 1"
            };
            state.Add(layer);

            var vm = CreateViewModel(new FakeMediaFilePicker(@"C:\mask.mp4"), state);
            vm.Opacity = 0.7;

            Assert.Equal(ShapeKind.ImportedPng, state.Layers.Single().Shape);
            Assert.Equal(pngPath, state.Layers.Single().AlphaPngPath);
        }
        finally
        {
            File.Delete(pngPath);
        }
    }

    [Fact]
    public async Task Transform_sliders_update_layer_state_in_real_time()
    {
        var maskPath = CreateTempMediaPath();
        var state = new OverlayWorkbenchState();
        var vm = CreateViewModel(new FakeMediaFilePicker(maskPath), state);
        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        vm.Scale = 1.5;
        vm.OffsetX = 0.1;
        vm.OffsetY = -0.05;
        vm.RotationDegrees = 30;
        vm.Feather = 0.4;

        var layer = state.Layers.Single();
        Assert.Equal(1.5, layer.Scale);
        Assert.Equal(0.1, layer.OffsetX);
        Assert.Equal(-0.05, layer.OffsetY);
        Assert.Equal(30, layer.RotationDegrees);
        Assert.Equal(0.4, layer.Feather);
    }

    [Fact]
    public void Selecting_layer_loads_transform_fields()
    {
        var state = new OverlayWorkbenchState();
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2)) with
        {
            Scale = 0.8,
            OffsetX = 0.2,
            OffsetY = 0.1,
            RotationDegrees = 15,
            Feather = 0.3
        };
        state.Add(layer);

        var vm = CreateViewModel(new FakeMediaFilePicker(@"C:\mask.mp4"), state);

        Assert.Equal(0.8, vm.Scale);
        Assert.Equal(0.2, vm.OffsetX);
        Assert.Equal(0.1, vm.OffsetY);
        Assert.Equal(15, vm.RotationDegrees);
        Assert.Equal(0.3, vm.Feather);
    }

    [Fact]
    public async Task Cancelled_file_picker_does_not_show_failure_message()
    {
        var state = new OverlayWorkbenchState();
        var vm = CreateViewModel(new FakeMediaFilePicker((string?)null), state);

        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        Assert.Empty(vm.Layers);
        Assert.False(vm.HasStatusMessage);
    }

    [Fact]
    public async Task Missing_file_shows_specific_status_message()
    {
        var state = new OverlayWorkbenchState();
        var vm = CreateViewModel(new FakeMediaFilePicker(@"C:\missing-mask.mp4"), state);

        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        Assert.Empty(vm.Layers);
        Assert.Contains("不存在", vm.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Chinese_path_mask_imports_successfully()
    {
        var maskPath = ResolveZhaoyuMaskPath();
        if (maskPath is null)
        {
            Assert.Skip("未找到赵雨蒙版测试素材。");
        }

        var state = new OverlayWorkbenchState();
        var library = CreateTempLibrary();
        var vm = CreateViewModel(
            new FakeMediaFilePicker(maskPath),
            state,
            new FakeMediaProbe(TimeSpan.FromSeconds(161)),
            library);

        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        Assert.Single(vm.Layers);
        Assert.Equal(maskPath, vm.Selected!.Layer.SourcePath);
        Assert.Equal(TimeSpan.FromSeconds(161), vm.Selected.Layer.SourceDuration);
        Assert.Contains("已导入", vm.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Chinese_path_mask_imports_with_real_ffprobe()
    {
        var maskPath = ResolveZhaoyuMaskPath();
        if (maskPath is null)
        {
            Assert.Skip("未找到赵雨蒙版测试素材。");
        }

        var ffprobePath = FindOnSystemPath("ffprobe");
        if (ffprobePath is null)
        {
            Assert.Skip("本机未找到 FFprobe，跳过真实探测集成测试。");
        }

        var probe = new FfprobeMediaProbe(
            new ExternalProcessRunner(),
            new RuntimeResolver(
                Path.Combine(Path.GetTempPath(), "jingxu-overlay-probe-" + Guid.NewGuid().ToString("N")),
                name => string.Equals(name, "ffprobe.exe", StringComparison.OrdinalIgnoreCase) ? ffprobePath : null));

        var state = new OverlayWorkbenchState();
        var library = CreateTempLibrary();
        var vm = CreateViewModel(new FakeMediaFilePicker(maskPath), state, probe, library);

        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        Assert.Single(vm.Layers);
        Assert.Equal(maskPath, vm.Selected!.Layer.SourcePath);
        Assert.True(vm.Selected.Layer.SourceDuration > TimeSpan.FromSeconds(160));
        Assert.Contains("已导入", vm.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Probe_failure_shows_chinese_status_with_stderr()
    {
        var maskPath = ResolveZhaoyuMaskPath() ?? @"C:\素材\测试 (1).mp4";
        var state = new OverlayWorkbenchState();
        var probe = new ThrowingMediaProbe(new MediaProbeException(
            maskPath,
            "媒体探测失败：FFprobe 退出码 1。",
            "Invalid data found when processing input"));
        var vm = CreateViewModel(new FakeMediaFilePicker(maskPath), state, probe);

        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        Assert.Empty(vm.Layers);
        Assert.Contains("媒体探测失败", vm.StatusMessage, StringComparison.Ordinal);
        Assert.Contains("Invalid data found", vm.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Importing_second_batch_appends_layers()
    {
        var pathA = CreateTempMediaPath();
        var pathB = CreateTempMediaPath();
        var state = new OverlayWorkbenchState();
        var library = CreateTempLibrary();
        var picker = new FakeMediaFilePicker(pathA);
        var vm = CreateViewModel(picker, state, libraryService: library);

        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);
        picker.SetPaths(pathB);
        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        Assert.Equal(2, vm.Layers.Count);
        Assert.Equal(OverlayMode.FreeCover, vm.Selected!.Layer.Mode);
    }

    [Fact]
    public void Import_command_uses_mask_video_dialog_title()
    {
        Assert.Equal("选择蒙版视频素材", OverlayEditorViewModel.MaskVideoDialogTitle);
    }

    [Fact]
    public async Task Import_passes_mask_dialog_title_to_picker()
    {
        var maskPath = CreateTempMediaPath();
        var picker = new FakeMediaFilePicker(maskPath);
        var state = new OverlayWorkbenchState();
        var library = CreateTempLibrary();
        var vm = CreateViewModel(picker, state, libraryService: library);

        await vm.ImportMaskMaterialsCommand.ExecuteAsync(null);

        Assert.Equal(OverlayEditorViewModel.MaskVideoDialogTitle, picker.LastDialogTitle);
    }

    [Fact]
    public void Layer_row_uses_read_only_display_name_for_list_binding()
    {
        var layer = OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2)) with
        {
            Name = "蒙版 1"
        };
        var row = new OverlayLayerRowViewModel(layer);

        Assert.Equal("蒙版 1", row.DisplayName);
        Assert.Equal("自由覆盖", row.ModeLabel);

        foreach (var propertyName in new[]
                 {
                     nameof(OverlayLayerRowViewModel.DisplayName),
                     nameof(OverlayLayerRowViewModel.ModeLabel),
                     nameof(OverlayLayerRowViewModel.SourceFileName),
                     nameof(OverlayLayerRowViewModel.BoundsText),
                     nameof(OverlayLayerRowViewModel.TransformText),
                     nameof(OverlayLayerRowViewModel.ZIndex),
                 })
        {
            var property = typeof(OverlayLayerRowViewModel).GetProperty(propertyName);
            Assert.NotNull(property);
            Assert.True(property!.CanRead);
            Assert.False(property.CanWrite);
        }

        Assert.Null(typeof(OverlayLayerRowViewModel).GetProperty("Name"));
    }

    [Fact]
    public void Overlay_editor_view_binds_read_only_layer_row_properties_one_way()
    {
        var repoRoot = FindRepoRoot();
        var xamlPath = Path.Combine(
            repoRoot,
            "src",
            "JingXu.Workbench",
            "Features",
            "Overlays",
            "OverlayEditorView.xaml");
        var xaml = File.ReadAllText(xamlPath);

        Assert.Contains("导入蒙版素材", xaml, StringComparison.Ordinal);
        Assert.Contains("ImportMaskMaterialsCommand", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("AddFreeCoverCommand", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("AddFullFrameCommand", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("AddShapeMaskCommand", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("选择系统预制", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("{Binding Name}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding DisplayName, Mode=OneWay}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding ModeLabel, Mode=OneWay}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding ZIndex, Mode=OneWay}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding SourceFileName, Mode=OneWay}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding BoundsText, Mode=OneWay}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding TransformText, Mode=OneWay}", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("{Binding ModeLabel}", xaml.Replace("{Binding ModeLabel, Mode=OneWay}", string.Empty, StringComparison.Ordinal), StringComparison.Ordinal);
        Assert.DoesNotContain("{Binding ZIndex}", xaml.Replace("{Binding ZIndex, Mode=OneWay}", string.Empty, StringComparison.Ordinal), StringComparison.Ordinal);
    }

    private static string? ResolveZhaoyuMaskPath()
    {
        const string explicitPath =
            @"C:\Users\dengkaile\OneDrive\Desktop\project2026071001\test-assets\赵雨蒙版\赵雨 (8).mp4";
        if (File.Exists(explicitPath))
        {
            return explicitPath;
        }

        return Directory.EnumerateFiles(
                @"C:\Users\dengkaile\OneDrive\Desktop\project2026071001\test-assets",
                "*.mp4",
                SearchOption.AllDirectories)
            .FirstOrDefault(p => p.Contains("赵雨", StringComparison.Ordinal) && p.Contains("(8)", StringComparison.Ordinal));
    }

    private static string? FindOnSystemPath(string tool)
    {
        var name = OperatingSystem.IsWindows() ? tool + ".exe" : tool;
        var pathEnv = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathEnv))
        {
            return null;
        }

        foreach (var dir in pathEnv.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            var candidate = Path.Combine(dir.Trim(), name);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private static string FindRepoRoot()
    {
        var dir = AppContext.BaseDirectory;
        while (!string.IsNullOrEmpty(dir))
        {
            if (File.Exists(Path.Combine(dir, "JingXu.Workbench.sln")))
            {
                return dir;
            }

            dir = Directory.GetParent(dir)?.FullName ?? string.Empty;
        }

        throw new InvalidOperationException("无法定位仓库根目录。");
    }

    private static OverlayLibraryService CreateTempLibrary()
    {
        var path = Path.Combine(Path.GetTempPath(), $"jingxu-overlay-lib-{Guid.NewGuid():N}.json");
        return new OverlayLibraryService(
            new AtomicJsonStore<OverlayLibraryDocument>(OverlayLibraryDocument.CurrentSchemaVersion),
            path);
    }

    private static OverlayEditorViewModel CreateViewModel(
        FakeMediaFilePicker picker,
        OverlayWorkbenchState state,
        IMediaProbe? probe = null,
        OverlayLibraryService? libraryService = null) =>
        new(picker, state, probe ?? new FakeMediaProbe(), new DirectUiDispatcher(), libraryService);

    private static string CreateTempMediaPath()
    {
        var path = Path.Combine(Path.GetTempPath(), $"jingxu-mask-test-{Guid.NewGuid():N}.mp4");
        File.WriteAllBytes(path, [0]);
        return path;
    }
}

internal sealed class FakeMediaFilePicker : IMediaFilePicker
{
    private IReadOnlyList<string>? _paths;

    public FakeMediaFilePicker(string? path) =>
        _paths = path is null ? null : [path];

    public FakeMediaFilePicker(IReadOnlyList<string> paths) => _paths = paths;

    public string? ImagePath { get; init; }

    public string? LastDialogTitle { get; private set; }

    public void SetPaths(params string[] paths) => _paths = paths;

    public IReadOnlyList<string>? PickVideoFiles(string? dialogTitle = null)
    {
        LastDialogTitle = dialogTitle;
        return _paths;
    }

    public string? PickAudioFile() => _paths is { Count: > 0 } ? _paths[0] : null;

    public string? PickImageFile() => ImagePath ?? (_paths is { Count: > 0 } ? _paths[0] : null);
}

internal sealed class FakeMediaProbe : IMediaProbe
{
    private readonly TimeSpan _duration;

    public FakeMediaProbe(TimeSpan? duration = null) =>
        _duration = duration ?? TimeSpan.FromSeconds(3);

    public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
        Task.FromResult(new MediaInfo(
            _duration,
            1080,
            1920,
            30m,
            "h264",
            "aac",
            true,
            0));
}

internal sealed class ThrowingMediaProbe(Exception exception) : IMediaProbe
{
    public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
        Task.FromException<MediaInfo>(exception);
}
