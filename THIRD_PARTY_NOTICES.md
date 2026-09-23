# 第三方声明（Third-Party Notices）

镜序工作台（JingXu Workbench）分发包包含以下第三方软件与数据。各组件受其许可证约束；**本文档不构成法律意见**，商业分发前请由法务复核 FFmpeg 构建配置与专利合规。

## FFmpeg

- **显示名称：** FFmpeg
- **相对路径：** `runtime/ffmpeg/ffmpeg.exe`
- **许可证：** GPL-3.0-or-later
- **官方下载：** https://ffmpeg.org/download.html
- **源代码：** https://github.com/FFmpeg/FFmpeg

应用通过命令行调用独立 `ffmpeg.exe`，**不**静态链接 `libav*`。分发包须随附对应构建配置说明与源码获取方式。不得捆绑带 `--enable-nonfree` 的 FFmpeg 产物。

## FFprobe

- **显示名称：** FFprobe
- **相对路径：** `runtime/ffmpeg/ffprobe.exe`
- **许可证：** GPL-3.0-or-later
- **官方下载：** https://ffmpeg.org/download.html
- **源代码：** https://github.com/FFmpeg/FFmpeg

## Whisper.cpp

- **显示名称：** Whisper.cpp
- **相对路径：** `runtime/whisper/whisper-cli.exe`
- **许可证：** MIT
- **发布页：** https://github.com/ggerganov/whisper.cpp/releases
- **源代码：** https://github.com/ggerganov/whisper.cpp

## Whisper 多语言 base 模型

- **显示名称：** Whisper 多语言 base 模型
- **相对路径：** `runtime/whisper/models/ggml-base.bin`
- **许可证：** MIT
- **模型来源：** https://huggingface.co/ggerganov/whisper.cpp
- **源代码：** https://github.com/ggerganov/whisper.cpp

## Tesseract OCR

- **显示名称：** Tesseract OCR
- **相对路径：** `runtime/tesseract/tesseract.exe`
- **许可证：** Apache-2.0
- **项目主页：** https://github.com/tesseract-ocr/tesseract
- **源代码：** https://github.com/tesseract-ocr/tesseract

## 嵌入式 Python（选品爬虫运行时）

- **显示名称：** CPython（Windows embeddable package）
- **相对路径：** `runtime/python/python.exe`
- **版本：** 由 `scripts/Resolve-SpiderRuntime.ps1` 的 `-Version` 决定（默认 3.12.10）
- **许可证：** PSF License 2.0
- **官方下载：** https://www.python.org/downloads/windows/
- **许可文本：** https://docs.python.org/3/license.html

应用以独立进程调用，不修改 Python 源码。分发包同时包含从 PyPI 安装的第三方库（无修改），随包清单见 `runtime/python/Lib/site-packages`：

| 组件 | 许可证 | 来源 |
|------|--------|------|
| DrissionPage | BSD-3-Clause | https://github.com/g1879/DrissionPage |
| requests | Apache-2.0 | https://github.com/psf/requests |
| openpyxl | MIT | https://openpyxl.readthedocs.io/ |
| tabulate | MIT | https://github.com/astanin/python-tabulate |
| lxml | BSD-3-Clause | https://lxml.de/ |
| 其余传递依赖（websocket-client、psutil、tldextract、cssselect、click、et_xmlfile 等） | BSD / Apache-2.0 / MIT | PyPI 元数据与各项目仓库 |

**用户须知：** 选品爬虫会访问抖音/快手公开页面并保存浏览器登录态（`%LocalAppData%\JingXu\Spider\browser_profile`，含 Cookie）。请确保使用方式符合目标平台服务条款与当地法律；该目录属敏感数据，不应提交到版本库或随包分发。

## 界面字体

- **IBM Plex Mono**（等宽数字/时间码）：SIL Open Font License 1.1
- 中文正文字体随发布包分发时，将在此节补充具体字体名称、许可证与来源 URL。

## 专利与编码器提示

H.264/H.265 等编码器可能涉及专利许可。硬件编码（NVENC/QSV/AMF）取决于显卡驱动与 FFmpeg 构建选项。用户在生产环境启用前须自行评估专利与合规风险。

## 源码提供

对适用 GPL/LGPL 组件，可在产品安装目录或随发布包提供书面 offer，指向上述源代码 URL，并在合理请求下提供对应源码副本。具体流程见 [docs/runtime-licensing.md](docs/runtime-licensing.md)。
