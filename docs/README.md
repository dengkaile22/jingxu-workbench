# 镜序工作台文档索引

本目录为 **JingXu.Workbench**（镜序工作台）的设计意图与开发现状文档入口。

> **仓库布局（2026-07-11 起）：** 源码、测试、脚本与文档统一在仓库根目录（当前开发分支 `feature/jingxu-implementation`）。  
> 历史「主仓只有 dist / 实现仅在 `.worktrees/`」双根布局已收敛；见 [status/2026-07-11-repo-and-doc-alignment.md](status/2026-07-11-repo-and-doc-alignment.md)。

## 设计意图（以规格为准）

| 文档 | 说明 |
|------|------|
| [设计规格](superpowers/specs/2026-07-10-video-workbench-design.md) | 产品目标、业务规则、架构边界、验收标准（已书面确认） |
| [实现计划](superpowers/plans/2026-07-10-video-workbench-implementation.md) | 按 Task 拆分的实现计划与文件结构目标 |
| [执行计划](plans/execution-plan.md) | 稳定化与收口执行计划 |
| [目标分析](plans/goal-analysis.md) | 团队执行阶段目标整理 |

## 工程说明（面向开发）

| 文档 | 说明 |
|------|------|
| [架构概览](architecture.md) | 分层边界：**设计意图 + 实现现状** |
| [开发指南](development.md) | SDK、命令、入口、CLI 开关、目录 |
| [测试说明](testing.md) | 测试分层与运行方式 |
| [发布流程](release.md) | 便携包 / 安装器 / 校验 |
| [Python 版发布流程](release-python.md) | PySide6 版的 PyInstaller 打包、随包运行时与自检 |
| [运行时许可](runtime-licensing.md) | FFmpeg / Whisper / Tesseract 合规 |
| [验收报告](acceptance-report.md) | Task 矩阵与已知阻塞项 |
| [Python 版迁移验收报告](python-migration-acceptance.md) | .NET → Python 迁移的能力对齐、测试证据与已知限制 |
| [选品爬虫重写说明与验证状态](spider-rewrite-status.md) | 分层提取/环境自检/登录态记录的设计、实测证据与**未验证部分** |

## 开发现状与对齐（2026-07-11）

文档承诺与代码不一致时：**以设计规格的产品/架构意图为准**；下列文档记录真实路径、入口、完成度与偏差，不假装已实现。

| 文档 | 说明 |
|------|------|
| [总览：实现对齐快照](status/2026-07-11-implementation-alignment.md) | 入口、目录、双轨误解澄清、总完成度 |
| [仓库布局收敛说明](status/2026-07-11-repo-and-doc-alignment.md) | 双根 → 单树、媒体资产与 git 边界 |
| [混剪与素材](modules/composition-mix-status.md) | 随机/序号拼接、画幅、BGM、差异化 |
| [蒙版模板](modules/overlays-mask-status.md) | 三类蒙版、素材库 |
| [字幕实验室](modules/subtitle-lab-status.md) | 手动/OCR/Whisper/烧录 |
| [队列与持久化](modules/render-queue-persistence-status.md) | 队列状态机、内存队列 vs 规格 JSON |
| [运行时与发布](modules/runtime-packaging-status.md) | runtime 解析、清单哈希、WiX |
| [类型与命名对照](status/2026-07-11-design-vs-code-names.md) | 规格名称 → 代码实际类型/路径 |

## 阅读顺序建议

1. 新同学：根目录 [README.md](../README.md) → 本索引 → [设计规格](superpowers/specs/2026-07-10-video-workbench-design.md) §1–4  
2. 改功能：对应 `modules/*-status.md` → 再改代码  
3. 发布： [release.md](release.md) → [acceptance-report.md](acceptance-report.md)
