using System.Globalization;
using System.Text;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>蒙版层 FFmpeg filter_complex 编译结果。</summary>
public sealed record OverlayFilterCompileResult(
    IReadOnlyList<string> PreInputArguments,
    IReadOnlyList<string> OverlayInputPaths,
    string FilterSuffix,
    string FinalVideoLabel);

/// <summary>将解析后的蒙版层编译为 FFmpeg 滤镜图后缀。</summary>
public static class OverlayFilterCompiler
{
    /// <summary>编译蒙版滤镜链，叠加在基础视频标签之后。</summary>
    public static Result<OverlayFilterCompileResult> Compile(
        IReadOnlyList<ResolvedOverlay> overlays,
        int mainInputCount,
        int targetWidth,
        int targetHeight,
        string baseVideoLabel = "vbase")
    {
        ArgumentNullException.ThrowIfNull(overlays);

        if (overlays.Count == 0)
        {
            return Result<OverlayFilterCompileResult>.Failure("未提供任何蒙版层。");
        }

        var preInputArgs = new List<string>();
        var overlayPaths = new List<string>();
        var builder = new StringBuilder();
        var currentBase = baseVideoLabel;

        for (var index = 0; index < overlays.Count; index++)
        {
            var resolved = overlays[index];
            var layer = resolved.Layer;
            var inputIndex = mainInputCount + index;
            var scaledLabel = $"ovfit{index}";
            var alphaLabel = $"ovalpha{index}";
            var outputLabel = $"vov{index}";

            overlayPaths.Add(layer.SourcePath);
            preInputArgs.Add("-stream_loop");
            preInputArgs.Add("-1");
            preInputArgs.Add("-i");
            preInputArgs.Add(layer.SourcePath);

            var activeSeconds = FormatSeconds(resolved.ActiveDuration);
            var startSeconds = FormatSeconds(resolved.Start);
            var endSeconds = FormatSeconds(resolved.Start + resolved.ActiveDuration);
            var (px, py, pw, ph) = layer.Bounds.ToPixels(targetWidth, targetHeight);
            var overlayX = px + (int)Math.Round(layer.OffsetX * targetWidth);
            var overlayY = py + (int)Math.Round(layer.OffsetY * targetHeight);

            builder.Append(CultureInfo.InvariantCulture,
                $"[{inputIndex}:v]trim=duration={activeSeconds},setpts=PTS-STARTPTS+{startSeconds}/TB,");
            builder.Append(BuildFitFilters(layer.Fit, pw, ph));

            if (Math.Abs(layer.Scale - OverlayLayer.DefaultScale) > 0.000001)
            {
                builder.Append(CultureInfo.InvariantCulture,
                    $"scale=iw*{FormatDecimal(layer.Scale)}:ih*{FormatDecimal(layer.Scale)},");
            }

            builder.Append(CultureInfo.InvariantCulture,
                $"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,format=rgba[{scaledLabel}];");

            var opacity = layer.Mode == OverlayMode.FullFrameLowOpacity
                ? OverlayLayer.FullFrameDefaultOpacity
                : layer.Opacity;

            builder.Append(CultureInfo.InvariantCulture,
                $"[{scaledLabel}]colorchannelmixer=aa={FormatDecimal(opacity)}[{alphaLabel}];");

            var overlaySource = alphaLabel;
            if (layer.Mode == OverlayMode.ShapeMask && layer.Shape != ShapeKind.ImportedPng)
            {
                var maskedLabel = $"{alphaLabel}m";
                builder.Append(BuildShapeAlphaMask(layer, pw, ph, alphaLabel, maskedLabel));
                builder.Append(';');
                overlaySource = maskedLabel;
            }

            if (Math.Abs(layer.RotationDegrees) > 0.000001)
            {
                var radians = layer.RotationDegrees * Math.PI / 180.0;
                var rotatedLabel = $"ovrot{index}";
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{overlaySource}]rotate={FormatDecimal(radians)}:c=none[{rotatedLabel}];");
                overlaySource = rotatedLabel;
            }

            if (layer.Feather > 0.000001)
            {
                var sigma = Math.Max(1, (int)Math.Round(layer.Feather * Math.Min(pw, ph) * 0.15));
                var featherLabel = $"ovfth{index}";
                var rgbLabel = $"ovrgb{index}";
                var alphaInLabel = $"ovain{index}";
                var alphaOutLabel = $"ovaout{index}";
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{overlaySource}]split[{rgbLabel}][{alphaInLabel}];");
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{alphaInLabel}]alphaextract,gblur=sigma={sigma}[{alphaOutLabel}];");
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{rgbLabel}][{alphaOutLabel}]alphamerge[{featherLabel}];");
                overlaySource = featherLabel;
            }

            builder.Append(CultureInfo.InvariantCulture,
                $"[{currentBase}][{overlaySource}]overlay=x={overlayX}-(overlay_w-{pw})/2:y={overlayY}-(overlay_h-{ph})/2:enable='between(t,{startSeconds},{endSeconds})'[{outputLabel}];");

            currentBase = outputLabel;
        }

        var suffix = builder.ToString().TrimEnd(';');
        return Result<OverlayFilterCompileResult>.Success(
            new OverlayFilterCompileResult(preInputArgs, overlayPaths, suffix, currentBase));
    }

    internal static string BuildFitFilters(OverlayFitMode fit, int targetW, int targetH) =>
        fit switch
        {
            OverlayFitMode.FillCrop =>
                $"scale={targetW}:{targetH}:force_original_aspect_ratio=increase,crop={targetW}:{targetH},",
            OverlayFitMode.Contain =>
                $"scale={targetW}:{targetH}:force_original_aspect_ratio=decrease,pad={targetW}:{targetH}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,",
            OverlayFitMode.Stretch =>
                $"scale={targetW}:{targetH},",
            _ => throw new ArgumentOutOfRangeException(nameof(fit), fit, null)
        };

    private static string BuildShapeAlphaMask(
        OverlayLayer layer,
        int width,
        int height,
        string inputLabel,
        string outputLabel) =>
        layer.Shape switch
        {
            ShapeKind.Ellipse =>
                $"[{inputLabel}]geq=lum='if(lt(pow(X-{width / 2},2)+pow(Y-{height / 2},2),pow(min({width},{height})/2,2)),255,0)':cb='p(X,Y)':cr='p(X,Y)'[{outputLabel}]",
            ShapeKind.RoundedRectangle =>
                $"[{inputLabel}]geq=lum='if(gt(X,8)*gt(Y,8)*gt({width}-X,8)*gt({height}-Y,8),255,if(lt(pow(min(X,8)+min({width}-X,8)-8,2)+pow(min(Y,8)+min({height}-Y,8)-8,2),64),255,0))':cb='p(X,Y)':cr='p(X,Y)'[{outputLabel}]",
            _ =>
                $"[{inputLabel}]copy[{outputLabel}]"
        };

    private static string FormatDecimal(double value) =>
        value.ToString("0.######", CultureInfo.InvariantCulture);

    private static string FormatSeconds(TimeSpan duration) =>
        duration.TotalSeconds.ToString("0.######", CultureInfo.InvariantCulture);
}
