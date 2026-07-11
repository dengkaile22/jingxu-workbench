# 运行时与发布 — 模块现状

## 文档目的

保留离线 sidecar 运行时与双产物（便携 + 安装包）意图，记录解析顺序、清单占位哈希与安装器现状。

## 目标设计

- 解析顺序：应用目录 `runtime/` → 用户设置目录 → `PATH`。
- 必需：FFmpeg/FFprobe；可选：Whisper、Tesseract（及模型/语言包）。
- `runtime-manifest.json` 固定 SHA-256；禁止发布流水线拉 `latest`。
- 产物：`JingXu-Workbench-Portable-win-x64.zip`、`JingXu-Workbench-Setup-win-x64.exe`；未签名时 SmartScreen 警告不视为构建失败。

规格：§4.3、§14；工程文档 [release.md](../release.md)、[runtime-licensing.md](../runtime-licensing.md)。

## 开发现状

| 能力 | 状态 | 路径 / 证据 |
|------|------|-------------|
| `RuntimeResolver` | ✅ | `Infrastructure/Runtime/RuntimeResolver.cs` |
| 诊断服务 | ✅ | `RuntimeDiagnosticService`；设置页使用 |
| 清单校验 | ✅ | `RuntimeManifestValidator` + 测试；清单文件 `build/runtime-manifest.json` |
| 哈希 | 🟡 | 组件 `sha256` 仍为全零占位；开发可用 `-AllowPlaceholderHash` |
| 布局说明 | ✅ | `runtime/README.md`：`ffmpeg/`、`whisper/`、`tesseract/` |
| 便携构建 | ✅ | `scripts/Build-Portable.ps1` → `artifacts/release/…Portable…zip` |
| MSI / Bundle 源 | 🟡 | `build/Installer/*.wxs`；Burn 需 `WixToolset.BootstrapperApplications`（见验收报告） |
| 校验脚本 | ✅ | `scripts/Verify-Release.ps1`（占位哈希/失败测试时非零退出属预期） |
| 自检 | ✅ | `JingXu.Workbench.exe --self-test` |

环境变量：无应用专用云密钥；进程依赖系统 `PATH` 作为第三解析层。不存在文档化的 `JINGXU_*` HTTP 服务环境变量集。

## 待对齐项

1. 用 `Resolve-Runtimes.ps1 -PrintHashes` 写入真实 SHA-256 后再宣称「可审计发布」。
2. 安装器：补齐 WiX Burn 扩展或文档改为「当前交付 MSI / 仅便携」。
3. 主仓 `dist/` 为已发布二进制快照；**源码构建以 worktree 脚本为准**，避免两处 docs 命令不一致。
