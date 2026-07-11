using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Features.Composition;
using JingXu.Workbench.Infrastructure.Persistence;
using JingXu.Workbench.Presentation.Tests.Infrastructure;

namespace JingXu.Workbench.Presentation.Tests.Composition;

public static class CompositionViewModelTestFactory
{
    public static CompositionViewModel Create(
        RenderCoordinator? coordinator = null,
        IMediaProbe? probe = null,
        IOutputFolderPicker? outputFolderPicker = null,
        OverlayWorkbenchState? overlayState = null,
        OverlayLibraryService? overlayLibraryService = null,
        TemplateService? templateService = null) =>
        new(
            probe ?? FakeMediaProbe.ForSixClips(),
            coordinator ?? RenderCoordinator.Create(
                new NoOpRenderExecutor(),
                new InMemoryRenderQueueStore(),
                maxConcurrency: 1),
            new RecordingMediaFilePicker(),
            outputFolderPicker ?? new RecordingOutputFolderPicker(),
            new DirectUiDispatcher(),
            overlayState ?? new OverlayWorkbenchState(),
            overlayLibraryService ?? CreateOverlayLibraryService(),
            templateService ?? CreateTemplateService());

    public static CompositionViewModel LoadedComposition(
        OverlayWorkbenchState? overlayState = null,
        OverlayLibraryService? overlayLibraryService = null,
        TemplateService? templateService = null)
    {
        var vm = Create(
            probe: FakeMediaProbe.ForSixClips(),
            overlayState: overlayState,
            overlayLibraryService: overlayLibraryService,
            templateService: templateService);
        vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips).GetAwaiter().GetResult();
        return vm;
    }

    public static async Task<CompositionViewModel> LoadedCompositionAsync(
        OverlayWorkbenchState? overlayState = null,
        OverlayLibraryService? overlayLibraryService = null,
        TemplateService? templateService = null)
    {
        var vm = Create(
            probe: FakeMediaProbe.ForSixClips(),
            overlayState: overlayState,
            overlayLibraryService: overlayLibraryService,
            templateService: templateService);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips).ConfigureAwait(false);
        return vm;
    }

    public static OverlayLibraryService CreateOverlayLibraryService(string? libraryPath = null)
    {
        var path = libraryPath ?? Path.Combine(
            Path.GetTempPath(),
            "jingxu-overlay-lib-" + Guid.NewGuid().ToString("N"),
            "overlay-library.json");

        return new OverlayLibraryService(
            new AtomicJsonStore<OverlayLibraryDocument>(OverlayLibraryDocument.CurrentSchemaVersion),
            path);
    }

    public static TemplateService CreateTemplateService(string? templatePath = null)
    {
        var path = templatePath ?? Path.Combine(
            Path.GetTempPath(),
            "jingxu-effect-tpl-" + Guid.NewGuid().ToString("N"),
            "effect-templates.json");

        return new TemplateService(
            new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion),
            path);
    }

    public static async Task SeedLibraryAsync(
        OverlayLibraryService service,
        params string[] filePaths)
    {
        var entries = filePaths
            .Select(path => new OverlayLibraryEntry(Guid.NewGuid(), path, [], null, null))
            .ToArray();
        await service.SaveAsync(new OverlayLibraryDocument { Entries = entries }).ConfigureAwait(false);
    }
}

public static class CompositionTestPaths
{
    public static IReadOnlyList<string> SixClips { get; } =
    [
        @"C:\素材\商品_片段_1.mp4",
        @"C:\素材\商品_片段_2.mp4",
        @"C:\素材\商品_片段_3.mp4",
        @"C:\素材\商品_片段_4.mp4",
        @"C:\素材\商品_片段_5.mp4",
        @"C:\素材\商品_片段_6.mp4"
    ];
}

public sealed class FakeMediaProbe : IMediaProbe
{
    private readonly Func<string, MediaInfo> _factory;

    private FakeMediaProbe(Func<string, MediaInfo> factory) => _factory = factory;

    public static FakeMediaProbe ForSixClips(TimeSpan? durationPerClip = null)
    {
        var duration = durationPerClip ?? TimeSpan.FromSeconds(30);
        return new FakeMediaProbe(_ => new MediaInfo(
            duration,
            Width: 1080,
            Height: 1920,
            FrameRate: 30,
            VideoCodec: "h264",
            AudioCodec: "aac",
            HasAudio: true,
            RotationDegrees: 0));
    }

    public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
        Task.FromResult(_factory(absolutePath));
}

public sealed class RecordingMediaFilePicker : IMediaFilePicker
{
    public IReadOnlyList<string>? NextPick { get; set; }

    public string? NextAudioPick { get; set; }

    public string? NextImagePick { get; set; }

    public string? LastVideoDialogTitle { get; private set; }

    public IReadOnlyList<string>? PickVideoFiles(string? dialogTitle = null)
    {
        LastVideoDialogTitle = dialogTitle;
        return NextPick;
    }

    public string? PickAudioFile() => NextAudioPick;

    public string? PickImageFile() => NextImagePick;
}

public sealed class RecordingOutputFolderPicker : IOutputFolderPicker
{
    public string? NextPick { get; set; }

    public string? PickOutputFolder() => NextPick;
}

public sealed class FailingMediaProbe(string mediaPath, string message) : IMediaProbe
{
    public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
        Task.FromException<MediaInfo>(new MediaProbeException(mediaPath, message));
}

/// <summary>固定返回指定 MediaInfo 的探测桩。</summary>
public sealed class FixedInfoMediaProbe(MediaInfo info) : IMediaProbe
{
    public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
        Task.FromResult(info);
}

/// <summary>抛出非 MediaProbeException，验证编排层兜底。</summary>
public sealed class CrashingMediaProbe : IMediaProbe
{
    public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
        Task.FromException<MediaInfo>(new InvalidOperationException("模拟探测链路崩溃"));
}
