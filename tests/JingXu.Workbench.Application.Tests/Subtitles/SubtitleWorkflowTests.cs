using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Application.Subtitles;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Domain.Subtitles;
using JingXu.Workbench.Infrastructure.Subtitles;

namespace JingXu.Workbench.Application.Tests.Subtitles;

public sealed class SubtitleWorkflowTests
{
    [Fact]
    public async Task Auto_flow_orders_extract_ocr_cluster_and_marks_results_unreviewed()
    {
        var workflow = SubtitleWorkflowTestFactory.Create();
        var result = await workflow.DetectAsync(
            "video.mp4",
            new Domain.Common.NormalizedRect(0, 0.55, 1, 0.45),
            null,
            CancellationToken.None);
        Assert.True(result.IsSuccess);
        Assert.Equal(["extract", "ocr", "cluster"], workflow.Trace);
        Assert.All(result.Value!, x => Assert.Equal(SubtitleReviewState.Unreviewed, x.State));
    }
}

public static class SubtitleWorkflowTestFactory
{
    public static SubtitleWorkflow Create() =>
        new(
            new FakeOcrDetector(),
            new FakeSpeechRecognizer(),
            new SubtitleCodecRegistry(),
            RenderCoordinator.Create(new NoOpRenderExecutor(), new InMemoryRenderQueueStore(), 1),
            new FakeMediaProbeForSubtitle());

    private sealed class FakeOcrDetector : ISubtitleOcrDetector
    {
        public Task<Result<IReadOnlyList<DetectedSubtitleSegment>>> DetectAsync(
            string videoPath,
            Domain.Common.NormalizedRect scanRegion,
            IProgress<string>? progress,
            CancellationToken cancellationToken) =>
            Task.FromResult(Result<IReadOnlyList<DetectedSubtitleSegment>>.Success(
            [
                new DetectedSubtitleSegment(
                    new Domain.Common.NormalizedRect(0.1, 0.7, 0.8, 0.2),
                    TimeSpan.Zero,
                    TimeSpan.FromSeconds(2),
                    0.9,
                    SubtitleReviewState.Unreviewed,
                    RequiresReview: true)
            ]));
    }

    private sealed class FakeSpeechRecognizer : ISpeechRecognizer
    {
        public Task<Result<IReadOnlyList<SubtitleCue>>> RecognizeAsync(
            string videoPath,
            IProgress<string>? progress,
            CancellationToken cancellationToken) =>
            Task.FromResult(Result<IReadOnlyList<SubtitleCue>>.Success(
                [SubtitleCue.Create(TimeSpan.Zero, TimeSpan.FromSeconds(1), "测试")]));
    }

    private sealed class FakeMediaProbeForSubtitle : IMediaProbe
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

    private sealed class NoOpRenderExecutor : IRenderExecutor
    {
        public Task<RenderExecutionResult> ExecuteAsync(
            RenderJob job,
            IProgress<RenderProgress>? progress,
            CancellationToken cancellationToken) =>
            Task.FromResult(RenderExecutionResult.Success());
    }
}
