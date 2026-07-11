using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Application.Subtitles;

/// <summary>字幕实验室用例编排：检测、识别、导入导出与烧录入队。</summary>
public sealed class SubtitleWorkflow
{
    private readonly ISubtitleOcrDetector _ocrDetector;
    private readonly ISpeechRecognizer _speechRecognizer;
    private readonly ISubtitleCodecRegistry _codecs;
    private readonly RenderCoordinator _renderCoordinator;
    private readonly IMediaProbe _mediaProbe;

    public SubtitleWorkflow(
        ISubtitleOcrDetector ocrDetector,
        ISpeechRecognizer speechRecognizer,
        ISubtitleCodecRegistry codecs,
        RenderCoordinator renderCoordinator,
        IMediaProbe mediaProbe)
    {
        _ocrDetector = ocrDetector;
        _speechRecognizer = speechRecognizer;
        _codecs = codecs;
        _renderCoordinator = renderCoordinator;
        _mediaProbe = mediaProbe;
    }

    /// <summary>测试钩子：记录自动检测阶段顺序。</summary>
    public IList<string> Trace { get; } = new List<string>();

    /// <summary>自动 OCR 检测字幕区域。</summary>
    public async Task<Result<IReadOnlyList<DetectedSubtitleSegment>>> DetectAsync(
        string videoPath,
        NormalizedRect scanRegion,
        IProgress<SubtitleWorkflowProgress>? progress,
        CancellationToken cancellationToken)
    {
        Trace.Clear();
        Trace.Add("extract");
        progress?.Report(new SubtitleWorkflowProgress("extract", "正在抽帧…", 0.1));

        Trace.Add("ocr");
        progress?.Report(new SubtitleWorkflowProgress("ocr", "正在 OCR 识别…", 0.45));

        IProgress<string>? ocrProgress = progress is null
            ? null
            : new Progress<string>(message =>
                progress.Report(new SubtitleWorkflowProgress("ocr", message, 0.6)));

        var ocrResult = await _ocrDetector
            .DetectAsync(videoPath, scanRegion, ocrProgress, cancellationToken)
            .ConfigureAwait(false);
        if (!ocrResult.IsSuccess)
        {
            return Result<IReadOnlyList<DetectedSubtitleSegment>>.Failure(ocrResult.Error!);
        }

        Trace.Add("cluster");
        progress?.Report(new SubtitleWorkflowProgress("cluster", "正在聚类字幕区域…", 0.85));

        return Result<IReadOnlyList<DetectedSubtitleSegment>>.Success(ocrResult.Value!);
    }

    /// <summary>Whisper 语音识别生成字幕草稿。</summary>
    public Task<Result<IReadOnlyList<SubtitleCue>>> TranscribeAsync(
        string videoPath,
        IProgress<string>? progress,
        CancellationToken cancellationToken) =>
        _speechRecognizer.RecognizeAsync(videoPath, progress, cancellationToken);

    /// <summary>从文件导入字幕。</summary>
    public Result<IReadOnlyList<SubtitleCue>> ImportFromFile(string path)
    {
        if (!File.Exists(path))
        {
            return Result<IReadOnlyList<SubtitleCue>>.Failure("字幕文件不存在。");
        }

        try
        {
            var content = File.ReadAllText(path);
            var codec = _codecs.ResolveByPath(path);
            return Result<IReadOnlyList<SubtitleCue>>.Success(codec.Read(content, path));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidOperationException)
        {
            return Result<IReadOnlyList<SubtitleCue>>.Failure($"无法读取字幕文件：{ex.Message}");
        }
    }

    /// <summary>导出字幕到文件。</summary>
    public Result<Unit> ExportToFile(
        IReadOnlyList<SubtitleCue> cues,
        string path,
        SubtitleFileFormat format,
        SubtitleStyle? style = null)
    {
        ArgumentNullException.ThrowIfNull(cues);
        if (string.IsNullOrWhiteSpace(path))
        {
            return Result<Unit>.Failure("请指定导出路径。");
        }

        var issues = SubtitleTimeline.Validate(cues);
        if (issues.Count > 0)
        {
            return Result<Unit>.Failure($"字幕时间轴无效：{issues[0].Message}");
        }

        try
        {
            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrWhiteSpace(directory))
            {
                Directory.CreateDirectory(directory);
            }

            var codec = _codecs.GetCodec(format);
            File.WriteAllText(path, codec.Write(cues, style));
            return Result<Unit>.Success(default);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Result<Unit>.Failure($"无法写入字幕文件：{ex.Message}");
        }
    }

    /// <summary>将字幕烧录任务加入渲染队列。</summary>
    public async Task<Result<RenderJob>> EnqueueBurnAsync(
        SubtitleBurnInPlan plan,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(plan);

        if (!File.Exists(plan.InputVideoPath))
        {
            return Result<RenderJob>.Failure("输入视频不存在。");
        }

        if (!File.Exists(plan.SubtitleFilePath))
        {
            return Result<RenderJob>.Failure("字幕文件不存在。");
        }

        var info = await _mediaProbe.ProbeAsync(plan.InputVideoPath, cancellationToken).ConfigureAwait(false);
        var asset = new MediaAsset(Guid.NewGuid(), plan.InputVideoPath, null, info);
        var singleClipPlan = new CompositionPlan(
            [new PlannedClip(asset, TimeSpan.Zero, info.Duration)],
            info.Duration,
            Seed: 0,
            TransitionDuration: TimeSpan.Zero);

        var request = new RenderRequest(
            singleClipPlan,
            plan.OutputPath,
            RenderProfile.For(QualityPreset.Balanced),
            OutputAspect.InheritFirst,
            [],
            HasSubtitles: true,
            SubtitleBurn: plan with { FrameWidth = info.Width, FrameHeight = info.Height });

        var job = RenderJob.CreateQueued(request);
        await _renderCoordinator.EnqueueAsync([job], cancellationToken).ConfigureAwait(false);
        return Result<RenderJob>.Success(job);
    }
}
