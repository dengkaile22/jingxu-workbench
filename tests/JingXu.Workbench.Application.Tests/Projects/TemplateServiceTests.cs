using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Effects;
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
}
