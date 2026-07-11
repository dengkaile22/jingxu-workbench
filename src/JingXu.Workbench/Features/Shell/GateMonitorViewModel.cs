using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Features.Composition;

namespace JingXu.Workbench.Features.Shell;

/// <summary>中央取景井监视器：素材选中后展示视频或首帧静图预览。</summary>
public sealed partial class GateMonitorViewModel : ObservableObject
{
    private readonly IMediaFrameExtractor _frameExtractor;
    private readonly IUiDispatcher _uiDispatcher;
    private int _loadGeneration;
    private string? _pendingVideoPath;
    private string? _pendingFileName;
    private string? _pendingResolution;
    private string? _pendingDuration;

    public GateMonitorViewModel(IMediaFrameExtractor frameExtractor, IUiDispatcher uiDispatcher)
    {
        _frameExtractor = frameExtractor;
        _uiDispatcher = uiDispatcher;
    }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowIdleChrome))]
    [NotifyPropertyChangedFor(nameof(ShowPreviewContent))]
    private bool _isIdle = true;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowPreviewContent))]
    private bool _isLoading;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowPreviewContent))]
    private bool _hasVideoPlayback;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowPreviewContent))]
    private bool _hasStaticFrame;

    [ObservableProperty]
    private string _monitorCaption = "监视器空闲";

    [ObservableProperty]
    private string _monitorHint = "离线就绪 · 导入素材后在此预览画面";

    [ObservableProperty]
    private string? _previewVideoPath;

    [ObservableProperty]
    private string? _previewImagePath;

    public bool ShowIdleChrome => IsIdle && !IsLoading;

    public bool ShowPreviewContent => !IsIdle && (IsLoading || HasVideoPlayback || HasStaticFrame);

    public async Task LoadFromMaterialAsync(MaterialRowViewModel? material, CancellationToken cancellationToken = default)
    {
        var generation = Interlocked.Increment(ref _loadGeneration);

        if (material is null || !material.HasValidAsset)
        {
            ResetIdle();
            return;
        }

        _uiDispatcher.Invoke(() =>
        {
            IsIdle = false;
            IsLoading = true;
            HasVideoPlayback = false;
            HasStaticFrame = false;
            PreviewVideoPath = null;
            PreviewImagePath = null;
            MonitorCaption = $"正在预览 · {material.FileName}";
            MonitorHint = $"{material.ResolutionText} · {material.DurationText}";
        });

        _pendingVideoPath = material.SourcePath;
        _pendingFileName = material.FileName;
        _pendingResolution = material.ResolutionText;
        _pendingDuration = material.DurationText;

        if (ShouldPreferStaticFrame(material.VideoCodec, material.SourcePath))
        {
            await LoadStaticFrameAsync(generation, material.SourcePath, cancellationToken).ConfigureAwait(false);
            return;
        }

        _uiDispatcher.Invoke(() =>
        {
            if (generation != _loadGeneration)
            {
                return;
            }

            IsLoading = false;
            HasVideoPlayback = true;
            PreviewVideoPath = material.SourcePath;
            MonitorCaption = $"正在预览 · {material.FileName}";
            MonitorHint = $"{material.ResolutionText} · {material.DurationText} · 视频播放";
        });
    }

    [RelayCommand]
    private async Task ReportPlaybackFailedAsync()
    {
        var generation = _loadGeneration;
        var path = _pendingVideoPath;
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        _uiDispatcher.Invoke(() =>
        {
            HasVideoPlayback = false;
            PreviewVideoPath = null;
            IsLoading = true;
            MonitorHint = "视频解码失败，正在抽取首帧静图…";
        });

        await LoadStaticFrameAsync(generation, path, CancellationToken.None).ConfigureAwait(false);
    }

    private async Task LoadStaticFrameAsync(int generation, string videoPath, CancellationToken cancellationToken)
    {
        var outputDir = Path.Combine(Path.GetTempPath(), "jingxu-gate-preview");
        Directory.CreateDirectory(outputDir);
        var outputPath = Path.Combine(outputDir, $"{Guid.NewGuid():N}.jpg");

        var result = await _frameExtractor
            .ExtractFirstFrameAsync(videoPath, outputPath, cancellationToken)
            .ConfigureAwait(false);

        _uiDispatcher.Invoke(() =>
        {
            if (generation != _loadGeneration)
            {
                return;
            }

            IsLoading = false;
            HasVideoPlayback = false;
            PreviewVideoPath = null;

            if (result.IsSuccess)
            {
                HasStaticFrame = true;
                PreviewImagePath = result.Value;
                MonitorCaption = $"正在预览 · {_pendingFileName}";
                MonitorHint = $"{_pendingResolution} · {_pendingDuration} · 首帧静图";
                return;
            }

            HasStaticFrame = false;
            PreviewImagePath = null;
            MonitorCaption = $"预览受限 · {_pendingFileName}";
            MonitorHint = result.Error ?? "无法生成预览画面。";
        });
    }

    private void ResetIdle()
    {
        Interlocked.Increment(ref _loadGeneration);
        _pendingVideoPath = null;
        _pendingFileName = null;
        _pendingResolution = null;
        _pendingDuration = null;

        _uiDispatcher.Invoke(() =>
        {
            IsIdle = true;
            IsLoading = false;
            HasVideoPlayback = false;
            HasStaticFrame = false;
            PreviewVideoPath = null;
            PreviewImagePath = null;
            MonitorCaption = "监视器空闲";
            MonitorHint = "离线就绪 · 导入素材后在此预览画面";
        });
    }

    private static bool ShouldPreferStaticFrame(string? videoCodec, string sourcePath)
    {
        // MediaElement / Media Foundation 对非 ASCII 路径与 HEVC 支持不可靠，优先走 FFmpeg 首帧。
        if (sourcePath.Any(static c => c > 127))
        {
            return true;
        }

        if (string.IsNullOrWhiteSpace(videoCodec))
        {
            return false;
        }

        return videoCodec.Contains("hevc", StringComparison.OrdinalIgnoreCase)
            || videoCodec.Contains("h265", StringComparison.OrdinalIgnoreCase)
            || videoCodec.Contains("av1", StringComparison.OrdinalIgnoreCase)
            || videoCodec.Contains("vp9", StringComparison.OrdinalIgnoreCase);
    }
}
