# Python 版迁移验收报告

**日期：** 2026-09-19
**目标：** 把「炳恒快速混剪」从 .NET(WPF) 迁移到 Python(PySide6)，仅 Windows x64，达到可交付状态
**范围：** `src/JingXu.Workbench.Py`（.NET 树保留作参照，不删除）

---

## 1. 结论

| 目标项 | 状态 | 证据 |
|--------|------|------|
| (1) Python 版纳入 Git 并规范化 | ✅ | 首次提交 `d97a9c6`，92 个文件；缓存与 `data/` 零泄漏（`git check-ignore` 验证） |
| (2) 逐模块补齐 .NET 独有能力 | ✅ | GPU 缩放/硬解、蒙版形状与 PNG 遮罩、贴纸画幅与宽高比锁定、音频音量语义、命令长度守卫；逐项对齐阈值与回退语义（见 §3） |
| (3) Windows x64 打包链路 | ✅ | `scripts/Build-Portable-Py.ps1` + `jingxu.spec`，脚本退出码 0，产物 405.8 MB ZIP + SHA-256，随包运行时自检通过 |
| (4) pytest 全绿并补测试 | ✅ | 单元 **589 通过 / 10 默认排除**；真机集成 **10 通过**；专项新增 100+ 用例（见 §4） |

唯一**主动不实现**项：staging 短路径别名（理由与量化依据见 §5）。

---

## 2. 交付物

| 文件 | 说明 |
|------|------|
| `artifacts/py-release/炳恒快速混剪-Py-Portable-win-x64.zip` | 405,800,687 字节 |
| `artifacts/py-release/SHA256SUMS.txt` | `ed18d8ab6bda53ebaa0b9347c7bf3d241853def2e52870a05772fc2614f17bd7` |
| `artifacts/py-build/炳恒快速混剪/` | 未压缩便携目录，789.6 MB |

解压即用：双击 `炳恒快速混剪.exe`。

---

## 3. 能力对齐明细

### 3.1 硬件解码与 GPU 缩放

按 .NET `HardwareVideoProcessingPlan` / `Selector` / `Failure` 三件套实现，接进滤镜图、命令行与回退链。

| 项 | 取值/行为 | 来源 |
|----|-----------|------|
| 白名单 | h264 + yuv420p + 旋转 0 + 偶数尺寸 + 128–4096 | `HardwareVideoProcessingPlan.cs:26-31` |
| 空 `pix_fmt` | 一律拒绝（避免探测不完整时冒险） | 语义统一决策 |
| Auto 门槛 | `can_scale` 且确有缩小收益 | `:33-38` |
| GPU 门槛 | 仅要求白名单 | 同上 |
| 设备参数 | `-init_hw_device qsv=jxgpu:hw_any` / `cuda=jxgpu:0` / `d3d11va=jxgpu` | `:51-55` |
| 缩放 | `scale_qsv=w=W:h=H:format=nv12` / `scale_cuda=…:passthrough=0` + `hwdownload,format=nv12` | `:69-74` |
| D3D11 | 只解码不缩放（实机 `scale_d3d11` 失败） | `docs/gpu-performance-1.0.2.md:53` |
| 舍入 | AwayFromZero（Python `round` 是银行家舍入，会差 1–2 像素） | `:111-112` |
| 循环输入 | 一律禁用硬解（QSV 循环会重建硬件帧上下文） | `FfmpegCommandCompiler.cs:153-161` |
| 回退链 | L1 软件解码保留硬编 → L2 CPU 兜底并记住坏编码器 → L3 归档诊断 | `FfmpegRenderExecutor.cs:254-345` |
| 重试条件 | 仅设备级/编码器级关键字触发；普通滤镜错误不重试 | `HardwareVideoProcessingFailure.cs`、`:719-761` |
| 脚本重写 | 每次重试重新生成滤镜脚本（否则残留 `scale_qsv` 必然二次失败） | 迁移新增 |

**真机验证（本机 Intel QSV）**：

```
编码器探测      → h264_qsv (Intel Quick Sync)
输入能力探测    → kind=qsv  can_scale=True
CPU 路径        → 1080x1920 2.00s  4.64 Mbps
AUTO 路径       → 1080x1920 2.00s  1.07 Mbps（实测启用 QSV）
GPU 强制路径    → 1080x1920 2.00s  1.07 Mbps（与 AUTO 字节一致）
分屏+羽化       → 1080x1920 2.00s（循环输入不插硬解）
```

