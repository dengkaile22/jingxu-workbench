# 测试说明

## 文档目的

说明自动化测试分层与运行方式。验收结论与仍失败项以 [acceptance-report.md](acceptance-report.md) 为准；功能完成度见 [status/2026-07-11-implementation-alignment.md](status/2026-07-11-implementation-alignment.md)。

## 目标设计

规格 §13：单元覆盖解析/排列/时间轴/队列；集成用 lavfi 短视频验证顺序、时长、蒙版、字幕、取消；发布验收含 DPI 与便携启动。

## 开发现状

### 测试分层

| 项目 | 范围 |
|------|------|
| `JingXu.Workbench.Domain.Tests` | 序号解析、排列、时间轴、队列状态机 |
| `JingXu.Workbench.Application.Tests` | 用例与规划器 |
| `JingXu.Workbench.Infrastructure.Tests` | FFmpeg 命令编译、FFprobe 解析、运行时清单 |
| `JingXu.Workbench.Presentation.Tests` | ViewModel 行为 |
| `JingXu.Workbench.IntegrationTests` | lavfi 短视频夹具、端到端媒体管线、打包验收 |

### 运行

```powershell
# 全部
dotnet test JingXu.Workbench.sln -c Release

# 打包相关
dotnet test tests/JingXu.Workbench.IntegrationTests --filter "FullyQualifiedName~Packaging"

# 媒体集成（需要 FFmpeg）
dotnet test tests/JingXu.Workbench.IntegrationTests --filter "FullyQualifiedName~Media"
```

缺少 FFmpeg 时，部分集成测试会通过 `Assert.Skip` 跳过，**发布验收脚本要求必需测试不得跳过**。

近期 Release 跑测结果与仍失败用例名见 [acceptance-report.md](acceptance-report.md)，勿假设「文档写了分层即全部绿灯」。

### 集成夹具

`LavfiMediaFactory` 使用 FFmpeg lavfi 生成带颜色与音频的短视频，验证硬切时长、序号顺序、蒙版与字幕等场景。

客户真机素材放在仓库根 `test-assets/`（见该目录 README）；**媒体文件不入库**。缺少目录时 `CustomerAssetAcceptanceTests` 会 Skip。

### 打包测试

- `RuntimePackageTests` — staging 运行时哈希与 `THIRD_PARTY_NOTICES.md` 覆盖
- `PortableArtifactTests` — 便携目录结构与 ZIP 文件名
- `WixSourceTests` — 安装范围不触及用户项目/文档目录

发布前运行 `scripts/Verify-Release.ps1` 执行完整校验。

## 待对齐项

- 集成/打包失败项清零前，验收报告与 Verify-Release 出口码保持「未完全通过」表述。
