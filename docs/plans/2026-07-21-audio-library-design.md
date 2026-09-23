# 音频库（Audio Library）设计文档

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（`src/JingXu.Workbench.Py`），文中 `.cs`/`.xaml` 路径仅作历史记录。

## 概述

将现有的「混剪页单文件 BGM」功能升级为完整的音频库系统，实现：
- 导入/管理多个音频素材到库中
- 每个渲染任务**随机抽取**库内一个音频作为背景音乐
- 音频时长**不够**时自动循环（已有 BGM aloop 机制支持）
- 音频时长**超出**时自动裁剪对齐成品时长（已有 BGM atrim 机制支持）
- 音量控制：**自定义固定值**或**随机区间**，范围 -100 ~ +100（增益百分比）
- 高随机性：使用 `DeterministicShuffleCycle.SelectIndexWithReshuffledCycles`（与贴纸一致）

---

## 设计原则

1. **按已有贴纸库模式复制**：文档/服务/ViewModel 结构对标 `StickerLibraryService`
2. **增量不删减**：保留现有 `BgmMixPlan`、`EnableBgm`、`BgmPath` 单文件 BGM 能力，新增的音频库作为**可选升级路径**
3. **入队时决定**：每个渲染任务在入队时从库中随机选一条，物化为 `BgmMixPlan` 传给现有渲染管线
4. **不影响现有渲染管线**：`AudioFilterCompiler` 已天然支持 `aloop`/`atrim`，仅需调整 `volume` 参数映射

---

## 新增文件

### 1. Domain: `src/JingXu.Workbench.Domain/Effects/AudioLibraryEntry.cs`

```csharp
namespace JingXu.Workbench.Domain.Effects;

/// <summary>音频库条目。</summary>
public sealed record AudioLibraryEntry(
    Guid Id,
    string FilePath,
    TimeSpan Duration,
    string? DisplayName,
    DateTimeOffset? LastUsedAt)
{
    public string FileName => System.IO.Path.GetFileName(FilePath);
}

/// <summary>音频音量模式。</summary>
public enum AudioVolumeMode
{
    /// <summary>使用默认音量（BGM 默认 18%，原声 100%）。</summary>
    Default,

    /// <summary>固定音量值。</summary>
    Fixed,

    /// <summary>在区间内随机。</summary>
    RandomRange
}

/// <summary>音频库物化后的混音计划（入队时生成，替换 BgmMixPlan）。</summary>
public sealed record AudioLibraryMixPlan(
    string Path,
    TimeSpan SourceDuration,
    double OriginalVolume,
    double BgmVolume,
    double FadeOutSeconds)
{
    /// <summary>物化为 BgmMixPlan（复用现有渲染管线）。</summary>
    public BgmMixPlan ToBgmMixPlan() =>
        new(Path, OriginalVolume, BgmVolume, FadeOutSeconds);
}
```

### 2. Application: `src/JingXu.Workbench.Application/Projects/AudioLibraryService.cs`

完全对标 `StickerLibraryService`，包含：

| 方法 | 说明 |
|------|------|
| `LoadAsync()` | 加载音频库 |
| `RegisterAsync(path, duration)` | 注册音频（含时长探测） |
| `RemoveAsync(id)` | 删除条目 |
| `ClearAllAsync()` | 清空库 |
| `TouchAsync(id)` | 更新最后使用时间 |

### 3. Presentation: `src/JingXu.Workbench/Features/AudioLibrary/AudioLibraryViewModel.cs`

新模块 ViewModel，对标 `StickerEditorViewModel`，包含：

| 属性/命令 | 说明 |
|-----------|------|
| `LibraryEntries` | 可观察库列表 |
| `ImportAudioFilesCommand` | 导入音频 |
| `RemoveEntryCommand` | 删除条目 |
| `ClearAllCommand` | 清空库 |
| `PreviewPlaybackCommand` | 试听选中音频 |

### 4. Presentation: `src/JingXu.Workbench/Features/AudioLibrary/AudioLibraryView.xaml` + `.cs`

音频库管理页面 UI。

---

## 修改文件

### 1. Domain: `src/JingXu.Workbench.Domain/Effects/EffectTemplate.cs`

在 `BgmMixPlan` 旁增加音量范围枚举和新构造：