### 3.2 蒙版形状与 PNG 遮罩

| 项 | 行为 |
|----|------|
| 形状枚举 | `NONE / RECTANGLE / ROUNDED_RECTANGLE / ELLIPSE / IMPORTED_PNG` |
| 椭圆 | 按 .NET 语义实现为**边界框内切圆**（半径 `min(W,H)/2`），非方框时只覆盖中间一块 |
| 圆角矩形 | **未沿用** .NET 字面实现（其 `min(X,r)+min(W-X,r)-r` 会整体擦除四条 r 宽边带、角部反而保留，几何上不是圆角）；改用标准「到圆角矩形边界距离」写法 |
| 表达式 | 用运行时 `W/H`（`scale=w:-2` 下帧高编译期不可知）；geq 齐写 `r/g/b/a` 四通道；不使用 `geq=lum=` |
| PNG 遮罩 | 走 `ExtraInput(-loop 1)` 而非 `movie=`，绕开 filtergraph 路径转义；支持 `luma` / `alpha` / `luma_alpha` 三档 + 反相 |
| 阶段顺序 | 不透明度 → 形状 alpha → PNG alpha → 上淡入/羽化 → 旋转 → 叠加 |
| 持久化 | 5 个新键；旧 JSON 缺键回落 `NONE`；**遮罩文件丢失时降级为无形状而非丢弃整条图层** |
| 附带修复 | `:self:` 自叠影哨兵此前被 `is_file()` 判为缺失而整条丢弃，导致项目重开后自叠影消失 |

**真机像素验收**（白底主片 + 红图层，量化红色像素占比）：

| 场景 | 占比 | 期望 |
|------|------|------|
| 无形状（基准） | 36.0% | ≈ 60%×60% |
| 椭圆 | 15.8% | = 36%·πW/(4H) ≈ 44% 的边界框（内切圆） |
| 圆角矩形（r=80） | 35.4% | 略低于基准（只削四角） |
| PNG 左半遮罩 | 18.0% | ≈ 基准一半 |
| 椭圆 + 羽化 | 15.2% | ≤ 纯椭圆（边界软化） |

### 3.3 贴纸独立画幅与宽高比锁定

对齐 `StickerAspectMode` / `FixedAspectRatio`：画布尺寸与显示名逐条一致；锁定后编辑宽或高会联动另一方向，超出可用空间时反推回驱动方向（两个方向都不越界）；预览画幅模式只影响本页画布，用户选独立画幅后混剪页改设置不再拽走编辑视角。

### 3.4 音频库音量语义

对齐 `AudioVolumeMapping`：−100 静音、0 = 默认 BGM 音量（增益 0.18）、+100 最大。旧项目/模板按增益反算迁移，**听感不变**。

### 3.5 命令行长度

对齐 `RenderPreflight.MaxCommandLineLength = 30000`：超限前抛出中文建议（减少素材数量 / 移到更浅目录），不再让 `CreateProcess` 抛原始错误。

---

## 4. 测试证据

| 套件 | 数量 | 结果 |
|------|------|------|
| 单元（默认） | 589 | 全绿 |
| 集成（`-m integration`，真机 FFmpeg） | 10 | 全绿 |
| 默认排除（需客户素材） | 10 | 按标记排除 |

本轮新增的专项测试：

| 文件 | 数量 | 覆盖 |
|------|------|------|
| `test_video_processing.py` | 85 | 白名单边界、Auto/GPU 门槛、四种 fit 尺寸、AwayFromZero 中点、设备参数、download-only、失败分类（逐条遍历关键字）、探测缓存与降级、滤镜图接入、诊断展示 |
| `test_render_fallback.py` | 14 | L1/L2/L3 回退、取消不被吞、CPU 不再回退、命令长度估算与守卫、80 片段深路径规模回归 |
| `test_layer_shape_mask.py` | 31 | 几何表达式、阶段顺序、三种 PNG 模式、反相、尺寸对齐、四类校验失败、持久化往返与降级、自叠影哨兵 |
| `test_layer_aspect_ratio.py` | 21 | 画布尺寸/显示名/比例对齐、容错解析、约束数学（含越界收口）、持久化 |
| `test_layer_page_aspect.py` | 11 | 画幅模式切换与隔离、双向联动、解锁保持尺寸、落盘重开恢复 |
| `test_app_paths.py` | 18 | 冻结/源码根目录解析、同级 runtime 优先、**不上溯源码布局**回归防线、组件解析留在便携目录、`--report-file` 端到端 |
| `test_probe_metadata.py` | 10 | `pix_fmt` 解析、旋转优先级与归一化、异常值容错 |

