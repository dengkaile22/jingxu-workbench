# 运行时二进制（runtime/）

本目录由发布流程填充，**请勿将第三方二进制提交到 Git**。

## 目录布局

将已验证的可执行文件与模型放入应用根目录下的 `runtime/`（与 `炳恒快速混剪.exe` 同级）：

```
runtime/
  ffmpeg/
    ffmpeg.exe
    ffprobe.exe
  whisper/
    whisper-cli.exe
    models/
      ggml-base.bin
  tesseract/
    tesseract.exe
```

## 解析顺序

1. **应用目录** `runtime/`（上表路径）
2. **设置中用户指定的目录**（设置页覆盖）
3. **系统 PATH**

## 开发机快速放置

若本机已安装 FFmpeg，可先依赖 PATH 跑通集成测试；要模拟便携包，可将官方构建复制到 `runtime/ffmpeg/`。

发布脚本支持从 PATH 引导必需工具（`-BootstrapFromPath`），**正式发布前**须将实测 SHA-256 写入 `build/runtime-manifest.json`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Resolve-Runtimes.ps1 -CacheDirectory runtime -PrintHashes
```

Whisper 与 Tesseract 为可选组件：字幕实验室在缺失时会给出中文提示，不影响拼接与渲染主流程。

## 清单与 staging

| 文件 | 说明 |
|------|------|
| `build/runtime-manifest.json` | 组件路径、SHA-256、许可与来源 URL |
| `artifacts/staging/runtime/` | `Resolve-Runtimes.ps1` 输出，供便携包/安装程序合并 |

详见 [docs/runtime-licensing.md](../docs/runtime-licensing.md) 与 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
