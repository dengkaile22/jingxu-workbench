# 架构概览

## 文档目的

说明镜序工作台的分层边界与数据流。**产品与架构意图以设计规格为准**；下文同时给出实现落点，避免把目标图误认为当前目录树。

完整规格：[superpowers/specs/2026-07-10-video-workbench-design.md](superpowers/specs/2026-07-10-video-workbench-design.md)  
迁移验收：[python-migration-acceptance.md](python-migration-acceptance.md)

> **技术栈变更（2026-09-23）：** 仓库已全面转向 Python（PySide6 + FFmpeg），
> 原 .NET/WPF 四层实现移除，最后保留点见 git 标签 `last-dotnet-reference`。
> 下文「目标设计」的分层意图仍然有效，实现落点改为 Python 目录。

## 目标设计

四层 Clean Architecture，Domain 不引用 UI 框架、文件系统或外部进程：

```text
UI (PySide6)        — Shell、各功能 Page/Widget
application         — 用例编排、队列调度、项目/模板服务
domain              — 纯业务规则与不可变模型
infrastructure      — FFprobe/FFmpeg、Whisper/Tesseract、JSON、Runtime、子进程
```

关键意图：

- 命令生成器只接受强类型计划，返回参数列表，不接受任意 shell 字符串。
- 统一进程运行器负责 stdout/stderr 与取消。
- 运行时解析：bundled `runtime/` → 用户目录 → `PATH`。
- 入队生成不可变渲染任务；队列与项目版本化 JSON 原子保存。

## 开发现状

### 真实项目边界

```text
src/JingXu.Workbench.Py/jingxu/ui              # 界面：shell_window、各功能 page、预览画布
src/JingXu.Workbench.Py/jingxu/application     # 用例编排：composition_service、渲染队列、下载
src/JingXu.Workbench.Py/jingxu/domain          # 纯领域：layers、render、subtitles、deterministic
src/JingXu.Workbench.Py/jingxu/infrastructure  # FFmpeg 编译/执行、探测、过滤图、持久化、诊断
src/JingXu.Spider/                             # 选品爬虫（独立 Python 包，用户主动触发联网）
```

### 数据流（已实现主路径）

1. 导入素材 → FFprobe 探测 → 媒体资产
2. `composition_service`（编排/入队校验）→ 合成计划
3. 渲染请求 → 队列入队
4. FFmpeg 命令编译 → 外部进程执行（硬解/缩放/编码三级回退）
5. 临时输出验证后按命名策略落到目标目录（封面生成）

### 打包与交付

- PyInstaller onedir：`scripts/Build-Portable-Py.ps1` + `scripts/jingxu.spec`
- MSI：`scripts/Build-Installer-Py.ps1` + `build/Installer-Py/*.wxs`（WiX 6）
- 产物：`artifacts/release/炳恒快速混剪-Py-win-x64.msi`

## 已知偏差

- 持久化队列：规格要求版本化 JSON；现状以进程内队列 + 任务日志为主，见 [modules/render-queue-persistence-status.md](modules/render-queue-persistence-status.md)。
- 形状/PNG 遮罩：领域、滤镜与持久化已就位，尚无独立编辑 UI（与 .NET 二期定位一致）。

