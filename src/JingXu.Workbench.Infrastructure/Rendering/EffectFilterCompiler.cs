using System.Globalization;
using System.Text;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>效果滤镜编译结果。</summary>
public sealed record EffectFilterChainResult(string FilterSuffix, string OutputVideoLabel);

/// <summary>将差异化效果与简单贴纸编译为 FFmpeg 视频滤镜链。</summary>
public static class EffectFilterCompiler
{
    /// <summary>编译效果滤镜图；无效果时返回空后缀与原始标签。</summary>
    public static string Compile(MaterializedEffect effect, string inputVideoLabel = "vbase", string outputVideoLabel = "vfx")
    {
        ArgumentNullException.ThrowIfNull(effect);
        return CompileChain(effect, sticker: null, inputVideoLabel, outputVideoLabel).FilterSuffix;
    }

    /// <summary>编译效果与可选贴纸的完整视频链。</summary>
    public static EffectFilterChainResult CompileChain(
        MaterializedEffect? effect,
        ImageSticker? sticker,
        string inputVideoLabel = "vbase",
        string outputVideoLabel = "vfx",
        string stickerOutputLabel = "vstk",
        int? stickerInputIndex = null)
    {
        var currentLabel = inputVideoLabel;
        var builder = new StringBuilder();

        if (effect is not null && effect.HasVisualAdjustments)
        {
            builder.Append('[').Append(currentLabel).Append(']');
            AppendEffectFilters(builder, effect);
            builder.Append('[').Append(outputVideoLabel).Append(']');
            currentLabel = outputVideoLabel;
        }

        if (sticker is not null)
        {
            if (stickerInputIndex is null)
            {
                throw new InvalidOperationException("编译贴纸滤镜时必须提供贴纸输入索引。");
            }

            if (builder.Length > 0)
            {
                builder.Append(';');
            }

            builder.Append(CompileSticker(sticker, currentLabel, stickerInputIndex.Value, stickerOutputLabel));
            currentLabel = stickerOutputLabel;
        }

        return new EffectFilterChainResult(builder.ToString(), currentLabel);
    }

    /// <summary>编译图片贴纸叠加滤镜；<paramref name="stickerInputIndex"/> 为贴纸输入流索引。</summary>
    public static string CompileSticker(
        ImageSticker sticker,
        string inputVideoLabel,
        int stickerInputIndex,
        string outputVideoLabel = "vstk")
    {
        ArgumentNullException.ThrowIfNull(sticker);
        if (stickerInputIndex < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(stickerInputIndex), "贴纸输入索引无效。");
        }

        var (px, py, pw, ph) = sticker.Bounds.ToPixels(1920, 1080);
        var scaledLabel = $"{outputVideoLabel}src";
        var alphaLabel = $"{outputVideoLabel}alpha";

        return string.Create(CultureInfo.InvariantCulture, $"""
            [{stickerInputIndex}:v]scale={pw}:{ph},format=rgba[{scaledLabel}];
            [{scaledLabel}]colorchannelmixer=aa={FormatDecimal(sticker.Opacity)}[{alphaLabel}];
            [{inputVideoLabel}][{alphaLabel}]overlay={px}:{py}[{outputVideoLabel}]
            """);
    }

    /// <summary>根据成片尺寸编译贴纸叠加滤镜。</summary>
    public static string CompileStickerForFrame(
        ImageSticker sticker,
        string inputVideoLabel,
        int stickerInputIndex,
        int frameWidth,
        int frameHeight,
        string outputVideoLabel = "vstk")
    {
        ArgumentNullException.ThrowIfNull(sticker);
        var (px, py, pw, ph) = sticker.Bounds.ToPixels(frameWidth, frameHeight);
        var scaledLabel = $"{outputVideoLabel}src";
        var alphaLabel = $"{outputVideoLabel}alpha";

        return string.Create(CultureInfo.InvariantCulture, $"""
            [{stickerInputIndex}:v]scale={pw}:{ph},format=rgba[{scaledLabel}];
            [{scaledLabel}]colorchannelmixer=aa={FormatDecimal(sticker.Opacity)}[{alphaLabel}];
            [{inputVideoLabel}][{alphaLabel}]overlay={px}:{py}[{outputVideoLabel}]
            """);
    }

    private static void AppendEffectFilters(StringBuilder builder, MaterializedEffect effect)
    {
        var filters = new List<string>();

        if (effect.Mirror == MirrorMode.Horizontal)
        {
            filters.Add("hflip");
        }
        else if (effect.Mirror == MirrorMode.Vertical)
        {
            filters.Add("vflip");
        }

        if (effect.CropPercent > 0)
        {
            var factor = FormatDecimal(1.0 - effect.CropPercent / 100.0);
            filters.Add($"crop=iw*{factor}:ih*{factor}:(iw-ow)/2:(ih-oh)/2");
        }

        if (Math.Abs(effect.Brightness) > 0.0001
            || Math.Abs(effect.Contrast - 1.0) > 0.0001
            || Math.Abs(effect.Saturation - 1.0) > 0.0001)
        {
            filters.Add(
                $"eq=brightness={FormatDecimal(effect.Brightness)}:contrast={FormatDecimal(effect.Contrast)}:saturation={FormatDecimal(effect.Saturation)}");
        }

        if (effect.DenoiseStrength > 0)
        {
            var strength = FormatDecimal(effect.DenoiseStrength);
            filters.Add($"hqdn3d={strength}:{strength}:{strength}");
        }

        if (filters.Count == 0)
        {
            filters.Add("copy");
        }

        builder.Append(string.Join(',', filters));
    }

    private static string FormatDecimal(double value) =>
        value.ToString("0.######", CultureInfo.InvariantCulture);
}
