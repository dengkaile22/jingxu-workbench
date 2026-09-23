# 镜序工作台验收报告

## 封版验收（2026-09，当前交付：Python 版）

**交付物**：`artifacts/release/炳恒快速混剪-Py-win-x64.msi`
（**350.2 MB**，SHA-256 `92686907049635f964a45669fe6101f66e0b6c2c04fc93e9bc790bae9c77f9cb`，
与 `SHA256SUMS-Py.txt` 一致）

### 体积（本轮优化：464.4 MB → 350.2 MB，−24.6%）

| 项 | 优化前 | 优化后 | 手段 |
|---|---:|---:|---|
| 便携目录 | 1143.2 MB | 764.0 MB | 见下 |
| MSI | 464.4 MB | **350.2 MB** | CAB 压缩后同比例下降 |

两处改动，都不牺牲功能：

1. **FFmpeg 换成 essentials 构建**（433.6 MB → 194.2 MB）
   原 full_build 把几乎所有可选库都编了进去（bluray / libsrt / libzmq /
   avisynth / libcaca / frei0r / vmaf / libplacebo / opencl / libjxl …），
   而本产品只用到 libx264 + aac + 硬件编码器 + 一批基础滤镜。
   切换前逐项核验 51 个滤镜、全部编码器与解复用器均不缺失，
   切换后 15 项真机集成测试全通过。
2. **剔除产品不用的打包负载**（379 MB）
   `cv2`（cv2.pyd 85 MB + opencv_videoio_ffmpeg 27 MB）是构建机装了、产品代码与
   爬虫都没 import 的包，被传递依赖拖进产物；另有 PySide6 的 Qml/Quick/Pdf/
   Network 与 translations（产品只用 QtCore/QtGui/QtWidgets/QtSvg）。

> 未动的项：Whisper `base` 模型（141 MB）是识别质量的直接来源，本版没有更小
> 的备份模型可回落，因此不替换、不降级。


### 测试矩阵（全部本机实跑）

| 层次 | 项数 | 结果 | 命令 |
|------|-----:|------|------|
| 工作台单元测试 | 1095 | **通过** | `python -m pytest` |
| 工作台集成测试（真机 FFmpeg） | 15 | **通过** | `python -m pytest -m integration` |
| 爬虫项目测试 | 71 | **通过** | `cd src/JingXu.Workbench.Py/JingXu.Spider && python -m pytest` |
| 打包产物 `--self-test` | 1 | `exit=0` / `success=true` | 见下 |
| 打包产物 `--import-check` | 1 | `exit=0` / `success=true` | 见下 |
| 打包产物 `--ui-probe` | 1 | `exit=0` / `success=true` | 见下 |

集成测试覆盖的真机链路：

* 混合素材拼接与画幅适配、BGM + 封面 + 自动编码器；
* 四屏羽化 + 贴纸 + 蒙版合成、双屏 + 主素材增强、自叠影；
* 字幕烧录与硬字幕去除、形状遮罩像素级验收；
* **队列端到端**：四种配置（顺序 / 随机批量 / 自定义序号 / 四屏+蒙版）并行入队，
  逐个走到 `COMPLETED`，并用 ffprobe 复核分辨率与时长；失败任务生成
  `.jingxu-logs/<任务ID>/` 归档；并发 1 与 2 都能跑完；
* 混剪页「效果预览」真实叠层渲染；
* 选品爬虫运行环境（内置解释器启动、依赖真正 import、浏览器可用、探测不写字节码）；
* 真实浏览器占用档案时的占用探测。

### 打包产物验证命令

```powershell
$app = 'artifacts\py-build\炳恒快速混剪\炳恒快速混剪.exe'
& $app --self-test    --report-file selftest.json   # success=true
& $app --import-check --report-file import.json     # success=true（扫码登录组件真的在包里）
& $app --ui-probe     --report-file ui.json         # success=true（预览画布 216×384，占控件 87%）
```

> 这三条是**发布前必跑**的门禁：`--import-check` 与 `--ui-probe` 分别覆盖
> "运行期动态导入有没有打进包"与"UI 在真实布局里是否可用"，
> 都是源码测试覆盖不到、只在冻结后才暴露的问题。

### 已知限制（未因封版而改变）

* **未做代码签名**：首次运行可能触发 SmartScreen，属预期行为。
* **爬虫真实抓取未验证**：抖音/快手有反爬且需登录态与真实对标账号，
  本机只能验证环境与失败可定位，详见 [spider-rewrite-status.md](spider-rewrite-status.md) §6。
* **NVIDIA / AMD 硬件编码未实机测量**：本机只有 Intel QSV 可实测；
  CUDA/AMF 有代码路径与探测，装到对应设备通过探测后才会启用。
* **125%/150% 真机缩放未人工确认**：自动化检查覆盖了固定高度 vs 字体行高、
  滚动兜底与数字输入框不截断，但未在真实高缩放显示器上逐项目视。
* **MSI 升级（覆盖安装）与卸载不删用户数据未实测**。

---

## 历史内容（.NET 版时期，仅作迁移参照）

> 以下为 .NET(WPF) 版阶段的验收记录。当前交付为 **Python 版**，验收以本节之前的
> 「封版验收」为准；.NET 源码已于 2026-09-23 移除（git 标签 `last-dotnet-reference`）。

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
