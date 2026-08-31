using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Domain.Effects;

/// <summary>
/// 上下双屏效果：按最终成片中的片段序号，从指定片段开始一直应用到结尾。
/// </summary>
public sealed record DoubleScreenEffectPlan(int StartClipIndex)
{
    public static Result<DoubleScreenEffectPlan> Create(int startClipIndex) =>
        startClipIndex < 1
            ? Result<DoubleScreenEffectPlan>.Failure("双屏起始视频必须从 1 开始。")
            : Result<DoubleScreenEffectPlan>.Success(new DoubleScreenEffectPlan(startClipIndex));

    public bool AppliesTo(int zeroBasedClipIndex) =>
        zeroBasedClipIndex >= 0 && zeroBasedClipIndex + 1 >= StartClipIndex;
}
