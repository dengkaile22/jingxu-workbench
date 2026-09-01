using System.Globalization;
using System.IO;
using System.Text;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>编译时需要写入临时目录的辅助文件。</summary>
public sealed record FfmpegAuxiliaryFile(string FileName, string Content);

/// <summary>FFmpeg 命令编译结果。</summary>
public sealed record FfmpegCompileResult(
    FfmpegCommand Command,
    IReadOnlyList<FfmpegAuxiliaryFile> AuxiliaryFiles,
    IReadOnlyList<FfmpegInputAlias> InputAliases)
{
    /// <summary>读取内联 <c>-filter_complex</c> 或脚本辅助文件中的滤镜图。</summary>
    public string? TryGetFilterComplex()
    {
        var args = Command.Arguments;
        for (var index = 0; index < args.Count - 1; index++)
        {
            if (args[index] == "-filter_complex")
            {
                return args[index + 1];
            }

            if (args[index] == "-filter_complex_script")
            {
                var fileName = args[index + 1];
                return AuxiliaryFiles
                    .FirstOrDefault(file => file.FileName.Equals(fileName, StringComparison.OrdinalIgnoreCase))
                    ?.Content;
            }
        }

        return null;
    }
}

/// <summary>
/// 将组合计划与输出配置编译为 FFmpeg 参数列表。
/// 绝不拼接 shell 命令行字符串。
/// </summary>
public static class FfmpegCommandCompiler
{
    /// <summary>写入 staging 的滤镜图脚本文件名（配合 <c>-filter_complex_script</c>）。</summary>
    public const string FilterComplexScriptFileName = "filter_complex.txt";

