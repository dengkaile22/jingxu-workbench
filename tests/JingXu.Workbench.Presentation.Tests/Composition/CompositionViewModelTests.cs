using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Presentation.Tests.Composition;

public sealed class CompositionViewModelTests
{
    [Fact]
    public async Task Import_auto_selects_first_valid_material()
    {
        var vm = CompositionViewModelTestFactory.Create(probe: FakeMediaProbe.ForSixClips());

        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        Assert.NotNull(vm.SelectedMaterial);
        Assert.Equal("商品_片段_1.mp4", vm.SelectedMaterial!.FileName);
        Assert.True(vm.SelectedMaterial.IsSelected);
    }

    [Fact]
    public async Task Select_material_command_updates_selection_state()
    {
        var vm = CompositionViewModelTestFactory.LoadedComposition();

        vm.SelectMaterialCommand.Execute(vm.Materials[1]);

        Assert.Equal(vm.Materials[1], vm.SelectedMaterial);
        Assert.True(vm.Materials[1].IsSelected);
        Assert.False(vm.Materials[0].IsSelected);
    }

    [Fact]
    public async Task Import_shows_probe_error_when_ffprobe_missing()
    {
        var vm = CompositionViewModelTestFactory.Create(
            probe: new FailingMediaProbe(@"C:\素材\片段_1.mp4", "未找到 FFprobe。请将 FFmpeg 放入 runtime/ffmpeg/，在设置中指定路径，或加入系统 PATH。"));

        await vm.ImportFilesCommand.ExecuteAsync([@"C:\素材\片段_1.mp4"]);

        Assert.Single(vm.Materials);
        Assert.Contains("FFprobe", vm.Materials[0].Diagnostic);
        Assert.False(vm.EnqueueCommand.CanExecute(null));
        Assert.Contains("成功 0 个", vm.StatusMessage);
    }

    [Fact]
    public async Task Import_wechat_hash_filename_imports_without_crash_and_shows_sequence_warning()
    {
        var probe = new FixedInfoMediaProbe(new MediaInfo(
            TimeSpan.FromSeconds(15.5),
            720,
            960,
            29.87m,
            "hevc",
            "aac",
            true,
            0));
        var vm = CompositionViewModelTestFactory.Create(probe: probe);
        var path = @"C:\xwechat\11e6dfdbde17e0e9f0a4bbefc95f4e1d.mp4";

        await vm.ImportFilesCommand.ExecuteAsync([path]);

        Assert.Single(vm.Materials);
        Assert.Equal("—", vm.Materials[0].SequenceLabel);
        Assert.Contains("未找到数字序号", vm.Materials[0].Diagnostic);
        Assert.Contains("已导入 1 个文件", vm.StatusMessage);
        Assert.True(vm.EnqueueCommand.CanExecute(null));
    }

    [Fact]
    public async Task Import_unexpected_probe_exception_becomes_row_diagnostic_not_crash()
    {
        var vm = CompositionViewModelTestFactory.Create(probe: new CrashingMediaProbe());

        var ex = await Record.ExceptionAsync(async () =>
            await vm.ImportFilesCommand.ExecuteAsync([@"C:\素材\任意.mp4"]));

        Assert.Null(ex);
        Assert.Single(vm.Materials);
        Assert.Contains("媒体探测失败", vm.Materials[0].Diagnostic);
        Assert.Contains("成功 0 个", vm.StatusMessage);
        Assert.False(vm.IsImporting);
    }

    [Fact]
    public async Task Import_shows_probe_metadata_and_sequence_diagnostics()
    {
        var vm = CompositionViewModelTestFactory.Create(
            probe: FakeMediaProbe.ForSixClips());

        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        Assert.Equal(6, vm.Materials.Count);
        Assert.All(vm.Materials, row => Assert.True(row.Duration > TimeSpan.Zero));
        Assert.All(vm.Materials, row => Assert.False(string.IsNullOrWhiteSpace(row.ResolutionText)));
        Assert.Equal(["1", "2", "3", "4", "5", "6"], vm.Materials.Select(m => m.SequenceLabel ?? string.Empty).ToArray());
    }

