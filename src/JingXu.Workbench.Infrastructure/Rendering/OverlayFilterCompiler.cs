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
        var nextInputIndex = mainInputCount;

        for (var index = 0; index < overlays.Count; index++)
        {
            var resolved = overlays[index];
            var layer = resolved.Layer;
            var scaledLabel = $"ovfit{index}";
            var alphaLabel = $"ovalpha{index}";
            var outputLabel = $"vov{index}";

            var activeSeconds = FormatSeconds(resolved.ActiveDuration);
            var startSeconds = FormatSeconds(resolved.Start);
            var endSeconds = FormatSeconds(resolved.Start + resolved.ActiveDuration);
            var (px, py, pw, ph) = layer.Bounds.ToPixels(targetWidth, targetHeight);
            var overlayX = px + (int)Math.Round(layer.OffsetX * targetWidth);
            var overlayY = py + (int)Math.Round(layer.OffsetY * targetHeight);
            var opacity = layer.Opacity;

            string overlaySource;
            string baseForOverlay;

            if (layer.IsSelfSource)
            {
                // 主片自叠影：从当前主轨 split，放大半透明再叠回（无外部 -i）。
                var keepLabel = $"ovselfkeep{index}";
                var ghostSrcLabel = $"ovselfsrc{index}";
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{currentBase}]split[{keepLabel}][{ghostSrcLabel}];");
                builder.Append(CultureInfo.InvariantCulture, $"[{ghostSrcLabel}]");
                builder.Append(BuildSelfFitAndScale(layer, px, py, pw, ph));
                builder.Append(CultureInfo.InvariantCulture, $"format=rgba[{scaledLabel}];");
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{scaledLabel}]colorchannelmixer=aa={FormatDecimal(opacity)}[{alphaLabel}];");
                overlaySource = alphaLabel;
                baseForOverlay = keepLabel;
            }
            else
            {
                var inputIndex = nextInputIndex++;
                overlayPaths.Add(layer.SourcePath);
                preInputArgs.Add("-stream_loop");
                preInputArgs.Add("-1");
                preInputArgs.Add("-i");
                preInputArgs.Add(layer.SourcePath);

                builder.Append(CultureInfo.InvariantCulture,
                    $"[{inputIndex}:v]trim=duration={activeSeconds},setpts=PTS-STARTPTS+{startSeconds}/TB,");
                builder.Append(BuildFitFilters(layer, pw, ph, px, py, targetWidth, targetHeight));
                builder.Append(BuildRelativeScale(layer, pw, ph));
                builder.Append(CultureInfo.InvariantCulture, $"format=rgba[{scaledLabel}];");
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{scaledLabel}]colorchannelmixer=aa={FormatDecimal(opacity)}[{alphaLabel}];");
                overlaySource = alphaLabel;
                baseForOverlay = currentBase;
            }

            if (layer.Mode == OverlayMode.ShapeMask)
            {
                var maskedLabel = $"{alphaLabel}m";
                builder.Append(BuildShapeAlphaMask(layer, pw, ph, index, overlaySource, maskedLabel));
                builder.Append(';');
                overlaySource = maskedLabel;
            }

            // 顶部渐变、底部分割线羽化和轻量边缘柔化合并为一次 alpha 平面处理，
            // 避免在 RGBA 四通道上重复 geq，以及随分辨率无限增大的高斯模糊。
            if (layer.TopFade > 0.000001 || layer.Feather > 0.000001)
            {
                var envelopeLabel = $"ovenvelope{index}";
                builder.Append(BuildAlphaEnvelope(
                    layer.TopFade,
                    layer.Feather,
                    pw,
                    ph,
                    overlaySource,
                    envelopeLabel));
                builder.Append(';');
                overlaySource = envelopeLabel;
            }

            if (Math.Abs(layer.RotationDegrees) > 0.000001)
            {
                var radians = layer.RotationDegrees * Math.PI / 180.0;
                var rotatedLabel = $"ovrot{index}";
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{overlaySource}]rotate={FormatDecimal(radians)}:c=none[{rotatedLabel}];");
                overlaySource = rotatedLabel;
            }

            builder.Append(CultureInfo.InvariantCulture,
                $"[{baseForOverlay}][{overlaySource}]overlay=x={overlayX}-(overlay_w-{pw})/2:y={overlayY}-(overlay_h-{ph})/2:enable='between(t,{startSeconds},{endSeconds})'[{outputLabel}];");

            currentBase = outputLabel;
        }

        var suffix = builder.ToString().TrimEnd(';');
        return Result<OverlayFilterCompileResult>.Success(
            new OverlayFilterCompileResult(preInputArgs, overlayPaths, suffix, currentBase));
    }

    /// <summary>
    /// 自叠影：主轨已是目标画幅，先按边界裁切，再相对缩放（放大中心裁回）。
    /// </summary>
    internal static string BuildSelfFitAndScale(OverlayLayer layer, int px, int py, int pw, int ph)
    {
        if (layer.SourceCropBounds is { } sourceCropBounds)
        {
            return BuildManualSourceCropFilters(sourceCropBounds) +
                   BuildManualSourceCropFitFilters(layer, pw, ph) +
                   BuildRelativeScale(layer, pw, ph);
        }

        var builder = new StringBuilder();
        builder.Append(CultureInfo.InvariantCulture, $"crop={pw}:{ph}:{px}:{py},");
        builder.Append(BuildRelativeScale(layer, pw, ph));
        return builder.ToString();
    }

    internal static string BuildRelativeScale(OverlayLayer layer, int pw, int ph)
    {
        if (Math.Abs(layer.Scale - OverlayLayer.DefaultScale) <= 0.000001)
        {
            return string.Empty;
        }

        var builder = new StringBuilder();
        builder.Append(CultureInfo.InvariantCulture,
            $"scale=iw*{FormatDecimal(layer.Scale)}:ih*{FormatDecimal(layer.Scale)},");
        // Scale>1：放大后中心裁回边界；Scale<1：缩小后透明 pad 回边界。
        if (layer.Scale > OverlayLayer.DefaultScale)
        {
            builder.Append(CultureInfo.InvariantCulture,
                $"crop={pw}:{ph}:(iw-ow)/2:(ih-oh)/2,");
        }
        else
        {
            builder.Append(CultureInfo.InvariantCulture,
                $"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,");
        }

        return builder.ToString();
    }

    internal static string BuildFitFilters(
        OverlayLayer layer,
        int boundsW,
        int boundsH,
        int boundsX,
        int boundsY,
        int canvasW,
        int canvasH)
    {
        if (layer.SourceCropBounds is { } sourceCropBounds)
        {
            // 手动框选是源素材取景，必须先裁源；之后使用不再裁切的适配链，
            // 避免 MatchCanvasCrop/FillCrop 的居中二次裁切重新切掉人物头部。
            return BuildManualSourceCropFilters(sourceCropBounds) +
                   BuildManualSourceCropFitFilters(layer, boundsW, boundsH);
        }

        return layer.Fit switch
        {
            OverlayFitMode.FillCrop =>
                $"scale={boundsW}:{boundsH}:force_original_aspect_ratio=increase,crop={boundsW}:{boundsH},",
            OverlayFitMode.Contain =>
                $"scale={boundsW}:{boundsH}:force_original_aspect_ratio=decrease,pad={boundsW}:{boundsH}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,",
            OverlayFitMode.Stretch =>
                $"scale={boundsW}:{boundsH},",
            OverlayFitMode.MatchCanvasCrop =>
                BuildMatchCanvasCropFilters(layer.SourceCropY, boundsW, boundsH, boundsX, boundsY, canvasW, canvasH),
            _ => throw new ArgumentOutOfRangeException(nameof(layer), layer.Fit, null)
        };
    }

    /// <summary>
    /// 将人工框选的源素材区域换算成像素安全的 FFmpeg crop 表达式。
    /// 宽高和起点都按偶数对齐，以兼容 yuv420 输入；源框为唯一取景裁切，
    /// 因此后续适配不得再进行居中裁切。
    /// </summary>
    internal static string BuildManualSourceCropFilters(NormalizedRect sourceCropBounds)
    {
        var x = FormatDecimal(sourceCropBounds.X);
        var y = FormatDecimal(sourceCropBounds.Y);
        var width = FormatDecimal(sourceCropBounds.Width);
        var height = FormatDecimal(sourceCropBounds.Height);

        return string.Create(
            CultureInfo.InvariantCulture,
            $"crop=w='max(2\\,trunc(iw*{width}/2)*2)':h='max(2\\,trunc(ih*{height}/2)*2)':x='trunc(min(iw-ow\\,iw*{x})/2)*2':y='trunc(min(ih-oh\\,ih*{y})/2)*2',");
    }

    private static string BuildManualSourceCropFitFilters(OverlayLayer layer, int boundsW, int boundsH) =>
        layer.Fit switch
        {
            OverlayFitMode.Stretch => $"scale={boundsW}:{boundsH},",
            OverlayFitMode.FillCrop or OverlayFitMode.Contain or OverlayFitMode.MatchCanvasCrop =>
                $"scale={boundsW}:{boundsH}:force_original_aspect_ratio=decrease,pad={boundsW}:{boundsH}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,",
            _ => throw new ArgumentOutOfRangeException(nameof(layer), layer.Fit, null)
        };

    /// <summary>
    /// 剪映流程：9:16 蒙版先按成片画幅（如 3:4）中心裁切（可上下偏移），缩放到画布后取 Bounds 窗口，
    /// 使覆盖区内人物比例与主片一致，避免直接 FillCrop 进横扁红框造成错误裁切。
    /// </summary>
    internal static string BuildMatchCanvasCropFilters(
        double sourceCropY,
        int boundsW,
        int boundsH,
        int boundsX,
        int boundsY,
        int canvasW,
        int canvasH)
    {
        var bias = FormatDecimal(Math.Clamp(sourceCropY, OverlayLayer.MinSourceCropY, OverlayLayer.MaxSourceCropY));
        // crop to canvas aspect using iw/ih expressions; y = (ih-oh)/2 * (1+bias) → -1 顶 / 0 中 / 1 底
        return string.Create(
            CultureInfo.InvariantCulture,
            $"crop=w='min(iw\\,ih*{canvasW}/{canvasH})':h='min(ih\\,iw*{canvasH}/{canvasW})':x='(iw-ow)/2':y='(ih-oh)/2*(1+{bias})',scale={canvasW}:{canvasH},crop={boundsW}:{boundsH}:{boundsX}:{boundsY},");
    }

    /// <summary>一次性在 alpha 平面应用顶部渐变、底部分割线羽化与受限边缘柔化。</summary>
    internal static string BuildAlphaEnvelope(
        double topFade,
        double feather,
        int width,
        int height,
        string inputLabel,
        string outputLabel)
    {
        var factors = new List<string>();
        if (topFade > 0.000001)
        {
            var fade = FormatDecimal(Math.Clamp(topFade, OverlayLayer.MinTopFade, OverlayLayer.MaxTopFade));
            factors.Add($"min(1,Y/(H*{fade}))");
        }

        if (feather > 0.000001)
        {
            var band = FormatDecimal(Math.Clamp(feather, OverlayLayer.MinFeather, OverlayLayer.MaxFeather));
            factors.Add($"min(1,max(0,(H-Y)/(H*{band}+0.000001)))");
        }

        var multiplier = factors.Count == 0 ? "1" : string.Join('*', factors);
        var sigma = ResolveEdgeFeatherSigma(feather, width, height);
        var blur = sigma > 0 ? $",gblur=sigma={sigma}" : string.Empty;
        var rgbLabel = $"{outputLabel}rgb";
        var alphaInLabel = $"{outputLabel}ain";
        var alphaOutLabel = $"{outputLabel}aout";

        return string.Create(
            CultureInfo.InvariantCulture,
            $"[{inputLabel}]split[{rgbLabel}][{alphaInLabel}];" +
            $"[{alphaInLabel}]alphaextract,geq=lum='lum(X,Y)*{multiplier}'{blur}[{alphaOutLabel}];" +
            $"[{rgbLabel}][{alphaOutLabel}]alphamerge[{outputLabel}]");
    }

    /// <summary>
    /// 分割线宽度已经由线性 alpha 表达，额外模糊只用于轻微软化侧边。
    /// 限制到 8px，避免高分辨率与高羽化值产生几十到上百像素的逐帧模糊。
    /// </summary>
    internal static int ResolveEdgeFeatherSigma(double feather, int width, int height)
    {
        if (feather <= 0.000001 || width <= 0 || height <= 0)
        {
            return 0;
        }

        var scaled = (int)Math.Round(
            Math.Clamp(feather, OverlayLayer.MinFeather, OverlayLayer.MaxFeather)
            * Math.Min(width, height)
            * 0.015);
        return Math.Clamp(scaled, 1, 8);
    }

    private static string BuildShapeAlphaMask(
        OverlayLayer layer,
        int width,
        int height,
        int overlayIndex,
        string inputLabel,
        string outputLabel)
    {
        // rgba 输入必须改 a 通道；旧版 geq=lum 会毁掉 alpha，导致椭圆/圆角蒙版整层不可见。
        return layer.Shape switch
        {
            ShapeKind.Ellipse =>
                $"[{inputLabel}]geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(pow(X-{width / 2},2)+pow(Y-{height / 2},2),pow(min({width},{height})/2,2)),alpha(X,Y),0)'[{outputLabel}]",
            ShapeKind.RoundedRectangle =>
                $"[{inputLabel}]geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(gt(X,8)*gt(Y,8)*gt({width}-X,8)*gt({height}-Y,8),alpha(X,Y),if(lt(pow(min(X,8)+min({width}-X,8)-8,2)+pow(min(Y,8)+min({height}-Y,8)-8,2),64),alpha(X,Y),0))'[{outputLabel}]",
            ShapeKind.ImportedPng => BuildImportedPngAlphaMask(layer, width, height, overlayIndex, inputLabel, outputLabel),
            _ =>
                $"[{inputLabel}]copy[{outputLabel}]"
        };
    }

    private static string BuildImportedPngAlphaMask(
        OverlayLayer layer,
        int width,
        int height,
        int overlayIndex,
        string inputLabel,
        string outputLabel)
    {
        if (string.IsNullOrWhiteSpace(layer.AlphaPngPath))
        {
            return $"[{inputLabel}]copy[{outputLabel}]";
        }

        var escaped = FfmpegFilterPathEscaper.EscapeForFilter(layer.AlphaPngPath);
        var maskLabel = $"ovpng{overlayIndex}";
        return string.Create(
            CultureInfo.InvariantCulture,
            $"movie='{escaped}',scale={width}:{height},format=gray[{maskLabel}];[{inputLabel}][{maskLabel}]alphamerge[{outputLabel}]");
    }

    private static string FormatDecimal(double value) =>
        value.ToString("0.######", CultureInfo.InvariantCulture);

    private static string FormatSeconds(TimeSpan duration) =>
        duration.TotalSeconds.ToString("0.######", CultureInfo.InvariantCulture);
}
