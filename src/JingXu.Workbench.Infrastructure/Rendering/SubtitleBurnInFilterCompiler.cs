using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>编译旧字幕去除 + 新字幕烧录 filter 图。</summary>
public static class SubtitleBurnInFilterCompiler
{
    /// <summary>生成完整 filter_complex 字符串。</summary>
    public static string Compile(SubtitleBurnInPlan plan)
    {
        ArgumentNullException.ThrowIfNull(plan);
        var subtitlePath = FfmpegFilterPathEscaper.EscapeForFilter(plan.SubtitleFilePath);
        var subtitleFilter = plan.SubtitleFormat == SubtitleFileFormat.Ass
            ? $"ass='{subtitlePath}'"
            : $"subtitles='{subtitlePath}'";

        if (plan.Removal is null)
        {
            return $"[0:v]{subtitleFilter}[vout]";
        }

        var removal = SubtitleRemovalFilterCompiler.Compile(plan.Removal);
        return $"{removal};[vsub]{subtitleFilter}[vout]";
    }
}
