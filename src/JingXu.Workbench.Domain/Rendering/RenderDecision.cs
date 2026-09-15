using JingXu.Workbench.Domain.Composition;

namespace JingXu.Workbench.Domain.Rendering;

/// <summary>根据请求快照判断能否使用 concat 直拷。</summary>
public sealed record RenderDecision(bool CanStreamCopy, IReadOnlyList<TranscodeReason> Reasons)
{
    /// <summary>分析请求并给出转码决策。</summary>
    public static RenderDecision For(RenderRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        var reasons = new List<TranscodeReason>();

        if (request.HasOverlays)
        {
            reasons.Add(TranscodeReason.Overlay);
        }

        if (request.HasEffects || request.DoubleScreen is not null || request.FourScreen is not null)
        {
            reasons.Add(TranscodeReason.Effects);
        }

        if (request.HasSubtitles)
        {
            reasons.Add(TranscodeReason.Subtitle);
        }

        if (request.HasBgm)
        {
            reasons.Add(TranscodeReason.Bgm);
        }

        if (request.HasRenderableMainMaterialBoost)
        {
            reasons.Add(TranscodeReason.MainMaterialBoost);
        }

        if (!request.Aspect.InheritFromFirstClip)
        {
            reasons.Add(TranscodeReason.AspectChange);
        }

        if (!request.OutputVideoSettings.IsOriginalResolution)
        {
            reasons.Add(TranscodeReason.OutputResolution);
        }

        if (!request.OutputVideoSettings.IsOriginalFrameRate)
        {
            reasons.Add(TranscodeReason.OutputFrameRate);
        }

        if (request.Plan.TransitionDuration > TimeSpan.Zero)
        {
            reasons.Add(TranscodeReason.Transition);
        }

        if (request.Profile.Quality is not QualityPreset.Lossless)
        {
            reasons.Add(TranscodeReason.QualityPreset);
        }

        if (HasStreamMismatch(request.Plan))
        {
            reasons.Add(TranscodeReason.StreamMismatch);
        }

        return new RenderDecision(reasons.Count == 0, reasons);
    }

    private static bool HasStreamMismatch(CompositionPlan plan)
    {
        if (plan.Clips.Count == 0)
        {
            return true;
        }

        var first = plan.Clips[0].Asset.Info;
        foreach (var clip in plan.Clips.Skip(1))
        {
            var info = clip.Asset.Info;
            if (!string.Equals(info.VideoCodec, first.VideoCodec, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (info.Width != first.Width || info.Height != first.Height)
            {
                return true;
            }

            if (info.FrameRate != first.FrameRate)
            {
                return true;
            }

            if (info.HasAudio != first.HasAudio)
            {
                return true;
            }

            if (info.HasAudio &&
                !string.Equals(info.AudioCodec ?? string.Empty, first.AudioCodec ?? string.Empty,
                    StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }
}
