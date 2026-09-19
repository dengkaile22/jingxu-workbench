# 炳恒快速混剪

## 1.0.2 更新（2026-09-12）

- 四屏羽化改为生成并复用静态灰度渐变，同源同尺寸画面只缩放一次，保留横竖接缝、四格交点及原有音轨规则。四屏可以与数字人视频叠加同时使用。
- 新增设备实测后的硬件解码及适用尺寸的 GPU 缩放，继续使用已有的 NVENC、QSV 或 AMF 硬件编码。自动模式在适合缩小画幅时启用输入加速，原尺寸保留软件解码以避免多余回传；GPU 模式可手动启用兼容的 8 位 H.264 主视频硬解。循环辅助素材、未知格式及不兼容输入保留软件处理，蒙版、贴纸和调色仍由 CPU 计算。
- 硬件解码或缩放失败时先重试软件解码，保留可用的硬件编码；编码器不可用时再回退 CPU。设置页显示实测能力，任务结果记录实际使用阶段。
- 四屏辅助素材按片段独立读取，并限制每路解码线程；处理尺寸达到 1280×720 面积的四屏任务自动逐个执行，减少帧缓冲和多任务资源争用。普通任务仍按设置的 1–4 并发执行。
- 修复取消已预留任务后队列可能停止调度的边界；进度同时显示百分比和实际渲染倍速。
- 失败摘要跳过 FFmpeg 输出大小统计，优先显示具体错误；退出码 `-12` 明确提示内存申请失败和重试建议。完整日志继续保存在输出目录的 `.jingxu-logs/<任务ID>/`。

## 1.0.1 更新（2026-09-12）

- 混剪页「效果与音频」新增 2×2 四屏，支持从指定片段生效、同源四格、同文件夹随机辅助素材及横竖中缝羽化。双屏与四屏互斥，随机来源在入队时固定，辅助画面不重复混入声音。
- 修复启动/手动清理误删活跃临时文件、共享字幕以及等待提交的素材库文件的问题；清理在后台执行。
- 下载半成品写入目标目录所在磁盘，取消或失败时回收，保留原有完整文件。
- 渲染按输出卷共享空间预留，复制素材前增加预算；空间不足时回收失效缓存并重新检查。
- 渲染失败后回收媒体暂存，完整日志及滤镜文本保存在输出目录的 `.jingxu-logs/<任务ID>/`，失败详情中可找到日志路径。旧任务诊断按 7 天与 64 MiB 策略回收，当前失败任务保留完整记录。
- 临时资源登记失败或执行器发生异常时，任务会明确失败并继续调度下一项，不再停留在「运行中」。


完全离线的 Windows 桌面视频批处理软件：随机/自定义序号拼接、画幅适配、滤镜贴纸 BGM、三类视频蒙版、离线字幕实验室与可恢复渲染队列。

**平台：** Windows 10/11 x64  
**分发：** Windows 标准 MSI 安装包（`artifacts/release/炳恒快速混剪-win-x64.msi`，未签名时可能触发 SmartScreen，见下文）

## 快速开始

1. 双击运行 `artifacts/release/炳恒快速混剪-win-x64.msi`（或从发布页下载的 MSI 安装包）。
2. 安装完成后从桌面或开始菜单启动「炳恒快速混剪」。本包为 **自包含** 发布，目标机器 **无需** 安装 .NET 运行时。
3. 拖入 MP4/MOV/MKV 等素材，确认左侧序号与缩略图。
4. 在中央编排区选择 **随机拼接** 或 **自定义序号**（紧凑输入 `264513` 或逗号输入 `2,6,4,5,1,3`）。
5. 在右侧设置画幅、质量与输出目录，点击 **入队渲染**；在底部队列查看进度、日志与打开输出目录。

首次启动会异步检测本地运行时；FFmpeg/FFprobe 为必需组件，Whisper 与 Tesseract 为字幕实验室可选组件。

## 离线保证

- 视频、音频、字幕与项目数据只在本机处理。
- 不依赖云端账号、API 密钥或在线素材商城。
- 语音识别、OCR 与 FFmpeg 渲染均在本地进程完成。
- 例外：**选品爬虫**由用户主动触发，会联网访问抖音/快手公开页面并保存浏览器登录态（`%LocalAppData%\JingXu\Spider\browser_profile`）；其余模块不产生网络流量。

## 运行时设置

应用按以下顺序解析工具：

1. 应用目录 `runtime/`（与 `炳恒快速混剪.exe` 同级）
2. 设置页中用户指定的绝对路径目录
3. 系统 `PATH`

