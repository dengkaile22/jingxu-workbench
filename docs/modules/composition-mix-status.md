# 混剪与素材 — 模块现状

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（主应用 `core/`，扩展 `extensions/`），文中 `.cs`/`.xaml` 路径仅作历史记录。

## 文档目的

保留规格中「批量混剪与差异化处理」的产品意图，并记录 UI/领域/渲染接线现状与缺口。

## 目标设计

- 拖放/多选导入；FFprobe 探测；文件名末段数字为序号。
- 随机种子可复现排列；自定义紧凑序号（如 `264513`）与逗号序号。
- 默认硬切、完整使用素材；可选交叉转场并显示实际时长。
- 画幅继承或 9:16/16:9/1:1/4:5/自定义；适配裁切/模糊底/黑边。
- 差异化（镜像、1%–3% 裁切、调色等）、滤镜、贴纸、BGM、封面；参数可存命名模板。
- 输出目录默认 `分镜输出`；同名追加三位序号。

规格：§5.1–5.6、§5.10。

## 开发现状

| 能力 | 状态 | 路径 / 证据 |
|------|------|-------------|
| 序号解析 | ✅ | `Domain/Composition/FileSequenceParser.cs` |
| 随机/自定义计划 | ✅ | `Domain/Composition/CompositionPlanner.cs`；`Application/Composition/CompositionOrchestrator.cs` |
| 混剪 UI | ✅ | `Features/Composition/CompositionView.xaml` + `CompositionViewModel.cs` |
| 素材行 | ✅ | `MaterialRowViewModel.cs`（无独立 Materials 模块） |
| 画幅统一策略 | ✅ | `Domain/Rendering/UnifiedAspectPolicy.cs`；UI 有预设与自定义宽高 |
| 差异化开关 | ✅ | UI `EnableVariationEffects` → `EffectTemplates.StandardVariation()` |
| BGM | ✅ | UI `BgmPath` / 音量相关入队；`AudioFilterCompiler` |
| 图片贴纸 | ✅ | `ImageSticker` + `EffectFilterCompiler`；混剪 UI 可选贴纸并调节位置/尺寸/透明度 |
| 主素材音量/缩放 | ✅ | `MainMaterialBoostPlan`；混剪 UI 固定/随机 100%–110%；主轨 loudnorm+volume / scale+crop；蒙版不生效 |
| 命名效果模板 | ✅ | `TemplateService` + `AtomicJsonStore`；混剪 UI 加载/应用/另存为（含贴纸快照） |
| 输出质量档 | ✅ | 混剪 UI 暴露无损/高/平衡/小体积 → `RenderProfile.For`；无损不可用时提示需转码 |
| 默认输出目录 | ✅ | 导入后按 `RenderRequestFactory.ResolveDefaultOutputDirectory`（同 `OutputNamePolicy`）；浏览可覆盖 |
| 随机批量每片素材数 | ✅ | UI `ClipsPerPlan`（每片素材数）留空=全部；`CompositionPlanner.PlanRandomBatch` 按指定数量随机抽取 |
| 交叉转场 | ❌/低 | `CompositionPlan.TransitionDuration`；入队侧实际为 `TimeSpan.Zero`；无 UI |
| 封面 | 🟡 | `CoverGenerator` + `CoverMode`；混剪 UI 封面控件暴露程度弱于规格叙述 |
| 项目级保存 | ❌ | 会话态为主；`ProjectDocument` 未挂壳层 |

入队工厂：`Application/Rendering/RenderRequestFactory.cs`。  
FFmpeg 编译：`Infrastructure/Rendering/FfmpegCommandCompiler.cs`（视频编码当前为 `libx264`）。

## 待对齐项

1. 规格「标题文字 / GIF 贴纸 / 贴纸起止时点」——图片贴纸已接 UI；其余标为后续里程碑。
2. 交叉转场：补 UI + 编译器，或在规格执行备注中标为后续里程碑。
3. `ProjectDocument` 打开/保存与标题栏「保存状态」——规格 UI §6.1，现状缺口。
4. 硬件编码器回退提示 —— `PreferHardwareEncoder` 与真实 `-c:v` 选择应对齐。
5. 命名模板暂存滤镜开关区间（内置标准差异化参数）与贴纸快照；未提供逐项滑条编辑滤镜 min/max。
