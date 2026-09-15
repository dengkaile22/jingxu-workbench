# 1.0.2 四屏、数字人性能与 GPU 验证记录

验证日期：2026-09-12。执行环境为 Windows、本机 i5-13500H / Intel Iris Xe，使用项目随包 FFmpeg 8.1.1。下面的耗时来自合成素材的本机实测，不能等同于客户 NVIDIA 机器或任意时长、分辨率素材的速度承诺。

## 实现与兼容范围

- 四屏保持 2×2 格子、横竖羽化和原有声音规则。羽化使用一帧静态灰度渐变，主视频决定结束；相同素材、相同格子尺寸只缩放一次。
- 同片段的重复辅助格共用解码标签，缩放后再分流；跨片段使用独立输入，消除重复源级分流和主动吸帧的无效支路。主片和四屏辅助素材每路使用 2 个解码线程。
- 新增 QSV/CUDA 硬件解码与缩放能力探测；D3D11VA 保守启用解码回传。探测使用实际编码的 H.264 样本，有超时、缓存、重新检测和临时资源租约。
- 自动模式继续优先使用 NVENC/QSV/AMF 编码，只在适合缩小尺寸的主片启用新增硬解和 GPU 缩放。手动 GPU 模式允许兼容主片硬解。CPU 模式保持软件路径。
- 当前硬解白名单为 8 位 H.264/yuv420p、无旋转、偶数尺寸且宽高在 128–4096 范围。旧项目主片缺少像素格式时只补充本次渲染信息，必须与已保存的尺寸、编码格式、旋转一致，不修改原请求快照。
- 循环辅助视频、数字人/透明蒙版、贴纸和调色继续使用软件处理。实测发现循环 QSV 辅助输入会重建硬件帧上下文并可能使 FFmpeg 崩溃，所以所有 `-stream_loop` 输入均禁用硬解。
- 输入硬件处理失败先重试软件解码并保留原硬件编码；编码器仍不可用时再回退 CPU。QSV 初始化、IO surface、帧池和 D3D11 帧提交错误均有序列回归，普通合成错误不触发硬件重试。
- 实际四屏处理面积达到 1280×720 时，队列自动逐个执行以减少资源争用；普通任务仍遵循 1–4 并发设置。预留后取消、FIFO、后续调度和持久化失败保护均有回归。
- 进度同时显示百分比和实际倍速。失败摘要跳过带前缀的统计行，退出码 -12 明确显示内存申请失败，失败日志保留在输出目录 `.jingxu-logs/<任务ID>/`。

## 独立性能复测

短样本：1080×1440、30 fps、2 秒动态测试图，叠加 320×480 的模拟人物视频。人物有透明度、顶部渐隐和边缘羽化。优化前后均使用 QSV 最终编码；优化前 GPU 选项只有硬件编码，新版分别验证自动与手动 GPU 模式。

| 场景 | 优化前 | 新版自动 | 新版手动 GPU |
|---|---:|---:|---:|
| 仅人物叠加 | 3.572 秒 | 2.074 秒 | 2.409 秒 |
| 四屏、保留羽化 | 12.149 秒 | 1.275 秒 | 1.181 秒 |
| 四屏＋人物、保留羽化 | 11.798 秒 | 1.550 秒 | 1.435 秒 |
| 四屏＋人物、无羽化对照 | 1.908 秒 | 1.054 秒 | 0.916 秒 |

四屏＋人物的自动模式在此样本上约为原来的 7.6 倍速度。首个场景包含首次编码器探测和初始化，其他场景在同一执行器内运行。耗时受机器负载、驱动和素材影响；没有使用全套并行测试中的耗时作为性能结论。

短样本原始记录：

- `artifacts/feather-validation/performance-before.json`
- `artifacts/gpu-delivery-validation/isolated-performance/avatar-compatibility-measurements-Auto.json`
- `artifacts/gpu-delivery-validation/isolated-performance/avatar-compatibility-measurements-Gpu.json`

10 秒多片段样本：两个 5 秒片段、0.5 秒循环辅助视频、循环人物叠加，输出 1080×1440。消除无效辅助分支的专项对照中，CPU 解码＋QSV 编码的峰值工作集从约 1214 MiB 降至约 513 MiB；最终独立复测为 509 MiB。这里是 FFmpeg 自报的峰值工作集，不能代表独立显存或全部系统提交内存。该专项对照用于验证帧缓冲改动，原始旧 MSI 没有对应的内存测量。

同编码器的缩小画幅测试还验证了 CenterCrop、Letterbox、Stretch 和 BlurBackground 四种适配，尺寸、时长、帧率和颜色均正确。真实 FFmpeg 拒绝首轮设备参数后，第二轮软件解码＋QSV 编码成功。性能原始数据与实际滤镜保存在 `artifacts/gpu-validation/`，最终独立复测数据保存在 `artifacts/gpu-delivery-validation/isolated-performance/`。

## 最终验证

- Release 构建：0 警告、0 错误。
- 最新完整测试：595 通过、4 跳过、0 失败，共 599 项。4 个跳过用例需要本机不存在的指定客户蒙版/视频样本。
- Application 96/96；Domain 107/107；Infrastructure 213 通过＋1 跳过；Integration 37 通过＋1 跳过；Presentation 142 通过＋2 跳过。
- 额外独立媒体复测：兼容组合 2/2、长片段 3/3、四种画幅与真实回退 1/1。
- 需求审查和代码质量审查提出的问题均已修复并复核，最终没有未解决的 P1/P2 发现。
- 构建、测试与发布工作区使用串行 `dotnet` 和独立测试数据目录，日常素材库不作为测试目录。

最终全套记录为 `artifacts/gpu-delivery-validation/final_*.trx`；构建记录为同目录 `build-final.log`，单独性能验证为 `isolated-*.trx`。

## 证据限制

本机真实验证的是 Intel QSV。NVIDIA CUDA 的命令、白名单、探测与回退有代码验证，但没有 NVIDIA 实机测量；安装后的设备探测通过才会启用。D3D11 的解码回传已实测，当前机器失败的 `scale_d3d11` 没有设为默认。

客户截图对应的完整 `render.log` 位于另一台机器，当前未获得。相同随包 FFmpeg 的受控内存分配失败返回 -12，可确认错误类别；无法据截图区分具体的系统内存、显卡资源或其他缓冲耗尽位置。四屏与数字人同时开启已经过真实组合输出和尾帧验证，不存在必须互斥的产品规则。

## 安装包交付

- MSI ProductVersion 与发布应用 FileVersion 均为 `1.0.2.0`。
- 发布应用 `--self-test` 退出码 0，JSON `success=true`；MSI 数据库属性已实际读取校验。
- 文件大小：192,089,117 字节（183.19 MiB）。
- SHA-256：`d96af2c34495102f2ea892efecc16e8fc84bd7babedddc8dbfea83dc65e2482b`。
- 原项目 `dist/炳恒快速混剪-win-x64.msi` 与用户指定 `C:/Users/dengkaile/OneDrive/Desktop/project2026071001/dist/炳恒快速混剪-win-x64.msi` 已同步，SHA-256 相同；各自带有 `SHA256SUMS.txt`。

打包记录在 `artifacts/gpu-delivery-validation/publish-msi.log`；版本、哈希及两个交付位置的验证记录在同目录 `package-verification.json`，发布启动自检记录为 `published-self-test.json`。