稳定性：全量连续 10 次运行 0 失败（此前存在的跨测试污染已定位并修复，见 §6）。

---

## 5. 主动不实现的项

**staging 短路径别名**（.NET 会把素材别名/复制为 staging 短名以压命令行长度）。

量化依据：Python 侧滤镜图早已外置为 `concat.filter` sidecar，命令行只承载参数本身。实测 80 个「10 层中文目录 + 长文件名」素材：

| 片段数 | argv 项数 | 估算命令行 | 滤镜脚本 |
|--------|-----------|------------|----------|
| 10 | 70 | 902 字符 | 3,149 字符 |
| 40 | 190 | 2,582 字符 | 12,629 字符 |
| 80 | 350 | 4,822 字符 | 25,269 字符 |

命令行要到约 500 个片段才会接近 Windows 32767 上限。别名化需额外承担同步、磁盘占用与清理风险，收益与风险不成比例。改为「预算守卫 + 可操作提示」。

---

## 6. 过程中发现并修复的真实缺陷

| # | 缺陷 | 影响 | 修复 |
|---|------|------|------|
| 1 | 直拷路径也做编码器/GPU 探测 | 纯 concat 任务多发起设备探测子进程 | 抽 `_resolve_processing`，只在转码路径调用 |
| 2 | 测试把 `subprocess.Popen` 全局打桩，而探测用同一 subprocess 模块对象 | 伪装成「偶发失败」（2/10） | 断言按命令特征筛选；回退用例注入软件处理计划 |
| 3 | ffmpeg 表达式的 `max()` **只接受两个参数** | 圆角矩形真机 `-22 Invalid argument`，完全无法渲染 | 改为嵌套两参；用真机验证 |
| 4 | 冻结后 `__file__` 指向解包目录 | 便携包找不到任何 runtime | 新增 `app_paths.py`，冻结时优先 exe 目录 |
| 5 | 冻结后仍上溯源码布局 | 命中打包机仓库 runtime，出现「缺组件却显示就绪」并暴露打包机绝对路径 | 冻结时不再上溯 |
| 6 | 窗口模式 stdout 不可靠 | 打包产物自检拿不到任何输出 | 新增 `--report-file`，报告写文件 |
| 7 | PS 5.1 把原生命令 stderr 当 terminating error | PyInstaller「构建成功却退出码 1」 | 原生命令统一走 `Invoke-NativeQuiet` |
| 8 | 窗口子系统程序不被可靠等待 | 报告文件未写完即被读取 | 改 `Start-Process -Wait`，并绕开 `NO_PROXY` 重复键 |

---

## 7. 已知限制

- **未做代码签名**：首次运行可能有 SmartScreen 提示，属预期行为。
- **Tesseract 未随包**：仓库 `runtime/tesseract/tesseract.exe` 是 1 字节占位文件，构建脚本会剔除并如实报缺失；需要 OCR 时放入真实可执行文件。
- **仅 Windows x64**：spec 与构建脚本都是 Windows 形态；跨平台交付需另立脚本。
- **形状/PNG 遮罩无编辑 UI**：与 .NET「二期」定位一致；领域、滤镜、持久化与校验已就位，合成预览会自动复用真实滤镜。
- **未接入 `Verify-Release.ps1`**：该脚本目前只校验 .NET 版产物。
- **两处刻意保留的 .NET 语义差异**：椭圆为内切圆（与 .NET 一致，非真椭圆）；圆角矩形改用修正几何（见 §3.2）。

---

## 8. 复现命令

```powershell
# 单元测试
cd src/JingXu.Workbench.Py
python -m pytest

# 真机集成测试（需 FFmpeg 在 PATH 或 runtime/ffmpeg/）
$env:PATH = "$PWD\..\..\runtime\ffmpeg;$env:PATH"
python -m pytest -m integration

# 打包便携包
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Portable-Py.ps1

# 打包产物自检
.\artifacts\py-build\炳恒快速混剪\炳恒快速混剪.exe --self-test --report-file .\selftest.json
```
