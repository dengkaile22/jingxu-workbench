using System.Globalization;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>编译字幕烧录 FFmpeg 命令。</summary>
public static class SubtitleBurnInCommandCompiler
{
    public static FfmpegCompileResult Compile(string ffmpegExecutable, SubtitleBurnInPlan plan, string tempOutputPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegExecutable);
        ArgumentNullException.ThrowIfNull(plan);
        ArgumentException.ThrowIfNullOrWhiteSpace(tempOutputPath);

        var filter = SubtitleBurnInFilterCompiler.Compile(plan);
        var arguments = new List<string>
        {
            "-y",
            "-i", plan.InputVideoPath,
            "-filter_complex", filter,
            "-map", "[vout]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "160k",
            "-progress", "pipe:1",
            "-nostats",
            tempOutputPath
        };

        return new FfmpegCompileResult(new FfmpegCommand(ffmpegExecutable, arguments), []);
    }
}
