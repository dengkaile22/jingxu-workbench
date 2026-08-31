using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Stickers;
using JingXu.Workbench.Infrastructure.Persistence;

namespace JingXu.Workbench.Application.Tests.Projects;

public sealed class TemplateServiceTests : IDisposable
{
    private readonly string _tempDir;

    public TemplateServiceTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "jingxu-template-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDir))
        {
            Directory.Delete(_tempDir, recursive: true);
        }
    }

    [Fact]
    public async Task Save_then_load_round_trips_effect_templates()
    {
        var store = new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion);
        var service = new TemplateService(store);
        var path = Path.Combine(_tempDir, "effect-templates.json");
        var source = new EffectTemplateDocument
        {
            Templates =
            [
                EffectTemplates.None,
                EffectTemplates.StandardVariation()
            ]
        };

        await service.SaveAsync(source, path);
        var loaded = await service.LoadAsync(path);

        Assert.Equal(EffectTemplateDocument.CurrentSchemaVersion, loaded.SchemaVersion);
        Assert.Equal(2, loaded.Templates.Count);
        Assert.Equal(EffectTemplates.None, loaded.Templates[0]);
        Assert.Equal(EffectTemplates.StandardVariation(), loaded.Templates[1]);
    }

    [Fact]
    public async Task Load_missing_file_returns_builtin_defaults()
    {
        var service = new TemplateService(
            new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion));
        var loaded = await service.LoadAsync(Path.Combine(_tempDir, "missing.json"));

        Assert.Equal(EffectTemplateDocument.WithDefaults.Templates.Count, loaded.Templates.Count);
        Assert.Contains(loaded.Templates, t => t.Id == EffectTemplates.StandardVariation().Id);
    }

    [Fact]
    public async Task Round_tripped_template_materializes_same_effect_for_seed()
    {
        var store = new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion);
        var service = new TemplateService(store);
        var path = Path.Combine(_tempDir, "templates.json");
        var template = EffectTemplates.StandardVariation();

        await service.SaveAsync(new EffectTemplateDocument { Templates = [template] }, path);
        var loaded = await service.LoadAsync(path);
        var restored = Assert.Single(loaded.Templates);

        Assert.Equal(template.Materialize(264513), restored.Materialize(264513));
    }

    [Fact]
    public async Task Save_then_load_round_trips_sticker_snapshot()
    {
        var store = new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion);
        var path = Path.Combine(_tempDir, "with-sticker.json");
        var service = new TemplateService(store, path);
        var template = EffectTemplates.StandardVariation();
        var source = new EffectTemplateDocument
        {
            Templates = [template],
            StickersByTemplateId = new Dictionary<string, StickerTemplateDto>
            {
                [template.Id] = new StickerTemplateDto
                {
                    Path = @"C:\贴纸\a.png",
                    X = 0.1,
                    Y = 0.2,
                    Width = 0.3,
                    Height = 0.25,
                    Opacity = 0.8
                }
            }
        };

        await service.SaveAsync(source);
        var loaded = await service.LoadAsync();

        Assert.True(loaded.StickersByTemplateId.TryGetValue(template.Id, out var sticker));
        Assert.Equal(@"C:\贴纸\a.png", sticker!.Path);
        Assert.Equal(0.1, sticker.X);
        Assert.Equal(0.8, sticker.Opacity);
    }

    [Fact]
    public async Task Save_then_load_round_trips_effect_settings_and_multiple_sticker_tracks()
    {
        var path = Path.Combine(_tempDir, "with-settings.json");
        var service = new TemplateService(
            new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion),
            path);
        var template = EffectTemplates.StandardVariation() with
        {
            Id = "user-settings",
            DisplayName = "双贴纸"
        };
        var source = new EffectTemplateDocument
        {
            Templates = [template],
            SettingsByTemplateId = new Dictionary<string, EffectTemplateSettingsDto>
            {
                [template.Id] = new EffectTemplateSettingsDto
                {
                    VariationIntensityPercent = 135,
                    StickerTracks =
                    [
                        new StickerTrackTemplateDto
                        {
                            Name = "左上",
                            Path = @"C:\贴纸\a.png",
                            X = 0.1,
                            Y = 0.2,
                            Width = 0.3,
                            Height = 0.25,
                            Opacity = 0.8,
                            RotationDegrees = -5,
                            IsEnabled = true,
                            FixedAspectRatio = FixedAspectRatio.Ratio1x1
                        },
                        new StickerTrackTemplateDto
                        {
                            Name = "右下",
                            Path = @"C:\贴纸\b.png",
                            X = 0.6,
                            Y = 0.7,
                            Width = 0.2,
                            Height = 0.15,
                            Opacity = 0.9,
                            RotationDegrees = 3,
                            IsEnabled = false
                        }
                    ]
                }
            }
        };

        await service.SaveAsync(source);
        var loaded = await service.LoadAsync();

        var settings = Assert.Contains(template.Id, loaded.SettingsByTemplateId);
        Assert.Equal(135, settings.VariationIntensityPercent);
        Assert.Collection(
            settings.StickerTracks,
            first =>
            {
                Assert.Equal("左上", first.Name);
                Assert.Equal(-5, first.RotationDegrees);
                Assert.Equal(FixedAspectRatio.Ratio1x1, first.FixedAspectRatio);
            },
            second =>
            {
                Assert.Equal("右下", second.Name);
                Assert.False(second.IsEnabled);
            });
    }

    [Fact]
    public async Task Rename_preserves_and_delete_removes_effect_settings()
    {
        var path = Path.Combine(_tempDir, "manage-settings.json");
        var service = new TemplateService(
            new AtomicJsonStore<EffectTemplateDocument>(EffectTemplateDocument.CurrentSchemaVersion),
            path);
        var template = EffectTemplates.StandardVariation() with
        {
            Id = "user-managed",
            DisplayName = "待管理"
        };
        await service.SaveAsync(new EffectTemplateDocument
        {
            Templates = [template],
            SettingsByTemplateId = new Dictionary<string, EffectTemplateSettingsDto>
            {
                [template.Id] = new EffectTemplateSettingsDto { VariationIntensityPercent = 80 }
            }
        });

        var renamed = await service.RenameUserTemplateAsync(template.Id, "已重命名");
        Assert.True(renamed.Renamed);
        Assert.Contains(template.Id, renamed.Document.SettingsByTemplateId);

        var deleted = await service.DeleteUserTemplateAsync(template.Id);
        Assert.True(deleted.Removed);
        Assert.DoesNotContain(template.Id, deleted.Document.SettingsByTemplateId);
    }
}
