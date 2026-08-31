namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>
/// staging 工作目录下的短相对路径别名，对应真实输入文件。
/// 执行前由渲染器硬链接/符号链接/复制到 staging，使 argv 中的 <c>-i</c> 保持短路径。
/// </summary>
public sealed record FfmpegInputAlias(string RelativePath, string AbsolutePath);
