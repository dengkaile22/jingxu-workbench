# 实现对齐快照（2026-07-11）

## 文档目的

对照已确认的设计规格与实现计划，如实记录 **产品意图保留项** 与 **代码开发现状**，避免 README/架构文档把目标写成已交付事实。后续改代码或改文档时以本快照为偏差清单入口。

## 目标设计（意图摘要）

- 完全离线的 Windows x64 WPF 视频批处理桌面应用（非 Web、无云端 API）。
- 四项目 Clean Architecture：Domain / Application / Infrastructure / Presentation(WPF)。
- 三大子系统：批量混剪与差异化、蒙版模板、离线字幕实验室；共享探测、FFmpeg 执行、队列、日志、设置。
- 项目/队列/设置为版本化 JSON 原子持久化；渲染任务入队为不可变快照；有界并发 1–4。
- 分发：self-contained 便携 ZIP + WiX 安装程序；捆绑 FFmpeg/FFprobe，可选 Whisper/Tesseract。

规格原文：[2026-07-10-video-workbench-design.md](../superpowers/specs/2026-07-10-video-workbench-design.md)

## 开发现状

### 仓库与可写根

| 位置 | 分支/内容 | 说明 |
|------|-----------|------|
| `project2026071001/`（主 worktree） | `main` | 设计规格 `docs/superpowers/*`、已发布 `dist/`；**无** `src/` 解决方案 |
| `.worktrees/jingxu-implementation/` | `feature/jingxu-implementation` | **完整源码、测试、脚本、本套工程文档** 所在处 |

本会话工作区为 implementation worktree；子 agent 无法调用 `move_agent_to_root`，文档写入以本 worktree 为准，并在主仓 `docs/` 增加索引指针。

### 真实入口与启动

| 项 | 实际 |
|----|------|
| 解决方案 | `JingXu.Workbench.sln` |
| UI 入口 | `src/JingXu.Workbench/App.xaml` + `App.xaml.cs` → `AppCompositionRoot.CreateShell()` → `ShellWindow` |
| 组合根 | `src/JingXu.Workbench/Bootstrap/AppCompositionRoot.cs` |
| 开发启动 | `dotnet run --project src/JingXu.Workbench/JingXu.Workbench.csproj` |
| 便携启动 | 解压后双击 `JingXu.Workbench.exe`（自包含，无需安装 .NET） |
| CLI（无 GUI 退出） | `--self-test`、`--import-smoke`、`--overlay-smoke`（见 `App.xaml.cs`） |

**不存在** `backend/`、`frontend/`、HTTP API、`pipeline/` 与 `agent_pipeline/` 双轨。若其它项目审计提到这些名称，与本仓库无关；此处「管线」仅指 FFmpeg 媒体处理链路。

### 目录现状（摘要）

```text
src/
  JingXu.Workbench/                 # WPF：Features/{Composition,Overlays,Subtitles,Queue,Settings,Shell}
  JingXu.Workbench.Application/     # 用例：Rendering、Projects、Subtitles、Composition、Overlays
  JingXu.Workbench.Domain/          # 纯领域：CompositionPlanner、RenderJob、Effects、Overlays…
  JingXu.Workbench.Infrastructure/  # FFmpeg/FFprobe、进程、Runtime、字幕 OCR/ASR、持久化
tests/                               # Domain/Application/Infrastructure/Presentation/Integration
scripts/                             # Build-Portable、Build-Installer、Resolve-Runtimes、Verify-Release…
build/                               # runtime-manifest.json、Installer/*.wxs
runtime/                             # 本地放置第三方二进制（不入 Git）
docs/                                # 本目录
```

### 完成度总览（相对规格）

| 子系统 | 完成度 | 说明 |
|--------|--------|------|
| 工程脚手架 / Clean Architecture | 高 | 四项目齐全，分析器警告视为错误 |
| 素材导入 + 序号/随机/自定义编排 | 高 | Domain + Composition UI 已接线 |
| 画幅 / 质量档 / FFmpeg 编译执行 | 高 | 软件编码 `libx264`；硬件编码字段存在但未真正选 NVENC/QSV/AMF |
| 差异化效果 / BGM | 中高 | UI 有开关与 BGM 路径；效果模板服务未挂 UI |
| 图片贴纸 | 中 | Domain/Infrastructure 支持；混剪 UI **未**暴露贴纸选择 |
| 三类蒙版 + 库 | 高 | Overlay 模块 + JSON 库；个别集成像素测试仍黄 |
| 字幕实验室 | 高 | 手动/OCR/Whisper/烧录链路与 UI 存在；依赖可选 runtime |
| 任务队列调度 | 中高 | `RenderCoordinator` 完整；**进程内内存存储**，非规格中的持久化队列文件 |
| 项目 JSON 打开/保存 | 低 | `ProjectDocument` 模型存在；**UI 未接线**完整项目存档 |
| 效果模板命名保存 | 低 | `TemplateService` 存在；**WPF 未引用** |
| 交叉转场 | 低 | `TransitionDuration` 字段存在；UI/入队恒为 `TimeSpan.Zero` |
| 运行时清单正式哈希 | 低 | `build/runtime-manifest.json` 仍为占位 `000…0` |
| WiX Burn 引导安装包 | 中 | MSI 源存在；Burn 扩展依赖见验收报告 |
| 自动化测试 | 中高 | 验收报告：Release 下多数通过，仍有集成/打包失败项 |

详细模块见 `docs/modules/*-status.md`；验收矩阵见 [acceptance-report.md](../acceptance-report.md)。

## 待对齐项（文档/产品）

1. 架构文档曾把 Application/Domain 画在 WPF 项目内部，且把 `CompositionPlanner` 归到 Application —— **已在 architecture.md 按现状修正说明**。
2. 规格中的 `MaterialsViewModel`、`TesseractRunner`、`JsonQueueStore` 等名称与代码不一致 —— 见 [命名对照](2026-07-11-design-vs-code-names.md)。
3. README 功能表表述接近「已交付产品」；能力上大体具备，但持久化项目/队列、硬件编码、贴纸 UI、交叉转场、正式签名安装包等仍有缺口 —— 以本快照与 modules 为准。
4. 主仓 `main` 与 feature worktree 文档不同步；发布合并前需决定以哪一侧 docs 为权威并复制。

## 非问题澄清

- **无** REST/GraphQL「API 路径过时」问题：本产品为桌面进程内调用，无 HTTP 表面。
- **无** `pipeline` vs `agent_pipeline` 双目录：仅 FFmpeg 渲染执行路径。
