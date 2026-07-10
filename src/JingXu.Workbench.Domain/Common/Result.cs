using System.Diagnostics.CodeAnalysis;

namespace JingXu.Workbench.Domain.Common;

/// <summary>
/// 轻量强类型操作结果，替代异常驱动的控制流。
/// </summary>
[SuppressMessage("Design", "CA1000:Do not declare static members on generic types",
    Justification = "静态工厂方法是 Result<T> 的标准使用模式。")]
public readonly record struct Result<T>(T? Value, string? Error)
{
    /// <summary>操作是否成功。</summary>
    public bool IsSuccess => Error is null;

    /// <summary>创建成功结果。</summary>
    public static Result<T> Success(T value) => new(value, null);

    /// <summary>创建失败结果，附带中文错误信息。</summary>
    public static Result<T> Failure(string error) => new(default, error);
}
