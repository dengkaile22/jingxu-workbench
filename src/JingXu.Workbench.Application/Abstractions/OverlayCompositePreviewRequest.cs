using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Application.Abstractions;

/// <summary>主片 + 蒙版半透明叠层的静帧预览请求。</summary>
public sealed record OverlayCompositePreviewRequest(
    string BaseVideoPath,
    OverlayLayer Layer,
    string OutputJpegPath,
    int OutputWidth = 216,
    int OutputHeight = 384);
