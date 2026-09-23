# 设计名称 ↔ 代码实际对照（2026-07-11）

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（`src/JingXu.Workbench.Py`），文中 `.cs`/`.xaml` 路径仅作历史记录。

## 文档目的

规格与实现计划中的类型/目录名是 **架构意图**；实现过程中部分命名演变。开发时以代码为准查找符号，以规格为准理解「应该做什么」。

## 目标设计（规格中的称呼）

见 [设计规格 §7–8](../superpowers/specs/2026-07-10-video-workbench-design.md) 与 [实现计划「文件结构」](../superpowers/plans/2026-07-10-video-workbench-implementation.md)。

## 开发现状对照表

| 规格 / 计划中的名称 | 代码实际 | 备注 |
|---------------------|----------|------|
| `MaterialsViewModel` / Materials 模块 | `CompositionViewModel` + `MaterialRowViewModel` | 素材栏并入混剪模块，无独立 Materials 功能目录 |
| `CompositionPlanner`（计划写在 Application） | `Domain.Composition.CompositionPlanner` | Application 另有 `CompositionOrchestrator` |
| `ProcessRunner` | `ExternalProcessRunner`（实现 `IExternalProcessRunner`） | |
| `TesseractRunner` | `TesseractSubtitleOcrDetector` + `TesseractTsvParser` | |
| `JsonProjectStore` / `JsonQueueStore` | `AtomicJsonStore<T>`；队列为 `InMemoryRenderQueueStore` | 通用原子 JSON 存储；**队列未落盘** |
| `ProjectService`（完整项目用例） | `ProjectService.RecoverJobs` 静态恢复辅助 | **不是**打开/保存项目的完整服务 |
| `ProjectDocument` | `Application.Projects.ProjectDocument` | 模型存在；壳层未做打开/保存 UX |
| `TemplateService` | `Application.Projects.TemplateService` | 存在；混剪 UI 已装配（加载/应用/另存为） |
| `CompositionRequest` | 入队路径使用 `RenderRequest` + `CompositionPlan` 等 | 无同名 `CompositionRequest` 类型 |
| `SequenceToken` | `FileSequenceParser` 解析结果嵌入 `MediaAsset` 序号 | 无独立 `SequenceToken` 类型 |
| `SubtitleProject` | `Domain.Subtitles` 模型（如 cue/timeline）+ `SubtitleWorkflow` | 命名不完全一致 |
| 左侧「批量混剪」等文案 | UI 短标签：混剪 / 蒙版 / 字幕 / 队列 / 设置 | `WorkspaceModule` 枚举 |
| 硬件编码 NVENC/QSV/AMF | `RenderProfile.PreferHardwareEncoder`；编译器写死 `-c:v libx264` | 意图保留在 profile；**执行层未选硬件编码器** |

## 待对齐项

- 合并主仓文档时，避免继续写已废弃规格名而不加「现名」脚注。
- 若产品要恢复规格中的独立「素材」导航，需新增模块或明确文档改为「素材并入混剪」。
