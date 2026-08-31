namespace JingXu.Workbench.Domain.Rendering;

/// <summary>导出画面分辨率预设。原画保持当前输出画幅的尺寸不变。</summary>
public enum OutputResolutionPreset
{
    /// <summary>保持当前画幅尺寸。</summary>
    Original,

    /// <summary>短边 480 像素。</summary>
    P480,

    /// <summary>短边 720 像素。</summary>
    P720,

    /// <summary>短边 1080 像素。</summary>
    P1080
}

/// <summary>导出帧率预设。原帧率跟随首段素材，保持既有行为。</summary>
public enum OutputFrameRatePreset
{
    /// <summary>跟随首段素材帧率。</summary>
    Original,

    Fps24,
    Fps25,
    Fps30,
    Fps50,
    Fps60
}

/// <summary>
/// 入队时冻结的导出分辨率与帧率策略。
/// 分辨率只缩放已经确定的输出画幅，不改变统一画幅的裁切、蒙版适配等语义。
/// </summary>
public readonly record struct OutputVideoSettings(
    OutputResolutionPreset Resolution = OutputResolutionPreset.Original,
    OutputFrameRatePreset FrameRate = OutputFrameRatePreset.Original)
{
    /// <summary>默认原画/原帧率策略。</summary>
    public static OutputVideoSettings Original => default;

    public bool IsOriginalResolution => Resolution == OutputResolutionPreset.Original;

    public bool IsOriginalFrameRate => FrameRate == OutputFrameRatePreset.Original;

    /// <summary>任一显式导出规格均必须重编码。</summary>
    public bool RequiresTranscode => !IsOriginalResolution || !IsOriginalFrameRate;

    /// <summary>
    /// 以当前输出画幅为基准按短边缩放。显式预设始终输出偶数尺寸，以兼容 yuv420p。
    /// 原画返回原尺寸，不改变现有语义。
    /// </summary>
    public (int Width, int Height) ResolveTargetSize(int canvasWidth, int canvasHeight)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(canvasWidth);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(canvasHeight);

        if (IsOriginalResolution)
        {
            return (canvasWidth, canvasHeight);
        }

        var shortEdge = ResolveShortEdge(Resolution);

        if (canvasWidth <= canvasHeight)
        {
            return (shortEdge, ScaleEven(canvasHeight, shortEdge, canvasWidth));
        }

        return (ScaleEven(canvasWidth, shortEdge, canvasHeight), shortEdge);
    }

    /// <summary>解析实际输出帧率；原帧率保持首段素材的既有行为。</summary>
    public decimal ResolveFrameRate(decimal firstClipFrameRate)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(firstClipFrameRate);

        return ResolveFrameRate(FrameRate, firstClipFrameRate);
    }

    private static int ResolveShortEdge(OutputResolutionPreset resolution) =>
        resolution switch
        {
            OutputResolutionPreset.P480 => 480,
            OutputResolutionPreset.P720 => 720,
            OutputResolutionPreset.P1080 => 1080,
            _ => throw new ArgumentOutOfRangeException(nameof(resolution), resolution, "未知的导出分辨率预设。")
        };

    private static decimal ResolveFrameRate(
        OutputFrameRatePreset frameRate,
        decimal firstClipFrameRate) =>
        frameRate switch
        {
            OutputFrameRatePreset.Original => firstClipFrameRate,
            OutputFrameRatePreset.Fps24 => 24m,
            OutputFrameRatePreset.Fps25 => 25m,
            OutputFrameRatePreset.Fps30 => 30m,
            OutputFrameRatePreset.Fps50 => 50m,
            OutputFrameRatePreset.Fps60 => 60m,
            _ => throw new ArgumentOutOfRangeException(nameof(frameRate), frameRate, "未知的导出帧率预设。")
        };

    private static int ScaleEven(int longEdge, int targetShortEdge, int currentShortEdge)
    {
        var scaled = longEdge * (targetShortEdge / (double)currentShortEdge);
        var roundedToEven = (int)Math.Round(scaled / 2d, MidpointRounding.AwayFromZero) * 2;
        return Math.Max(2, roundedToEven);
    }
}
