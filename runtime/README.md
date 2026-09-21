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
    tessdata/
      chi_sim.traineddata
      eng.traineddata
      osd.traineddata
  python/
    python.exe                 # 嵌入式 CPython（scripts/Resolve-SpiderRuntime.ps1 生成）
  spider/
    cli.py                     # 选品爬虫源码（发布时从 src/JingXu.Spider/ 暂存）
    core/
    ecommerce_spider/
```

`python/` 与 `spider/` 由发布流程暂存，用于随包运行的选品爬虫（无需用户安装 Python）。构建内置运行环境：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Resolve-SpiderRuntime.ps1
```

脚本会下载嵌入式 Python 与 `src/JingXu.Spider/requirements.txt` 中的依赖，并在结束时自检导入。国内网络可用 `-PipIndexUrl https://pypi.tuna.tsinghua.edu.cn/simple` 加速。

## 解析顺序

1. **应用目录** `runtime/`（上表路径）
2. **设置中用户指定的目录**（设置页覆盖）
3. **系统 PATH**

选品爬虫的 Python 与源码按 内置 `runtime/python`、`runtime/spider` → 开发仓目录 `src/JingXu.Spider/` → 系统 Python 的顺序解析；未随包分发内置环境时自动回退系统 Python（需自行安装 `requirements.txt` 依赖）。

## 开发机快速放置

若本机已安装 FFmpeg，可先依赖 PATH 跑通集成测试；要模拟便携包，可将官方构建复制到 `runtime/ffmpeg/`。

发布脚本支持从 PATH 引导必需工具（`-BootstrapFromPath`），**正式发布前**须将实测 SHA-256 写入 `build/runtime-manifest.json`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Resolve-Runtimes.ps1 -CacheDirectory runtime -PrintHashes
```

Whisper 与 Tesseract 为可选组件：字幕实验室在缺失时会给出中文提示，不影响拼接与渲染主流程。

### Tesseract 放置说明（硬字幕 OCR）

官方 [tesseract-ocr/tesseract](https://github.com/tesseract-ocr/tesseract) **不提供 Windows 独立二进制**，
需使用 UB Mannheim 构建的安装包再解包（无需系统级安装）：

```powershell
# 1) 下载安装包（约 48 MB）
curl.exe -L -o "$env:TEMP\tesseract-setup.exe" `
  https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.4.0.20240606.exe

# 2) 用 7-Zip 解包到 runtime/tesseract（DLL 必须与 exe 同目录）
& 'C:\Program Files\7-Zip\7z.exe' x "$env:TEMP\tesseract-setup.exe" -o"runtime\tesseract" -y

# 3) 补中文语言包（安装包只带 eng / osd）
#    注意：必须用 tessdata（标准版），不能用 tessdata_fast。
curl.exe -L -o runtime\tesseract\tessdata\chi_sim.traineddata `
  https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata
```

**两条实测踩过的坑：**

1. **`chi_sim` 必须用标准 [tessdata](https://github.com/tesseract-ocr/tessdata)**。
   [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) 的 `chi_sim.traineddata`
   （2.4 MB）在本构建下对同样的图**返回空结果**（`Empty page!!`），换标准版
   （42.3 MB）即正确识别。已确认不是下载损坏（两次下载 SHA-256 一致）。
2. **`tsv` 不能当位置参数**：tesseract 会把 `outputbase` 后的首个位置参数当作
   **配置文件**，`... stdout -l chi_sim+eng tsv` 会报
   `read_params_file: Can't open tsv` 并退回纯文本；必须用
   `-c tessedit_create_tsv=1`。此项已在 `infrastructure/ocr.py` 修正。

`runtime/tesseract/` 完整部署约 **280 MB**（含语言包），会显著增大安装包体积；
未部署时「OCR 检测硬字幕」不可用，其余字幕功能（Whisper 识别、区域框选、
烧录样式、去字幕）不受影响。

## 清单与 staging

| 文件 | 说明 |
|------|------|
| `build/runtime-manifest.json` | 组件路径、SHA-256、许可与来源 URL |
| `artifacts/staging/runtime/` | `Resolve-Runtimes.ps1` 输出，供便携包/安装程序合并 |

详见 [docs/runtime-licensing.md](../docs/runtime-licensing.md) 与 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
