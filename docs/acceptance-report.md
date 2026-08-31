# 镜序工作台验收报告

**日期：** 2026-07-10（总控收口验证：2026-07-11）  
**规格：** [2026-07-10-video-workbench-design.md](superpowers/specs/2026-07-10-video-workbench-design.md)  
**工作树：** `feature/jingxu-implementation`（未提交）  
**文档对齐补充：** [实现对齐快照](status/2026-07-11-implementation-alignment.md) · [文档索引](README.md)

图例：✅ 已通过 · 🟡 部分通过/待发布哈希或手动证据 · ❌ 未通过

---

## 22 Task 完成矩阵

| Task | 状态 | 证据 |
|------|------|------|
| 1 SDK/解决方案脚手架 | ✅ | `global.json`、`JingXu.Workbench.sln`、五测试项目；`git log` 已提交 |
| 2 序号/表达式解析 | ✅ | `FileSequenceParserTests` 全绿 |
| 3 随机/自定义编排 | ✅ | `CompositionPlannerTests` 全绿 |
| 4 原子 JSON 持久化 | ✅ | `AtomicJsonStoreTests`、`ProjectServiceTests` |
| 5 运行时/进程/进度 | ✅ | `RuntimeResolverTests`、`ExternalProcessRunnerTests`、`FfmpegProgressParserTests` |
| 6 FFprobe 探测 | ✅ | `FfprobeJsonParserTests`、`FfprobeMediaProbeTests` |
| 7 渲染队列协调 | ✅ | `RenderCoordinatorTests`、`RenderQueueRecoveryTests` |
| 8 WPF 壳层/主题 | ✅ | `ShellViewModelTests`、`ThemeContractTests`、布局测量 |
| 9 画幅/质量/FFmpeg 编译 | ✅ | `RenderProfileTests`、`FfmpegCommandCompilerTests` |
| 10 三类蒙版 | ✅ | `OverlayTimelineResolverTests`、`OverlayFilterCompilerTests` |
| 11 差异化/贴纸/BGM | ✅ | `EffectTemplateTests`、`EffectFilterCompilerTests`、`AudioFilterCompilerTests`、入队接线 |
| 12 预检/执行/封面 | ✅ | `RenderPreflightTests`、`FfmpegRenderExecutorTests`、`CoverGenerator` |
| 13 混剪 WPF 工作流 | ✅ | `CompositionViewModelTests`、`OverlayEditorViewModelTests`、`RenderQueueViewModelTests` |
| 14 M2 媒体集成 | 🟡 | `CompositionRenderTests`、`AudioAndCoverTests` 等 15/17 通过；`Three_overlay_modes_*` 1 项失败待调参 |
| 15 字幕模型/手动去除 | ✅ | `SubtitleTimelineTests`、编解码与 `SubtitleRemovalFilterCompilerTests` |
| 16 OCR 抽帧/聚类 | ✅ | `FrameSamplingPlannerTests`、`SubtitleRegionClustererTests`、`TesseractTsvParserTests` |
| 17 Whisper 识别 | ✅ | `WhisperSrtParserTests`、`WhisperRunnerTests` |
| 18 字幕实验室 UI/烧录 | ✅ | `SubtitleWorkflowTests`、`SubtitleLabViewModelTests`、`PreviewCoordinateMapperTests` |
| 19 运行时清单/设置 | ✅ | `RuntimeManifestValidatorTests`、`SettingsViewModelTests`、`SelfTestRunner --self-test` |
| 20 文档/运行时 staging | 🟡 | `README.md`、`THIRD_PARTY_NOTICES.md`、`docs/*`；清单仍为占位 SHA-256（开发模式） |
| 21 便携包/安装器 | 🟡 | 便携 ZIP ✅；MSI 已构建并作为唯一安装器；不再交付 Burn 引导程序 |
| 22 发布验收 | 🟡 | 本报告；`Verify-Release.ps1` 占位哈希/2 项集成失败时非零退出 |

---

## 自动化验证（2026-07-11 新鲜运行）

```text
dotnet build JingXu.Workbench.sln -c Release  → 0 错误 / 0 警告
dotnet test JingXu.Workbench.sln -c Release   → 235 通过 / 2 失败 / 0 跳过
  Domain 52 + Application 38 + Infrastructure 83 + Presentation 47 + Integration 15 = 235
  失败：RuntimePackageTests（占位 sha256）、OverlayRenderTests.Three_overlay_modes_*
dotnet publish → artifacts/publish/win-x64/
便携 ZIP     → artifacts/release/炳恒快速混剪-Portable-win-x64.zip
```

---

## 规格 5–14 节摘要

| 节 | 状态 | 说明 |
|----|------|------|
| 5 业务规则 | 🟡 | 序号/随机/硬切/效果/蒙版/字幕领域测试齐全；部分 lavfi 像素验收待稳定 |
| 6 UI | 🟡 | 五区工作台、设置/队列导航完整；DPI 截屏待手动 |
| 7 架构 | ✅ | Clean Architecture、ArgumentList、单一 ProcessRunner |
| 8–11 数据/队列/错误 | ✅ | 状态机、预检、中文诊断 |
| 12 开发标准 | ✅ | 分析器即错误；无占位按钮 |
| 13 测试 | 🟡 | 237 项自动化；2 项集成待修 |
| 14 发布 | 🟡 | 便携包与 MSI 可交付；发布前仍需固定运行时哈希 |

---

## 阻塞项（需用户/发布前处理）

1. 更新 `build/runtime-manifest.json` 中各组件真实 SHA-256（`Resolve-Runtimes.ps1 -PrintHashes`）
2. 将 FFmpeg/Whisper/Tesseract/模型/字体放入 `runtime/` 或设置页指定路径
3. 手动 UI 冒烟（1920×1080 / 125% / 150%）并附截图
