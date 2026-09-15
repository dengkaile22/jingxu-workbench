using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Presentation.Tests.Infrastructure;

namespace JingXu.Workbench.Presentation.Tests.Composition;

public sealed class FourScreenCompositionTests
{
    [Fact]
    public void Enabling_a_screen_layout_disables_the_other_layout()
    {
        var vm = CompositionViewModelTestFactory.Create();
        vm.EnableDoubleScreen = true;
        vm.EnableFourScreen = true;
        Assert.False(vm.EnableDoubleScreen);
        vm.EnableDoubleScreen = true;
        Assert.False(vm.EnableFourScreen);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(7)]
    public async Task Invalid_start_clip_is_rejected_before_enqueue(int start)
    {
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), new InMemoryRenderQueueStore(), 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableVariationEffects = true;
        vm.EnableFourScreen = true;
        vm.FourScreenStartClipIndex = start;

        await vm.EnqueueCommand.ExecuteAsync(null);

        Assert.Empty(coordinator.Jobs);
        Assert.Contains("四屏起始", vm.ValidationMessage, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Enqueue_preserves_four_screen_settings_and_fixed_sources()
    {
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), new InMemoryRenderQueueStore(), 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableVariationEffects = true;
        vm.EnableFourScreen = true;
        vm.FourScreenStartClipIndex = 2;
        vm.FourScreenUseRandomCurrentFolder = true;
        vm.FourScreenFeatherPixels = 96;

        await vm.EnqueueCommand.ExecuteAsync(null);

        var request = Assert.Single(coordinator.Jobs).Request!;
        var effect = Assert.IsType<FourScreenEffectPlan>(request.FourScreen);
        Assert.Equal(5, effect.ClipSelections.Count);
        Assert.Equal(96, effect.FeatherPixels);
        Assert.Null(request.DoubleScreen);
        vm.FourScreenFeatherPixels = 8;
        Assert.Equal(96, effect.FeatherPixels);
    }

    [Fact]
    public void Composition_view_exposes_four_screen_source_start_and_feather_controls()
    {
        var root = AppContext.BaseDirectory;
        while (!File.Exists(Path.Combine(root, "JingXu.Workbench.sln")))
        {
            root = Path.GetDirectoryName(root) ?? throw new InvalidOperationException("未找到仓库。");
        }

        var xaml = File.ReadAllText(Path.Combine(root, "src", "JingXu.Workbench", "Features", "Composition", "CompositionView.xaml"));
        Assert.Contains("{Binding EnableFourScreen}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding FourScreenStartClipIndex, UpdateSourceTrigger=PropertyChanged}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding FourScreenUseRandomCurrentFolder}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding FourScreenFeatherEnabled}", xaml, StringComparison.Ordinal);
        Assert.Contains("{Binding FourScreenFeatherPixels}", xaml, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Saved_four_screen_template_restores_settings_and_legacy_template_disables_it()
    {
        var templateRoot = Path.Combine(Path.GetTempPath(), "jingxu-four-template-" + Guid.NewGuid().ToString("N"));
        var service = CompositionViewModelTestFactory.CreateTemplateService(Path.Combine(templateRoot, "templates.json"));
        try
        {
            var vm = CompositionViewModelTestFactory.Create(templateService: service);
            vm.EnableVariationEffects = true;
            vm.EnableFourScreen = true;
            vm.FourScreenStartClipIndex = 3;
            vm.FourScreenUseRandomCurrentFolder = true;
            vm.FourScreenFeatherEnabled = false;
            vm.FourScreenFeatherPixels = 80;
            vm.NewTemplateName = "四屏模板";
            await vm.SaveEffectTemplateCommand.ExecuteAsync(null);

            var restored = CompositionViewModelTestFactory.Create(templateService: service);
            await restored.LoadEffectTemplatesCommand.ExecuteAsync(null);
            restored.SelectedEffectTemplate = restored.EffectTemplatesList.Single(template => template.DisplayName == "四屏模板");
            Assert.True(restored.EnableFourScreen, restored.ValidationMessage);
            Assert.Equal(3, restored.FourScreenStartClipIndex);
            Assert.True(restored.FourScreenUseRandomCurrentFolder);
            Assert.False(restored.FourScreenFeatherEnabled);
            Assert.Equal(80, restored.FourScreenFeatherPixels);
            restored.SelectedEffectTemplate = EffectTemplates.StandardVariation();
            Assert.False(restored.EnableFourScreen);
        }
        finally
        {
            if (Directory.Exists(templateRoot))
            {
                Directory.Delete(templateRoot, recursive: true);
            }
        }
    }
}
