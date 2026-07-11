using System.Globalization;
using System.Text;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>编译时需要写入临时目录的辅助文件。</summary>
public sealed record FfmpegAuxiliaryFile(string FileName, string Content);

/// <summary>FFmpeg 命令编译结果。</summary>
public sealed record FfmpegCompileResult(
    FfmpegCommand Command,
    IReadOnlyList<FfmpegAuxiliaryFile> AuxiliaryFiles);

/// <summary>
/// 将组合计划与输出配置编译为 FFmpeg 参数列表。
/// 绝不拼接 shell 命令行字符串。
/// </summary>
public static class FfmpegCommandCompiler
{
    /// <summary>编译主渲染命令。</summary>
    public static FfmpegCompileResult Compile(string ffmpegExecutable, RenderRequest request, string tempOutputPath)
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
            : CompileTranscode(ffmpegExecutable, request, tempOutputPath);
    }

    /// <summary>验证命令行长度是否在 Windows 保守预算内。</summary>
    public static Result<Unit> ValidateCommandBudget(FfmpegCommand command) =>
        command.EstimatedCommandLineLength > RenderPreflight.MaxCommandLineLength
            ? Result<Unit>.Failure(
                $"FFmpeg 命令过长（约 {command.EstimatedCommandLineLength} 字符），超过 {RenderPreflight.MaxCommandLineLength} 字符的安全上限。请减少素材数量或拆分任务。")
            : Result<Unit>.Success(default);

    private static FfmpegCompileResult CompileStreamCopy(
        string ffmpegExecutable,
        RenderRequest request,
        string tempOutputPath)
    {
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
            tempOutputPath
        };

        return new FfmpegCompileResult(
            new FfmpegCommand(ffmpegExecutable, arguments),
            [new FfmpegAuxiliaryFile("concat.txt", listContent)]);
    }

    private static FfmpegCompileResult CompileTranscode(
        string ffmpegExecutable,
        RenderRequest request,
        string tempOutputPath)
    {
        var (targetWidth, targetHeight) = ResolveTargetSize(request);
        var targetFps = request.Plan.Clips[0].Asset.Info.FrameRate;
        var fpsText = FormatDecimal(targetFps);

        var arguments = new List<string> { "-y" };
        foreach (var clip in request.Plan.Clips)
        {
            arguments.Add("-i");
            arguments.Add(clip.Asset.Path);
        }

        var nextInputIndex = request.Plan.Clips.Count;
        int? bgmInputIndex = null;
        int? stickerInputIndex = null;

        if (request.HasRenderableBgm && request.Bgm is not null)
        {
            arguments.Add("-i");
            arguments.Add(request.Bgm.Path);
            bgmInputIndex = nextInputIndex++;
        }

        if (request.Sticker is not null)
        {
            arguments.Add("-i");
            arguments.Add(request.Sticker.Path);
            stickerInputIndex = nextInputIndex++;
        }

        var overlayBaseLabel = ResolveOverlayBaseVideoLabel(request);
        OverlayFilterCompileResult? overlayResult = null;
        if (request.HasRenderableOverlays)
        {
            var resolved = OverlayTimelineResolver.ResolveAll(request.Plan, request.OverlayLayers);
            if (!resolved.IsSuccess)
            {
                throw new InvalidOperationException(resolved.Error);
            }

            var overlayCompile = OverlayFilterCompiler.Compile(
                resolved.Value!,
                nextInputIndex,
                targetWidth,
                targetHeight,
                overlayBaseLabel);

            if (!overlayCompile.IsSuccess)
            {
                throw new InvalidOperationException(overlayCompile.Error);
            }

            overlayResult = overlayCompile.Value!;
            arguments.AddRange(overlayResult!.PreInputArguments);
        }

        var videoOutLabel = overlayResult?.FinalVideoLabel ?? overlayBaseLabel;
        var filter = BuildFilterGraph(
            request,
            targetWidth,
            targetHeight,
            fpsText,
            overlayResult,
            bgmInputIndex,
            stickerInputIndex);
        arguments.Add("-filter_complex");
        arguments.Add(filter);
        arguments.Add("-map");
        arguments.Add($"[{videoOutLabel}]");
        arguments.Add("-map");
        arguments.Add("[aout]");
        arguments.Add("-c:v");
        arguments.Add("libx264");
        arguments.Add("-crf");
        arguments.Add((request.Profile.Crf ?? 22).ToString(CultureInfo.InvariantCulture));
        arguments.Add("-pix_fmt");
        arguments.Add("yuv420p");
        arguments.Add("-c:a");
        arguments.Add("aac");
        arguments.Add("-b:a");
        arguments.Add($"{request.Profile.AudioKbps}k");
        if (request.Effect?.ClearMetadata == true)
        {
            arguments.Add("-map_metadata");
            arguments.Add("-1");
        }

        arguments.Add("-progress");
        arguments.Add("pipe:1");
        arguments.Add("-nostats");
        arguments.Add(tempOutputPath);

        return new FfmpegCompileResult(new FfmpegCommand(ffmpegExecutable, arguments), []);
    }

    private static string ResolveOverlayBaseVideoLabel(RenderRequest request)
    {
        var label = "vbase";
        if (request.Effect?.HasVisualAdjustments == true)
        {
            label = "vfx";
        }

        if (request.Sticker is not null)
        {
            label = "vstk";
        }

        return label;
    }

    private static string BuildFilterGraph(
        RenderRequest request,
        int targetWidth,
        int targetHeight,
        string fpsText,
        OverlayFilterCompileResult? overlayResult,
        int? bgmInputIndex,
        int? stickerInputIndex)
    {
        var plan = request.Plan;
        var builder = new StringBuilder();
        var concatInputs = new StringBuilder();
        var audioOutLabel = request.HasRenderableBgm ? "aout_raw" : "aout";

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
            builder.Append(CultureInfo.InvariantCulture, $"fps={fpsText},setsar=1,format=yuv420p[v{index}];");

            if (clip.Asset.Info.HasAudio)
            {
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{index}:a]aformat=sample_rates=48000:channel_layouts=stereo,aresample=48000[a{index}];");
            }
            else
            {
                builder.Append(CultureInfo.InvariantCulture,
                    $"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={durationSeconds},asetpts=PTS-STARTPTS[a{index}];");
            }

            concatInputs.Append(CultureInfo.InvariantCulture, $"[v{index}][a{index}]");
        }

        builder.Append(CultureInfo.InvariantCulture,
            $"{concatInputs}concat=n={plan.Clips.Count}:v=1:a=1[vbase][{audioOutLabel}]");

        AppendEffectAndStickerChain(builder, request, targetWidth, targetHeight, stickerInputIndex);

        if (overlayResult is not null)
        {
            builder.Append(';');
            builder.Append(overlayResult.FilterSuffix);
        }

        if (request.HasRenderableBgm)
        {
            builder.Append(';');
            builder.Append(AudioFilterCompiler.Compile(new AudioMixCompileRequest(
                MainAudioLabel: audioOutLabel,
                OutputDuration: plan.Duration,
                BgmInputIndex: bgmInputIndex,
                Bgm: request.Bgm,
                MainHasAudio: plan.Clips.Any(c => c.Asset.Info.HasAudio))));
        }

        return builder.ToString();
    }

    private static void AppendEffectAndStickerChain(
        StringBuilder builder,
        RenderRequest request,
        int targetWidth,
        int targetHeight,
        int? stickerInputIndex)
    {
        var currentLabel = "vbase";
        var wroteSegment = false;

        if (request.Effect?.HasVisualAdjustments == true)
        {
            builder.Append(';');
            builder.Append(EffectFilterCompiler.Compile(request.Effect, currentLabel, "vfx"));
            currentLabel = "vfx";
            wroteSegment = true;
        }

        if (request.Sticker is not null && stickerInputIndex is not null)
        {
            builder.Append(wroteSegment ? ';' : ';');
            builder.Append(EffectFilterCompiler.CompileStickerForFrame(
                request.Sticker,
                currentLabel,
                stickerInputIndex.Value,
                targetWidth,
                targetHeight,
                "vstk"));
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

    private static (int Width, int Height) ResolveTargetSize(RenderRequest request)
    {
        if (!request.Aspect.InheritFromFirstClip &&
            request.Aspect.TargetWidth is > 0 &&
            request.Aspect.TargetHeight is > 0)
        {
            return (request.Aspect.TargetWidth.Value, request.Aspect.TargetHeight.Value);
        }

        var first = request.Plan.Clips[0].Asset.Info;
        return NormalizeDimensions(first);
    }

    internal static (int Width, int Height) NormalizeDimensions(MediaInfo info) =>
        info.RotationDegrees is 90 or 270
            ? (info.Height, info.Width)
            : (info.Width, info.Height);

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

    private static string FormatSeconds(TimeSpan duration) =>
        duration.TotalSeconds.ToString("0.######", CultureInfo.InvariantCulture);
}
