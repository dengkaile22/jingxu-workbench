namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>只识别输入设备、硬解和硬件回传错误；普通合成滤镜错误交还原失败诊断。</summary>
internal static class HardwareVideoProcessingFailure
{
    public static bool IsHardwareFailure(string stderr)
    {
        if (string.IsNullOrWhiteSpace(stderr)) { return false; }
        string[] deviceErrors =
        [
            "Device creation failed", "Device setup failed for decoder", "No device available for decoder",
            "Failed setup for format qsv", "Failed setup for format cuda", "Failed setup for format d3d11",
            "Failed to create a QSV device", "hwaccel initialisation returned error", "Hardware does not support image size",
            "Cannot load nvcuda", "CUDA_ERROR", "Reconfiguring filter graph because hwaccel changed",
            "Error initializing the MFX video decoder", "Error during QSV decoding", "Error initializing a QSV frame pool",
            "Failed to begin frame: 0x", "Failed to execute: 0x", "Failed to end frame: 0x"
        ];
        if (deviceErrors.Any(marker => stderr.Contains(marker, StringComparison.OrdinalIgnoreCase))) { return true; }

        foreach (var line in stderr.Split('\n'))
        {
            // QSV 的 IO surface、解码器和帧池错误由同一组件输出；限定同一行，避免误认后续普通滤镜错误。
            var hardwareComponent = line.Contains("h264_qsv", StringComparison.OrdinalIgnoreCase)
                || line.Contains("scale_qsv", StringComparison.OrdinalIgnoreCase)
                || line.Contains("scale_cuda", StringComparison.OrdinalIgnoreCase)
                || line.Contains("hwdownload", StringComparison.OrdinalIgnoreCase)
                || line.Contains("init_hw_device", StringComparison.OrdinalIgnoreCase)
                || line.Contains("hwaccel_device", StringComparison.OrdinalIgnoreCase);
            if (hardwareComponent && (line.Contains("error", StringComparison.OrdinalIgnoreCase)
                || line.Contains("failed", StringComparison.OrdinalIgnoreCase)
                || line.Contains("invalid", StringComparison.OrdinalIgnoreCase)
                || line.Contains("not supported", StringComparison.OrdinalIgnoreCase)))
            {
                return true;
            }
        }
        return false;
    }
}
