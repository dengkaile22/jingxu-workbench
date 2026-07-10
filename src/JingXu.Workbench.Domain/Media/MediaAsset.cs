namespace JingXu.Workbench.Domain.Media;

/// <summary>
/// 带有稳定标识、路径、序号和探测信息的媒体素材。
/// </summary>
public sealed record MediaAsset(
    Guid Id,
    string Path,
    int? SequenceIndex,
    MediaInfo Info);
