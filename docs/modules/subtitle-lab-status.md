# 字幕实验室 — 模块现状

## 文档目的

保留离线「去字幕 / 换字幕」双工作流意图，记录领域、进程运行时与 UI 接线，以及可选组件依赖。

## 目标设计

- 手动：预览框选区域；裁切重构 / 模糊 / `delogo`；导入 SRT/ASS 或手写字幕。
- 自动：抽帧 → Tesseract → 聚类区域；Whisper.cpp 离线 ASR；人工校对后烧录。
- 全部本地；低置信度不得静默删除。

规格：§5.8。

## 开发现状

| 能力 | 状态 | 路径 / 证据 |
|------|------|-------------|
| 字幕时间轴 / 模型 | ✅ | `Domain/Subtitles/*` |
| 工作流编排 | ✅ | `Application/Subtitles/SubtitleWorkflow.cs`、`FrameSamplingPlanner`、`SubtitleRegionClusterer` |
| SRT/ASS 编解码 | ✅ | `Infrastructure/Subtitles/SrtSubtitleCodec.cs`、`AssSubtitleCodec.cs`、`SubtitleCodecRegistry` |
| OCR | ✅ | `TesseractSubtitleOcrDetector` + `TesseractTsvParser`（规格名 `TesseractRunner` 已更名） |
| Whisper | ✅ | `WhisperRunner` + `WhisperSrtParser` |
| 去除/烧录滤镜与命令 | ✅ | `SubtitleRemovalFilterCompiler`、`SubtitleBurnInFilterCompiler`、`SubtitleBurnInCommandCompiler` |
| UI | ✅ | `Features/Subtitles/SubtitleLabView.xaml` + `SubtitleLabViewModel`、`PreviewCoordinateMapper` |
| 运行时可选 | ✅ | 缺 Whisper/Tesseract 时设置/诊断提示；不阻断主混剪 |

烧录路径当前视频编码示例仍见 `libx264`（与主渲染一致）。

## 待对齐项

1. 正式包需在 `runtime/whisper/`、`runtime/tesseract/` 放入二进制与模型，并写入真实 SHA-256。
2. README「字幕实验室」表述可用；需注明 **可选运行时**，避免读者以为开箱即含 OCR/ASR。
3. 规格「最多 3600 帧 / 下方 45%」等参数以 `FrameSamplingPlanner` 实现为准；若有偏差，改文档或改代码二选一（意图优先保留上限与可配置扫描区）。
