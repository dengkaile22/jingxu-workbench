using System.Windows;
using System.Windows.Controls;
using JingXu.Workbench.Features.Stickers;
using JingXu.Workbench.Presentation.Tests.Infrastructure;
using JingXu.Workbench.Presentation.Tests.Shell;

namespace JingXu.Workbench.Presentation.Tests.Stickers;

[Collection(WpfAppScope.Name)]
public sealed class StickerEditorViewTests
{
    private readonly WpfAppFixture _app;

    public StickerEditorViewTests(WpfAppFixture app) => _app = app;

    [Fact]
    public void Parameter_editor_loads_and_lays_out_with_the_real_theme()
    {
        _app.Invoke(() =>
        {
            var shell = ShellViewModelTestFactory.Create();
            var view = new StickerEditorView
            {
                DataContext = shell.StickerModule
            };

            view.Measure(new Size(1200, 900));
            view.Arrange(new Rect(0, 0, 1200, 900));
            view.UpdateLayout();

            Assert.NotNull(view.FindName("PreviewCanvas"));
            var clearButton = Assert.IsType<Button>(view.FindName("ClearStickerLibraryButton"));
            Assert.Same(shell.StickerModule.ClearStickerLibraryCommand, clearButton.Command);
            Assert.False(clearButton.IsEnabled);
            var libraryList = Assert.IsType<ListBox>(view.FindName("StickerLibraryList"));
            Assert.True(VirtualizingPanel.GetIsVirtualizing(libraryList));
            Assert.Equal(VirtualizationMode.Recycling, VirtualizingPanel.GetVirtualizationMode(libraryList));
            Assert.True(ScrollViewer.GetCanContentScroll(libraryList));
            Assert.True(view.DesiredSize.Width > 0);
            Assert.True(view.DesiredSize.Height > 0);
        });
    }
}
