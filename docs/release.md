# 发布流程

> **本文原描述 .NET 版（WPF）流水线，该流水线已于 2026-09-23 随 .NET 树一并移除**
> （git 标签 `last-dotnet-reference` 可回查）。
> **当前唯一发布流程是 Python 版**：[release-python.md](release-python.md)
> （`scripts/Build-Portable-Py.ps1` + `scripts/jingxu.spec` + `scripts/Build-Installer-Py.ps1`）。

## 仍然适用的部分（运行时准备）

### 1. 准备运行时

将已验证的 FFmpeg、Whisper、Tesseract 放入 `runtime/`（或独立缓存目录），更新 `build/runtime-manifest.json` 中的固定 SHA-256：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Resolve-Runtimes.ps1 `
  -CacheDirectory runtime `
  -PrintHashes
```

**禁止**在发布脚本中下载可变 `latest` 资产；仅复制已验证缓存。

## 代码签名

无证书时产物未签名，SmartScreen 可能警告。签名非构建失败条件，但交付说明须明确标注（见根目录 `README.md`）。
