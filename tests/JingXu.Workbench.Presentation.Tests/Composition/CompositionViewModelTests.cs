using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Domain.Stickers;
using JingXu.Workbench.Features.Overlays;
using JingXu.Workbench.Features.Stickers;
using JingXu.Workbench.Infrastructure.Persistence;
using JingXu.Workbench.Presentation.Tests.Infrastructure;

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

    [Theory]
    [InlineData(VideoProcessingMode.Auto)]
    [InlineData(VideoProcessingMode.Cpu)]
    [InlineData(VideoProcessingMode.Gpu)]
    public async Task Enqueue_snapshots_selected_processing_mode(VideoProcessingMode mode)
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.SelectedProcessingMode = mode;
        await vm.EnqueueCommand.ExecuteAsync(null);

        Assert.Equal(mode, Assert.Single(coordinator.Jobs).Request!.ProcessingMode);
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

        var stickerPath = Path.Combine(Path.GetTempPath(), $"jingxu-sticker-test-{Guid.NewGuid():N}.png");
        File.WriteAllBytes(stickerPath, [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
        try
        {
            vm.Mode = CompositionMode.CustomSequence;
            vm.SequenceExpression = "123456";
            vm.StickerEditor.AddStickerCommand.Execute(new StickerLibraryEntryRowViewModel(
                new StickerLibraryEntry(Guid.NewGuid(), stickerPath, null, null)));
            var track = Assert.Single(vm.StickerEditor.Tracks);
            track.X = 10;
            track.Y = 20;
            track.Width = 30;
            track.Height = 25;
            track.StickerOpacity = 80;

            await vm.EnqueueCommand.ExecuteAsync(null);

            var job = Assert.Single(coordinator.Jobs);
            Assert.True(job.Request!.HasEffects);
            Assert.Single(job.Request.Stickers);
            Assert.Equal(stickerPath, job.Request.Stickers[0].Path);
            Assert.Equal(0.1, job.Request.Stickers[0].Bounds.X);
            Assert.Equal(0.8, job.Request.Stickers[0].Opacity);
        }
        finally
        {
            File.Delete(stickerPath);
        }
    }

    [Fact]
    public async Task Save_and_reload_effect_template_restores_variation_and_sticker_track_parameters()
    {
        var templateService = CompositionViewModelTestFactory.CreateTemplateService();
        var vm = CompositionViewModelTestFactory.Create(templateService: templateService);
        await vm.LoadEffectTemplatesCommand.ExecuteAsync(null);

        var stickerPaths = new[]
        {
            Path.Combine(Path.GetTempPath(), $"jingxu-sticker-template-a-{Guid.NewGuid():N}.png"),
            Path.Combine(Path.GetTempPath(), $"jingxu-sticker-template-b-{Guid.NewGuid():N}.png")
        };
        foreach (var path in stickerPaths)
        {
            File.WriteAllBytes(path, [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
        }

        try
        {
            vm.EnableVariationEffects = true;
            vm.VariationIntensityPercent = 80;
            vm.StickerEditor.AddStickerCommand.Execute(new StickerLibraryEntryRowViewModel(
                new StickerLibraryEntry(Guid.NewGuid(), stickerPaths[0], null, null)));
            vm.StickerEditor.AddStickerCommand.Execute(new StickerLibraryEntryRowViewModel(
                new StickerLibraryEntry(Guid.NewGuid(), stickerPaths[1], null, null)));

            vm.StickerEditor.Tracks[0].Name = "左上角标";
            vm.StickerEditor.Tracks[0].X = 8;
            vm.StickerEditor.Tracks[0].Y = 12;
            vm.StickerEditor.Tracks[0].Width = 22;
            vm.StickerEditor.Tracks[0].Height = 18;
            vm.StickerEditor.Tracks[0].StickerOpacity = 75;
            vm.StickerEditor.Tracks[0].RotationDegrees = -6;
            vm.StickerEditor.Tracks[1].Name = "右下角标";
            vm.StickerEditor.Tracks[1].X = 62;
            vm.StickerEditor.Tracks[1].Y = 70;
            vm.StickerEditor.Tracks[1].Width = 24;
            vm.StickerEditor.Tracks[1].Height = 16;
            vm.StickerEditor.Tracks[1].StickerOpacity = 90;
            vm.StickerEditor.Tracks[1].RotationDegrees = 4;
            vm.StickerEditor.Tracks[1].IsEnabled = false;

            vm.NewTemplateName = "双角标模板";
            await vm.SaveEffectTemplateCommand.ExecuteAsync(null);

            Assert.True(File.Exists(templateService.StorePath), vm.ValidationMessage);
            var persisted = await templateService.LoadAsync();
            Assert.Contains(persisted.Templates, template => template.DisplayName == "双角标模板");

            var reloaded = CompositionViewModelTestFactory.Create(templateService: templateService);
            await reloaded.LoadEffectTemplatesCommand.ExecuteAsync(null);
            reloaded.VariationIntensityPercent = 20;
            reloaded.SelectedEffectTemplate = reloaded.EffectTemplatesList.First(
                template => template.DisplayName == "双角标模板");
            reloaded.ApplySelectedTemplateCommand.Execute(null);

            Assert.True(reloaded.EnableVariationEffects);
            Assert.Equal(80, reloaded.VariationIntensityPercent);
            Assert.Equal(2, reloaded.StickerEditor.Tracks.Count);
            Assert.Collection(
                reloaded.StickerEditor.Tracks,
                first =>
                {
                    Assert.Equal("左上角标", first.Name);
                    Assert.Equal(stickerPaths[0], first.SourcePath);
                    Assert.Equal(8, first.X);
                    Assert.Equal(12, first.Y);
                    Assert.Equal(22, first.Width);
                    Assert.Equal(18, first.Height);
                    Assert.Equal(75, first.StickerOpacity);
                    Assert.Equal(-6, first.RotationDegrees);
                    Assert.True(first.IsEnabled);
                },
                second =>
                {
                    Assert.Equal("右下角标", second.Name);
                    Assert.Equal(stickerPaths[1], second.SourcePath);
                    Assert.Equal(62, second.X);
                    Assert.Equal(70, second.Y);
                    Assert.Equal(24, second.Width);
                    Assert.Equal(16, second.Height);
                    Assert.Equal(90, second.StickerOpacity);
                    Assert.Equal(4, second.RotationDegrees);
                    Assert.False(second.IsEnabled);
                });
        }
        finally
        {
            foreach (var path in stickerPaths)
            {
                File.Delete(path);
            }
        }
    }

    [Fact]
    public async Task Startup_template_load_does_not_overwrite_template_saved_while_loading()
    {
        var root = Path.Combine(Path.GetTempPath(), $"jingxu-template-startup-race-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        var templatePath = Path.Combine(root, "effect-templates.json");

        try
        {
            var seedService = new TemplateService(
                new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion),
                templatePath);
            await seedService.SaveAsync(EffectTemplateDocument.WithDefaults);

            var blockingStore = new BlockingFirstLoadJsonStore<EffectTemplateDocument>(
                new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion));
            var templateService = new TemplateService(blockingStore, templatePath);
            var vm = CompositionViewModelTestFactory.Create(templateService: templateService);

            await blockingStore.FirstLoadStarted.WaitAsync(TimeSpan.FromSeconds(5));
            vm.NewTemplateName = "启动竞态模板";
            var saveTask = vm.SaveEffectTemplateCommand.ExecuteAsync(null);

            blockingStore.ReleaseFirstLoad();
            await blockingStore.FirstLoadCompleted.WaitAsync(TimeSpan.FromSeconds(5));
            await saveTask;

            Assert.Contains(vm.EffectTemplatesList, template => template.DisplayName == "启动竞态模板");
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task Batch_enqueue_randomly_replaces_sticker_from_persistent_library_per_output()
    {
        var root = Path.Combine(Path.GetTempPath(), $"jingxu-sticker-enqueue-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var templatePath = Path.Combine(root, "template.png");
            var firstPath = Path.Combine(root, "first.png");
            var secondPath = Path.Combine(root, "second.png");
            await File.WriteAllBytesAsync(templatePath, [0x89, 0x50, 0x4E, 0x47]);
            await File.WriteAllBytesAsync(firstPath, [0x89, 0x50, 0x4E, 0x47]);
            await File.WriteAllBytesAsync(secondPath, [0x89, 0x50, 0x4E, 0x47]);

            var stickerLibrary = new StickerLibraryService(
                new AtomicJsonStore<StickerLibraryDocument>(StickerLibraryDocument.CurrentSchemaVersion),
                Path.Combine(root, "sticker-library.json"));
            await stickerLibrary.RegisterAsync(firstPath);
            await stickerLibrary.RegisterAsync(secondPath);
            var stickerTracksSvc1 = new StickerTracksService(
                new AtomicJsonStore<StickerTracksDocument>(StickerTracksDocument.CurrentSchemaVersion),
                Path.Combine(root, "sticker-tracks.json"));
            var stickerEditor = new StickerEditorViewModel(
                stickerLibrary,
                stickerTracksSvc1,
                new RecordingMediaFilePicker(),
                new DirectUiDispatcher())
            {
                UseRandomStickerLibrary = true
            };
            stickerEditor.AddStickerCommand.Execute(new StickerLibraryEntryRowViewModel(
                new StickerLibraryEntry(Guid.NewGuid(), templatePath, null, null)));

            var store = new InMemoryRenderQueueStore();
            var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
            var vm = CompositionViewModelTestFactory.Create(
                coordinator,
                stickerEditor: stickerEditor);
            await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
            vm.Mode = CompositionMode.CustomSequence;
            vm.SequenceExpression = "123456;654321";

            await vm.EnqueueCommand.ExecuteAsync(null);

            Assert.Equal(2, coordinator.Jobs.Count);
            var firstSticker = Assert.Single(coordinator.Jobs[0].Request!.Stickers);
            var secondSticker = Assert.Single(coordinator.Jobs[1].Request!.Stickers);
            Assert.NotEqual(templatePath, firstSticker.Path);
            Assert.NotEqual(firstSticker.Path, secondSticker.Path);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task Sequential_product_enqueues_use_each_random_sticker_before_repeating()
    {
        var root = Path.Combine(Path.GetTempPath(), $"jingxu-sticker-product-random-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var templatePath = Path.Combine(root, "template.png");
            var libraryPaths = Enumerable.Range(1, 4)
                .Select(index => Path.Combine(root, $"library-{index}.png"))
                .ToArray();
            await File.WriteAllBytesAsync(templatePath, [0x89, 0x50, 0x4E, 0x47]);
            foreach (var path in libraryPaths)
            {
                await File.WriteAllBytesAsync(path, [0x89, 0x50, 0x4E, 0x47]);
            }

            var stickerLibrary = new StickerLibraryService(
                new AtomicJsonStore<StickerLibraryDocument>(StickerLibraryDocument.CurrentSchemaVersion),
                Path.Combine(root, "sticker-library.json"));
            foreach (var path in libraryPaths)
            {
                await stickerLibrary.RegisterAsync(path);
            }

            var stickerTracksSvc2 = new StickerTracksService(
                new AtomicJsonStore<StickerTracksDocument>(StickerTracksDocument.CurrentSchemaVersion),
                Path.Combine(root, "sticker-tracks.json"));
            var stickerEditor = new StickerEditorViewModel(
                stickerLibrary,
                stickerTracksSvc2,
                new RecordingMediaFilePicker(),
                new DirectUiDispatcher())
            {
                UseRandomStickerLibrary = true
            };
            stickerEditor.AddStickerCommand.Execute(new StickerLibraryEntryRowViewModel(
                new StickerLibraryEntry(Guid.NewGuid(), templatePath, null, null)));

            var store = new InMemoryRenderQueueStore();
            var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
            var vm = CompositionViewModelTestFactory.Create(coordinator, stickerEditor: stickerEditor);
            await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
            vm.Mode = CompositionMode.CustomSequence;
            vm.SequenceExpression = "123456";

            for (var product = 0; product < libraryPaths.Length; product++)
            {
                await vm.EnqueueCommand.ExecuteAsync(null);
            }

            var selectedPaths = coordinator.Jobs
                .Select(job => Assert.Single(job.Request!.Stickers).Path)
                .ToArray();
            Assert.Equal(libraryPaths.Length, selectedPaths.Length);
            Assert.Equal(
                libraryPaths.Length,
                selectedPaths.Distinct(StringComparer.OrdinalIgnoreCase).Count());
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task Enqueue_rejects_sticker_bounds_outside_the_video_frame()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);

        var stickerPath = Path.Combine(Path.GetTempPath(), $"jingxu-invalid-sticker-{Guid.NewGuid():N}.png");
        File.WriteAllBytes(stickerPath, [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
        try
        {
            vm.Mode = CompositionMode.CustomSequence;
            vm.SequenceExpression = "123456";
            vm.StickerEditor.AddStickerCommand.Execute(new StickerLibraryEntryRowViewModel(
                new StickerLibraryEntry(Guid.NewGuid(), stickerPath, null, null)));
            var track = Assert.Single(vm.StickerEditor.Tracks);
            track.X = 90;
            track.Width = 20;

            await vm.EnqueueCommand.ExecuteAsync(null);

            Assert.Empty(coordinator.Jobs);
            Assert.Contains("贴纸", vm.ValidationMessage);
            Assert.Contains("范围", vm.ValidationMessage);
        }
        finally
        {
            File.Delete(stickerPath);
        }
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
    public async Task Sequential_product_enqueues_use_each_random_mask_before_repeating()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\mask-template.mp4", TimeSpan.FromSeconds(2)));
        var library = CompositionViewModelTestFactory.CreateOverlayLibraryService();
        var libraryPaths = new[]
        {
            @"C:\library\one.mp4",
            @"C:\library\two.mp4",
            @"C:\library\three.mp4",
            @"C:\library\four.mp4"
        };
        await CompositionViewModelTestFactory.SeedLibraryAsync(library, libraryPaths);

        var vm = CompositionViewModelTestFactory.Create(
            coordinator,
            overlayState: state,
            overlayLibraryService: library);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableOverlayOnOutput = true;
        vm.UseRandomOverlayLibrary = true;

        for (var product = 0; product < libraryPaths.Length; product++)
        {
            await vm.EnqueueCommand.ExecuteAsync(null);
        }

        var selectedPaths = coordinator.Jobs
            .Select(job => Assert.Single(job.Request!.OverlayLayers).SourcePath)
            .ToArray();
        Assert.Equal(libraryPaths.Length, selectedPaths.Length);
        Assert.Equal(
            libraryPaths.Length,
            selectedPaths.Distinct(StringComparer.OrdinalIgnoreCase).Count());
    }

    [Fact]
    public async Task Random_mask_uses_selected_start_clip_after_materials_and_queue_are_cleared()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var state = new OverlayWorkbenchState();
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\mask-first.mp4", TimeSpan.FromSeconds(2)) with
        {
            Name = "蒙版 1",
            StartClipIndex = 1
        });
        state.Add(OverlayLayer.CreateScreenshotPreset(@"C:\mask-second.mp4", TimeSpan.FromSeconds(2)) with
        {
            Name = "蒙版 2",
            StartClipIndex = 1
        });
        var library = CompositionViewModelTestFactory.CreateOverlayLibraryService();
        await CompositionViewModelTestFactory.SeedLibraryAsync(
            library,
            @"C:\library\one.mp4",
            @"C:\library\two.mp4");
        var overlayLayersSvc = new OverlayLayersService(
            new AtomicJsonStore<OverlayLayersDocument>(OverlayLayersDocument.CurrentSchemaVersion),
            Path.Combine(Path.GetTempPath(), $"jingxu-overlay-layers-{Guid.NewGuid():N}.json"));
        var overlayEditor = new OverlayEditorViewModel(
            new RecordingMediaFilePicker(),
            state,
            FakeMediaProbe.ForSixClips(),
            new DirectUiDispatcher(),
            overlayLayersSvc,
            library)
        {
            UseRandomMaskLibrary = true
        };
        var vm = CompositionViewModelTestFactory.Create(
            coordinator,
            overlayState: state,
            overlayLibraryService: library,
            overlayEditor: overlayEditor);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableOverlayOnOutput = true;
        vm.UseRandomOverlayLibrary = true;

        await vm.EnqueueCommand.ExecuteAsync(null);
        Assert.Equal(1, Assert.Single(Assert.Single(coordinator.Jobs).Request!.OverlayLayers).StartClipIndex);

        vm.ClearMaterialsCommand.Execute(null);
        await coordinator.ClearAllJobsAsync();
        overlayEditor.Selected = overlayEditor.Layers.Single(row => row.DisplayName == "蒙版 2");
        overlayEditor.StartClipIndex = 3;
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";

        await vm.EnqueueCommand.ExecuteAsync(null);

        var latestJob = coordinator.Jobs[coordinator.Jobs.Count - 1];
        Assert.Equal(3, Assert.Single(latestJob.Request!.OverlayLayers).StartClipIndex);
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
    public async Task Successful_enqueue_clears_previous_runtime_validation_failure()
    {
        var store = new InMemoryRenderQueueStore();
        var coordinator = RenderCoordinator.Create(new NoOpRenderExecutor(), store, maxConcurrency: 1);
        var vm = CompositionViewModelTestFactory.Create(coordinator);
        await vm.ImportFilesCommand.ExecuteAsync(CompositionTestPaths.SixClips);
        vm.Mode = CompositionMode.CustomSequence;
        vm.SequenceExpression = "123456";
        vm.EnableOverlayOnOutput = true;

        await vm.EnqueueCommand.ExecuteAsync(null);
        Assert.Contains("未配置蒙版层", vm.ValidationMessage);

        vm.EnableOverlayOnOutput = false;
        await vm.EnqueueCommand.ExecuteAsync(null);

        Assert.Single(coordinator.Jobs);
        Assert.Empty(vm.ValidationMessage);
        Assert.Contains("已将 1 个任务加入队列", vm.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public void Composition_view_shows_enqueue_result_next_to_enqueue_button()
    {
        var repoRoot = FindRepoRoot();
        var xamlPath = Path.Combine(
            repoRoot,
            "src",
            "JingXu.Workbench",
            "Features",
            "Composition",
            "CompositionView.xaml");
        var xaml = File.ReadAllText(xamlPath);

        Assert.Contains("x:Name=\"EnqueueFeedback\"", xaml, StringComparison.Ordinal);
        Assert.Contains("Text=\"{Binding ValidationMessage}\"", xaml, StringComparison.Ordinal);
        Assert.Contains("Text=\"{Binding StatusMessage}\"", xaml, StringComparison.Ordinal);
    }

    [Fact]
    public void Composition_view_exposes_auto_cpu_and_gpu_processor_selector()
    {
        var repoRoot = FindRepoRoot();
        var xamlPath = Path.Combine(
            repoRoot,
            "src",
            "JingXu.Workbench",
            "Features",
            "Composition",
            "CompositionView.xaml");
        var xaml = File.ReadAllText(xamlPath);

        Assert.Contains("AutomationProperties.Name=\"处理器自动\"", xaml, StringComparison.Ordinal);
        Assert.Contains("AutomationProperties.Name=\"处理器CPU\"", xaml, StringComparison.Ordinal);
        Assert.Contains("AutomationProperties.Name=\"处理器GPU\"", xaml, StringComparison.Ordinal);
        Assert.Contains(
            "IsChecked=\"{Binding SelectedProcessingMode, Converter={StaticResource EnumToBool}, ConverterParameter=Auto}\"",
            xaml,
            StringComparison.Ordinal);
    }

    [Fact]
    public void Composition_view_exposes_double_screen_source_and_feather_controls()
    {
        var repoRoot = FindRepoRoot();
        var xamlPath = Path.Combine(
            repoRoot,
            "src",
            "JingXu.Workbench",
            "Features",
            "Composition",
            "CompositionView.xaml");
        var xaml = File.ReadAllText(xamlPath);

        Assert.Contains("随机抽取当前素材文件夹", xaml, StringComparison.Ordinal);
        Assert.Contains("双屏中缝羽化", xaml, StringComparison.Ordinal);
        Assert.Contains("双屏羽化强度", xaml, StringComparison.Ordinal);
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

    private static string FindRepoRoot()
    {
        var dir = AppContext.BaseDirectory;
        while (!string.IsNullOrEmpty(dir))
        {
            if (File.Exists(Path.Combine(dir, "JingXu.Workbench.sln")))
            {
                return dir;
            }

            dir = Directory.GetParent(dir)?.FullName ?? string.Empty;
        }

        throw new InvalidOperationException("无法定位仓库根目录。");
    }
}
