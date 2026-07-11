using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Application.Subtitles;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Domain.Subtitles;
using JingXu.Workbench.Features.Subtitles;
using JingXu.Workbench.Infrastructure.Subtitles;

namespace JingXu.Workbench.Presentation.Tests.Subtitles;

public sealed class SubtitleLabViewModelTests
{
    [Fact]
    public void Burn_is_disabled_until_regions_and_timeline_are_valid()
    {
        var vm = SubtitleLabViewModelTestFactory.WithUnreviewedRegion();
        Assert.False(vm.RenderCommand.CanExecute(null));
        Assert.Contains("确认字幕区域", vm.BlockingMessage);
    }

    [Fact]
    public void Export_is_enabled_for_valid_cues_without_video()
    {
        var vm = SubtitleLabViewModelTestFactory.WithValidCuesOnly();
        Assert.True(vm.ExportSrtCommand.CanExecute(null));
    }
}

public static class SubtitleLabViewModelTestFactory
{
    public static SubtitleLabViewModel WithUnreviewedRegion()
    {
        var vm = Create();
        vm.VideoPath = @"C:\素材\video.mp4";
        vm.Cues.Add(new SubtitleCueRowViewModel(1, SubtitleCue.Create(TimeSpan.Zero, TimeSpan.FromSeconds(2), "测试")));
        vm.DetectedSegments.Add(new DetectedSubtitleSegment(
            new NormalizedRect(0.1, 0.7, 0.8, 0.2),
            TimeSpan.Zero,
            TimeSpan.FromSeconds(2),
            0.4,
            SubtitleReviewState.Unreviewed,
            RequiresReview: true));
        return vm;
    }

    public static SubtitleLabViewModel WithValidCuesOnly()
    {
        var vm = Create();
        vm.Cues.Add(new SubtitleCueRowViewModel(1, SubtitleCue.Create(TimeSpan.Zero, TimeSpan.FromSeconds(2), "测试")));
        return vm;
    }

    public static SubtitleLabViewModel Create() =>
        new(
            new SubtitleWorkflow(
                new NoOpOcr(),
                new NoOpSpeech(),
                new SubtitleCodecRegistry(),
                RenderCoordinator.Create(new NoOpExecutor(), new InMemoryRenderQueueStore(), 1),
                new NoOpProbe()),
            new NoOpProbe(),
            new RecordingSubtitlePicker(),
            new SubtitleCodecRegistry());

    private sealed class NoOpOcr : ISubtitleOcrDetector
    {
        public Task<Result<IReadOnlyList<DetectedSubtitleSegment>>> DetectAsync(
            string videoPath,
            NormalizedRect scanRegion,
            IProgress<string>? progress,
            CancellationToken cancellationToken) =>
            Task.FromResult(Result<IReadOnlyList<DetectedSubtitleSegment>>.Success([]));
    }

    private sealed class NoOpSpeech : ISpeechRecognizer
    {
        public Task<Result<IReadOnlyList<SubtitleCue>>> RecognizeAsync(
            string videoPath,
            IProgress<string>? progress,
            CancellationToken cancellationToken) =>
            Task.FromResult(Result<IReadOnlyList<SubtitleCue>>.Success([]));
    }

    private sealed class NoOpProbe : IMediaProbe
    {
        public Task<MediaInfo> ProbeAsync(string absolutePath, CancellationToken cancellationToken) =>
            Task.FromResult(new MediaInfo(
                TimeSpan.FromSeconds(10),
                1920,
                1080,
                30,
                "h264",
                "aac",
                true,
                0));
    }

    private sealed class NoOpExecutor : IRenderExecutor
    {
        public Task<RenderExecutionResult> ExecuteAsync(
            RenderJob job,
            IProgress<RenderProgress>? progress,
            CancellationToken cancellationToken) =>
            Task.FromResult(RenderExecutionResult.Success());
    }

    private sealed class RecordingSubtitlePicker : ISubtitleLabFilePicker
    {
        public string? PickVideoFile() => null;

        public string? PickSubtitleFile() => null;

        public string? PickExportSubtitlePath(string suggestedFileName) => null;

        public string? PickExportVideoPath(string suggestedFileName) => null;
    }
}
