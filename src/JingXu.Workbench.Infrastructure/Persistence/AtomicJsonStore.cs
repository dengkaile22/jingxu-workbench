using System.Text.Json;
using System.Text.Json.Serialization;
using JingXu.Workbench.Application.Abstractions;

namespace JingXu.Workbench.Infrastructure.Persistence;

/// <summary>
/// 将临时文件提交为目标文件的策略。生产环境使用原子替换；测试可注入失败以验证旧文件不被破坏。
/// </summary>
public interface IFileCommitter
{
    /// <summary>将 <paramref name="tempPath"/> 提交为 <paramref name="targetPath"/>。</summary>
    void Commit(string tempPath, string targetPath);
}

/// <summary>默认原子提交：目标存在时 <see cref="File.Replace"/>，否则 <see cref="File.Move"/>。</summary>
public sealed class AtomicFileCommitter : IFileCommitter
{
    public void Commit(string tempPath, string targetPath)
    {
        if (File.Exists(targetPath))
        {
            File.Replace(tempPath, targetPath, destinationBackupFileName: null);
        }
        else
        {
            File.Move(tempPath, targetPath);
        }
    }
}

/// <summary>
/// 使用临时文件写入后原子替换的 JSON 存储实现。
/// schema 版本上限由构造参数注入，避免与具体文档类型硬耦合。
/// </summary>
public sealed class AtomicJsonStore<T> : IAtomicJsonStore<T> where T : class
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    private readonly int _supportedSchemaVersion;
    private readonly IFileCommitter _committer;

    /// <summary>创建存储。</summary>
    /// <param name="supportedSchemaVersion">本应用可读写的最高 schema 版本。</param>
    /// <param name="committer">文件提交策略；为空时使用原子替换。</param>
    public AtomicJsonStore(int supportedSchemaVersion, IFileCommitter? committer = null)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(supportedSchemaVersion);
        _supportedSchemaVersion = supportedSchemaVersion;
        _committer = committer ?? new AtomicFileCommitter();
    }

    public async Task<DocumentLoadResult<T>> LoadAsync(string path, CancellationToken cancellationToken)
    {
        var bytes = await File.ReadAllBytesAsync(path, cancellationToken).ConfigureAwait(false);

        var accessMode = DocumentAccessMode.ReadWrite;
        using (var versionDoc = JsonDocument.Parse(bytes))
        {
            if (versionDoc.RootElement.TryGetProperty("schemaVersion", out var versionProp) &&
                versionProp.TryGetInt32(out var version) &&
                version > _supportedSchemaVersion)
            {
                accessMode = DocumentAccessMode.ReadOnlyNewerSchema;
            }
        }

        var document = JsonSerializer.Deserialize<T>(bytes, SerializerOptions)
            ?? throw new InvalidOperationException($"无法反序列化文档：{path}");

        return new DocumentLoadResult<T>(document, accessMode);
    }

    public async Task SaveAsync(string path, T document, DocumentAccessMode accessMode,
        CancellationToken cancellationToken)
    {
        if (accessMode == DocumentAccessMode.ReadOnlyNewerSchema)
        {
            throw new ReadOnlyDocumentException();
        }

        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var tempPath = path + ".tmp";

        try
        {
            await using (var stream = new FileStream(tempPath, FileMode.Create, FileAccess.Write,
                FileShare.None, 4096, useAsync: true))
            {
                await JsonSerializer.SerializeAsync(stream, document, SerializerOptions, cancellationToken)
                    .ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }

            _committer.Commit(tempPath, path);
        }
        catch
        {
            if (File.Exists(tempPath))
            {
                try { File.Delete(tempPath); }
                catch { /* 最大努力清理 */ }
            }

            throw;
        }
    }
}
