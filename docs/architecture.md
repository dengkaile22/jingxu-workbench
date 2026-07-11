# 架构概览

## 文档目的

说明镜序工作台的分层边界与数据流。**产品与架构意图以设计规格为准**；下文同时给出实现落点，避免把目标图误认为当前目录树。

完整规格：[superpowers/specs/2026-07-10-video-workbench-design.md](superpowers/specs/2026-07-10-video-workbench-design.md)  
现状快照：[status/2026-07-11-implementation-alignment.md](status/2026-07-11-implementation-alignment.md)

## 目标设计

四层 Clean Architecture，Domain 不引用 WPF、文件系统或外部进程：

```text
Presentation (WPF)     — Shell、各功能 View/ViewModel
Application            — 用例编排、队列调度、项目/模板服务
Domain                 — 纯业务规则与不可变模型
Infrastructure         — FFprobe/FFmpeg、Whisper/Tesseract、JSON、Runtime、Job Object
```

关键意图：

- 命令生成器只接受强类型计划，返回 `ArgumentList`，不接受任意 shell 字符串。
- 统一进程运行器负责 stdout/stderr、取消与 Windows Job Object。
- `RuntimeResolver`：bundled `runtime/` → 用户目录 → `PATH`。
- 入队生成不可变 `RenderJob`；队列与项目版本化 JSON 原子保存。

## 开发现状

### 真实项目边界（四个 csproj）

```text
src/JingXu.Workbench                    # Presentation：App、ShellWindow、Features/*、Bootstrap
src/JingXu.Workbench.Application      # Abstractions、Rendering、Projects、Subtitles、Composition、Overlays
src/JingXu.Workbench.Domain             # Composition（含 CompositionPlanner）、Effects、Overlays、Rendering、Subtitles、Media
src/JingXu.Workbench.Infrastructure     # Media、Rendering、Processes、Runtime、Persistence、Subtitles
```

> 旧版示意图曾把 Application/Domain 画在 `JingXu.Workbench` 项目内部，易误导；**层是项目边界，不是 WPF 项目内的文件夹。**

### 数据流（已实现主路径）

1. 导入素材 → `FfprobeMediaProbe` → `MediaAsset`
2. `CompositionPlanner` / `CompositionOrchestrator` → `CompositionPlan`
3. `RenderRequestFactory` 等生成 `RenderRequest` → `RenderCoordinator` 入队 `RenderJob`
4. `FfmpegCommandCompiler` → `ExternalProcessRunner` / `FfmpegRenderExecutor`
5. 临时输出验证后按命名策略落到目标目录（封面见 `CoverGenerator`）

### 与目标的主要偏差

| 意图 | 现状 |
|------|------|
| 持久化队列 JSON | `InMemoryRenderQueueStore`（进程内） |
| 完整项目文档服务 | `ProjectDocument` 存在；UI 未完整打开/保存；`ProjectService` 目前主要是中断任务恢复辅助 |
| `CompositionPlanner` 在 Application | 实际在 **Domain** |
| `ProcessRunner` / `TesseractRunner` | 现名 `ExternalProcessRunner` / `TesseractSubtitleOcrDetector` |
| 硬件编码器自动选择 | Profile 有 `PreferHardwareEncoder`；编译当前固定 `libx264` |
| 默认并发可在 UI 调 1–4 | 协调器支持；组合根默认 1；设置 UI 未暴露 |

命名对照：[status/2026-07-11-design-vs-code-names.md](status/2026-07-11-design-vs-code-names.md)

## 待对齐项

1. 实现 JSON `IRenderQueueStore` 或持续在文档中标注「内存队列」。
2. 硬件编码选择与失败回退提示对齐规格 §5.9。
3. 合并文档时删除/更正任何 backend/API/pipeline 双轨描述（本仓库无此结构）。