便携包已预置 `runtime/` 布局；开发机可从 [runtime/README.md](runtime/README.md) 了解如何手动放置二进制。发布清单与 SHA-256 见 `build/runtime-manifest.json`，许可说明见 [docs/runtime-licensing.md](docs/runtime-licensing.md) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

选品爬虫使用内置 `runtime/python` 与 `runtime/spider`（随包分发时无需安装 Python）；开发机构建内置环境：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Resolve-SpiderRuntime.ps1
```

更新运行时后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Resolve-Runtimes.ps1 -CacheDirectory runtime -PrintHashes
```

将输出的哈希写入 `build/runtime-manifest.json` 后再打包。

## 主要功能

| 模块 | 说明 |
|------|------|
| 批量混剪 | 随机种子可复现、批量差异化、滤镜/贴纸/BGM、封面 |
| 选品爬虫 | 抖音/快手对标账号带货爆品抓取、跨账号共性筛选，一键送入下载与混剪 |
| 蒙版模板 | 自行导入蒙版视频素材、列表编辑参数、多层叠加到成片 |
| 字幕实验室 | 手动框选去除、OCR 自动定位、Whisper 离线识别、SRT/ASS 烧录 |
| 任务队列 | 可暂停调度、单任务取消（进程树终止）、失败隔离与重试 |

## Python 跨平台版（开发中）

`src/JingXu.Workbench.Py/` 为 PySide6 + FFmpeg 的跨平台重写版（Windows/macOS/Linux），
已打通素材导入 → 顺序/随机/自定义序号编排 → 画幅适配 → 渲染队列的完整链路；
蒙版羽化/上淡入/来源裁剪与合成预览、随机旋转、上下双屏、无损直拷、OCR 自动定位、
交叉转场与项目保存/打开（`.jxproj`）也已迁移，
详见 [src/JingXu.Workbench.Py/README.md](src/JingXu.Workbench.Py/README.md)。

已与 .NET 版对齐的能力：GPU 硬解与 `scale_qsv`/`scale_cuda` 缩放（含三级回退）、
蒙版形状与 PNG 遮罩、贴纸独立画幅与宽高比锁定、音频库音量语义（−100..+100）。

Windows x64 便携包打包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Portable-Py.ps1
```

产物为 `artifacts/release/炳恒快速混剪-Py-Portable-win-x64.zip`（含随包 `runtime/`），
MSI 安装包为 `artifacts/release/炳恒快速混剪-Py-win-x64.msi`，
详见 [docs/release-python.md](docs/release-python.md)。

## 输出与目录

- 单源文件夹任务默认输出到源目录下 `分镜输出`。
- 多来源任务默认输出到项目目录下 `分镜输出`。
- 同名文件自动追加三位序号，不静默覆盖。

## 构建发布 MSI（开发者）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Publish-Msi.ps1 -AllowPlaceholderHash -BootstrapFromPath
```

执行后将自动完成编译发布、依赖打包与 WiX 6 构建，并输出至 `artifacts/release/炳恒快速混剪-win-x64.msi`。

详见 [docs/release.md](docs/release.md)。

## SmartScreen 与代码签名

当前构建产物 **未使用代码签名证书**。Windows 首次运行可能显示 **SmartScreen 未知发布者** 警告。这是预期行为，**不视为构建失败**。获取证书并完成 Authenticode 签名后，警告可消除。企业环境可将内部证书加入信任链。

## 文档索引

- [文档总索引（设计意图 + 开发现状）](docs/README.md)
- [实现对齐快照 2026-07-11](docs/status/2026-07-11-implementation-alignment.md)
- [架构（意图与现状）](docs/architecture.md)
- [开发指南（含真实入口/CLI）](docs/development.md)
- [测试](docs/testing.md)
- [发布流程](docs/release.md)
- [运行时许可](docs/runtime-licensing.md)
- [验收报告](docs/acceptance-report.md)
- [设计规格](docs/superpowers/specs/2026-07-10-video-workbench-design.md)

> **说明：** 上表「主要功能」描述的是产品目标能力。队列持久化、项目存档、硬件编码、贴纸 UI、交叉转场等与规格的偏差见 `docs/modules/*-status.md`，不以营销口吻视为 100% 已交付。

## 常见错误

| 现象 | 处理 |
|------|------|
| 入队前提示 FFmpeg 不可用 | 检查 `runtime/ffmpeg/` 或设置中的自定义路径 |
| 渲染失败 | 打开任务日志，确认编码器/滤镜是否被当前 FFmpeg 支持 |
| 字幕 OCR/识别灰色 | 安装或放置 Tesseract / Whisper 可选组件 |
| SmartScreen 拦截 | 点击“更多信息”→“仍要运行”，或改用已签名安装包 |
