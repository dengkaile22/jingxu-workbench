using JingXu.Workbench.Features.Settings;
using JingXu.Workbench.Infrastructure.Rendering;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Presentation.Tests.Settings;

public sealed class SettingsViewModelTests
{
    [Theory]
    [InlineData(HardwareVideoProcessingKind.Qsv, true, "缩放可用 GPU")]
    [InlineData(HardwareVideoProcessingKind.D3D11, false, "缩放使用 CPU")]
    public async Task Refresh_diagnostics_reports_measured_decoding_and_scaling_capabilities(HardwareVideoProcessingKind kind, bool scale, string expected)
    {
        var vm = SettingsViewModelFactory.WithFfmpegAndEncoder(
            new(VideoEncoderKind.H264Qsv, "Intel QSV", "QSV 完成"), new(kind, scale));
        await vm.RefreshDiagnosticsCommand.ExecuteAsync(null);

        Assert.Contains("硬件解码", vm.GpuProcessingStatus, StringComparison.Ordinal);
        Assert.Contains(expected, vm.GpuProcessingStatus, StringComparison.Ordinal);
        Assert.Contains("高分辨率四屏任务自动逐个处理", vm.ConcurrencyHint, StringComparison.Ordinal);
    }

    [Fact]
    public void Render_concurrency_options_include_four_for_upgraded_computers()
    {
        var vm = SettingsViewModelFactory.WithMissing(RuntimeKind.Ffmpeg);

        Assert.Equal([1, 2, 3, 4], vm.ConcurrencyOptions);
    }

    [Fact]
    public async Task Runtime_check_reports_actionable_chinese_status()
    {
        var vm = SettingsViewModelFactory.WithMissing(RuntimeKind.Tesseract);
        await vm.RefreshRuntimeStatusCommand.ExecuteAsync(null);

        var tesseract = vm.RuntimeStatuses.Single(x => x.Kind == RuntimeKind.Tesseract);
        Assert.Contains("未找到 Tesseract", tesseract.Message, StringComparison.Ordinal);
        Assert.False(string.IsNullOrWhiteSpace(tesseract.SuggestedAction));
    }

    [Fact]
    public async Task Refresh_populates_all_manifest_components()
    {
        var vm = SettingsViewModelFactory.WithMissing(RuntimeKind.Ffmpeg);
        await vm.RefreshRuntimeStatusCommand.ExecuteAsync(null);

        Assert.Contains(vm.RuntimeStatuses, x => x.Kind == RuntimeKind.Ffmpeg);
        Assert.Contains(vm.RuntimeStatuses, x => x.Kind == RuntimeKind.Ffprobe);
        Assert.Contains(vm.RuntimeStatuses, x => x.Kind == RuntimeKind.Tesseract);
    }

    [Fact]
    public async Task Refresh_diagnostics_without_ffmpeg_reports_cpu_fallback()
    {
        var vm = SettingsViewModelFactory.WithMissing(RuntimeKind.Ffmpeg);
        await vm.RefreshDiagnosticsCommand.ExecuteAsync(null);

        Assert.Contains("CPU（libx264）", vm.GpuEncoderStatus, StringComparison.Ordinal);
        Assert.Contains("NVIDIA", vm.GpuEncoderHint, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Refresh_diagnostics_shows_detected_nvenc_encoder()
    {
        var vm = SettingsViewModelFactory.WithFfmpegAndEncoder(
            new VideoEncoderSelection(
                VideoEncoderKind.H264Nvenc,
                "NVIDIA GPU（NVENC）",
                "使用 NVIDIA GPU（NVENC）完成。"));
        await vm.RefreshDiagnosticsCommand.ExecuteAsync(null);

        Assert.Contains("h264_nvenc", vm.GpuEncoderStatus, StringComparison.Ordinal);
        Assert.Contains("NVIDIA", vm.GpuEncoderStatus, StringComparison.Ordinal);
    }
}
