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
    public static string Compile(
        MaterializedEffect effect,
        string inputVideoLabel = "vbase",
        string outputVideoLabel = "vfx",
        int? outputWidth = null,
        int? outputHeight = null)
    {
        ArgumentNullException.ThrowIfNull(effect);
        return CompileChain(
            effect,
            [],
            inputVideoLabel,
            outputVideoLabel,
            outputWidth: outputWidth,
            outputHeight: outputHeight).FilterSuffix;
    }

    /// <summary>编译效果与可选贴纸的完整视频链。</summary>
    /// <param name="outputWidth">效果链输出画布宽度；提供时会在视觉效果后恢复该宽度。</param>
    /// <param name="outputHeight">效果链输出画布高度；提供时会在视觉效果后恢复该高度。</param>
    public static EffectFilterChainResult CompileChain(
        MaterializedEffect? effect,
        IReadOnlyList<ImageSticker> stickers,
        string inputVideoLabel = "vbase",
        string outputVideoLabel = "vfx",
        string stickerOutputLabel = "vstk",
        IReadOnlyList<int>? stickerInputIndices = null,
        int frameWidth = 1920,
        int frameHeight = 1080,
        int? outputWidth = null,
        int? outputHeight = null)
    {
        var currentLabel = inputVideoLabel;
        var builder = new StringBuilder();

        if (effect is not null && effect.HasVisualAdjustments)
        {
            builder.Append('[').Append(currentLabel).Append(']');
            AppendEffectFilters(builder, effect);
            AppendOutputCanvasNormalization(builder, outputWidth, outputHeight);
            builder.Append('[').Append(outputVideoLabel).Append(']');
            currentLabel = outputVideoLabel;
        }

        if (stickers is { Count: > 0 })
        {
            if (stickerInputIndices is null || stickerInputIndices.Count != stickers.Count)
            {
                throw new InvalidOperationException("编译贴纸滤镜时必须提供与贴纸数量一致的输入索引。");
            }

            for (var i = 0; i < stickers.Count; i++)
            {
                if (builder.Length > 0)
                {
                    builder.Append(';');
                }

                var stepOutput = i == stickers.Count - 1 ? stickerOutputLabel : $"{stickerOutputLabel}{i}";
                builder.Append(CompileSticker(stickers[i], currentLabel, stickerInputIndices[i], frameWidth, frameHeight, stepOutput));
                currentLabel = stepOutput;
            }
        }

        return new EffectFilterChainResult(builder.ToString(), currentLabel);
    }

    /// <summary>编译图片贴纸叠加滤镜；<paramref name="stickerInputIndex"/> 为贴纸输入流索引。</summary>
    public static string CompileSticker(
        ImageSticker sticker,
        string inputVideoLabel,
        int stickerInputIndex,
        int frameWidth,
        int frameHeight,
        string outputVideoLabel = "vstk")
    {
        ArgumentNullException.ThrowIfNull(sticker);
        if (stickerInputIndex < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(stickerInputIndex), "贴纸输入索引无效。");
        }

        var (px, py, pw, ph) = sticker.Bounds.ToPixels(frameWidth, frameHeight);
        var scaledLabel = $"{outputVideoLabel}src";
        var rotatedLabel = $"{outputVideoLabel}rot";
        var alphaLabel = $"{outputVideoLabel}alpha";

        var hasRotation = Math.Abs(sticker.RotationDegrees) > 0.0001;
        var rotationFilter = hasRotation
            ? $"[{scaledLabel}]rotate={FormatDecimal(sticker.RotationDegrees * Math.PI / 180.0)}:c=none[{rotatedLabel}];[{rotatedLabel}]colorchannelmixer=aa={FormatDecimal(sticker.Opacity)}[{alphaLabel}];"
            : $"[{scaledLabel}]colorchannelmixer=aa={FormatDecimal(sticker.Opacity)}[{alphaLabel}];";

        // shortest=1：贴纸输入用 -loop/-stream_loop 无限循环时，以主片时长收束，覆盖整段拼接。
        return string.Create(CultureInfo.InvariantCulture, $"""
            [{stickerInputIndex}:v]scale={pw}:{ph},format=rgba[{scaledLabel}];
            {rotationFilter}
            [{inputVideoLabel}][{alphaLabel}]overlay={px}:{py}:shortest=1[{outputVideoLabel}]
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

        if (Math.Abs(effect.RotationDegrees) > 0.0001)
        {
            var radians = FormatDecimal(effect.RotationDegrees * Math.PI / 180.0);
            filters.Add($"rotate={radians}:ow=iw:oh=ih:c=black");
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

    private static void AppendOutputCanvasNormalization(
        StringBuilder builder,
        int? outputWidth,
        int? outputHeight)
    {
        if (outputWidth is > 0 && outputHeight is > 0)
        {
            builder.Append(CultureInfo.InvariantCulture, $",scale={outputWidth.Value}:{outputHeight.Value},setsar=1");
        }
    }

    private static string FormatDecimal(double value) =>
        value.ToString("0.######", CultureInfo.InvariantCulture);
}
