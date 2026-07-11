using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Application.Composition;

/// <summary>单条编排预览：序号链与预计时长。</summary>
public sealed record CompositionPreviewPlan(
    int PlanNumber,
    IReadOnlyList<int> Sequence,
    TimeSpan Duration);

/// <summary>编排校验与预览结果。</summary>
public sealed record CompositionPreviewResult(
    bool CanEnqueue,
    string ValidationMessage,
    IReadOnlyList<CompositionPreviewPlan> Plans,
    IReadOnlyList<CompositionPlan> ExecutablePlans);

/// <summary>
/// 素材导入与编排预览的应用层编排。ViewModel 只消费强类型结果，不直接拼接 FFmpeg 参数。
/// </summary>
public static class CompositionOrchestrator
{
    private const int ProbeConcurrency = 4;

    /// <summary>并发探测媒体并解析文件名序号。</summary>
    public static async Task<IReadOnlyList<MediaImportOutcome>> ImportAsync(
        IMediaProbe probe,
        IReadOnlyList<string> absolutePaths,
        CancellationToken cancellationToken)
    {
        if (absolutePaths.Count == 0)
        {
            return [];
        }

        using var gate = new SemaphoreSlim(ProbeConcurrency);
        var tasks = absolutePaths.Select(path => ImportOneAsync(probe, path, gate, cancellationToken));
        var outcomes = await Task.WhenAll(tasks).ConfigureAwait(false);
        return ApplyDuplicateDiagnostics(outcomes);
    }

    /// <summary>根据当前模式生成预览与入队前校验。</summary>
    public static CompositionPreviewResult BuildPreview(
        IReadOnlyList<MediaAsset> assets,
        CompositionMode mode,
        string sequenceExpression,
        int batchCount,
        int randomSeed)
    {
        if (assets.Count == 0)
        {
            return new CompositionPreviewResult(
                false,
                "请先导入至少一个视频素材。",
                [],
                []);
        }

        if (HasDuplicateSequenceIndices(assets))
        {
            return new CompositionPreviewResult(
                false,
                "存在重复序号，自定义序号拼接前请先处理重复项。",
                [],
                []);
        }

        return mode switch
        {
            CompositionMode.Random => BuildRandomPreview(assets, batchCount, randomSeed),
            CompositionMode.CustomSequence => BuildCustomPreview(assets, sequenceExpression),
            _ => new CompositionPreviewResult(false, "未知编排模式。", [], [])
        };
    }

    private static async Task<MediaImportOutcome> ImportOneAsync(
        IMediaProbe probe,
        string absolutePath,
        SemaphoreSlim gate,
        CancellationToken cancellationToken)
    {
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var fileName = Path.GetFileName(absolutePath);
            var indexResult = FileSequenceParser.ExtractIndex(fileName);
            int? sequenceIndex = indexResult.IsSuccess ? indexResult.Value : null;
            string? sequenceWarning = indexResult.IsSuccess
                ? null
                : indexResult.Error;

            try
            {
                var info = await probe.ProbeAsync(absolutePath, cancellationToken).ConfigureAwait(false);
                var asset = new MediaAsset(Guid.NewGuid(), absolutePath, sequenceIndex, info);
                return new MediaImportOutcome(absolutePath, asset, sequenceWarning, null);
            }
            catch (MediaProbeException ex)
            {
                return new MediaImportOutcome(absolutePath, null, sequenceWarning, ex.Message);
            }
            catch (Exception ex)
            {
                return new MediaImportOutcome(
                    absolutePath,
                    null,
                    sequenceWarning,
                    $"媒体探测失败：{ex.Message}");
            }
        }
        finally
        {
            gate.Release();
        }
    }

    private static IReadOnlyList<MediaImportOutcome> ApplyDuplicateDiagnostics(
        IReadOnlyList<MediaImportOutcome> outcomes)
    {
        var indexCounts = outcomes
            .Where(o => o.Asset?.SequenceIndex is not null)
            .GroupBy(o => o.Asset!.SequenceIndex!.Value)
            .Where(g => g.Count() > 1)
            .Select(g => g.Key)
            .ToHashSet();

        if (indexCounts.Count == 0)
        {
            return outcomes;
        }

        return outcomes
            .Select(outcome =>
            {
                if (outcome.Asset?.SequenceIndex is int index && indexCounts.Contains(index))
                {
                    var duplicateMessage = $"序号 {index} 重复，自定义序号拼接前需处理。";
                    var warning = outcome.SequenceWarning is null
                        ? duplicateMessage
                        : $"{outcome.SequenceWarning} {duplicateMessage}";
                    return outcome with { SequenceWarning = warning };
                }

                return outcome;
            })
            .ToArray();
    }

    private static CompositionPreviewResult BuildRandomPreview(
        IReadOnlyList<MediaAsset> assets,
        int batchCount,
        int randomSeed)
    {
        if (batchCount <= 0)
        {
            return new CompositionPreviewResult(
                false,
                "批量数量必须为正整数。",
                [],
                []);
        }

        var result = CompositionPlanner.PlanRandomBatch(assets, batchCount, randomSeed);
        if (!result.IsSuccess)
        {
            return new CompositionPreviewResult(false, result.Error!, [], []);
        }

        var preview = result.Value!
            .Select((plan, index) => ToPreview(index + 1, plan))
            .ToArray();

        return new CompositionPreviewResult(true, string.Empty, preview, result.Value!);
    }

    private static CompositionPreviewResult BuildCustomPreview(
        IReadOnlyList<MediaAsset> assets,
        string sequenceExpression)
    {
        var expressions = FileSequenceParser.SplitExpressions(sequenceExpression);
        if (expressions.Count == 0)
        {
            return new CompositionPreviewResult(
                false,
                "序号表达式不能为空。",
                [],
                []);
        }

        var previews = new List<CompositionPreviewPlan>(expressions.Count);
        var plans = new List<CompositionPlan>(expressions.Count);

        foreach (var expression in expressions)
        {
            var parseResult = FileSequenceParser.Parse(expression);
            if (!parseResult.IsSuccess)
            {
                return new CompositionPreviewResult(
                    false,
                    $"表达式「{expression}」：{parseResult.Error!}",
                    [],
                    []);
            }

            var planResult = CompositionPlanner.PlanCustom(
                assets,
                parseResult.Value!,
                TimeSpan.Zero);

            if (!planResult.IsSuccess)
            {
                return new CompositionPreviewResult(
                    false,
                    $"表达式「{expression}」：{planResult.Error!}",
                    [],
                    []);
            }

            plans.Add(planResult.Value!);
            previews.Add(ToPreview(previews.Count + 1, planResult.Value!));
        }

        return new CompositionPreviewResult(true, string.Empty, previews, plans);
    }

    private static CompositionPreviewPlan ToPreview(int planNumber, CompositionPlan plan)
    {
        var sequence = plan.Clips
            .Select(clip => clip.Asset.SequenceIndex ?? 0)
            .ToArray();

        return new CompositionPreviewPlan(planNumber, sequence, plan.Duration);
    }

    private static bool HasDuplicateSequenceIndices(IReadOnlyList<MediaAsset> assets)
    {
        var seen = new HashSet<int>();
        foreach (var asset in assets)
        {
            if (asset.SequenceIndex is not int index)
            {
                continue;
            }

            if (!seen.Add(index))
            {
                return true;
            }
        }

        return false;
    }
}

/// <summary>单条素材导入结果。</summary>
public sealed record MediaImportOutcome(
    string SourcePath,
    MediaAsset? Asset,
    string? SequenceWarning,
    string? ProbeError);
