# 主仓与文档对齐说明（2026-07-11）

## 文档目的

记录仓库从「主根 + jingxu-implementation worktree」双树过渡到**单一工作树**的结论，以及文档/媒体资产的 git 边界。

## 目标设计

单一产品「镜序工作台」：离线 Windows WPF 视频批处理；设计规格为意图标准；实现按 Clean Architecture 四项目落地；docs 与源码同树维护。

## 开发现状

### 根目录选择（已收敛）

- 开发工作目录：`project2026071001`（分支 `feature/jingxu-implementation`）。
- 可编译源码、工程文档、安装器脚本均在**本树**：`src/`、`tests/`、`scripts/`、`build/`、`docs/`。
- 历史路径 `.worktrees/jingxu-implementation` 中未提交工作已并入本树后移除多余 worktree；`.worktrees/` 仍由 `.gitignore` 忽略。

### 核实结论（相对「常见不对齐」清单）

| 常见审计项 | 本仓库结论 |
|------------|------------|
| README / 架构与入口不一致 | 有过时层图（已修正 `architecture.md`）；真实入口 `App.xaml.cs` → `AppCompositionRoot` |
| pipeline vs agent_pipeline | **不存在**；非本产品结构 |
| API 路径 / 环境变量过时 | **无 HTTP API**；仅 CLI `--self-test` 等与 `PATH`/runtime 解析 |
| 文档承诺 vs 未实现 | 有：内存队列、项目存档 UI、硬件编码、贴纸 UI、转场、正式哈希等 — 见 `docs/modules/` |
| 废弃模块名 | 规格名与代码名有演变 — 见 `docs/status/2026-07-11-design-vs-code-names.md` |

### 媒体与大文件（git 边界）

| 路径 | 策略 |
|------|------|
| `test-assets/**`（客户 `.mp4`） | **本地保留**，gitignore；验收测试缺失时 Skip |
| 根目录 `*.rar` | **不入库**；解压到 `test-assets/` 后可删压缩包 |
| `runtime/*`（二进制） | 已 ignore；仅跟踪 `runtime/README.md` |
| `dist/` | 已 ignore（发布产物） |

说明见 [test-assets/README.md](../../test-assets/README.md)。

### 权威阅读路径

1. 意图：`docs/superpowers/specs/2026-07-10-video-workbench-design.md`
2. 现状总览：`docs/status/2026-07-11-implementation-alignment.md`
3. 模块：`docs/modules/*-status.md`
4. 验收：`docs/acceptance-report.md`

## 待对齐项

1. feature 合并进 `main` 时，将本树 `docs/`（含 status/modules）与 `src/` 一并进入 `main`，本说明可缩为历史注记。
2. 建议将本次「worktree 并入 + 文档/打包文件 + gitignore 媒体边界」作为一次显式 commit（需用户确认后再提交）。
