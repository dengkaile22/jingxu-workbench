# Python 版发布流程（Windows x64）

本文对应根目录 `core/`（PySide6 + FFmpeg）与 `extensions/spider/` 的打包与交付。
本仓库已全面转向 Python，原 .NET/WPF 发布流水线于 2026-09-23 移除
（git 标签 `last-dotnet-reference` 可回查）。

## 交付物

交付统一输出到 `artifacts/release/`，交付只认这一个目录。

| 文件 | 说明 |
|------|------|
| `artifacts/release/炳恒快速混剪-Py-win-x64.msi` | **当前唯一交付物**：MSI（开始菜单 + 桌面快捷方式，可卸载） |
| `artifacts/release/SHA256SUMS-Py.txt` | MSI 校验和 |
| `artifacts/py-build/炳恒快速混剪/` | 未压缩的便携目录（**MSI 的打包输入**；可安全删除，脚本会重建） |

命名中的 `Py` 沿用自与原 .NET 版产物区分的时期，现为唯一交付命名。

> **交付目录只保留 MSI。**
> - 便携 ZIP（`炳恒快速混剪-Py-Portable-win-x64.zip`）与 `SHA256SUMS-PyPortable.txt`
>   已移除：其内容与 MSI 完全重叠（同一份 `py-build` 目录的压缩形态），
>   同时保留两者会白占约 466 MB。
>   `Build-Portable-Py.ps1` **默认仍会产出该 ZIP**；只要 MSI 时加 `-SkipArchive`。
> - 原 .NET 版交付物与构建脚本已随 .NET 树移除（git 标签 `last-dotnet-reference`）。

> 历史 `dist/` 交付目录已废弃（内容与 `artifacts/release/` 完全相同）；
> 打包脚本只写 `artifacts/release/`。注意 `Build-Portable-Py.ps1` 只覆盖本次产出的同名文件，
> **不会**整目录清理，以免误删同目录下的其它交付物。

## 构建 MSI 安装包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Installer-Py.ps1
```

前置条件：WiX Toolset 6（`wix.exe` 在 PATH 或 `C:\Program Files\WiX Toolset v6.0\bin\`）。
便携目录不存在时脚本会自动先执行 `Build-Portable-Py.ps1`。

| 开关 | 用途 |
|------|------|
| `-PortableDirectory <路径>` | 指定便携目录来源 |
| `-OutputDirectory <路径>` | 指定 MSI 输出目录（默认 `artifacts/release`） |
| `-ProductVersion 1.0.4.0` | MSI ProductVersion（四段数字） |
| `-SkipPortableBuild` | 便携目录缺失时直接失败，不自动打包 |

安装包关键属性（脚本会在构建后直接读 MSI 数据库校验）：

| 属性 | 值 |
|------|-----|
| ProductName | 炳恒快速混剪（Python 版） |
| ProductVersion | 1.0.4.0 |
| UpgradeCode | `{B8D5F3C2-A0E4-4F7B-9D6C-2E3F4A5B6C7D}` |
| Scope | `perUserOrMachine`（无管理员权限时按用户安装） |
| 语言 / 代码页 | 2052 / 936 |

**UpgradeCode 隔离**：脚本内置「UpgradeCode 不得等于历史 .NET 版」的断言
（常量保留，防止旧注册表残留互相触发 MajorUpgrade）。

实测安装行为（本机验证）：无管理员权限时安装到
`%LOCALAPPDATA%\Programs\炳恒快速混剪 Python 版`，2680 个文件、789.6 MB，
并创建开始菜单与桌面快捷方式；卸载后目录、注册表卸载项、开始菜单文件夹均被清除。

安装后自检（证明装完即可用，运行时全部解析到安装目录内）：

```powershell
& "$env:LOCALAPPDATA\Programs\炳恒快速混剪 Python 版\炳恒快速混剪.exe" --self-test --report-file "$env:TEMP\selftest.json"
```

## 打包便携包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Portable-Py.ps1
```

前置条件：

- `python -m pip install pyinstaller PySide6`（PyInstaller 6.x；本仓库验证 6.20.0 / PySide6 6.11.0）
- `runtime/` 中至少包含 `ffmpeg/`（必需）；`whisper/`、`tesseract/`、`python/` 为可选

