using JingXu.Workbench.Domain.Overlays;

namespace JingXu.Workbench.Application.Overlays;

/// <summary>跨模块共享的蒙版配置快照，入队时深拷贝到 <see cref="Domain.Rendering.RenderRequest"/>。</summary>
public sealed class OverlayWorkbenchState
{
    private readonly List<OverlayLayer> _layers = [];

    /// <summary>当前配置的蒙版层（只读视图）。</summary>
    public IReadOnlyList<OverlayLayer> Layers => _layers;

    /// <summary>是否已配置至少一层蒙版。</summary>
    public bool HasLayers => _layers.Count > 0;

    /// <summary>入队时是否将蒙版叠加到成片。</summary>
    public bool IsEnabled { get; set; }

    /// <summary>是否从素材库随机选取蒙版素材路径（保留层参数）。</summary>
    public bool UseRandomLibrarySource { get; set; }

    /// <summary>蒙版配置或开关变更时触发。</summary>
    public event Action? Changed;

    /// <summary>设置入队开关并通知订阅方。</summary>
    public void SetEnabled(bool enabled)
    {
        if (IsEnabled == enabled)
        {
            return;
        }

        IsEnabled = enabled;
        Changed?.Invoke();
    }

    /// <summary>设置随机素材库开关并通知订阅方。</summary>
    public void SetUseRandomLibrarySource(bool useRandom)
    {
        if (UseRandomLibrarySource == useRandom)
        {
            return;
        }

        UseRandomLibrarySource = useRandom;
        Changed?.Invoke();
    }

    /// <summary>替换全部蒙版层。</summary>
    public void ReplaceAll(IEnumerable<OverlayLayer> layers)
    {
        ArgumentNullException.ThrowIfNull(layers);
        var sorted = OverlayTimelineResolver.Sort(layers).ToArray();
        _layers.Clear();
        _layers.AddRange(sorted);
        Changed?.Invoke();
    }

    /// <summary>追加一层蒙版。</summary>
    public void Add(OverlayLayer layer)
    {
        ArgumentNullException.ThrowIfNull(layer);
        var next = _layers.ToList();
        next.Add(layer);
        ReplaceAll(next);
    }

    /// <summary>更新指定名称的蒙版层。</summary>
    public void Update(string name, OverlayLayer layer)
    {
        ArgumentNullException.ThrowIfNull(layer);
        var index = _layers.FindIndex(x => x.Name == name);
        if (index < 0)
        {
            return;
        }

        _layers[index] = layer;
        ReplaceAll(_layers);
    }

    /// <summary>移除蒙版层。</summary>
    public void Remove(string name)
    {
        _layers.RemoveAll(x => x.Name == name);
        Changed?.Invoke();
    }

    /// <summary>创建入队用的不可变副本。</summary>
    public IReadOnlyList<OverlayLayer> CreateSnapshot() => _layers.ToArray();
}
