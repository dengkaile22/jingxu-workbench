# 测试说明

## 文档目的

说明自动化测试分层与运行方式。验收结论与仍失败项以 [acceptance-report.md](acceptance-report.md) 与 [python-migration-acceptance.md](python-migration-acceptance.md) 为准。

## 目标设计

规格 §13：单元覆盖解析/排列/时间轴/队列；集成用短视频验证顺序、时长、蒙版、字幕、取消；发布验收含 DPI 与便携启动。

## 测试分层（Python / pytest）

测试位于 `src/JingXu.Workbench.Py/tests/`：

| 层 | 范围 |
|------|------|
| 默认（单元） | 序号解析、排列、时间轴、队列状态机、命令编译、过滤图、持久化、UI 页面结构与控件行为 |
| `-m integration` | 真机 FFmpeg 端到端管线（需 `runtime/ffmpeg/` 或 PATH 中有 FFmpeg） |
| 默认排除（10 项） | 需客户真机素材的用例；媒体文件不入库（`test-assets/`，见其 README） |

### 运行

```powershell
cd src/JingXu.Workbench.Py

# 单元测试
python -m pytest

# 真机集成（需 FFmpeg）
$env:PATH = "$PWD\..\..\runtime\ffmpeg;$env:PATH"
python -m pytest -m integration

# 单个文件
python -m pytest tests/test_layer_shape_mask.py
```

### 打包验收

```powershell
# 便携目录 + 自检（报告写文件，窗口模式 stdout 不可靠）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Portable-Py.ps1 -SkipArchive
.\artifacts\py-build\炳恒快速混剪\炳恒快速混剪.exe --self-test --report-file .\selftest.json

# MSI
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Installer-Py.ps1
```

打包脚本内置校验（产物非零字节、MSI 属性可读、UpgradeCode 断言等）；失败即非零退出。

## 待对齐项

- 发布前尚无统一的 `Verify-Release` 出口（原脚本只覆盖 .NET 产物，已随 .NET 树移除）；当前以打包脚本自带校验 + pytest 结果为准。