脚本按顺序执行：

1. 校验 PyInstaller 与 PySide6 可用
2. `pyinstaller --noconfirm --clean scripts/jingxu.spec`（onedir 布局，无控制台窗口）
3. 把 `runtime/{ffmpeg,whisper,tesseract,python}` 复制到 **exe 同级** 的 `runtime/`
4. 复制选品爬虫源码到 `runtime/spider`（排除 `data/`、`tests/`、`examples/`、`gui/` 等）
5. 复制 `runtime-manifest.json`、`THIRD_PARTY_NOTICES.md`、README
6. **在打包目录内执行 `--self-test`**，退出码非 0 或 `success=false` 即整体失败
7. 生成 ZIP 与 SHA-256

常用开关：

| 开关 | 用途 |
|------|------|
| `-RuntimeDirectory <路径>` | 指定运行时缓存目录（默认仓库 `runtime/`） |
| `-OutputDirectory <路径>` | 指定产物目录（默认 `artifacts/release`） |
| `-SkipArchive` | 只产出未压缩目录（本地快速验证） |
| `-SkipSelfTest` | 跳过启动自检（**不可用于正式发布**） |
| `-ReuseBuild` | 复用已编译目录并重做运行时复制与自检；若源码或打包规格较新则拒绝复用 |

## 目录形态

```text
炳恒快速混剪/
├── 炳恒快速混剪.exe          # 入口（无控制台窗口）
├── _internal/                # PyInstaller 运行时与依赖
├── runtime/                  # 随包运行时（与 exe 同级，这是解析的关键）
│   ├── ffmpeg/{ffmpeg.exe,ffprobe.exe}
│   ├── whisper/{whisper-cli.exe,models/ggml-base.bin}   # 可选
│   ├── tesseract/tesseract.exe                          # 可选
│   ├── python/                                          # 可选（选品爬虫内置解释器）
│   └── spider/                                          # 选品爬虫源码
├── runtime-manifest.json
├── THIRD_PARTY_NOTICES.md
└── 使用说明-Python版.md
```

**为什么 `runtime/` 放在 exe 同级而不是打进 exe**：FFmpeg 约 430 MB，打进 exe 会让
每次启动都解包上百 MB；放在同级还能让用户单独替换 FFmpeg 版本而无需重新打包。
`core/jingxu/infrastructure/app_paths.py` 在冻结运行时优先解析 `sys.executable` 所在目录，
因此该布局是必需约定。

## 验证

打包后建议依次确认：

```powershell
# 1. 自检（脚本已自动执行一次）
.\炳恒快速混剪.exe --self-test

# 2. 无界面导入冒烟
.\炳恒快速混剪.exe --import-smoke .\素材.mp4

# 3. 图形界面
.\炳恒快速混剪.exe
```

自检报告字段：`success` / `manifestValid` / `components` /
`missingRequired` / `window` / `ffmpeg` / `ffprobe`。

## 已知限制

- **未做代码签名**：首次运行可能出现 SmartScreen「未知发布者」提示，属预期行为，
  不视为构建失败。
- **Tesseract 占位文件会被剔除**：历史上发布流水线会在 `runtime/tesseract/` 放
  1 字节占位文件，脚本检测到小于 64 KB 的可执行文件时整目录剔除，避免被误判为
  可用（`runtime_tesseract()` 同样按 64 KB 过滤）。
- **可选组件缺失不阻断打包**：缺少 Whisper/Tesseract 时脚本以警告继续，对应功能
  在界面中显示为不可用。
- **仅 Windows x64**：本流程未验证 macOS/Linux。PyInstaller spec 与构建脚本都是
  Windows 形态（`.exe`、robocopy、ZIP 命名），跨平台交付需要另立脚本。
- **无统一发布校验出口**：原 `Verify-Release.ps1` 只覆盖 .NET 产物，已随 .NET 树移除。
  当前以打包脚本自带校验（自检、MSI 属性读取、UpgradeCode 断言）+ pytest 结果为准。
