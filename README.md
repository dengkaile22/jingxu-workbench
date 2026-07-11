# 镜序工作台（JingXu Workbench）

完全离线的 Windows 桌面视频批处理软件：随机/自定义序号拼接、画幅适配、滤镜贴纸 BGM、三类视频蒙版、离线字幕实验室与可恢复渲染队列。

**平台：** Windows 10/11 x64  
**分发：** 便携 ZIP + WiX 安装程序（均未签名时可能触发 SmartScreen，见下文）

## 快速开始

1. 解压 `JingXu-Workbench-Portable-win-x64.zip` 到任意目录（路径尽量避免中文空格以外的特殊字符）。
2. 双击 `JingXu.Workbench.exe` 启动。本包为 **自包含** 发布，目标机器 **无需** 安装 .NET 运行时。
3. 拖入 MP4/MOV/MKV 等素材，确认左侧序号与缩略图。
4. 在中央编排区选择 **随机拼接** 或 **自定义序号**（紧凑输入 `264513` 或逗号输入 `2,6,4,5,1,3`）。
5. 在右侧设置画幅、质量与输出目录，点击 **入队渲染**；在底部队列查看进度、日志与打开输出目录。

首次启动会异步检测本地运行时；FFmpeg/FFprobe 为必需组件，Whisper 与 Tesseract 为字幕实验室可选组件。

## 离线保证

- 不上传视频、音频、字幕或项目数据。
- 不依赖云端账号、API 密钥或在线素材商城。
- 语音识别、OCR 与 FFmpeg 渲染均在本地进程完成。

## 运行时设置

应用按以下顺序解析工具：

1. 应用目录 `runtime/`（与 `JingXu.Workbench.exe` 同级）
2. 设置页中用户指定的绝对路径目录
3. 系统 `PATH`

便携包已预置 `runtime/` 布局；开发机可从 [runtime/README.md](runtime/README.md) 了解如何手动放置二进制。发布清单与 SHA-256 见 `build/runtime-manifest.json`，许可说明见 [docs/runtime-licensing.md](docs/runtime-licensing.md) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

更新运行时后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Resolve-Runtimes.ps1 -CacheDirectory runtime -PrintHashes
```

将输出的哈希写入 `build/runtime-manifest.json` 后再打包。

## 主要功能

| 模块 | 说明 |
|------|------|
| 批量混剪 | 随机种子可复现、批量差异化、滤镜/贴纸/BGM、封面 |
| 蒙版模板 | 自由覆盖层、全屏低透明度、形状遮罩，多层叠加 |
| 字幕实验室 | 手动框选去除、OCR 自动定位、Whisper 离线识别、SRT/ASS 烧录 |
| 任务队列 | 可暂停调度、单任务取消（进程树终止）、失败隔离与重试 |

## 输出与目录

- 单源文件夹任务默认输出到源目录下 `分镜输出`。
- 多来源任务默认输出到项目目录下 `分镜输出`。
- 同名文件自动追加三位序号，不静默覆盖。

## 构建发布（开发者）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Portable.ps1 -AllowPlaceholderHash -BootstrapFromPath
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Installer.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Verify-Release.ps1
```

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