```csharp
// 新增：音频增益映射常量
public static class AudioVolumeMapping
{
    /// <summary>
    /// 将用户界面 -100~+100 的百分比值映射为 FFmpeg volume 增益因子。
    /// -100 → 0.0（静音）, 0 → 1.0（原声）, +100 → 2.0（两倍）
    /// </summary>
    public static double PercentToGain(double percent) =>
        Math.Clamp(1.0 + percent / 100.0, 0.0, 2.0);
}
```

### 2. Application: `src/JingXu.Workbench.Application/Rendering/RenderRequestFactory.cs`

新增 `CreateForPlans` 重载或参数，支持传入 `IReadOnlyList<AudioLibraryMixPlan>? audioPlansPerPlan`。

### 3. Infrastructure: `src/JingXu.Workbench.Infrastructure/Rendering/AudioFilterCompiler.cs`

当前 `Compile` 方法已支持 BGM 循环/裁剪：
- `aloop=loop=-1:size=2e+09` → 无限循环（时长不够自动补）
- `atrim=duration={durationSeconds}` → 裁剪到成品时长（超出自动截断）
- `volume={FormatDecimal(bgm.BgmVolume)}` → 音量增益

**不需要修改**：音频库物化后的 `BgmMixPlan` 直接传入现有路径即可。

### 4. Infrastructure: `src/JingXu.Workbench.Infrastructure/Rendering/FfmpegCommandCompiler.cs`

当前已通过 `request.Bgm` 传入 BgmMixPlan，音频库物化后生成同样的结构，**无需修改**。

### 5. Presentation: `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs`

这是**核心修改文件**，需要整合音频库随机选择逻辑。

#### a) 新增字段/属性

```csharp
// 音频库状态
private AudioLibraryService? _audioLibraryService;
private int _audioLibrarySeed = Random.Shared.Next();
private long _nextRandomAudioSelectionOrdinal;

// 入队时的全局抽取序号在构造函数中初始化
_nextRandomAudioSelectionOrdinal = coordinator.Jobs.Count;
```

#### b) 新增 UI 属性（对标贴纸随机替换）

| 属性 | 类型 | 说明 |
|------|------|------|
| `EnableAudioLibrary` | bool | 启用音频库（替换单文件 BGM） |
| `AudioVolumeMode` | AudioVolumeMode | Default/Fixed/RandomRange |
| `AudioFixedVolumePercent` | double | 固定音量值（-100~100） |
| `AudioVolumeMinPercent` | double | 随机音量下限 |
| `AudioVolumeMaxPercent` | double | 随机音量上限 |
| `AudioLibraryEntryCount` | int | 库内音频数量 |
| `HasAudioLibraryEntries` | bool | 是否有库条目 |

#### c) 入队时随机选择逻辑（对标 `TryBuildStickersForPlan`）

```csharp
private AudioLibraryMixPlan? ResolveAudioForPlan(
    IReadOnlyList<AudioLibraryEntry> libraryEntries,
    CompositionPlan plan,
    long planOrdinal,
    int seed)
{
    if (!EnableAudioLibrary || libraryEntries.Count == 0)
    {
        return null;  // 回退到单文件 BGM
    }

    var index = DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
        libraryEntries.Count,
        seed,
        planOrdinal,
        branchIndex: 3);  // 与贴纸/蒙版不同的 branchIndex 避免冲突

    var entry = libraryEntries[index];

    double bgmGain;
    if (AudioVolumeMode == AudioVolumeMode.Fixed)
    {
        bgmGain = AudioVolumeMapping.PercentToGain(AudioFixedVolumePercent);
    }
    else if (AudioVolumeMode == AudioVolumeMode.RandomRange)
    {
        var rng = DeterministicRandom.FromBranch(seed, 200 + (int)(planOrdinal % 1000));
        var percent = AudioVolumeMinPercent + (AudioVolumeMaxPercent - AudioVolumeMinPercent) * rng.NextDouble();
        bgmGain = AudioVolumeMapping.PercentToGain(percent);
    }
    else
    {
        bgmGain = 0.18;  // Default: 保持现有 BGM 默认音量 18%
    }

    return new AudioLibraryMixPlan(
        entry.FilePath,
        entry.Duration,
        OriginalVolume: 1.0,  // 原声保持 100%
        BgmVolume: bgmGain,
        FadeOutSeconds: 1.0);
}
```