    [Fact]
    public void Invalid_custom_expression_disables_enqueue_with_specific_message()
    {
        var vm = CompositionViewModelTestFactory.LoadedComposition();
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "2,a,3";

        Assert.False(vm.EnqueueCommand.CanExecute(null));
        Assert.Contains("第 2 项", vm.ValidationMessage);
    }

    [Fact]
    public void Custom_expression_shows_expanded_preview_and_duration()
    {
        var vm = CompositionViewModelTestFactory.LoadedComposition();
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "264513";

        Assert.Single(vm.PreviewPlans);
        Assert.Equal("2 → 6 → 4 → 5 → 1 → 3", vm.PreviewPlans[0].SequenceText);
        Assert.Equal(TimeSpan.FromSeconds(180), vm.PreviewPlans[0].Duration);
        Assert.True(vm.EnqueueCommand.CanExecute(null));
    }

    [Fact]
    public void Random_batch_preview_shows_multiple_plans()
    {
        var vm = CompositionViewModelTestFactory.LoadedComposition();
        vm.Mode = CompositionMode.Random;
        vm.BatchCount = 3;
        vm.RandomSeed = 42;

        Assert.Equal(3, vm.PreviewPlans.Count);
        Assert.All(vm.PreviewPlans, plan => Assert.Equal(6, plan.ClipCount));
        Assert.True(vm.EnqueueCommand.CanExecute(null));
    }

    [Fact]
    public async Task Enqueue_adds_previewed_jobs_to_coordinator()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        await vm.EnqueueCommand.ExecuteAsync(null);

