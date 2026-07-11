using System.IO;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Application.Subtitles;
using JingXu.Workbench.Features.Composition;
using JingXu.Workbench.Features.Overlays;
using JingXu.Workbench.Features.Queue;
using JingXu.Workbench.Features.Settings;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Features.Subtitles;
using JingXu.Workbench.Infrastructure.Bootstrap;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Persistence;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;
using JingXu.Workbench.Infrastructure.Subtitles;

namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// 组合根：在应用启动时构建对象图。集中一处装配视图模型与服务，
/// 避免视图直接 new 依赖，便于后续里程碑接入应用/基础设施服务。
/// </summary>
public sealed class AppCompositionRoot
{
    private readonly IFolderLauncher _folderLauncher;
    private readonly IMediaProbe _mediaProbe;
    private readonly IMediaFilePicker _mediaFilePicker;
    private readonly IOutputFolderPicker _outputFolderPicker;
    private readonly OverlayWorkbenchState _overlayState;

    public AppCompositionRoot()
        : this(new ShellFolderLauncher(), CreateDefaultMediaProbe(), new WpfMediaFilePicker(), new WpfOutputFolderPicker())
    {
    }

    public AppCompositionRoot(
        IFolderLauncher folderLauncher,
        IMediaProbe? mediaProbe = null,
        IMediaFilePicker? mediaFilePicker = null,
        IOutputFolderPicker? outputFolderPicker = null,
        IRenderExecutor? renderExecutor = null,
        OverlayWorkbenchState? overlayState = null,
        IUiDispatcher? uiDispatcher = null)
    {
        _folderLauncher = folderLauncher;
        _mediaProbe = mediaProbe ?? CreateDefaultMediaProbe();
        _mediaFilePicker = mediaFilePicker ?? new WpfMediaFilePicker();
        _outputFolderPicker = outputFolderPicker ?? new WpfOutputFolderPicker();
        _overlayState = overlayState ?? new OverlayWorkbenchState();
        UiDispatcher = uiDispatcher ?? new WpfUiDispatcher();
        RenderCoordinator = RenderCoordinator.Create(
            renderExecutor ?? CreateDefaultRenderExecutor(),
            new InMemoryRenderQueueStore(),
            maxConcurrency: 1);
    }

    /// <summary>渲染协调器实例（壳层与后续模块共享）。</summary>
    public RenderCoordinator RenderCoordinator { get; }

    /// <summary>UI 线程调度器实例。</summary>
    public IUiDispatcher UiDispatcher { get; }

    /// <summary>构建壳层视图模型及其缓存的模块实例。</summary>
    public ShellViewModel CreateShell()
    {
        var appRoot = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var resolver = new RuntimeResolver(appRoot, FindOnPath);
        var runner = new ExternalProcessRunner();
        var mediaProbe = new FfprobeMediaProbe(runner, resolver);
        var codecs = new SubtitleCodecRegistry();

        var overlayLibrary = new OverlayLibraryService(
            new AtomicJsonStore<OverlayLibraryDocument>(OverlayLibraryDocument.CurrentSchemaVersion));
        var composition = new CompositionViewModel(
            _mediaProbe,
            RenderCoordinator,
            _mediaFilePicker,
            _outputFolderPicker,
            UiDispatcher,
            _overlayState,
            overlayLibrary);
        var overlays = new OverlayEditorViewModel(_mediaFilePicker, _overlayState, _mediaProbe, UiDispatcher, overlayLibrary);
        var workflow = new SubtitleWorkflow(
            new TesseractSubtitleOcrDetector(runner, resolver, mediaProbe),
            new WhisperRunner(runner, resolver, appRoot),
            codecs,
            RenderCoordinator,
            mediaProbe);
        var subtitles = new SubtitleLabViewModel(workflow, mediaProbe, new WpfSubtitleLabFilePicker(), codecs);
        var queue = new RenderQueueViewModel();
        queue.BindCoordinator(RenderCoordinator);
        var settings = new SettingsViewModel(
            new RuntimeDiagnosticService(appRoot, resolver, runner));
        var frameExtractor = new FfmpegMediaFrameExtractor(runner, resolver);
        return new ShellViewModel(composition, overlays, subtitles, queue, settings, _folderLauncher, frameExtractor, UiDispatcher);
    }

    private static IRenderExecutor CreateDefaultRenderExecutor()
    {
        var appRoot = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        return RenderInfrastructure.CreateFfmpegRenderExecutor(appRoot);
    }

    private static FfprobeMediaProbe CreateDefaultMediaProbe()
    {
        var appRoot = AppDomain.CurrentDomain.BaseDirectory;
        var resolver = new RuntimeResolver(appRoot, FindOnPath);
        return new FfprobeMediaProbe(new ExternalProcessRunner(), resolver);
    }

    private static string? FindOnPath(string executableName)
    {
        var pathValue = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathValue))
        {
            return null;
        }

        foreach (var directory in pathValue.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(directory.Trim(), executableName);
                if (File.Exists(candidate))
                {
                    return candidate;
                }

                if (OperatingSystem.IsWindows())
                {
                    var withExe = candidate.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
                        ? candidate
                        : candidate + ".exe";
                    if (File.Exists(withExe))
                    {
                        return withExe;
                    }
                }
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        return null;
    }
}