#### d) 入队核心方法 `EnqueueCoreAsync` 修改

在现有 BGM 处理块之后，增加：

```csharp
// 确定最终 BgmMixPlan：音频库优先，回退单文件 BGM
AudioLibraryMixPlan? audioPlan = null;
if (EnableAudioLibrary && libraryEntries.Count > 0)
{
    audioPlan = ResolveAudioForPlan(libraryEntries, plan, i, ...);
}

// 使用 audioPlan.ToBgmMixPlan() 替代现有的 bgm
var bgmForRequest = audioPlan?.ToBgmMixPlan() ?? bgm;
```

#### e) 新增命令

| 命令 | 说明 |
|------|------|
| `ImportAudioFilesCommand` | 导入音频到库 |
| `RefreshAudioLibraryCommand` | 刷新库列表 |

### 6. Presentation: `src/JingXu.Workbench/Features/Shell/ShellViewModel.cs`

- 在 `WorkspaceModule` 枚举新增 `AudioLibrary` 条目
- 在 `Modules` 列表新增一个 `ShellModuleTab("音频", ...)`
- 在 `_content` 字典缓存 `AudioLibraryViewModel` 实例
- 在构造函数参数列表新增 `AudioLibraryViewModel`

### 7. Presentation: `src/JingXu.Workbench/Bootstrap/AppCompositionRoot.cs`

- 注册 `AudioLibraryService`（使用 `AtomicJsonStore<AudioLibraryDocument>`）
- 创建 `AudioLibraryViewModel` 实例
- 传递给 `ShellViewModel`
- 传递给 `CompositionViewModel`（供入队时随机选择）

### 8. Presentation: `src/JingXu.Workbench/ShellWindow.xaml`

- 新增 `DataTemplate` for `AudioLibraryViewModel → AudioLibraryView`

### 9. Presentation: `src/JingXu.Workbench/Features/Shell/WorkspaceModule.cs`

新增枚举值：

```csharp
/// <summary>音频库。</summary>
AudioLibrary,
```

---

## 影响分析

### ✅ 不影响的功能

| 模块 | 影响 | 原因 |
|------|------|------|
| 现有单文件 BGM | **完全保留** | 音频库关闭时回退到现有 `EnableBgm` + `BgmPath` |
| 渲染管线 | **无影响** | 音频库最终物化为 `BgmMixPlan`，管线无感知 |
| 蒙版系统 | **无影响** | 仅增不改 |
| 贴纸系统 | **无影响** | 仅增不改 |
| 字幕实验室 | **无影响** | 独立模块 |
| 下载模块 | **无影响** | 独立模块 |
| 设置/自检 | **无影响** | 不涉及运行时 |
| 队列调度 | **无影响** | 入队后任务快照不变 |
| 画幅/统一比例 | **无影响** | 音频不涉及画幅 |

### 🔶 需注意的风险

| 风险 | 说明 |
|------|------|
| **配置文件新增** | `%LOCALAPPDATA%\JingXu\audio-library.json` 新文件，升级时自动创建 |
| **内存占用** | 音频库列表常驻内存（与贴纸库同级） |
| **硬件编码与 BGM** | 现有逻辑：有 BGM 时强制转码，音频库继承此行为 |
| **种子确定性** | 随机选取使用独立 `branchIndex=3`，不与其他随机系统冲突 |
| **文件不存在** | 库中文件删除后入队时自动跳过，详见下方「文件可用性检测」 |

---

## 文件可用性检测（File Health Check）

用户担心库中的音频文件被移动/删除后，入队时随机选到「死文件」。这套检测机制**极轻量**，在入队时实时完成，不额外启动进程、不读取文件内容。

### 设计：三层次递进

