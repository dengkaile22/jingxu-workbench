# 运行时许可与合规

本文档说明镜序工作台所捆绑或调用的第三方运行时许可。**不构成法律意见**；对外商业分发前须由法务确认 FFmpeg 构建选项、GPL/LGPL 义务与音视频专利。

## FFmpeg / FFprobe（GPL-3.0-or-later）

- **调用方式：** 独立进程，命令行参数；不链接 `libav*`。
- **分发要求：** 提供许可证文本、构建配置摘要与源代码获取方式（见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)）。
- **禁止：** 捆绑 `--enable-nonfree` 构建。
- **专利：** H.264/H.265 等编码可能需额外专利许可；硬件编码取决于驱动与构建。

用户开发机上的 GPLv3 full build 可用于本地验收；对外包须按最终商业策略复核。

## Whisper.cpp 与模型（MIT）

- 可执行文件：`runtime/whisper/whisper-cli.exe`
- 默认模型：`runtime/whisper/models/ggml-base.bin`
- 源代码与模型来源 URL 已列入 `build/runtime-manifest.json` 与第三方声明。

## Tesseract OCR（Apache-2.0）

- 可执行文件：`runtime/tesseract/tesseract.exe`
- 语言数据（如 `chi_sim`、`eng`）随包分发时须单独记录版本与许可。

## 字体

- IBM Plex Mono：SIL Open Font License 1.1（应用内嵌资源）
- 中文 UI 字体：随发布包补充具体许可条目

## SHA-256 固定哈希

`build/runtime-manifest.json` 为可审计清单。发布流水线只复制哈希已验证的文件到 `artifacts/staging/runtime`；占位哈希 `000…000` 仅允许开发模式（`-AllowPlaceholderHash`），正式发布必须替换为实测值。

## 源码提供流程（GPL 家族）

对适用组件，安装介质或书面说明中提供源代码 URL；收到合理请求后，在合理期限内提供与分发二进制对应的源码副本。具体联系人/流程由发行方运营政策决定。
