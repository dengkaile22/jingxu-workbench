using System.IO;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Common;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Features.AudioLibrary;
using JingXu.Workbench.Features.Composition;
using JingXu.Workbench.Features.Downloads;
using JingXu.Workbench.Features.Overlays;
using JingXu.Workbench.Features.Queue;
using JingXu.Workbench.Features.Settings;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Features.Spider;
using JingXu.Workbench.Features.Stickers;
using JingXu.Workbench.Infrastructure.Bootstrap;
using JingXu.Workbench.Infrastructure.Downloads;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Persistence;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Rendering;
using JingXu.Workbench.Infrastructure.Runtime;
using JingXu.Workbench.Infrastructure.Spider;

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
    private readonly IExternalProcessRunner _processRunner;
    private readonly HardwareVideoEncoderSelector _encoderSelector;
    private readonly HardwareVideoProcessingSelector _processingSelector;

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
        _processRunner = new ExternalProcessRunner();
        _encoderSelector = new HardwareVideoEncoderSelector(_processRunner);
        _processingSelector = new HardwareVideoProcessingSelector(_processRunner);
        UiDispatcher = uiDispatcher ?? new WpfUiDispatcher();
        RenderCoordinator = RenderCoordinator.Create(
            renderExecutor ?? CreateDefaultRenderExecutor(),
            new InMemoryRenderQueueStore(),
            maxConcurrency: 2,
            // Post（异步）避免渲染进度回调用同步 Invoke 阻塞工作线程并挤占 UI。
            marshalToUi: action => UiDispatcher.Post(action));
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
        var overlayLibrary = new OverlayLibraryService(
            new AtomicJsonStore<OverlayLibraryDocument>(OverlayLibraryDocument.CurrentSchemaVersion));
        var stickerLibrary = new StickerLibraryService(
            new AtomicJsonStore<StickerLibraryDocument>(StickerLibraryDocument.CurrentSchemaVersion));
        var stickerTracksService = new StickerTracksService(
            new AtomicJsonStore<StickerTracksDocument>(StickerTracksDocument.CurrentSchemaVersion));
        var templateService = new TemplateService(
            new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion));
        var sequenceTemplateService = new SequenceTemplateService(
            new AtomicJsonStore<SequenceTemplateDocument>(SequenceTemplateDocument.CurrentSchemaVersion));
        var frameExtractor = new FfmpegMediaFrameExtractor(runner, resolver);
        var audioLibraryService = new AudioLibraryService(
            new AtomicJsonStore<AudioLibraryDocument>(AudioLibraryDocument.CurrentSchemaVersion));
        var audioLibrary = new AudioLibraryViewModel(
            audioLibraryService,
            mediaProbe,
            _mediaFilePicker,
            UiDispatcher);
        var overlayLayersService = new OverlayLayersService(
            new AtomicJsonStore<OverlayLayersDocument>(OverlayLayersDocument.CurrentSchemaVersion));
        var overlays = new OverlayEditorViewModel(
            _mediaFilePicker,
            _overlayState,
            _mediaProbe,
            UiDispatcher,
            overlayLayersService,
            overlayLibrary,
            frameExtractor);
        var stickers = new StickerEditorViewModel(
            stickerLibrary,
            stickerTracksService,
            _mediaFilePicker,
            UiDispatcher);
        var fileExistenceCache = new FileExistenceCache();
        var composition = new CompositionViewModel(
            _mediaProbe,
            RenderCoordinator,
            _mediaFilePicker,
            _outputFolderPicker,
            UiDispatcher,
            _overlayState,
            overlayLibrary,
            templateService,
            frameExtractor,
            sequenceTemplateService,
            stickers,
            overlays,
            audioLibraryService,
            fileExistenceCache);
        var downloader = new HttpClientVideoDownloader();
        var urlResolver = new SmartVideoUrlResolver();
        var downloads = new DownloadViewModel(downloader, urlResolver, UiDispatcher);
        var spiderService = new PythonSpiderService(runner, appRoot, FindOnPath);
        ShellViewModel? shellRef = null;
        var spider = new SpiderViewModel(spiderService, downloads, UiDispatcher, _folderLauncher, mod => shellRef?.NavigateTo(mod));
        var queue = new RenderQueueViewModel(UiDispatcher);
        queue.BindCoordinator(RenderCoordinator);
        var settings = new SettingsViewModel(
            new RuntimeDiagnosticService(appRoot, resolver, runner),
            RenderCoordinator,
            _encoderSelector,
            _processingSelector);
        // 音频库初始化后在后台加载库数据
        _ = audioLibrary.LoadAsync(CancellationToken.None);
        shellRef = new ShellViewModel(composition, overlays, stickers, downloads, spider, queue, settings, audioLibrary, _folderLauncher, frameExtractor, UiDispatcher);
        return shellRef;
    }

    /// <summary>
    /// 启动后在后台探测 GPU 编码器，避免第一次转码才排队等探针。
    /// 失败只记日志，不影响窗口显示。
    /// </summary>
    public void WarmGpuEncoderProbe() => _ = WarmGpuEncoderProbeAsync();

    private async Task WarmGpuEncoderProbeAsync()
    {
        try
        {
            var appRoot = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var resolver = new RuntimeResolver(appRoot, FindOnPath);
            var ffmpeg = resolver.Resolve("ffmpeg", userDirectory: null);
            await _encoderSelector
                .SelectAsync(ffmpeg.Path, VideoProcessingMode.Auto, CancellationToken.None)
                .ConfigureAwait(false);
        }
        catch (RuntimeToolNotFoundException)
        {
            // 没有 FFmpeg 时无法探测；设置页会提示安装运行时。
        }
        catch (Exception ex)
        {
            System.Diagnostics.Trace.TraceWarning($"启动时探测 GPU 编码器失败：{ex.GetBaseException().Message}");
        }
    }

    private IRenderExecutor CreateDefaultRenderExecutor()
    {
        var appRoot = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        return RenderInfrastructure.CreateFfmpegRenderExecutor(
            appRoot,
            runner: _processRunner,
            encoderSelector: _encoderSelector,
            processingSelector: _processingSelector);
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
