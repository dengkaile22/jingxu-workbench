using System.Globalization;
using System.Text;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>输出文件命名与默认目录策略。</summary>
public static class OutputNamePolicy
{
    /// <summary>
    /// 单一源文件夹时使用 <c>&lt;source&gt;\分镜输出</c>；
    /// 多来源时使用 <c>&lt;project&gt;\分镜输出</c>。
    /// 与 <see cref="JingXu.Workbench.Application.Rendering.RenderRequestFactory.ResolveDefaultOutputDirectory"/> 语义一致。
    /// </summary>
    public static string DefaultDirectory(IReadOnlyList<string> sourceFolders, string projectDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(projectDirectory);
        ArgumentNullException.ThrowIfNull(sourceFolders);

        if (sourceFolders.Count == 1 &&
            !string.IsNullOrWhiteSpace(sourceFolders[0]))
        {
            return Path.Combine(sourceFolders[0], "分镜输出");
        }

        return Path.Combine(projectDirectory, "分镜输出");
    }

    /// <summary>在目标目录中为输出文件分配不冲突的路径（三位序号后缀）。</summary>
    public static string AllocateUniquePath(string directory, string baseFileName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(directory);
        ArgumentException.ThrowIfNullOrWhiteSpace(baseFileName);

        var candidate = Path.Combine(directory, baseFileName);
        if (!File.Exists(candidate))
        {
            return candidate;
        }

        var name = Path.GetFileNameWithoutExtension(baseFileName);
        var ext = Path.GetExtension(baseFileName);
        for (var index = 1; index <= 999; index++)
        {
            candidate = Path.Combine(directory, $"{name}_{index:D3}{ext}");
            if (!File.Exists(candidate))
            {
                return candidate;
            }
        }

        throw new InvalidOperationException($"无法在目录 {directory} 中为 {baseFileName} 分配唯一文件名。");
    }
}
