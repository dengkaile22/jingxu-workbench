namespace JingXu.Workbench.Application.Abstractions;

/// <summary>
/// 文档访问模式。
/// </summary>
public enum DocumentAccessMode
{
    /// <summary>可读写。</summary>
    ReadWrite,

    /// <summary>只读：文档版本高于应用支持的版本。</summary>
    ReadOnlyNewerSchema
}

/// <summary>
/// 文档加载结果。
/// </summary>
public sealed record DocumentLoadResult<T>(T Document, DocumentAccessMode AccessMode);

/// <summary>
/// 只读文档异常：试图写入来自更新版本的文档。
/// </summary>
public sealed class ReadOnlyDocumentException : InvalidOperationException
{
    public ReadOnlyDocumentException()
        : base("无法保存来自更新版本的只读文档。请升级应用程序后再试。") { }
}

/// <summary>
/// 原子 JSON 存储接口。保存使用临时文件写入后原子替换。
/// </summary>
public interface IAtomicJsonStore<T> where T : class
{
    /// <summary>加载文档。高于当前版本时返回只读模式。</summary>
    Task<DocumentLoadResult<T>> LoadAsync(string path, CancellationToken cancellationToken);

    /// <summary>原子保存文档。ReadOnly 模式下抛出 ReadOnlyDocumentException。</summary>
    Task SaveAsync(string path, T document, DocumentAccessMode accessMode, CancellationToken cancellationToken);
}
