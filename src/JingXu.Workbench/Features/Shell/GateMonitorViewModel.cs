using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Projects;
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
    private TempResourceLease? _previewResource;

    partial void OnPreviewImagePathChanged(string? value)
    {
        var previous = _previewResource;
        _previewResource = string.IsNullOrWhiteSpace(value) ? null : TempResourceLease.Acquire(value);
        previous?.Dispose();
    }

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
            var previousImage = PreviewImagePath;
            IsIdle = false;
            IsLoading = true;
            HasVideoPlayback = false;
            HasStaticFrame = false;
            PreviewVideoPath = null;
            PreviewImagePath = null;
            MonitorCaption = $"正在预览 · {material.FileName}";
            MonitorHint = $"{material.ResolutionText} · {material.DurationText}";
            TryDeleteOwnedGatePreview(previousImage);
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
        try { await LoadStaticFrameCoreAsync(generation, videoPath, cancellationToken).ConfigureAwait(false); }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
            {
                if (generation != _loadGeneration) { return; }
                IsLoading = false;
                HasStaticFrame = false;
                HasVideoPlayback = false;
                PreviewImagePath = null;
                MonitorCaption = $"预览受限 · {_pendingFileName}";
                MonitorHint = $"预览失败：{ex.GetBaseException().Message}";
            });
        }
    }

    private async Task LoadStaticFrameCoreAsync(int generation, string videoPath, CancellationToken cancellationToken)
    {
        var outputDir = Path.Combine(JingXu.Workbench.Application.Projects.WorkbenchDataPaths.GetTempDirectory(), "jingxu-gate-preview");
        Directory.CreateDirectory(outputDir);
        var outputPath = Path.Combine(outputDir, $"{Guid.NewGuid():N}.jpg");
        using var pendingResource = TempResourceLease.Acquire(outputPath);

        var result = await _frameExtractor
            .ExtractFirstFrameAsync(videoPath, outputPath, cancellationToken)
            .ConfigureAwait(false);

        if (generation != _loadGeneration)
        {
            TryDeleteOwnedGatePreview(outputPath);
            return;
        }

        _uiDispatcher.Invoke(() =>
        {
            if (generation != _loadGeneration)
            {
                TryDeleteOwnedGatePreview(outputPath);
                return;
            }

            IsLoading = false;
            HasVideoPlayback = false;
            PreviewVideoPath = null;

            if (result.IsSuccess)
            {
                var previous = PreviewImagePath;
                HasStaticFrame = true;
                PreviewImagePath = result.Value;
                TryDeleteOwnedGatePreview(previous);
                MonitorCaption = $"正在预览 · {_pendingFileName}";
                MonitorHint = $"{_pendingResolution} · {_pendingDuration} · 首帧静图";
                return;
            }

            TryDeleteOwnedGatePreview(outputPath);
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
            var previousImage = PreviewImagePath;
            IsIdle = true;
            IsLoading = false;
            HasVideoPlayback = false;
            HasStaticFrame = false;
            PreviewVideoPath = null;
            PreviewImagePath = null;
            MonitorCaption = "监视器空闲";
            MonitorHint = "离线就绪 · 导入素材后在此预览画面";
            TryDeleteOwnedGatePreview(previousImage);
        });
    }

    /// <summary>只删 %TEMP%\jingxu-gate-preview 下本监视器生成的 JPEG。</summary>
    private static void TryDeleteOwnedGatePreview(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        try
        {
            var previewDirectory = Path.GetFullPath(Path.Combine(JingXu.Workbench.Application.Projects.WorkbenchDataPaths.GetTempDirectory(), "jingxu-gate-preview"))
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            var fullPath = Path.GetFullPath(path);
            if (!fullPath.StartsWith(previewDirectory, StringComparison.OrdinalIgnoreCase)
                || !string.Equals(Path.GetExtension(fullPath), ".jpg", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            if (File.Exists(fullPath))
            {
                File.Delete(fullPath);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
        {
        }
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
