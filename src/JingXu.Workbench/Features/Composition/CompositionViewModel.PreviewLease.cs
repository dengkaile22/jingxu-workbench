using JingXu.Workbench.Application.Projects;

namespace JingXu.Workbench.Features.Composition;

public sealed partial class CompositionViewModel
{
    private IDisposable? _overlayCompositePreviewLease;

    partial void OnOverlayCompositePreviewPathChanged(string? value)
    {
        // 先保护新预览再释放旧预览，与生成期间的临时租约衔接，避免清理线程删掉正在显示的帧。
        var nextLease = string.IsNullOrWhiteSpace(value) ? null : TempResourceLease.Acquire(value);
        var previousLease = Interlocked.Exchange(ref _overlayCompositePreviewLease, nextLease);
        previousLease?.Dispose();
    }
}