```
┌─ 第 1 层：极速缓存（内存） ─────────────────────────┐
│  将 File.Exists 结果缓存在 ConcurrentDictionary 中， │
│  每条条目带时间戳，TTL = 30 秒。                     │
│  避免同一文件在连续任务入队时反复系统调用。              │
└──────────────────────────────────────────────────────┘
        ↓ 缓存未命中 / 已过期
┌─ 第 2 层：File.Exists（~1μs 级） ─────────────────────┐
│  .NET 原生 API，纯内核元数据查询，不读文件头/不打开流。 │
│  SSD 上单次调用 < 1μs，HDD < 5ms。                    │
│  结果写入第 1 层缓存（含「不存在」的负缓存）。           │
└──────────────────────────────────────────────────────┘
        ↓ 文件不存在
┌─ 第 3 层：自动跳过 + 回退 ───────────────────────────┐
│  ❌ 当前文件不存在 → 跳过，尝试下一个随机索引           │
│     （仍用 reshuffled cycles 保证均匀性）               │
│  ❌ 全部库文件都不存在 → 静默跳过（无 BGM）             │
│  ✅ 库非空但部分失效 → 继续用剩余有效文件随机            │
└──────────────────────────────────────────────────────┘
```

### 新增工具类：`src/JingXu.Workbench.Application/Common/FileExistenceCache.cs`

```csharp
namespace JingXu.Workbench.Application.Common;

/// <summary>
/// 极速文件存在性缓存。
/// File.Exists 本身已是 O(1) 内核调用，但批量编排（如 100 条计划）
/// 可能重复检测同一文件。此缓存以 TTL 避免重复系统调用。
/// 30 秒过期：足够覆盖一次批量入队，又不会让被删除文件长期「假活」。
/// </summary>
public sealed class FileExistenceCache
{
    private static readonly TimeSpan Ttl = TimeSpan.FromSeconds(30);
    private readonly ConcurrentDictionary<string, (bool Exists, long Tick)> _cache = new(StringComparer.OrdinalIgnoreCase);

    /// <summary>检查文件是否存在（缓存加速）。</summary>
    public bool Exists(string path)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;

        var now = Environment.TickCount64;
        if (_cache.TryGetValue(path, out var cached))
        {
            if (now - cached.Tick < Ttl.Ticks)
                return cached.Exists;
        }

        var exists = File.Exists(path);
        _cache[path] = (exists, now);
        return exists;
    }

    /// <summary>使缓存失效（文件被重新导入/修改时调用）。</summary>
    public void Invalidate(string path)
    {
        _cache.TryRemove(path, out _);
    }

    /// <summary>清空全部缓存（切换项目或长时间空闲时触发）。</summary>
    public void Clear() => _cache.Clear();
}
```

### Application 层：`src/JingXu.Workbench.Application/Projects/AudioLibraryEntryResolver.cs`

入队时随机选取 + 文件有效性验证的编排逻辑，单独抽取为工具类，便于测试：

```csharp
public static class AudioLibraryEntryResolver
{
    /// <summary>
    /// 从音频库中为单个成片计划选取一条有效的音频。
    /// 文件不存在时自动尝试下一个随机候补（最多重试 5 次），
    /// 全部无效时返回 null（静默跳过，不影响渲染）。
    /// </summary>
    public static AudioLibraryEntry? Resolve(
        IReadOnlyList<AudioLibraryEntry> library,
        int jobSeed,
        long planOrdinal,
        FileExistenceCache fileCache)
    {
        if (library.Count == 0) return null;

        var maxAttempts = Math.Min(5, library.Count);
        for (var attempt = 0; attempt < maxAttempts; attempt++)
        {
            var index = DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
                library.Count,
                jobSeed,
                planOrdinal + attempt,  // attempt 偏移保证重试不命中同一文件
                branchIndex: 3);

            var entry = library[index];
            if (fileCache.Exists(entry.FilePath))
            {
                return entry;
            }
        }

        return null;  // 全部候补都失效，静默跳过
    }
}
```

### 性能数据（参考）

| 场景 | 耗时 | 说明 |
|------|------|------|
| File.Exists（SSD，缓存命中） | **~0ns** | 纯内存查找，无系统调用 |
| File.Exists（SSD，缓存未命中） | **~0.5-2μs** | 一次 GetFileAttributesEx 内核调用 |
| File.Exists（NVMe） | **~0.3μs** | 现代 NVMe SSD |
| 批量 100 条计划全部检测 | **< 200μs** | 含 100 次 File.Exists |
| 音频库管理页「刷新」 | **< 1ms** | 仅检测库内条目，数十到数百条 |

**结论**：这套检测的 CPU 开销远低于用户一次鼠标点击，完全无需担心性能。

### 扩展到贴纸库和蒙版库（可选但推荐）

