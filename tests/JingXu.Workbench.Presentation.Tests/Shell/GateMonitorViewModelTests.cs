using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Features.Composition;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Presentation.Tests.Composition;
using JingXu.Workbench.Presentation.Tests.Infrastructure;

namespace JingXu.Workbench.Presentation.Tests.Shell;

public sealed class GateMonitorViewModelTests
{
    [Fact]
    public void Starts_in_idle_state()
    {
        var monitor = new GateMonitorViewModel(new FakeMediaFrameExtractor(), new DirectUiDispatcher());

        Assert.True(monitor.IsIdle);
        Assert.False(monitor.ShowPreviewContent);
        Assert.Equal("监视器空闲", monitor.MonitorCaption);
        Assert.Contains("导入素材后在此预览", monitor.MonitorHint);
    }

    [Fact]
    public async Task H264_material_enables_video_playback()
    {
        var monitor = new GateMonitorViewModel(new FakeMediaFrameExtractor(), new DirectUiDispatcher());
        var material = new MaterialRowViewModel(
            "片段_1.mp4",
            @"C:\素材\片段_1.mp4",
            "1",
            TimeSpan.FromSeconds(12),
            "1080×1920",
            null,
            hasValidAsset: true,
            videoCodec: "h264");

        await monitor.LoadFromMaterialAsync(material);

        Assert.False(monitor.IsIdle);
        Assert.True(monitor.HasVideoPlayback);
        Assert.False(monitor.HasStaticFrame);
        Assert.Equal(@"C:\素材\片段_1.mp4", monitor.PreviewVideoPath);
        Assert.Contains("片段_1.mp4", monitor.MonitorCaption);
        Assert.Contains("视频播放", monitor.MonitorHint);
    }

    [Fact]
    public async Task Hevc_material_uses_static_frame_extractor()
    {
        var extractor = new FakeMediaFrameExtractor(@"C:\temp\frame.jpg");
        var monitor = new GateMonitorViewModel(extractor, new DirectUiDispatcher());
        var material = new MaterialRowViewModel(
            "微信素材.mp4",
            @"C:\xwechat\clip.mp4",
            "—",
            TimeSpan.FromSeconds(8),
            "720×960",
            "未找到数字序号",
            hasValidAsset: true,
            videoCodec: "hevc");

        await monitor.LoadFromMaterialAsync(material);

        Assert.False(monitor.IsIdle);
        Assert.False(monitor.HasVideoPlayback);
        Assert.True(monitor.HasStaticFrame);
        Assert.Equal(@"C:\temp\frame.jpg", monitor.PreviewImagePath);
        Assert.Contains("首帧静图", monitor.MonitorHint);
        Assert.Equal(@"C:\xwechat\clip.mp4", extractor.LastVideoPath);
    }

    [Fact]
    public async Task Playback_failure_falls_back_to_static_frame()
    {
        var extractor = new FakeMediaFrameExtractor(@"C:\temp\fallback.jpg");
        var monitor = new GateMonitorViewModel(extractor, new DirectUiDispatcher());
        var material = new MaterialRowViewModel(
            "片段_2.mp4",
            @"C:\素材\片段_2.mp4",
            "2",
            TimeSpan.FromSeconds(20),
            "1080×1920",
            null,
            hasValidAsset: true,
            videoCodec: "h264");

        await monitor.LoadFromMaterialAsync(material);
        await monitor.ReportPlaybackFailedCommand.ExecuteAsync(null);

        Assert.False(monitor.HasVideoPlayback);
        Assert.True(monitor.HasStaticFrame);
        Assert.Equal(@"C:\temp\fallback.jpg", monitor.PreviewImagePath);
        Assert.Contains("首帧静图", monitor.MonitorHint);
    }

    [Fact]
    public async Task Invalid_material_resets_idle_state()
    {
        var monitor = new GateMonitorViewModel(new FakeMediaFrameExtractor(), new DirectUiDispatcher());
        var material = new MaterialRowViewModel(
            "损坏.mp4",
            @"C:\素材\损坏.mp4",
            null,
            TimeSpan.Zero,
            "—",
            "媒体探测失败",
            hasValidAsset: false);

        await monitor.LoadFromMaterialAsync(material);

        Assert.True(monitor.IsIdle);
        Assert.Equal("监视器空闲", monitor.MonitorCaption);
    }

    [Fact]
    public async Task Frame_extractor_failure_shows_chinese_hint_without_generic_failure()
    {
        var monitor = new GateMonitorViewModel(new FakeMediaFrameExtractor(error: "未找到 FFmpeg。"), new DirectUiDispatcher());
        var material = new MaterialRowViewModel(
            "hevc.mp4",
            @"C:\素材\hevc.mp4",
            "1",
            TimeSpan.FromSeconds(5),
            "1080×1920",
            null,
            hasValidAsset: true,
            videoCodec: "hevc");

        await monitor.LoadFromMaterialAsync(material);

        Assert.False(monitor.HasStaticFrame);
        Assert.Contains("预览受限", monitor.MonitorCaption);
        Assert.Contains("未找到 FFmpeg", monitor.MonitorHint);
    }
}

internal sealed class FakeMediaFrameExtractor : IMediaFrameExtractor
{
    private readonly string? _outputPath;
    private readonly string? _error;

    public FakeMediaFrameExtractor(string? outputPath = null, string? error = null)
    {
        _outputPath = outputPath ?? Path.Combine(Path.GetTempPath(), "fake-frame.jpg");
        _error = error;
    }

    public string? LastVideoPath { get; private set; }

    public Task<Result<string>> ExtractFirstFrameAsync(
        string videoPath,
        string outputJpegPath,
        CancellationToken cancellationToken)
    {
        LastVideoPath = videoPath;
        return Task.FromResult(
            _error is null
                ? Result<string>.Success(_outputPath!)
                : Result<string>.Failure(_error));
    }
}
