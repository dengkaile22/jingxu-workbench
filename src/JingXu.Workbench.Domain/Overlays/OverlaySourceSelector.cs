using JingXu.Workbench.Domain.Composition;

namespace JingXu.Workbench.Domain.Overlays;

/// <summary>从蒙版素材库中按任务种子确定性随机选取条目。</summary>
public static class OverlaySourceSelector
{
    /// <summary>
    /// 使用任务种子从库中选取一条蒙版素材。
    /// 相同种子与库内容保证得到相同结果。
    /// </summary>
    public static OverlayLibraryEntry Select(
        IReadOnlyList<OverlayLibraryEntry> library,
        int jobSeed,
        int branchIndex = 0)
    {
        ArgumentNullException.ThrowIfNull(library);

        if (library.Count == 0)
        {
            throw new InvalidOperationException("蒙版素材库为空，无法随机选取。");
        }

        if (library.Count == 1)
        {
            return library[0];
        }

        var random = DeterministicRandom.FromBranch(jobSeed, branchIndex);
        var index = random.Next(library.Count);
        return library[index];
    }

    /// <summary>批量选取多条不重复条目（库容量不足时允许重复）。</summary>
    public static IReadOnlyList<OverlayLibraryEntry> SelectMany(
        IReadOnlyList<OverlayLibraryEntry> library,
        int count,
        int jobSeed)
    {
        ArgumentNullException.ThrowIfNull(library);

        if (count <= 0)
        {
            return [];
        }

        if (library.Count == 0)
        {
            throw new InvalidOperationException("蒙版素材库为空，无法随机选取。");
        }

        var results = new List<OverlayLibraryEntry>(count);
        for (var i = 0; i < count; i++)
        {
            results.Add(Select(library, jobSeed, branchIndex: i));
        }

        return results;
    }
}
