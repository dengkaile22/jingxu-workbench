# 运行时与发布 — 模块现状

> **存档（2026-09-23）：** 本文以 .NET/WPF 时期的路径与类型为证据，该参照树已移除（git 标签 `last-dotnet-reference`）。现行技术栈为 Python（`src/JingXu.Workbench.Py`），文中 `.cs`/`.xaml` 路径仅作历史记录。

## 文档目的

保留离线 sidecar 运行时与产物（便携目录 + MSI 安装包）意图，记录解析顺序、清单占位哈希与安装器现状。
（.NET 版双产物流水线已于 2026-09-23 随 .NET 树移除，git 标签 `last-dotnet-reference`。）

## 目标设计

- 解析顺序：应用目录 `runtime/` → 用户设置目录 → `PATH`。
- 必需：FFmpeg/FFprobe；可选：Whisper、Tesseract（及模型/语言包）。
- `runtime-manifest.json` 固定 SHA-256；禁止发布流水线拉 `latest`。
- 产物：`炳恒快速混剪-Py-win-x64.msi`；未签名时 SmartScreen 警告不视为构建失败。

规格：§4.3、§14；工程文档 [release-python.md](../release-python.md)、[runtime-licensing.md](../runtime-licensing.md)。

## 开发现状

| 能力 | 状态 | 路径 / 证据 |
|------|------|-------------|
| 运行时解析 | ✅ | `jingxu/infrastructure/app_paths.py`（冻结时 exe 同级优先） |
| 诊断服务 | ✅ | `jingxu/infrastructure/diagnostics.py`；设置页使用 |
| 清单校验 | ✅ | `jingxu/infrastructure/runtime_manifest.py`（按名核对）+ 测试；清单文件 `build/runtime-manifest.json` |
| 哈希 | 🟡 | 组件 `sha256` 仍为全零占位；正式发布前用 `Resolve-Runtimes.ps1 -PrintHashes` 写入真实值 |
| 布局说明 | ✅ | `runtime/README.md`：`ffmpeg/`、`whisper/`、`tesseract/` |
| 便携构建 | ✅ | `scripts/Build-Portable-Py.ps1` → `artifacts/py-build/`（+ 可选 ZIP） |
| MSI 安装源 | ✅ | `build/Installer-Py/Product.wxs`、`Package.wxs`、`License.rtf` |
| 自检 | ✅ | `炳恒快速混剪.exe --self-test --report-file <path>` |

环境变量：无应用专用云密钥；进程依赖系统 `PATH` 作为第三解析层。不存在文档化的 `JINGXU_*` HTTP 服务环境变量集。

## 待对齐项

1. 用 `Resolve-Runtimes.ps1 -PrintHashes` 写入真实 SHA-256 后再宣称「可审计发布」。
2. 交付历史以 git 标签为准：`last-dotnet-reference`（.NET 参照树最后保留点）。
