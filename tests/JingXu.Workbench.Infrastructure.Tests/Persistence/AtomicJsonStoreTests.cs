using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Infrastructure.Persistence;

namespace JingXu.Workbench.Infrastructure.Tests.Persistence;

public sealed class AtomicJsonStoreTests : IDisposable
{
    private readonly string _tempDir;

    public AtomicJsonStoreTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "jingxu-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDir))
        {
            Directory.Delete(_tempDir, recursive: true);
        }
    }

    private static AtomicJsonStore<ProjectDocument> CreateStore(IFileCommitter? committer = null) =>
        new(ProjectDocument.CurrentSchemaVersion, committer);

    [Fact]
    public async Task Save_then_load_round_trips_schema_version_and_unicode()
    {
        var store = CreateStore();
        var source = ProjectDocument.Create("口红混剪", _tempDir);
        var filePath = Path.Combine(_tempDir, "project.jxproj");

        await store.SaveAsync(filePath, source, DocumentAccessMode.ReadWrite, default);
        var loaded = await store.LoadAsync(filePath, default);

        Assert.Equal(ProjectDocument.CurrentSchemaVersion, loaded.Document.SchemaVersion);
        Assert.Equal("口红混剪", loaded.Document.Name);
        Assert.Equal(DocumentAccessMode.ReadWrite, loaded.AccessMode);
    }

    [Fact]
    public async Task Newer_schema_opens_read_only_and_cannot_be_overwritten()
    {
        var filePath = Path.Combine(_tempDir, "future.jxproj");

        // 手动写一个比当前版本高的 schema
        var json = $$"""
        {
          "schemaVersion": {{ProjectDocument.CurrentSchemaVersion + 1}},
          "name": "未来项目"
        }
        """;
        await File.WriteAllTextAsync(filePath, json);

        var store = CreateStore();
        var result = await store.LoadAsync(filePath, default);

        Assert.Equal(DocumentAccessMode.ReadOnlyNewerSchema, result.AccessMode);
        await Assert.ThrowsAsync<ReadOnlyDocumentException>(() =>
            store.SaveAsync(filePath, result.Document, result.AccessMode, default));
    }

    [Fact]
    public async Task Save_does_not_leave_temp_file_on_success()
    {
        var store = CreateStore();
        var source = ProjectDocument.Create("测试", _tempDir);
        var filePath = Path.Combine(_tempDir, "clean.jxproj");

        await store.SaveAsync(filePath, source, DocumentAccessMode.ReadWrite, default);

        Assert.False(File.Exists(filePath + ".tmp"));
        Assert.True(File.Exists(filePath));
    }

    [Fact]
    public async Task Save_creates_directory_if_missing()
    {
        var store = CreateStore();
        var source = ProjectDocument.Create("嵌套", _tempDir);
        var nestedDir = Path.Combine(_tempDir, "sub", "dir");
        var filePath = Path.Combine(nestedDir, "project.jxproj");

        await store.SaveAsync(filePath, source, DocumentAccessMode.ReadWrite, default);

        Assert.True(File.Exists(filePath));
    }

    [Fact]
    public async Task Overwrite_preserves_data_integrity()
    {
        var store = CreateStore();
        var filePath = Path.Combine(_tempDir, "overwrite.jxproj");

        var first = ProjectDocument.Create("第一版", _tempDir);
        await store.SaveAsync(filePath, first, DocumentAccessMode.ReadWrite, default);

        var second = ProjectDocument.Create("第二版", _tempDir);
        await store.SaveAsync(filePath, second, DocumentAccessMode.ReadWrite, default);

        var loaded = await store.LoadAsync(filePath, default);
        Assert.Equal("第二版", loaded.Document.Name);
    }

    [Fact]
    public async Task Commit_failure_preserves_previous_target_bytes()
    {
        var filePath = Path.Combine(_tempDir, "fault.jxproj");
        var first = ProjectDocument.Create("保留版", _tempDir);
        await CreateStore().SaveAsync(filePath, first, DocumentAccessMode.ReadWrite, default);
        var originalBytes = await File.ReadAllBytesAsync(filePath);

        var failing = new ThrowingFileCommitter();
        var store = CreateStore(failing);
        var second = ProjectDocument.Create("不应写入", _tempDir);

        await Assert.ThrowsAsync<IOException>(() =>
            store.SaveAsync(filePath, second, DocumentAccessMode.ReadWrite, default));

        Assert.Equal(originalBytes, await File.ReadAllBytesAsync(filePath));
        Assert.False(File.Exists(filePath + ".tmp"));

        var reloaded = await CreateStore().LoadAsync(filePath, default);
        Assert.Equal("保留版", reloaded.Document.Name);
    }

    private sealed class ThrowingFileCommitter : IFileCommitter
    {
        public void Commit(string tempPath, string targetPath) =>
            throw new IOException("模拟提交失败。");
    }
}
