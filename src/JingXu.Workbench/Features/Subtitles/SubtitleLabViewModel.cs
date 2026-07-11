using System.Collections.ObjectModel;
using System.IO;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Application.Subtitles;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Subtitles;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Infrastructure.Subtitles;

namespace JingXu.Workbench.Features.Subtitles;

/// <summary>字幕实验室模块视图模型。</summary>
public sealed partial class SubtitleLabViewModel : WorkspaceModuleViewModel
{
    private readonly SubtitleWorkflow _workflow;
    private readonly IMediaProbe _mediaProbe;
    private readonly ISubtitleLabFilePicker _filePicker;
    private MediaInfo? _videoInfo;
    private PreviewCoordinateMapper? _mapper;

    public SubtitleLabViewModel(
        SubtitleWorkflow workflow,
        IMediaProbe mediaProbe,
        ISubtitleLabFilePicker filePicker,
        ISubtitleCodecRegistry codecs)
    {
        _workflow = workflow;
        _mediaProbe = mediaProbe;
        _filePicker = filePicker;
        _ = codecs;
    }

    public override WorkspaceModule ModuleKind => WorkspaceModule.Subtitles;

    public override string Title => "字幕实验室";

    public ObservableCollection<SubtitleCueRowViewModel> Cues { get; } = [];

