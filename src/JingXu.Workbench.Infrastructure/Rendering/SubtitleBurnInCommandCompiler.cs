using System.Globalization;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>编译字幕烧录 FFmpeg 命令。</summary>
public static class SubtitleBurnInCommandCompiler
{
    public static FfmpegCompileResult Compile(string ffmpegExecutable, SubtitleBurnInPlan plan, string tempOutputPath)
    {
        ArgumentNullException.ThrowIfNull(plan);
        return Compile(
            ffmpegExecutable,
            plan,
            tempOutputPath,
            OutputVideoSettings.Original,
            canvasWidth: plan.FrameWidth,
            canvasHeight: plan.FrameHeight,
            firstClipFrameRate: 1m);
    }

    /// <summary>
    /// 编译字幕烧录命令，并在字幕烧录完成后应用显式的导出规格。
    /// 原画/原帧率路径保持与既有命令完全一致。
    /// </summary>
    public static FfmpegCompileResult Compile(
        string ffmpegExecutable,
        SubtitleBurnInPlan plan,
        string tempOutputPath,
        OutputVideoSettings outputVideoSettings,
        int canvasWidth,
        int canvasHeight,
        decimal firstClipFrameRate)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegExecutable);
        ArgumentNullException.ThrowIfNull(plan);
        ArgumentException.ThrowIfNullOrWhiteSpace(tempOutputPath);

        var filter = SubtitleBurnInFilterCompiler.Compile(plan);
        var outputVideoLabel = "vout";
        if (outputVideoSettings.RequiresTranscode)
        {
            var exportFilters = new List<string>();
            if (!outputVideoSettings.IsOriginalResolution)
            {
                var (targetWidth, targetHeight) = outputVideoSettings.ResolveTargetSize(canvasWidth, canvasHeight);
                exportFilters.Add($"scale={targetWidth}:{targetHeight}");
            }

            if (!outputVideoSettings.IsOriginalFrameRate)
            {
                var targetFrameRate = outputVideoSettings.ResolveFrameRate(firstClipFrameRate);
                exportFilters.Add($"fps={targetFrameRate.ToString(CultureInfo.InvariantCulture)}");
            }

            exportFilters.Add("setsar=1");
            exportFilters.Add("format=yuv420p");
            filter = $"{filter};[vout]{string.Join(',', exportFilters)}[vexport]";
            outputVideoLabel = "vexport";
        }

        var aliaser = new FfmpegPathAliaser();
        var arguments = new List<string>
        {
            "-y",
            "-i", aliaser.Alias(plan.InputVideoPath),
            "-filter_complex_script", FfmpegCommandCompiler.FilterComplexScriptFileName,
            "-map", $"[{outputVideoLabel}]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "faster",
            "-threads", "0",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "160k",
            "-progress", "pipe:1",
            "-nostats",
            Path.GetFileName(tempOutputPath)
        };

        return new FfmpegCompileResult(
            new FfmpegCommand(ffmpegExecutable, arguments),
            [new FfmpegAuxiliaryFile(FfmpegCommandCompiler.FilterComplexScriptFileName, filter)],
            aliaser.Aliases);
    }
}
