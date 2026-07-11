namespace JingXu.Workbench.Domain.Rendering;

/// <summary>异比例素材在输出画幅中的适配方式。</summary>
public enum AspectFitMode
{
    /// <summary>居中裁切填满目标画幅。</summary>
    CenterCrop,

    /// <summary>模糊背景填充。</summary>
    BlurBackground,

    /// <summary>黑边/信箱模式（Contain）。</summary>
    Letterbox,

    /// <summary>拉伸至目标画幅（Stretch）。</summary>
    Stretch
}

/// <summary>输出画幅策略。</summary>
public sealed record OutputAspect(
    bool InheritFromFirstClip,
    int? TargetWidth,
    int? TargetHeight,
    AspectFitMode FitMode)
{
    /// <summary>继承第一条素材的画幅，默认居中裁切。</summary>
    public static OutputAspect InheritFirst { get; } =
        new(true, null, null, AspectFitMode.CenterCrop);

    /// <summary>指定目标分辨率。</summary>
    public static OutputAspect Custom(int width, int height, AspectFitMode fitMode = AspectFitMode.CenterCrop) =>
        new(false, width, height, fitMode);
}
