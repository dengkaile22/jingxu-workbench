# 发布流程

## 文档目的

描述便携包与 MSI 安装程序的目标产物与脚本。运行时哈希等 **开发现状** 见 [modules/runtime-packaging-status.md](modules/runtime-packaging-status.md) 与 [acceptance-report.md](acceptance-report.md)。

> **本文描述的是 .NET 版（WPF）流水线。当前对外交付的是 Python 版**，
> 见 [release-python.md](release-python.md)（`scripts/Build-Portable-Py.ps1` +
> `scripts/jingxu.spec` + `scripts/Build-Installer-Py.ps1`）。
>
> .NET 版的安装包与便携包**已从交付目录移除**以避免与在用版本混淆；
> .NET 源码与本文所述脚本仍保留，可随时重建。

## 目标设计

交付自包含便携 ZIP 与 WiX MSI 安装程序；运行时哈希可审计；未签名时 SmartScreen 警告不视为构建失败（规格 §14）。

## 开发现状（摘要）

- 便携包脚本可用；开发机常用 `-AllowPlaceholderHash -BootstrapFromPath`。
- `build/runtime-manifest.json` 当前多为占位 SHA-256，**不可**当作正式发布证据。
- WiX MSI 源在 `build/Installer/`；当前只保留 MSI 安装方式，不生成 Burn/Setup EXE。

## 产物

| 文件 | 说明 |
|------|------|
| `artifacts/release/炳恒快速混剪-Portable-win-x64.zip` | 自包含便携版 |
| `artifacts/release/炳恒快速混剪-win-x64.msi` | WiX MSI 安装程序 |
| `artifacts/release/SHA256SUMS.txt` | 产物 SHA-256 校验和 |

## 步骤

### 1. 准备运行时

将已验证的 FFmpeg、Whisper、Tesseract 放入 `runtime/`（或独立缓存目录），更新 `build/runtime-manifest.json` 中的固定 SHA-256：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Resolve-Runtimes.ps1 `
  -CacheDirectory runtime `
  -PrintHashes
```

**禁止**在发布脚本中下载可变 `latest` 资产；仅复制已验证缓存。

### 2. Staging

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Resolve-Runtimes.ps1 -CacheDirectory runtime
```

输出：`artifacts/staging/runtime/`

### 3. 便携包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Portable.ps1
```

内部执行 `dotnet publish`（`win-x64`、`--self-contained`、无 PDB），合并 runtime 与声明文件，生成 ZIP 与哈希。

开发机无完整运行时时可使用 `-AllowPlaceholderHash -BootstrapFromPath`（**不可用于正式发布**）。

### 4. MSI 安装程序

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Installer.ps1
```

需要 **WiX Toolset 6.x**（`wix.exe` 在 PATH）。源文件位于 `build/Installer/`。构建脚本只生成 MSI，不生成 Burn/Setup EXE。

安装程序仅管理 `Program Files` 下的应用目录，**不**写入用户文档或 `分镜输出` 目录；卸载不删除用户项目与成片。

### 5. 发布校验

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Verify-Release.ps1
```

失败条件包括：构建警告、必需测试失败/跳过、占位标记、缺失产物、哈希不匹配等。

## 代码签名

无证书时产物未签名，SmartScreen 可能警告。签名非构建失败条件，但交付说明须明确标注（见根目录 `README.md`）。