当前贴纸库和蒙版库在入队随机选取时**没有**文件存在性检测。建议用同一 `FileExistenceCache` 同步补充到：
- `StickerEditorViewModel.TryBuildEnabledTracksForPlan` → 贴纸随机选取时检查文件
- `OverlayEnqueueResolver.ResolveForPlan` → 蒙版随机替换时检查文件

这样三个库（贴纸/蒙版/音频）的随机选取行为一致，都具备「文件失效自动跳过」能力。

---

## 实施路线

### Step 1: Domain 层
- 新建 `AudioLibraryEntry.cs`
- 新增 `AudioVolumeMapping` 和 `AudioLibraryMixPlan`

### Step 2: Application 层
- 新建 `Common/FileExistenceCache.cs`（极速文件存在性缓存）
- 新建 `Projects/AudioLibraryEntryResolver.cs`（随机选取 + 文件有效性编排）
- 新建 `Projects/AudioLibraryService.cs`（对标 `StickerLibraryService`）

### Step 3: Presentation 层
- 新建 `AudioLibraryViewModel` + `AudioLibraryView.xaml/.cs`
- 修改 `WorkspaceModule.cs` 添加枚举
- 修改 `ShellViewModel.cs` 添加模块导航
- 修改 `AppCompositionRoot.cs` 注册服务

### Step 4: 混编页集成
- 修改 `CompositionViewModel.cs` 集成随机选择和音量控制
- 修改 `CompositionView.xaml` 添加音频库开关和音量选项 UI

### Step 5: 验证
- 构建 + 运行
- 测试：导入音频 → 随机选取 → 循环/裁剪 → 音量控制

---

## 与贴纸的差异对照

| 维度 | 贴纸库 | 音频库 |
|------|--------|--------|
| 领域模型 | `StickerTrack` + `StickerLibraryEntry` | `AudioLibraryEntry` |
| 持久化 | `StickerLibraryService` + JSON | `AudioLibraryService` + JSON |
| 随机算法 | `SelectIndexWithReshuffledCycles` | **同样使用** `SelectIndexWithReshuffledCycles` |
| 入队替换 | `TryBuildEnabledTracksForPlan` | `ResolveAudioForPlan` |
| 轨道数 | 多条贴纸叠加 | 每次只选 **1 条**音频 |
| 音量控制 | 无（贴纸不涉及） | -100~+100 固定/随机 |
| 时长处理 | 不涉及 | aloop 循环 + atrim 裁剪 |

---

## 效果预览（用户角度）

### 音频库管理页
```
┌─────────────────────────────────┐
│ 音频库        [导入文件] [清空]   │
├─────────────────────────────────┤
│ 🎵 bgm_01.mp3  00:45  最近使用  │
│ 🎵 bgm_02.mp3  03:20  2026-07  │
│ 🎵 chill.wav    02:15  2026-07  │
└─────────────────────────────────┘
```

### 混剪页（音频库区）
```
┌─ 启用音频库（随机选取） ─────────────────┐
│ ☑ 启用音频库（库内 3 条音频）            │
│                                          │
│ 音量模式： ◎ 默认  ○ 固定  ○ 随机区间   │
│                                          │
│ 固定音量 ───────────●──────────── +100   │
│             0 (原声)                     │
│                                          │
│ 或                                        │
│ 最小 ─●─────── +100  最大 ────●──── +100 │
└──────────────────────────────────────────┘
```

---

## 总结

- **新文件**: 6 个（Domain Model + FileExistenceCache + AudioLibraryEntryResolver + Service + ViewModel + View）
- **修改文件**: 7 个（CompositionViewModel、ShellViewModel、AppCompositionRoot、ShellWindow.xaml、WorkspaceModule.cs、EffectTemplate.cs、RenderRequestFactory.cs）
- **总工作量**: 中（~600-800 行新代码 + ~250 行修改）
- **可单独实施**: ✅ 音频库的导入管理页面可以独立工作，混剪页的随机选取依赖前者
- **不影响现有功能**: ✅ 关闭音频库开关即可回退到单文件 BGM
- **文件失效防护**: ✅ 三层递进（内存缓存 → File.Exists → 自动跳过），单次检测 < 2μs
- **可选扩展到贴纸/蒙版库**: ✅ 同一 `FileExistenceCache` 可复用
