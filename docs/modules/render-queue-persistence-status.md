# 渲染队列与持久化 — 模块现状

## 文档目的

保留「不可变任务快照、有界并发、暂停/取消、崩溃恢复、版本化 JSON」意图，明确当前队列存储与项目持久化的真实完成度。

## 目标设计

- 状态机：`Draft → Queued → Preparing → Running → Finalizing → Completed`，失败可重试，可取消。
- 入队快照后 UI 修改不影响已入队任务。
- 默认并发 1，用户可选 1–4；暂停只停调度；取消走 Job Object 杀进程树。
- 每次状态变化原子保存队列；项目/设置为带 `schemaVersion` 的 JSON。

规格：§8–10。

## 开发现状

| 能力 | 状态 | 路径 / 证据 |
|------|------|-------------|
| `JobState` / `RenderJob` | ✅ | `Domain/Rendering/RenderJob.cs` |
| 协调器 | ✅ | `Application/Rendering/RenderCoordinator.cs`（`maxConcurrency` clamp 1–4，`PauseQueue`） |
| 预检 | ✅ | `RenderPreflight.cs` |
| 执行 | ✅ | `FfmpegRenderExecutor` + `ExternalProcessRunner` + `WindowsJobObject` |
| 组合根默认并发 / UI 调节 | ✅ | `AppCompositionRoot` 默认 `maxConcurrency: 2`；设置页已支持 1–4 并发调节并即时应用 |
| 队列 UI | ✅ | `Features/Queue/RenderQueueViewModel.cs` 绑定 `RenderCoordinator` |
| 队列持久化 | ❌ 相对规格 | `InMemoryRenderQueueStore`（`RenderQueueInfrastructure.cs`）；**进程退出即丢失** |
| 中断恢复算法 | 🟡 | `ProjectService.RecoverJobs` / `RenderQueueRecovery` 有逻辑；缺持久化则重启恢复无数据源 |
| `AtomicJsonStore<T>` | ✅ | 通用实现已用于蒙版库等 |
| `ProjectDocument` | 🟡 | 类型存在；无完整打开/保存 UX |
| 设置 | 🟡 | `SettingsViewModel` + `RuntimeDiagnosticService`；非完整「用户设置 JSON 文档」规格叙述 |

## 待对齐项

1. **高优先级文档诚实性：** 凡写「队列原子保存 / 重启恢复」处，须标注现状为内存队列，或实现 `IRenderQueueStore` 的 JSON 落盘版。
2. 设置中暴露 1–4 并发，与 `SetMaxConcurrencyAsync` 对齐。
3. 项目打开/保存与标题栏脏标记 —— 规格 §6.1 / §8。
