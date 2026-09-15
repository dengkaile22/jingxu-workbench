using JingXu.Workbench.Application.Projects;

namespace JingXu.Workbench.Presentation.Tests.Composition;

public sealed class CompositionPreviewLeaseTests
{
    [Fact]
    public void Displayed_composite_preview_is_registered_until_replaced_or_cleared()
    {
        var vm = CompositionViewModelTestFactory.Create();
        var root = Path.Combine(WorkbenchDataPaths.GetTempDirectory(), "jingxu-preview-lease-" + Guid.NewGuid().ToString("N"));
        var first = Path.Combine(root, "first.jpg");
        var second = Path.Combine(root, "second.jpg");
        try
        {
            vm.OverlayCompositePreviewPath = first;
            Assert.True(IsRegistered(first));
            vm.OverlayCompositePreviewPath = second;
            Assert.False(IsRegistered(first));
            Assert.True(IsRegistered(second));
            vm.OverlayCompositePreviewPath = null;
            Assert.False(IsRegistered(second));
        }
        finally
        {
            vm.OverlayCompositePreviewPath = null;
        }
    }

    private static bool IsRegistered(string path)
    {
        return TempResourceLease.IsInUse(path);
    }
}
