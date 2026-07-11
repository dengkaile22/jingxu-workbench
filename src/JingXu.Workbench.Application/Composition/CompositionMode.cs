namespace JingXu.Workbench.Application.Composition;

/// <summary>混剪编排模式：随机批量或自定义序号。</summary>
public enum CompositionMode
{
    /// <summary>按种子生成随机排列的批量成片。</summary>
    Random,

    /// <summary>按序号表达式生成固定顺序成片。</summary>
    CustomSequence
}
