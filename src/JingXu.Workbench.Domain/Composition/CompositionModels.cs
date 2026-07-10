using JingXu.Workbench.Domain.Media;

namespace JingXu.Workbench.Domain.Composition;

/// <summary>
/// 组合计划中的单个片段，记录素材、起始时间和时长。
/// </summary>
public sealed record PlannedClip(
    MediaAsset Asset,
    TimeSpan Start,
    TimeSpan Duration);

/// <summary>
/// 完整的成片组合计划：已展开的片段列表、总时长、种子和转场时长。
/// </summary>
public sealed record CompositionPlan(
    IReadOnlyList<PlannedClip> Clips,
    TimeSpan Duration,
    int Seed,
    TimeSpan TransitionDuration);
