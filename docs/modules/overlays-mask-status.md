# 蒙版模板 — 模块现状

## 文档目的

保留「三类视频蒙版、多层合成、素材库、随机抽取」的设计意图，记录 Overlay 模块实现与已知测试缺口。

## 目标设计

- 三种模式：自由覆盖层、全屏低透明度、形状遮罩；均可多层。
- 从第 N 个主素材开头换算绝对时间；默认可丢弃蒙版音频；时长不足循环并对齐片尾。
- 素材库：路径、标签、缩略图、最近使用；随机抽取由任务种子派生。
- 适配：填满裁切 / 完整适配 / 拉伸。

规格：§5.7。

## 开发现状

| 能力 | 状态 | 路径 / 证据 |
|------|------|-------------|
| 领域模型与时间轴 | ✅ | `Domain/Overlays/OverlayModels.cs`、`OverlayTimelineResolver.cs`、`OverlaySourceSelector.cs` |
| 滤镜编译 | ✅ | `Infrastructure/Rendering/OverlayFilterCompiler.cs` |
| 入队解析 | ✅ | `Application/Overlays/OverlayEnqueueResolver.cs`、`OverlayWorkbenchState.cs` |
| 编辑 UI | ✅ | `Features/Overlays/OverlayEditorView.xaml` + `OverlayEditorViewModel.cs` |
| 素材库 JSON | ✅ | `OverlayLibraryService` + `AtomicJsonStore<OverlayLibraryDocument>`；组合根已装配 |
| 混剪侧启用蒙版 | ✅ | `CompositionViewModel` 的 overlay 相关开关与库随机选项 |
| 冒烟 CLI | ✅ | `App` 参数 `--overlay-smoke` → `OverlaySmokeRunner` |
| 像素级集成 | ✅ | `OverlayRenderTests`（含椭圆形状遮罩）通过；滤镜改为 rgba alpha |

壳层导航：`WorkspaceModule.Overlays`，标签「蒙版」。

## 待对齐项

1. ~~稳定三类蒙版 lavfi/像素集成测试~~：`OverlayRenderTests` 现用椭圆验证形状 alpha；滤镜已改为 rgba `geq`/`alphamerge`。
2. 文档勿再写独立 `Materials` 蒙版入口；蒙版库在 Overlays 模块 + 混剪侧引用。
3. `OverlayAudioMode.Mix`：渲染侧已接线（`AudioFilterCompiler.CompileOverlayMix`）；蒙版页可选「混入蒙版音轨」。
4. 随机素材库：入队时 `ProbeSourceDurationsAsync` 探测真实时长（替换默认 3s 元数据）。
