# 四屏特效与缓存磁盘修复实施计划

> 执行方式：在当前任务内按 subagent-driven-development 分工；每项先运行失败回归，再实现并审查。用户已授权执行，不在步骤之间重复询问。

**目标：** 实现 Word 反馈中的 2×2 四屏效果，完善临时文件生命周期、失败诊断和磁盘空间管理。

**架构：** 四屏使用独立计划和滤镜编译器，在现有请求及 WPF 界面接入。缓存使用跨进程资源登记和清理协调，诊断文件与大体积暂存分离；同卷任务共享空间预留，下载在目标卷写半成品。

**技术栈：** C# / .NET 10 / WPF / xUnit / bundled FFmpeg。

## 工作边界

- 保留当前 27 个已修改文件及 2 个未跟踪文件，原始内容已备份到 artifacts/fix-baseline-*。
- 不清理 C:\ProgramData\Synaptics 或任何不属于本软件的文件。
- 不扩展字幕入口、完整项目存档等与本次文档无关的功能。
- 修改完成后交付源码、真实测试证据和更新后的 MSI；不自动提交已有用户改动。

## 任务一 四屏功能

**文件：** Domain/Effects/FourScreenEffectPlan.cs（新增），Domain/Rendering/RenderRequest.cs，Application/Rendering/RenderRequestFactory.cs、RenderPreflight.cs，Infrastructure/Rendering/FourScreenFilterCompiler.cs（新增）、FfmpegCommandCompiler.cs，Features/Composition/CompositionViewModel*.cs、CompositionView.xaml，对应 Domain/Application/Infrastructure/Presentation/Integration 测试。

- [x] 增加四屏计划、固定随机结果、片段范围和互斥回归；确认缺失功能失败。
- [x] 实现普通四格同源、随机一主三辅、同文件夹素材不足可重复、音频保持主轨。
- [x] 实现 2×2 尺寸适配及横竖缝羽化；素材位置与来源在入队时固定。
- [x] 接通 WPF 起始序号、随机模式和羽化设置，双屏四屏互斥；检查模板兼容。
- [x] 真实 FFmpeg 测试用不同颜色判断四格来源，核对时长、分辨率及声音，重跑现有双屏回归。

## 任务二 临时文件和诊断

**文件：** Application/Projects/TempResourceLease.cs（新增）、WorkbenchCacheCleanup.cs、StagingLeaseStore.cs，Infrastructure/Rendering/FfmpegRenderExecutor.cs，所有预览/OCR/Whisper 临时文件生产者，App.xaml.cs、SettingsViewModel.cs 和对应测试。

- [x] 增加失败后日志保留、活跃资源不被启动/手动清理、登记路径不越界的回归。
- [x] 通过跨进程登记与锁协调清理和生产者，进程退出后登记可被回收。
- [x] 成功删除暂存；失败/取消保留有界诊断并回收媒体、别名；记录实际诊断路径。
- [x] 清理使用所属路径白名单，保留用户素材、成片、库 JSON 与活跃资源。
- [x] 启动和手动扫描在后台执行，正确显示忙碌和完成状态。

## 任务三 磁盘与下载

**文件：** Infrastructure/Rendering/RenderDiskSpaceReservations.cs（新增）、StagingInputMaterializer.cs、FfmpegRenderExecutor.cs，Downloads/HttpClientVideoDownloader.cs 及对应测试。

- [x] 增加并发预留释放、素材复制预算、下载目标卷半成品及取消回收回归。
- [x] 输出卷按任务共享空间预算；需要真实复制输入时，在复制前预留字节数；正常/异常/取消都释放。
- [x] 空间不足时仅回收已失效本软件资源并复查，失败提示包含目标卷及诊断。
- [x] 下载先写目标目录的专属临时子目录，完成后原子替换/移动，失败取消删除半成品。

## 验证与交付

- [x] 定向测试先红后绿；所有 dotnet 构建使用 -m:1，避免共享 obj 写入竞争。
- [x] `dotnet build JingXu.Workbench.sln -c Release --no-restore -p:RuntimeIdentifier= -m:1`。
- [x] `dotnet test JingXu.Workbench.sln -c Release --no-build --no-restore -m:1`，PATH 优先 runtime/ffmpeg。
- [x] 对需求符合性及代码质量分别审查，处理所有实际问题。
- [x] 更新使用说明，构建 MSI，核验 SHA-256 和发布目录自检；如环境阻止某项验证，明确记录原因。

## 完成验证

- 2026-09-12：Release 构建 0 警告、0 错误；全套 535 项，531 通过、4 项缺少指定客户素材而跳过。
- CPU 和本机 GPU 各连续完成 8 个四屏任务，成片保留，暂存和活跃登记全部释放。
- 新增启动自检阻塞回归：修复前 15 秒超时；修复后发布程序约 0.45 秒返回成功 JSON，退出码 0。
- MSI 版本 1.0.1.0，最终 SHA-256：3632b0c21995c5c8a4d989dedad517c0aa5ebca540d64f38c0bb5b56558e6e34。
- 必需 FFmpeg/FFprobe 文件哈希与清单匹配；NuGet locked restore 与 git diff --check 通过。
- 未执行真实安装后的人工点击验收，未处理来源未确认的 Synaptics 文件。