    /// <summary>编译主渲染命令。</summary>
    public static FfmpegCompileResult Compile(
        string ffmpegExecutable,
        RenderRequest request,
        string tempOutputPath,
        VideoEncoderKind encoder = VideoEncoderKind.Libx264)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ffmpegExecutable);
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(tempOutputPath);

        if (request.Plan.Clips.Count == 0)
        {
            throw new InvalidOperationException("组合计划不包含任何片段，无法编译 FFmpeg 命令。");
        }

        var decision = RenderDecision.For(request);
        return decision.CanStreamCopy
            ? CompileStreamCopy(ffmpegExecutable, request, tempOutputPath)
            : CompileTranscode(ffmpegExecutable, request, tempOutputPath, encoder);
    }

    /// <summary>验证命令行长度是否在 Windows 保守预算内。</summary>
    public static Result<Unit> ValidateCommandBudget(FfmpegCommand command) =>
        command.EstimatedCommandLineLength > RenderPreflight.MaxCommandLineLength
            ? Result<Unit>.Failure(
                $"FFmpeg 命令过长（约 {command.EstimatedCommandLineLength} 字符），超过 {RenderPreflight.MaxCommandLineLength} 字符的安全上限。滤镜图已外置为脚本、输入已缩短为 staging 相对路径后仍超限，请减少素材数量或拆分任务。")
            : Result<Unit>.Success(default);

    private static FfmpegCompileResult CompileStreamCopy(
        string ffmpegExecutable,
        RenderRequest request,
        string tempOutputPath)
    {
        // concat 列表写入辅助文件，长路径不占 argv；输出用 staging 相对名。
        var listContent = BuildConcatList(request.Plan);
        var arguments = new List<string>
        {
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", "concat.txt",
            "-c", "copy",
            "-progress", "pipe:1",
            "-nostats",
            Path.GetFileName(tempOutputPath)
        };

        return new FfmpegCompileResult(
            new FfmpegCommand(ffmpegExecutable, arguments),
            [new FfmpegAuxiliaryFile("concat.txt", listContent)],
            []);
    }

    private static FfmpegCompileResult CompileTranscode(
        string ffmpegExecutable,
        RenderRequest request,
        string tempOutputPath,
        VideoEncoderKind encoder)
    {
        var (canvasWidth, canvasHeight) = OutputCanvasResolver.Resolve(request);
        var (targetWidth, targetHeight) = request.OutputVideoSettings.ResolveTargetSize(canvasWidth, canvasHeight);
        var targetFps = request.OutputVideoSettings.ResolveFrameRate(
            request.Plan.Clips[0].Asset.Info.FrameRate);
        var fpsText = FormatDecimal(targetFps);
        var profile = ResolveTranscodeProfile(request.Profile);
        var aliaser = new FfmpegPathAliaser();

        // 这里使用 libx264 + 软件 filter_complex。不要强制自动硬解，否则部分驱动会输出
        // 无法直接进入 scale/crop/overlay 等软件滤镜的硬件帧，导致渲染初始化失败。
        // 所有 -i 使用 staging 短相对路径，避免深目录/中文长路径撑爆 CreateProcess argv。
        var arguments = new List<string> { "-y" };

        foreach (var clip in request.Plan.Clips)
        {
            arguments.Add("-i");
            arguments.Add(aliaser.Alias(clip.Asset.Path));
        }

        var nextInputIndex = request.Plan.Clips.Count;
        var doubleScreenInputIndices = new Dictionary<int, int>();
        var doubleScreenSourceInputIndices = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        if (request.DoubleScreen?.SourceMode == DoubleScreenSourceMode.RandomCurrentFolder)
        {
            foreach (var selection in request.DoubleScreen.ClipSelections.OrderBy(static selection => selection.ClipIndex))
            {
                if (selection.ClipIndex < 0 || selection.ClipIndex >= request.Plan.Clips.Count ||
                    !request.DoubleScreen.AppliesTo(selection.ClipIndex))
                {
                    continue;
                }

                if (doubleScreenInputIndices.ContainsKey(selection.ClipIndex))
                {
                    throw new InvalidOperationException(
                        $"双屏随机素材快照包含重复的视频序号：{selection.ClipIndex + 1}。");
                }

                var sourceAlias = aliaser.Alias(selection.SourceAsset.Path);
                if (!doubleScreenSourceInputIndices.TryGetValue(sourceAlias, out var sourceInputIndex))
                {
                    arguments.Add("-stream_loop");
                    arguments.Add("-1");
                    arguments.Add("-i");
                    arguments.Add(sourceAlias);
                    sourceInputIndex = nextInputIndex++;
                    doubleScreenSourceInputIndices.Add(sourceAlias, sourceInputIndex);
                }

                doubleScreenInputIndices.Add(selection.ClipIndex, sourceInputIndex);
            }
        }

        int? bgmInputIndex = null;
        var stickerInputIndices = new List<int>();

        if (request.HasRenderableBgm && request.Bgm is not null)
        {
            arguments.Add("-i");
            arguments.Add(aliaser.Alias(request.Bgm.Path));
            bgmInputIndex = nextInputIndex++;
        }

        foreach (var sticker in request.Stickers ?? [])
        {
            if (string.IsNullOrWhiteSpace(sticker.Path))
            {
                continue;
            }

            AppendLoopedStickerInput(arguments, aliaser.Alias(sticker.Path));
            stickerInputIndices.Add(nextInputIndex++);
        }

        var overlayBaseLabel = ResolveOverlayBaseVideoLabel(request);
        OverlayFilterCompileResult? overlayResult = null;
        var overlayInputBase = nextInputIndex;
        if (request.HasRenderableOverlays)
        {
            var resolved = OverlayTimelineResolver.ResolveAll(request.Plan, request.OverlayLayers);
            if (!resolved.IsSuccess)
            {
                throw new InvalidOperationException(resolved.Error);
            }

            var overlayCompile = OverlayFilterCompiler.Compile(
                resolved.Value!,
                overlayInputBase,
                targetWidth,
                targetHeight,
                overlayBaseLabel);

            if (!overlayCompile.IsSuccess)
            {
                throw new InvalidOperationException(overlayCompile.Error);
            }

            overlayResult = overlayCompile.Value!;
            arguments.AddRange(aliaser.RewriteDashIArguments(overlayResult!.PreInputArguments));
        }

        var stickerBaseLabel = overlayResult?.FinalVideoLabel ?? overlayBaseLabel;
        var videoOutLabel = stickerInputIndices.Count > 0 ? "vstk" : stickerBaseLabel;
        var filter = BuildFilterGraph(
            request,
            targetWidth,
            targetHeight,
            fpsText,
            overlayResult,
            overlayInputBase,
            bgmInputIndex,
            stickerInputIndices,
            stickerBaseLabel,
            doubleScreenInputIndices);
        // 将滤镜图写入 sidecar，避免 Windows CreateProcess ~32K 命令行上限
        // （蒙版/贴纸/特效叠加后 filter_complex 常达数万字符）。
        arguments.Add("-filter_complex_script");
        arguments.Add(FilterComplexScriptFileName);
        arguments.Add("-map");
        arguments.Add($"[{videoOutLabel}]");
        arguments.Add("-map");
        arguments.Add("[aout]");
        arguments.AddRange(VideoEncoderArguments.Build(encoder, profile));
        arguments.Add("-pix_fmt");
        arguments.Add("yuv420p");
        arguments.Add("-c:a");
        arguments.Add("aac");
        arguments.Add("-b:a");
        arguments.Add($"{profile.AudioKbps}k");
        if (request.Effect?.ClearMetadata == true)
        {
            arguments.Add("-map_metadata");
            arguments.Add("-1");
        }

        arguments.Add("-progress");
        arguments.Add("pipe:1");
        arguments.Add("-nostats");
        arguments.Add(Path.GetFileName(tempOutputPath));

        return new FfmpegCompileResult(
            new FfmpegCommand(ffmpegExecutable, arguments),
            [new FfmpegAuxiliaryFile(FilterComplexScriptFileName, filter)],
            aliaser.Aliases);
    }

    /// <summary>
    /// Lossless is only valid for the stream-copy path. When rendering enters the
    /// transcode path, use a compatible profile instead of emitting zero-bitrate AAC.
    /// </summary>
    private static RenderProfile ResolveTranscodeProfile(RenderProfile profile) =>
        profile.Quality == QualityPreset.Lossless ? RenderProfile.Balanced : profile;

    private static string ResolveOverlayBaseVideoLabel(RenderRequest request)
    {
        return request.Effect?.HasVisualAdjustments == true ? "vfx" : "vbase";
    }

    private static string BuildFilterGraph(
        RenderRequest request,
        int targetWidth,
        int targetHeight,
        string fpsText,
        OverlayFilterCompileResult? overlayResult,
        int overlayInputBase,
        int? bgmInputIndex,
        IReadOnlyList<int> stickerInputIndices,
        string stickerBaseLabel,
        Dictionary<int, int> doubleScreenInputIndices)
    {
        var plan = request.Plan;
        var builder = new StringBuilder();
        var concatInputs = new StringBuilder();
        var mixOverlayLayers = CollectMixOverlayLayers(request, overlayInputBase);
        var needsOverlayAudioMix = mixOverlayLayers.Count > 0;
        var concatAudioLabel = request.HasRenderableBgm || needsOverlayAudioMix ? "a_base" : "aout";

        for (var index = 0; index < plan.Clips.Count; index++)
        {
            var clip = plan.Clips[index];
            var durationSeconds = FormatSeconds(clip.Duration);
            var fitFilter = BuildAspectFitFilter(
                request.Aspect.FitMode,
                targetWidth,
                targetHeight,
                index);

            builder.Append(fitFilter);

            var scaleFactor = ResolveClipScaleFactor(request, index);
            if (scaleFactor > 1.000001)
            {
                builder.Append(BuildMainClipScaleFilter(scaleFactor, targetWidth, targetHeight));
            }

            var doubleScreenApplies = request.DoubleScreen?.AppliesTo(index) == true;
            var fittedVideoLabel = doubleScreenApplies ? $"v{index}fit" : $"v{index}";
            builder.Append(
                CultureInfo.InvariantCulture,
                $"fps={fpsText},setsar=1,format=yuv420p[{fittedVideoLabel}];");

            if (doubleScreenApplies)
            {
                var selection = request.DoubleScreen!.SelectionFor(index);
                var sourceInputIndex = -1;
                if (request.DoubleScreen.SourceMode == DoubleScreenSourceMode.RandomCurrentFolder &&
                    (selection is null || !doubleScreenInputIndices.TryGetValue(index, out sourceInputIndex)))
                {
                    throw new InvalidOperationException(
                        $"第 {index + 1} 个视频缺少双屏随机素材快照，无法开始渲染。请重新入队。 ");
                }

                var featherPixels = request.DoubleScreen.FeatherEnabled
                    ? request.DoubleScreen.FeatherPixels
                    : 0;
                if (selection is not null && doubleScreenInputIndices.TryGetValue(index, out sourceInputIndex))
                {
                    builder.Append(BuildDoubleScreenFilter(
                        index,
                        sourceInputIndex,
                        targetWidth,
                        targetHeight,
                        selection.Placement,
                        request.DoubleScreen.FeatherEnabled,
                        featherPixels,
                        durationSeconds,
                        fpsText));
                }
                else
                {
                    builder.Append(BuildDoubleScreenFilter(
                        index,
                        targetWidth,
                        targetHeight,
                        featherPixels));
                }
            }

            if (clip.Asset.Info.HasAudio)
            {
                builder.Append(BuildMainClipAudioFilter(request, index, clip.Duration));
            }
            else
            {
                builder.Append(CultureInfo.InvariantCulture,
                    $"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={durationSeconds},asetpts=PTS-STARTPTS[a{index}];");
            }

            concatInputs.Append(CultureInfo.InvariantCulture, $"[v{index}][a{index}]");
        }

        builder.Append(CultureInfo.InvariantCulture,
            $"{concatInputs}concat=n={plan.Clips.Count}:v=1:a=1[vbase][{concatAudioLabel}]");

        AppendEffectChain(builder, request, targetWidth, targetHeight);

        if (overlayResult is not null)
        {
            builder.Append(';');
            builder.Append(overlayResult.FilterSuffix);
        }

        AppendStickerChain(
            builder,
            request,
            targetWidth,
            targetHeight,
            stickerInputIndices,
            stickerBaseLabel);

        var audioAfterBgm = concatAudioLabel;
        if (request.HasRenderableBgm)
        {
            var bgmOutput = needsOverlayAudioMix ? "a_bgm" : "aout";
            builder.Append(';');
            builder.Append(AudioFilterCompiler.Compile(new AudioMixCompileRequest(
                MainAudioLabel: concatAudioLabel,
                OutputDuration: plan.Duration,
                BgmInputIndex: bgmInputIndex,
                Bgm: request.Bgm,
                MainHasAudio: plan.Clips.Any(c => c.Asset.Info.HasAudio),
                OutputLabel: bgmOutput)));
            audioAfterBgm = bgmOutput;
        }

        if (needsOverlayAudioMix)
        {
            builder.Append(';');
            builder.Append(AudioFilterCompiler.CompileOverlayMix(
                audioAfterBgm,
                mixOverlayLayers,
                plan.Duration));
        }

        return builder.ToString();
    }

    /// <summary>双屏中缝默认羽化带宽（像素）；实际还会按半高收紧，并取偶数以兼容 yuv420。</summary>
    internal const int DefaultDoubleScreenBlendPixels = 48;

    /// <summary>
    /// 上下双屏：各半高放大裁切后，在中缝用垂直 alpha 渐变软过渡（避免硬切缝）。
    /// 奇数总高时上半 <c>H/2</c>、下半 <c>H-H/2</c>，保证拼回原画布高度。
    /// </summary>
    internal static string BuildDoubleScreenFilter(int clipIndex, int targetWidth, int targetHeight)
        => BuildDoubleScreenFilter(
            clipIndex,
            targetWidth,
            targetHeight,
            DefaultDoubleScreenBlendPixels);

    private static string BuildDoubleScreenFilter(
        int clipIndex,
        int targetWidth,
        int targetHeight,
        int requestedBlendPixels)
    {
        // 奇数高度时不能简单除以 2，否则上下叠完会少 1 像素，导致 concat 尺寸不匹配。
        var topHeight = targetHeight / 2;
        var bottomHeight = targetHeight - topHeight;
        var blend = ResolveDoubleScreenBlendPixels(topHeight, bottomHeight, requestedBlendPixels);
        if (blend < 2)
        {
            return string.Create(
                CultureInfo.InvariantCulture,
                $"[v{clipIndex}fit]split=2[v{clipIndex}top_src][v{clipIndex}bottom_src];" +
                $"[v{clipIndex}top_src]scale={targetWidth}:{topHeight}:force_original_aspect_ratio=increase," +
                $"crop={targetWidth}:{topHeight}:(iw-ow)/2:(ih-oh)/2[v{clipIndex}top];" +
                $"[v{clipIndex}bottom_src]scale={targetWidth}:{bottomHeight}:force_original_aspect_ratio=increase," +
                $"crop={targetWidth}:{bottomHeight}:(iw-ow)/2:(ih-oh)/2[v{clipIndex}bottom];" +
                $"[v{clipIndex}top][v{clipIndex}bottom]vstack=inputs=2[v{clipIndex}];");
        }

        // 上下各多裁 blend 像素重叠，顶层在重叠带内 alpha 线性降到 0，露出下层 → 中缝渐变过渡。
        var topCropHeight = topHeight + blend;
        var bottomCropHeight = bottomHeight + blend;
        var fadeStart = topHeight - blend;
        return string.Create(
            CultureInfo.InvariantCulture,
            $"[v{clipIndex}fit]split=2[v{clipIndex}top_src][v{clipIndex}bottom_src];" +
            $"[v{clipIndex}top_src]scale={targetWidth}:{topCropHeight}:force_original_aspect_ratio=increase," +
            $"crop={targetWidth}:{topCropHeight}:(iw-ow)/2:(ih-oh)/2,format=rgba," +
            $"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(Y,{fadeStart}),255,if(gte(Y,{topHeight}),0,255*({topHeight}-Y)/{blend}))'[v{clipIndex}top];" +
            $"[v{clipIndex}bottom_src]scale={targetWidth}:{bottomCropHeight}:force_original_aspect_ratio=increase," +
            $"crop={targetWidth}:{bottomCropHeight}:(iw-ow)/2:(ih-oh)/2[v{clipIndex}bottom];" +
            $"[v{clipIndex}bottom]pad={targetWidth}:{targetHeight}:0:{fadeStart}:black[v{clipIndex}base];" +
            $"[v{clipIndex}base][v{clipIndex}top]overlay=0:0,format=yuv420p[v{clipIndex}];");
    }

    /// <summary>
    /// 使用已物化的外部视频素材生成双屏滤镜。外部输入会循环并裁切到当前片段时长，
    /// 因而不会因为随机素材比主片短而让 overlay 提前结束。
    /// </summary>
    internal static string BuildDoubleScreenFilter(
        int clipIndex,
        int sourceInputIndex,
        int targetWidth,
        int targetHeight,
        DoubleScreenPlacement placement,
        bool featherEnabled,
        int featherPixels,
        string durationSeconds,
        string fpsText)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(durationSeconds);
        ArgumentException.ThrowIfNullOrWhiteSpace(fpsText);

        var topHeight = targetHeight / 2;
        var bottomHeight = targetHeight - topHeight;
        var blend = featherEnabled
            ? ResolveDoubleScreenBlendPixels(topHeight, bottomHeight, featherPixels)
            : 0;
        var auxSourceLabel = $"ds{clipIndex}aux_src";
        var topInputLabel = placement == DoubleScreenPlacement.Top
            ? auxSourceLabel
            : $"v{clipIndex}fit";
        var bottomInputLabel = placement == DoubleScreenPlacement.Top
            ? $"v{clipIndex}fit"
            : auxSourceLabel;
        var builder = new StringBuilder();

        builder.Append(CultureInfo.InvariantCulture,
            $"[{sourceInputIndex}:v]fps={fpsText},trim=duration={durationSeconds},setpts=PTS-STARTPTS[{auxSourceLabel}];");

        if (blend < 2)
        {
            builder.Append(CultureInfo.InvariantCulture,
                $"[{topInputLabel}]scale={targetWidth}:{topHeight}:force_original_aspect_ratio=increase," +
                $"crop={targetWidth}:{topHeight}:(iw-ow)/2:(ih-oh)/2[ds{clipIndex}top];" +
                $"[{bottomInputLabel}]scale={targetWidth}:{bottomHeight}:force_original_aspect_ratio=increase," +
                $"crop={targetWidth}:{bottomHeight}:(iw-ow)/2:(ih-oh)/2[ds{clipIndex}bottom];" +
                $"[ds{clipIndex}top][ds{clipIndex}bottom]vstack=inputs=2[v{clipIndex}];");
            return builder.ToString();
        }

        var topCropHeight = topHeight + blend;
        var bottomCropHeight = bottomHeight + blend;
        var fadeStart = topHeight - blend;
        builder.Append(CultureInfo.InvariantCulture,
            $"[{topInputLabel}]scale={targetWidth}:{topCropHeight}:force_original_aspect_ratio=increase," +
            $"crop={targetWidth}:{topCropHeight}:(iw-ow)/2:(ih-oh)/2,format=rgba," +
            $"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(Y,{fadeStart}),255,if(gte(Y,{topHeight}),0,255*({topHeight}-Y)/{blend}))'[ds{clipIndex}top];" +
            $"[{bottomInputLabel}]scale={targetWidth}:{bottomCropHeight}:force_original_aspect_ratio=increase," +
            $"crop={targetWidth}:{bottomCropHeight}:(iw-ow)/2:(ih-oh)/2[ds{clipIndex}bottom];" +
            $"[ds{clipIndex}bottom]pad={targetWidth}:{targetHeight}:0:{fadeStart}:black[ds{clipIndex}base];" +
            $"[ds{clipIndex}base][ds{clipIndex}top]overlay=0:0,format=yuv420p[v{clipIndex}];");
        return builder.ToString();
    }

    /// <summary>按半高收紧中缝羽化带宽；过矮时返回 0，调用方回退硬切 vstack。</summary>
    internal static int ResolveDoubleScreenBlendPixels(int topHeight, int bottomHeight)
        => ResolveDoubleScreenBlendPixels(
            topHeight,
            bottomHeight,
            DefaultDoubleScreenBlendPixels);

    private static int ResolveDoubleScreenBlendPixels(
        int topHeight,
        int bottomHeight,
        int requestedBlendPixels)
    {
        var maxBand = Math.Min(topHeight, bottomHeight) / 3;
        if (maxBand < 2 || requestedBlendPixels < 2)
        {
            return 0;
        }

        var blend = Math.Min(requestedBlendPixels, maxBand);
        if ((blend & 1) != 0)
        {
            blend--;
        }

        return blend < 2 ? 0 : blend;
    }

    private static List<(int InputIndex, TimeSpan Start, TimeSpan ActiveDuration)> CollectMixOverlayLayers(
        RenderRequest request,
        int overlayInputBase)
    {
        if (!request.HasRenderableOverlays || request.OverlayLayers is null || request.OverlayLayers.Count == 0)
        {
            return [];
        }

        var resolved = OverlayTimelineResolver.ResolveAll(request.Plan, request.OverlayLayers);
        if (!resolved.IsSuccess)
        {
            return [];
        }

        var mix = new List<(int InputIndex, TimeSpan Start, TimeSpan ActiveDuration)>();
        var nextInputIndex = overlayInputBase;
        foreach (var layerResolved in resolved.Value!)
        {
            if (layerResolved.Layer.IsSelfSource)
            {
                // 自叠影无外部输入、无独立音轨。
                continue;
            }

            var inputIndex = nextInputIndex++;
            if (layerResolved.Layer.AudioMode != OverlayAudioMode.Mix)
            {
                continue;
            }

            mix.Add((inputIndex, layerResolved.Start, layerResolved.ActiveDuration));
        }

        return mix;
    }

    private static void AppendEffectChain(
        StringBuilder builder,
        RenderRequest request,
        int targetWidth,
        int targetHeight)
    {
        if (request.Effect?.HasVisualAdjustments != true)
        {
            return;
        }

        builder.Append(';');
        builder.Append(EffectFilterCompiler.Compile(
            request.Effect,
            "vbase",
            "vfx",
            outputWidth: targetWidth,
            outputHeight: targetHeight));
    }

    private static void AppendStickerChain(
        StringBuilder builder,
        RenderRequest request,
        int targetWidth,
        int targetHeight,
        IReadOnlyList<int> stickerInputIndices,
        string inputVideoLabel)
    {
        var stickers = (request.Stickers ?? [])
            .Where(s => !string.IsNullOrWhiteSpace(s.Path))
            .ToList();

        if (stickers.Count > 0 && stickerInputIndices.Count > 0)
        {
            var validCount = Math.Min(stickers.Count, stickerInputIndices.Count);
            if (validCount > 0)
            {
                var validStickers = stickers.Take(validCount).ToList();
                var validIndices = stickerInputIndices.Take(validCount).ToList();

                if (builder.Length > 0)
                {
                    builder.Append(';');
                }

                var chain = EffectFilterCompiler.CompileChain(
                    effect: null,
                    validStickers,
                    inputVideoLabel,
                    outputVideoLabel: "vfx",
                    stickerOutputLabel: "vstk",
                    validIndices,
                    frameWidth: targetWidth,
                    frameHeight: targetHeight);
                builder.Append(chain.FilterSuffix);
            }
        }
    }

    internal static string BuildAspectFitFilter(
        AspectFitMode requestFitMode,
        int targetWidth,
        int targetHeight,
        int inputIndex)
    {
        var inputLabel = $"[{inputIndex}:v]";
        return requestFitMode switch
        {
            AspectFitMode.CenterCrop =>
                $"{inputLabel}scale={targetWidth}:{targetHeight}:force_original_aspect_ratio=increase,crop={targetWidth}:{targetHeight},",
            AspectFitMode.Letterbox =>
                $"{inputLabel}scale={targetWidth}:{targetHeight}:force_original_aspect_ratio=decrease,pad={targetWidth}:{targetHeight}:(ow-iw)/2:(oh-ih)/2:black,",
            AspectFitMode.BlurBackground =>
                $"{inputLabel}split[bg{inputIndex}][fg{inputIndex}];" +
                $"[bg{inputIndex}]scale={targetWidth}:{targetHeight},boxblur=20:1[bgblur{inputIndex}];" +
                $"[fg{inputIndex}]scale={targetWidth}:{targetHeight}:force_original_aspect_ratio=decrease[fgfit{inputIndex}];" +
                $"[bgblur{inputIndex}][fgfit{inputIndex}]overlay=(W-w)/2:(H-h)/2,",
            AspectFitMode.Stretch =>
                $"{inputLabel}scale={targetWidth}:{targetHeight},",
            _ => throw new ArgumentOutOfRangeException(nameof(requestFitMode), requestFitMode, null)
        };
    }

    /// <summary>
    /// 主轨缩放：适配画幅后放大再中心裁回目标尺寸（仅主素材；蒙版层不走此路径）。
    /// </summary>
    internal static string BuildMainClipScaleFilter(double scaleFactor, int targetWidth, int targetHeight)
    {
        var factor = FormatDouble(scaleFactor);
        return string.Create(
            CultureInfo.InvariantCulture,
            $"scale=iw*{factor}:ih*{factor},crop={targetWidth}:{targetHeight}:(iw-ow)/2:(ih-oh)/2,");
    }

    /// <summary>
    /// 主轨音频：格式统一 →（可选）loudnorm 响度归一 →（可选）volume 增益 →
    /// 按分镜时长 atrim（loudnorm 单遍会改变样本长度，不裁切会导致成片时长校验失败）。
    /// </summary>
    internal static string BuildMainClipAudioFilter(RenderRequest request, int clipIndex, TimeSpan clipDuration)
    {
        var boost = request.HasRenderableMainMaterialBoost ? request.MainMaterialBoost : null;
        var durationSeconds = FormatSeconds(clipDuration);
        var builder = new StringBuilder();
        builder.Append(CultureInfo.InvariantCulture,
            $"[{clipIndex}:a]aformat=sample_rates=48000:channel_layouts=stereo,aresample=48000");

        if (boost?.NormalizeLoudness == true)
        {
            // 单遍 loudnorm：统一各拼接素材响度后再调大（非双遍测量，短片段可能略偏）。
            builder.Append(",loudnorm=I=-16:TP=-1.5:LRA=11");
        }

        if (boost?.EnableVolume == true)
        {
            var factor = ResolveClipVolumeFactor(boost, clipIndex);
            if (Math.Abs(factor - 1.0) > 0.000001)
            {
                builder.Append(CultureInfo.InvariantCulture, $",volume={FormatDouble(factor)}");
            }
        }

        // 始终对齐到分镜时长，避免 loudnorm/重采样导致音轨略长于视频。
        builder.Append(CultureInfo.InvariantCulture,
            $",atrim=duration={durationSeconds},asetpts=PTS-STARTPTS[a{clipIndex}];");
        return builder.ToString();
    }

    private static double ResolveClipScaleFactor(RenderRequest request, int clipIndex)
    {
        if (!request.HasRenderableMainMaterialBoost ||
            request.MainMaterialBoost?.EnableScale != true)
        {
            return 1.0;
        }

        var factors = request.MainMaterialBoost.ScaleFactors;
        return clipIndex >= 0 && clipIndex < factors.Count ? factors[clipIndex] : 1.0;
    }

    private static double ResolveClipVolumeFactor(MaterializedMainMaterialBoost boost, int clipIndex)
    {
        var factors = boost.VolumeFactors;
        return clipIndex >= 0 && clipIndex < factors.Count ? factors[clipIndex] : 1.0;
    }

    /// <summary>
    /// 贴纸输入循环到主片结束：静图用 <c>-loop 1</c>，GIF/视频用 <c>-stream_loop -1</c>，
    /// 配合 overlay 的 <c>shortest=1</c> 覆盖整段拼接时长。
    /// </summary>
    private static void AppendLoopedStickerInput(List<string> arguments, string path)
    {
        if (IsStaticImageSticker(path))
        {
            arguments.Add("-loop");
            arguments.Add("1");
        }
        else
        {
            arguments.Add("-stream_loop");
            arguments.Add("-1");
        }

        arguments.Add("-i");
        arguments.Add(path);
    }

    private static bool IsStaticImageSticker(string path)
    {
        var extension = Path.GetExtension(path);
        return extension.Equals(".png", StringComparison.OrdinalIgnoreCase)
            || extension.Equals(".jpg", StringComparison.OrdinalIgnoreCase)
            || extension.Equals(".jpeg", StringComparison.OrdinalIgnoreCase)
            || extension.Equals(".bmp", StringComparison.OrdinalIgnoreCase)
            || extension.Equals(".webp", StringComparison.OrdinalIgnoreCase);
    }

    private static string BuildConcatList(CompositionPlan plan)
    {
        var builder = new StringBuilder();
        foreach (var clip in plan.Clips)
        {
            var escaped = EscapeConcatPath(clip.Asset.Path);
            builder.Append("file '").Append(escaped).Append('\'').AppendLine();
        }

        return builder.ToString();
    }

    internal static string EscapeConcatPath(string absolutePath) =>
        absolutePath.Replace('\\', '/').Replace("'", "'\\''", StringComparison.Ordinal);

    private static string FormatDecimal(decimal value) =>
        value.ToString(CultureInfo.InvariantCulture);

    private static string FormatDouble(double value) =>
        value.ToString("0.######", CultureInfo.InvariantCulture);

    private static string FormatSeconds(TimeSpan duration) =>
        duration.TotalSeconds.ToString("0.######", CultureInfo.InvariantCulture);
}
