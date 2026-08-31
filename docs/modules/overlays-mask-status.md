# 蒙版模板 — 模块现状

## 文档目的

记录 Overlay 模块实现与交互：**主流程仅为「导入蒙版素材」**（与混剪页导入主素材同构），已移除「自由覆盖 / 全屏低透明 / 形状遮罩」三类添加入口；**主片自叠影**入口已从 UI 移除（领域/渲染仍保留，勿当默认）。

## 目标设计

- **主交互**：蒙版页主按钮「导入蒙版素材」→ 多选视频 → 探测 → 加入蒙版列表，并写入素材库。
- 列表展示已导入蒙版（名称、文件名、边界、变换）；选中后可编辑透明度、起始片段、边界与变换等参数。
- **禁止** UI 再出现三类模式作为添加入口；列表也不再展示「自由覆盖 / 全屏低透明 / 形状遮罩」标签。
- 从第 N 个主素材开头换算绝对时间；默认可丢弃蒙版音频；时长不足循环并对齐片尾。
- 素材库：路径、标签、缩略图、最近使用；随机抽取由任务种子派生。
- 适配（混剪页）：填满裁切 / **裁成画幅再覆盖** / 完整适配 / 拉伸。
- 领域层仍保留三类 `OverlayMode` 与 PNG alpha 供渲染/兼容。
- **导入默认**走 `CreateImportedMaskPreset` → `CreateGhostOverlayPreset`：
  - `OverlayMode.FreeCover`
  - **Bounds = 上半红框** `ImportedMaskBounds ≈ (0.05, 0.05, 0.90, 0.42)`（Y≈0.05–0.47，近全宽略缩，减轻盖住下半商品）
  - 领域层 Opacity≈0.28（28% 不透明度 ≈ 72% 透明）、Scale=1、OffsetY=0、FillCrop
  - UI 标签为「透明度（0–100%）」：0=完全不透明，100=完全透明；已和领域 Opacity 反向对齐
  - **TopFade=1**：框内垂直 alpha = `min(1, Y/(H*TopFade))`（**中间一带更实，向上逐渐变淡**）
  - 下半屏基本无蒙版（靠 Bounds，不是全屏糊一层）
- **商品 3:4 + 蒙版 9:16**：混剪页选统一比例 3:4 时，蒙版适配自动切到 `MatchCanvasCrop`（先按画幅比例中心裁切蒙版源，可 `SourceCropY` 上下选取，再取覆盖区）。对齐剪映「先裁成 3:4 再覆盖 → 调分割 → 羽化」。
- 滤镜侧：`MatchCanvasCrop` = `crop(画幅比例)` → `scale(画布)` → `crop(Bounds)`；`geq` 乘 `TopFade`；`Feather` 软化底边分割线并 `gblur` 边缘；再 `overlay`。
- 右下角画中画保留为 `CreatePipMaskPreset`。`CreateScreenshotPreset`（顶部半屏横幅）仅截图类场景。形状/PNG 编辑 UI 为第二期。

规格：§5.7（交互已从「三类添加按钮」收敛为导入素材）。

## 开发现状

| 能力 | 状态 | 路径 / 证据 |
|------|------|-------------|
| 领域模型与时间轴 | ✅ | `Domain/Overlays/OverlayModels.cs`、`OverlayTimelineResolver.cs`、`OverlaySourceSelector.cs` |
| 滤镜编译 | ✅ | `Infrastructure/Rendering/OverlayFilterCompiler.cs` |
| 入队解析 | ✅ | `Application/Overlays/OverlayEnqueueResolver.cs`、`OverlayWorkbenchState.cs` |
| 编辑 UI | ✅ | `Features/Overlays/OverlayEditorView.xaml` + `OverlayEditorViewModel.cs`（仅 `ImportMaskMaterialsCommand`；区域预览蓝框可编辑 Bounds） |
| 素材库 JSON | ✅ | `OverlayLibraryService` + `AtomicJsonStore<OverlayLibraryDocument>`；导入时自动注册 |
| 混剪侧启用蒙版 | ✅ | `CompositionViewModel` 的 overlay 相关开关与库随机选项 |
| 冒烟 CLI | ✅ | `App` 参数 `--overlay-smoke` → `OverlaySmokeRunner` |
| 像素级集成 | ✅ | `OverlayRenderTests`（含椭圆形状遮罩）通过；滤镜改为 rgba alpha |
| 客户验收成片 | ✅ | `CustomerAssetAcceptanceTests` → `test-assets/验收成片-叠影蒙版.mp4` |

壳层导航：`WorkspaceModule.Overlays`，标签「蒙版」。

对话框标题：蒙版导入为「选择蒙版视频素材」；混剪导入默认为「选择视频素材」。

## 运行注意

- **Debug 输出**：`src/JingXu.Workbench/bin/Debug/net10.0-windows/炳恒快速混剪.exe`
- **便携/dist 包**：`dist/炳恒快速混剪.exe` 若时间戳旧于 Debug，会仍显示旧三选 UI；改完后须重新复制或重新打包，并**关掉正在运行的旧进程再启动新 exe**。

## 待对齐项

1. ~~稳定三类蒙版 lavfi/像素集成测试~~：`OverlayRenderTests` 现用椭圆验证形状 alpha；滤镜已改为 rgba `geq`/`alphamerge`。
2. 文档勿再写独立 `Materials` 蒙版入口；蒙版库在 Overlays 模块 + 混剪侧引用。
3. `OverlayAudioMode.Mix`：渲染侧已接线（`AudioFilterCompiler.CompileOverlayMix`）；蒙版页可选「混入蒙版音轨」。
4. 随机素材库：入队时 `ProbeSourceDurationsAsync` 探测真实时长（替换默认 3s 元数据）。
5. 形状/PNG 遮罩编辑 UI（第二期）；领域与渲染已保留。