        Assert.Single(coordinator.Jobs);
        Assert.Single(store.Jobs);
    }

    [Fact]
    public async Task Enqueue_attaches_render_request_snapshot_to_each_job()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
        vm.OutputDirectory = @"C:\输出\混剪";
        vm.OutputFileNamePrefix = "测试成片";

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        await vm.EnqueueCommand.ExecuteAsync(null);

        var job = Assert.Single(coordinator.Jobs);
        Assert.NotNull(job.Request);
        Assert.Equal(@"C:\输出\混剪\测试成片.mp4", job.Request.OutputPath);
        Assert.Equal(RenderProfile.Balanced, job.Request.Profile);
        Assert.Equal(OutputAspect.InheritFirst, job.Request.Aspect);
        Assert.Equal(6, job.Request.Plan.Clips.Count);
    }

    [Fact]
    public async Task Enqueue_uses_selected_quality_profile()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.SelectedQuality = QualityPreset.High;
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        await vm.EnqueueCommand.ExecuteAsync(null);

        var job = Assert.Single(coordinator.Jobs);
        Assert.Equal(RenderProfile.High, job.Request!.Profile);
    }

    [Fact]
    public async Task Import_sets_default_output_to_source_storyboard_folder()
    {
        var vm = CompositionViewModelTestFactory.Create();
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        Assert.Equal(@"C:\素材\分镜输出", vm.OutputDirectory);
    }

    [Fact]
    public async Task Import_multi_source_uses_project_storyboard_folder()
    {
        var vm = CompositionViewModelTestFactory.Create();
        await vm.ImportFilesCommand.ExecuteAsync(
        [
            @"C:\素材A\片段_1.mp4",
            @"D:\素材B\片段_2.mp4"
        ]);

        Assert.Equal(
            Path.Combine(RenderRequestFactory.DefaultProjectDirectory, "分镜输出"),
            vm.OutputDirectory);
    }

    [Fact]
    public async Task Browse_output_prevents_import_from_overwriting_directory()
    {
        var picker = new RecordingOutputFolderPicker { NextPick = @"E:\自定义输出" };
        var vm = CompositionViewModelTestFactory.Create(outputFolderPicker: picker);
        vm.PickOutputDirectoryCommand.Execute(null);

        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        Assert.Equal(@"E:\自定义输出", vm.OutputDirectory);
    }

    [Fact]
    public async Task Enqueue_with_sticker_attaches_image_sticker()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableSticker = true;
        vm.StickerPath = @"C:\贴纸\logo.png";
        vm.StickerXPercent = 10;
        vm.StickerYPercent = 20;
        vm.StickerWidthPercent = 30;
        vm.StickerHeightPercent = 25;
        vm.StickerOpacityPercent = 80;
        await vm.EnqueueCommand.ExecuteAsync(null);

        var job = Assert.Single(coordinator.Jobs);
        Assert.True(job.Request!.HasEffects);
        Assert.NotNull(job.Request.Sticker);
        Assert.Equal(@"C:\贴纸\logo.png", job.Request.Sticker!.Path);
        Assert.Equal(0.1, job.Request.Sticker.Bounds.X);
        Assert.Equal(0.8, job.Request.Sticker.Opacity);
    }

    [Fact]
    public async Task Save_and_apply_effect_template_round_trips_sticker()
    {
        var templateService = CompositionViewModelTestFactory.CreateTemplateService();
        var vm = CompositionViewModelTestFactory.Create(templateService: templateService);
        await vm.LoadEffectTemplatesCommand.ExecuteAsync(null);

        vm.EnableVariationEffects = true;
        vm.EnableSticker = true;
        vm.StickerPath = @"C:\贴纸\badge.png";
        vm.StickerXPercent = 55;
        vm.StickerYPercent = 60;
        vm.StickerWidthPercent = 18;
        vm.StickerHeightPercent = 12;
        vm.StickerOpacityPercent = 90;
        vm.NewTemplateName = "角标模板";
        await vm.SaveEffectTemplateCommand.ExecuteAsync(null);

        Assert.Contains(vm.EffectTemplatesList, t => t.DisplayName == "角标模板");

        vm.EnableSticker = false;
        vm.StickerPath = string.Empty;
        vm.SelectedEffectTemplate = vm.EffectTemplatesList.First(t => t.DisplayName == "角标模板");
        vm.ApplySelectedTemplateCommand.Execute(null);

        Assert.True(vm.EnableSticker);
        Assert.Equal(@"C:\贴纸\badge.png", vm.StickerPath);
        Assert.Equal(55, vm.StickerXPercent);
        Assert.Equal(90, vm.StickerOpacityPercent);
        Assert.True(vm.EnableVariationEffects);
    }

    [Fact]
    public async Task Enqueue_batch_attaches_numbered_render_requests()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
        vm.OutputDirectory = @"D:\成片";
        vm.OutputFileNamePrefix = "批量";

        vm.Mode = CompositionMode.Random;
        vm.BatchCount = 2;
        vm.RandomSeed = 7;
        await vm.EnqueueCommand.ExecuteAsync(null);

        Assert.Equal(2, coordinator.Jobs.Count);
        Assert.All(coordinator.Jobs, job => Assert.NotNull(job.Request));
        Assert.Equal(@"D:\成片\批量_001.mp4", coordinator.Jobs[0].Request!.OutputPath);
        Assert.Equal(@"D:\成片\批量_002.mp4", coordinator.Jobs[1].Request!.OutputPath);
    }

    [Fact]
    public void Empty_output_settings_disable_enqueue()
    {
        var vm = CompositionViewModelTestFactory.LoadedComposition();
        vm.OutputDirectory = "   ";

        Assert.False(vm.EnqueueCommand.CanExecute(null));
    }

    [Fact]
    public async Task Duplicate_sequence_indices_block_enqueue_with_message()
    {
        var vm = CompositionViewModelTestFactory.Create(
            probe: FakeMediaProbe.ForSixClips());
        await vm.ImportFilesCommand.ExecuteAsync(
        [
            @"C:\素材\片段_1.mp4",
            @"C:\素材\片段_1_copy.mp4",
            @"C:\素材\片段_2.mp4"
        ]);

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "112";

        Assert.False(vm.EnqueueCommand.CanExecute(null));
        Assert.Contains("重复序号", vm.ValidationMessage);
    }

    [Fact]
    public void Empty_materials_disable_enqueue()
    {
        var vm = CompositionViewModelTestFactory.Create();
        Assert.False(vm.EnqueueCommand.CanExecute(null));
        Assert.Contains("导入", vm.ValidationMessage);
    }

    [Fact]
    public async Task Enqueue_with_effects_and_bgm_writes_render_request_flags()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableVariationEffects = true;
        vm.EnableBgm = true;
        vm.BgmPath = @"C:\音频\配乐.mp3";
        await vm.EnqueueCommand.ExecuteAsync(null);

        var job = Assert.Single(coordinator.Jobs);
        Assert.True(job.Request!.HasEffects);
        Assert.True(job.Request.HasBgm);
        Assert.NotNull(job.Request.Effect);
        Assert.Equal(@"C:\音频\配乐.mp3", job.Request.Bgm!.Path);
        Assert.Equal(0.18, job.Request.Bgm.BgmVolume);
    }

    [Fact]
    public void Overlay_switch_off_shows_closed_status_label()
    {
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2)));
        var vm = CompositionViewModelTestFactory.Create(overlayState: state);

        vm.EnableOverlayOnOutput = false;

        Assert.Contains("已关闭", vm.OverlayStatusLabel);
        Assert.False(state.IsEnabled);
    }

    [Fact]
    public void Overlay_switch_on_shows_enabled_status_label()
    {
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2)));
        var vm = CompositionViewModelTestFactory.LoadedComposition(overlayState: state);

        vm.EnableOverlayOnOutput = true;

        Assert.Contains("已开启", vm.OverlayStatusLabel);
        Assert.Contains("叠加到成片", vm.OverlayStatusLabel);
        Assert.True(state.IsEnabled);
    }

    [Fact]
    public async Task Enqueue_without_overlay_switch_omits_overlay_layers()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2)));
        var vm = CompositionViewModelTestFactory.Create(coordinator, overlayState: state);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableOverlayOnOutput = false;
        await vm.EnqueueCommand.ExecuteAsync(null);

        var job = Assert.Single(coordinator.Jobs);
        Assert.False(job.Request!.HasOverlays);
        Assert.Empty(job.Request.OverlayLayers);
    }

    [Fact]
    public async Task Enqueue_with_overlay_switch_attaches_configured_layers()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2)));
        var vm = CompositionViewModelTestFactory.Create(coordinator, overlayState: state);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableOverlayOnOutput = true;
        await vm.EnqueueCommand.ExecuteAsync(null);

        var job = Assert.Single(coordinator.Jobs);
        Assert.True(job.Request!.HasOverlays);
        Assert.Equal(@"C:\mask.mp4", job.Request.OverlayLayers[0].SourcePath);
    }

    [Fact]
    public async Task Enqueue_with_random_library_uses_library_source_path()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2)));
        var library = CompositionViewModelTestFactory.CreateOverlayLibraryService();
        await CompositionViewModelTestFactory.SeedLibraryAsync(
            library,
            @"C:\library\one.mp4",
            @"C:\library\two.mp4",
            @"C:\library\three.mp4");

        var vm = CompositionViewModelTestFactory.Create(coordinator, overlayState: state, overlayLibraryService: library);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableOverlayOnOutput = true;
        vm.UseRandomOverlayLibrary = true;
        await vm.EnqueueCommand.ExecuteAsync(null);

        var job = Assert.Single(coordinator.Jobs);
        Assert.True(job.Request!.HasOverlays);
        Assert.Contains(@"C:\library\", job.Request.OverlayLayers[0].SourcePath);
        Assert.NotEqual(@"C:\mask.mp4", job.Request.OverlayLayers[0].SourcePath);
    }

    [Fact]
    public void Multi_expression_custom_mode_shows_multiple_preview_plans()
    {
        var vm = CompositionViewModelTestFactory.LoadedComposition();
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "264513; 351246";

        Assert.Equal(2, vm.PreviewPlans.Count);
        Assert.True(vm.EnqueueCommand.CanExecute(null));
        Assert.Contains("独立成片", vm.PreviewSummary);
    }

    [Fact]
    public async Task Multi_expression_enqueue_creates_multiple_jobs()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
        vm.OutputDirectory = @"C:\输出\混剪";
        vm.OutputFileNamePrefix = "批量自定义";

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456; 654321";
        await vm.EnqueueCommand.ExecuteAsync(null);

        Assert.Equal(2, coordinator.Jobs.Count);
        Assert.Equal(@"C:\输出\混剪\批量自定义_001.mp4", coordinator.Jobs[0].Request!.OutputPath);
        Assert.Equal(@"C:\输出\混剪\批量自定义_002.mp4", coordinator.Jobs[1].Request!.OutputPath);
    }

    [Fact]
    public async Task Enabled_overlay_without_layers_or_library_blocks_enqueue()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableOverlayOnOutput = true;

        await vm.EnqueueCommand.ExecuteAsync(null);

        Assert.Empty(coordinator.Jobs);
        Assert.Contains("未配置蒙版层", vm.ValidationMessage);
    }

    [Fact]
    public async Task Enqueue_with_unified_aspect_attaches_custom_output_aspect()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.EnableUnifiedAspect = true;
        vm.AspectPreset = OutputCanvasPreset.Vertical9x16;
        vm.ClipFitMode = AspectFitMode.Letterbox;
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        await vm.EnqueueCommand.ExecuteAsync(null);

        var job = Assert.Single(coordinator.Jobs);
        Assert.False(job.Request!.Aspect.InheritFromFirstClip);
        Assert.Equal(1080, job.Request.Aspect.TargetWidth);
        Assert.Equal(1920, job.Request.Aspect.TargetHeight);
        Assert.Equal(AspectFitMode.Letterbox, job.Request.Aspect.FitMode);
    }

    [Fact]
    public async Task Enqueue_with_unified_aspect_applies_overlay_fit_to_layers()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\mask.mp4", TimeSpan.FromSeconds(2)));
        var vm = CompositionViewModelTestFactory.Create(coordinator, overlayState: state);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.EnableUnifiedAspect = true;
        vm.OverlayFitMode = OverlayFitMode.Contain;
        vm.EnableOverlayOnOutput = true;
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        await vm.EnqueueCommand.ExecuteAsync(null);

        var job = Assert.Single(coordinator.Jobs);
        Assert.Equal(OverlayFitMode.Contain, job.Request!.OverlayLayers[0].Fit);
    }

    [Fact]
    public void Unified_aspect_preview_updates_when_preset_changes()
    {
        var vm = CompositionViewModelTestFactory.LoadedComposition();
        vm.EnableUnifiedAspect = true;
        vm.AspectPreset = OutputCanvasPreset.Vertical9x16;

        Assert.Contains("1080×1920", vm.UnifiedAspectPreviewDescription);
        Assert.Contains("已启用统一比例", vm.UnifiedAspectPreviewDescription);
    }

    [Fact]
    public void Custom_aspect_with_invalid_dimensions_disables_enqueue()
    {
        var vm = CompositionViewModelTestFactory.LoadedComposition();
        vm.EnableUnifiedAspect = true;
        vm.AspectPreset = OutputCanvasPreset.Custom;
        vm.CustomAspectWidth = 0;

        Assert.False(vm.EnqueueCommand.CanExecute(null));
    }
}
