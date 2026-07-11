using JingXu.Workbench.Domain.Common;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Application.Subtitles;

/// <summary>OCR 帧观测（用于跨帧聚类）。</summary>
public sealed record OcrFrameObservation(
    TimeSpan Timestamp,
    NormalizedRect Region,
    double Confidence);

/// <summary>将抖动 OCR 框聚类为稳定字幕区域。</summary>
public static class SubtitleRegionClusterer
{
    private static readonly TimeSpan MaxTimeGap = TimeSpan.FromSeconds(1.5);
    private const double MinIoU = 0.35;
    private const double LowConfidenceThreshold = 0.55;

    /// <summary>按时间与区域 IoU 聚类；低置信度簇标记为需审阅。</summary>
    public static IReadOnlyList<DetectedSubtitleSegment> Cluster(IReadOnlyList<OcrFrameObservation> observations)
    {
        ArgumentNullException.ThrowIfNull(observations);
        if (observations.Count == 0)
        {
            return [];
        }

        var ordered = observations.OrderBy(x => x.Timestamp).ToArray();
        var clusters = new List<List<OcrFrameObservation>> { new() { ordered[0] } };

        for (var i = 1; i < ordered.Length; i++)
        {
            var current = ordered[i];
            var lastCluster = clusters[^1];
            var last = lastCluster[^1];
            var timeGap = current.Timestamp - last.Timestamp;
            var iou = ComputeIoU(last.Region, current.Region);

            if (timeGap <= MaxTimeGap && iou >= MinIoU)
            {
                lastCluster.Add(current);
            }
            else
            {
                clusters.Add(new() { current });
            }
        }

        return clusters.Select(BuildSegment).ToArray();
    }

    private static DetectedSubtitleSegment BuildSegment(IReadOnlyList<OcrFrameObservation> cluster)
    {
        var xs = cluster.Select(x => x.Region.X).OrderBy(x => x).ToArray();
        var ys = cluster.Select(x => x.Region.Y).OrderBy(x => x).ToArray();
        var rights = cluster.Select(x => x.Region.Right).OrderBy(x => x).ToArray();
        var bottoms = cluster.Select(x => x.Region.Bottom).OrderBy(x => x).ToArray();

        var medianX = xs[xs.Length / 2];
        var medianY = ys[ys.Length / 2];
        var medianRight = rights[rights.Length / 2];
        var medianBottom = bottoms[bottoms.Length / 2];
        var region = new NormalizedRect(
            medianX,
            medianY,
            Math.Max(0.01, medianRight - medianX),
            Math.Max(0.01, medianBottom - medianY));

        var avgConfidence = cluster.Average(x => x.Confidence);
        var requiresReview = avgConfidence < LowConfidenceThreshold
            || cluster.Any(x => x.Confidence < LowConfidenceThreshold);

        return new DetectedSubtitleSegment(
            region,
            cluster.Min(x => x.Timestamp),
            cluster.Max(x => x.Timestamp),
            avgConfidence,
            SubtitleReviewState.Unreviewed,
            requiresReview);
    }

    private static double ComputeIoU(NormalizedRect a, NormalizedRect b)
    {
        var left = Math.Max(a.X, b.X);
        var top = Math.Max(a.Y, b.Y);
        var right = Math.Min(a.Right, b.Right);
        var bottom = Math.Min(a.Bottom, b.Bottom);
        var intersection = Math.Max(0, right - left) * Math.Max(0, bottom - top);
        var union = a.Width * a.Height + b.Width * b.Height - intersection;
        return union <= 0 ? 0 : intersection / union;
    }
}