    public ObservableCollection<DetectedSubtitleSegment> DetectedSegments { get; } = [];

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RenderCommand))]
    [NotifyCanExecuteChangedFor(nameof(ExportSrtCommand))]
    [NotifyPropertyChangedFor(nameof(HasVideo))]
    [NotifyPropertyChangedFor(nameof(BlockingMessage))]
    [NotifyPropertyChangedFor(nameof(PreviewHint))]
    private string _videoPath = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasStatusMessage))]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RenderCommand))]
    [NotifyPropertyChangedFor(nameof(BlockingMessage))]
    private SubtitleRemovalMode _removalMode = SubtitleRemovalMode.Blur;

    [ObservableProperty]
    private bool _isBusy;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ScanRegionDescription))]
    private bool _scanFullFrame;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasSelectionOverlay))]
    private NormalizedRect? _manualRegion;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasSelectionOverlay))]
    private Rect _selectionOverlayRect;

    public bool HasVideo => !string.IsNullOrWhiteSpace(VideoPath);

    public bool HasStatusMessage => !string.IsNullOrWhiteSpace(StatusMessage);

    public bool HasSelectionOverlay => !SelectionOverlayRect.IsEmpty;

    public string ScanRegionDescription => ScanFullFrame ? "全画面扫描" : "下方 45% 扫描";

    public string PreviewHint => HasVideo
        ? "在预览区拖拽框选字幕区域；OCR 检测后可在此确认或调整。"
        : "导入视频后在此预览并框选字幕区域。";

    public string BlockingMessage
    {
        get
        {
            if (!HasVideo)
            {
                return "请先导入视频。";
            }

            if (Cues.Count == 0)
            {
                return "请导入或编辑至少一条字幕。";
            }

            var issues = SubtitleTimeline.Validate(Cues.Select(x => x.ToCue()).ToArray());
            if (issues.Count > 0)
            {
                return $"字幕时间轴无效：{issues[0].Message}";
            }

            if (SubtitleTimeline.HasBlockingUnreviewedSegments(DetectedSegments.ToArray()))
            {
                return "请先确认字幕区域后再烧录。";
            }

            return string.Empty;
        }
    }

    partial void OnVideoPathChanged(string value) => _ = RefreshVideoInfoAsync();

    [RelayCommand]
    private void PickVideo()
    {
        var path = _filePicker.PickVideoFile();
        if (!string.IsNullOrWhiteSpace(path))
        {
            VideoPath = path;
            StatusMessage = $"已选择视频：{Path.GetFileName(path)}";
        }
    }

    [RelayCommand]
    private void ImportSubtitle()
    {
        var path = _filePicker.PickSubtitleFile();
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        var result = _workflow.ImportFromFile(path);
        if (!result.IsSuccess)
        {
            StatusMessage = result.Error!;
            return;
        }

        ReplaceCues(result.Value!);
        StatusMessage = $"已导入 {Cues.Count} 条字幕。";
        NotifyBlockingChanged();
    }

    [RelayCommand(CanExecute = nameof(CanExport))]
    private void ExportSrt()
    {
        var path = _filePicker.PickExportSubtitlePath(
            string.IsNullOrWhiteSpace(VideoPath) ? "字幕.srt" : $"{Path.GetFileNameWithoutExtension(VideoPath)}.srt");
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        var format = Path.GetExtension(path).Equals(".ass", StringComparison.OrdinalIgnoreCase)
            ? SubtitleFileFormat.Ass
            : SubtitleFileFormat.Srt;
        var result = _workflow.ExportToFile(Cues.Select(x => x.ToCue()).ToArray(), path, format);
        StatusMessage = result.IsSuccess ? $"已导出到 {path}" : result.Error!;
    }

    private bool CanExport() =>
        Cues.Count > 0 && SubtitleTimeline.Validate(Cues.Select(x => x.ToCue()).ToArray()).Count == 0;

    [RelayCommand]
    private void AddCue()
    {
        var index = Cues.Count + 1;
        Cues.Add(new SubtitleCueRowViewModel(index, SubtitleCue.Create(TimeSpan.Zero, TimeSpan.FromSeconds(2), "新字幕")));
        NotifyBlockingChanged();
    }

    [RelayCommand]
    private void RemoveSelectedCue(SubtitleCueRowViewModel? row)
    {
        if (row is null)
        {
            return;
        }

        Cues.Remove(row);
        ReindexCues();
        NotifyBlockingChanged();
    }

    [RelayCommand]
    private async Task DetectRegionsAsync()
    {
        if (!HasVideo)
        {
            StatusMessage = "请先导入视频。";
            return;
        }

        IsBusy = true;
        try
        {
            var scanRegion = ScanFullFrame
                ? NormalizedRect.FullFrame
                : new NormalizedRect(0, 0.55, 1, 0.45);
            var result = await _workflow.DetectAsync(
                VideoPath,
                scanRegion,
                new Progress<SubtitleWorkflowProgress>(p => StatusMessage = p.Message),
                CancellationToken.None).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                StatusMessage = result.Error!;
                return;
            }

            DetectedSegments.Clear();
            foreach (var segment in result.Value!)
            {
                DetectedSegments.Add(segment);
            }

            if (DetectedSegments.Count > 0)
            {
                UpdateSelectionOverlay(DetectedSegments[0].Region);
            }

            StatusMessage = $"自动检测完成，共 {DetectedSegments.Count} 个区域。";
            NotifyBlockingChanged();
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    private async Task TranscribeAsync()
    {
        if (!HasVideo)
        {
            StatusMessage = "请先导入视频。";
            return;
        }

        IsBusy = true;
        try
        {
            var result = await _workflow.TranscribeAsync(
                VideoPath,
                new Progress<string>(p => StatusMessage = p),
                CancellationToken.None).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                StatusMessage = result.Error!;
                return;
            }

            ReplaceCues(result.Value!);
            StatusMessage = $"Whisper 识别完成，共 {Cues.Count} 条字幕。";
            NotifyBlockingChanged();
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    private void ConfirmAllSegments()
    {
        var confirmed = DetectedSegments
            .Select(segment => segment with { State = SubtitleReviewState.Confirmed, RequiresReview = false })
            .ToArray();
        DetectedSegments.Clear();
        foreach (var segment in confirmed)
        {
            DetectedSegments.Add(segment);
        }

        NotifyBlockingChanged();
        StatusMessage = "已确认全部检测区域。";
    }

    [RelayCommand(CanExecute = nameof(CanRender))]
    private async Task RenderAsync()
    {
        var outputPath = _filePicker.PickExportVideoPath(
            string.IsNullOrWhiteSpace(VideoPath) ? "字幕成片.mp4" : $"{Path.GetFileNameWithoutExtension(VideoPath)}_字幕.mp4");
        if (string.IsNullOrWhiteSpace(outputPath))
        {
            return;
        }

        var subtitlePath = Path.Combine(
            Path.GetTempPath(),
            "jingxu-subtitle-burn",
            Guid.NewGuid().ToString("N") + ".ass");
        Directory.CreateDirectory(Path.GetDirectoryName(subtitlePath)!);
        var export = _workflow.ExportToFile(
            Cues.Select(x => x.ToCue()).ToArray(),
            subtitlePath,
            SubtitleFileFormat.Ass);
        if (!export.IsSuccess)
        {
            StatusMessage = export.Error!;
            return;
        }

        SubtitleRemovalPlan? removal = null;
        var activeRegion = ResolveActiveRegion();
        if (activeRegion is not null && _videoInfo is not null)
        {
            removal = new SubtitleRemovalPlan(RemovalMode, activeRegion.Value, _videoInfo.Width, _videoInfo.Height);
        }

        var plan = new SubtitleBurnInPlan(
            VideoPath,
            outputPath,
            subtitlePath,
            SubtitleFileFormat.Ass,
            _videoInfo?.Width ?? 1920,
            _videoInfo?.Height ?? 1080,
            removal);

        IsBusy = true;
        try
        {
            var enqueue = await _workflow.EnqueueBurnAsync(plan, CancellationToken.None).ConfigureAwait(true);
            StatusMessage = enqueue.IsSuccess
                ? "字幕烧录任务已加入队列，请在底部队列查看进度。"
                : enqueue.Error!;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private bool CanRender() => !IsBusy && string.IsNullOrWhiteSpace(BlockingMessage);

    /// <summary>预览容器尺寸变化时更新坐标映射与叠加层。</summary>
    public void UpdatePreviewLayout(double viewportWidth, double viewportHeight, double dpiScale = 1.0)
    {
        if (_mapper is null || viewportWidth <= 0 || viewportHeight <= 0)
        {
            SelectionOverlayRect = Rect.Empty;
            return;
        }

        var layout = _mapper.ComputeLayout(viewportWidth, viewportHeight, dpiScale);
        var region = ResolveActiveRegion();
        SelectionOverlayRect = region is null
            ? Rect.Empty
            : PreviewCoordinateMapper.NormalizedToViewportRect(region.Value, layout);
    }

    /// <summary>将预览区拖拽矩形转换为归一化字幕区域。</summary>
    public void ApplySelectionFromViewport(double x, double y, double width, double height, double viewportWidth, double viewportHeight, double dpiScale = 1.0)
    {
        if (_mapper is null || viewportWidth <= 0 || viewportHeight <= 0)
        {
            return;
        }

        var layout = _mapper.ComputeLayout(viewportWidth, viewportHeight, dpiScale);
        var result = PreviewCoordinateMapper.ViewportRectToNormalized(x, y, width, height, layout);
        if (!result.IsSuccess)
        {
            StatusMessage = result.Error!;
            return;
        }

        ManualRegion = result.Value;
        UpdateSelectionOverlay(result.Value!);
        StatusMessage = "已更新手动字幕区域。";
    }

    [RelayCommand]
    private void ApplyManualRegionAsDetected()
    {
        if (ManualRegion is null)
        {
            StatusMessage = "请先在预览区框选字幕区域。";
            return;
        }

        var region = ManualRegion.Value;
        DetectedSegments.Clear();
        DetectedSegments.Add(new DetectedSubtitleSegment(
            region,
            TimeSpan.Zero,
            _videoInfo?.Duration ?? TimeSpan.FromSeconds(10),
            1.0,
            SubtitleReviewState.Confirmed,
            RequiresReview: false));
        NotifyBlockingChanged();
        StatusMessage = "手动区域已确认为去字幕范围。";
    }

    private NormalizedRect? ResolveActiveRegion()
    {
        if (ManualRegion is not null)
        {
            return ManualRegion;
        }

        var confirmed = DetectedSegments.FirstOrDefault(s => s.State == SubtitleReviewState.Confirmed);
        if (confirmed is not null)
        {
            return confirmed.Region;
        }

        return DetectedSegments.Count > 0 ? DetectedSegments[0].Region : null;
    }

    private void UpdateSelectionOverlay(NormalizedRect region)
    {
        ManualRegion = region;
        OnPropertyChanged(nameof(HasSelectionOverlay));
    }

    private async Task RefreshVideoInfoAsync()
    {
        if (!HasVideo)
        {
            _videoInfo = null;
            _mapper = null;
            SelectionOverlayRect = Rect.Empty;
            return;
        }

        try
        {
            _videoInfo = await _mediaProbe.ProbeAsync(VideoPath, CancellationToken.None).ConfigureAwait(true);
            _mapper = new PreviewCoordinateMapper(
                _videoInfo.Width,
                _videoInfo.Height,
                _videoInfo.RotationDegrees);
        }
        catch (Exception)
        {
            _videoInfo = null;
            _mapper = null;
            SelectionOverlayRect = Rect.Empty;
            StatusMessage = "无法读取视频信息。";
        }
    }

    private void ReplaceCues(IReadOnlyList<SubtitleCue> cues)
    {
        Cues.Clear();
        for (var i = 0; i < cues.Count; i++)
        {
            Cues.Add(new SubtitleCueRowViewModel(i + 1, cues[i]));
        }

        NotifyBlockingChanged();
    }

    private void ReindexCues()
    {
        for (var i = 0; i < Cues.Count; i++)
        {
            var cue = Cues[i].ToCue();
            Cues[i] = new SubtitleCueRowViewModel(i + 1, cue with { Index = i + 1 });
        }
    }

    private void NotifyBlockingChanged()
    {
        OnPropertyChanged(nameof(BlockingMessage));
        RenderCommand.NotifyCanExecuteChanged();
        ExportSrtCommand.NotifyCanExecuteChanged();
    }
}
