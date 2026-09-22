# 炳恒快速混剪 · Python 版（JingXu.Workbench.Py）

Windows / macOS / Linux 桌面版：PySide6 + 系统 FFmpeg。本目录是整个应用的
**唯一实现**（.NET 版源码保留在 `src/JingXu.Workbench.*` 仅作迁移参照）。

## 运行

```bash
cd src/JingXu.Workbench.Py
python -m pip install -e ".[download]"   # 安装依赖（PySide6 + yt-dlp 下载引擎）
python -m jingxu                         # 启动图形界面
python -m jingxu --self-test             # 无界面自检（JSON 报告，退出码 0/1）
python -m jingxu --import-check          # 检查运行期动态导入的组件（扫码登录能否用）
python -m jingxu --ui-probe              # 启动主窗口并测量关键控件几何（UI 回归用）
python -m jingxu --import-smoke a.mp4    # 探测素材并输出 JSON 报告
python -m jingxu --overlay-smoke mask.mp4 --overlay-preset free   # 蒙版合成静帧冒烟
```

`--import-check` 与 `--ui-probe` 在发布流程里是**必需环节**：

- 「扫码登录」由应用进程内 `import DrissionPage` 完成，PyInstaller 静态分析看不到，
  缺收集时只在用户点按钮那一刻报 `No module named`；`Build-Portable-Py.ps1`
  已把它接成构建门禁，不通过即终止构建。
- 图层预览画布的尺寸问题只在**真实布局**里暴露（单独渲染控件或只跑源码都测不到），
  `--ui-probe` 把画布实际绘制尺寸变成可断言的 JSON 报告（当前 216×384，对齐 .NET 版）。

FFmpeg/FFprobe 解析顺序：`JINGXU_RUNTIME_DIR` → 仓库/安装目录 `runtime/ffmpeg/` → 系统 `PATH`。
运行时清单（`build/runtime-manifest.json`）在设置页与自检中做结构与哈希校验；
`JINGXU_SKIP_HASH_VERIFY=1` 可跳过哈希核验（开发构建）。

**可选组件**

| 功能 | 依赖 | 安装方式 |
|------|------|----------|
| 批量下载（抖音/快手/B站） | yt-dlp | `pip install yt-dlp`；`JINGXU_YTDLP_COOKIES` 指向 cookies.txt 可下载登录内容 |
| 字幕离线识别 | `runtime/whisper/whisper-cli.exe` + `models/ggml-base.bin` | 下载 whisper.cpp 发布包与 base 模型放入 `runtime/whisper/` |
| 字幕 OCR 自动定位 | `runtime/tesseract/tesseract.exe`（含 chi_sim 语言包） | 放入 `runtime/tesseract/` |
| 选品爬虫 | `pip install -e ".[spider]"` | DrissionPage + openpyxl |

## 测试

```bash
python -m pytest                     # 单元测试（约 360 项）
python -m pytest -m integration      # 真机渲染（需要 FFmpeg）
```

## 与 .NET 版的功能对照

图例：✅ 同功能 · 🟡 已实现但交互略简化 · ➕ Python 版增强 · ⏳ 未迁移

**壳层与队列**

| 能力 | 状态 | 说明 |
|------|------|------|
| 标题栏 / 模块栏 / 素材栏 / 取景井 / 检查器 / 底部队列条 | ✅ | 包含最大化内边距补偿与入场动画 |
| 任务队列状态机 | ✅ | Draft→Queued→Preparing→Running→Finalizing→Completed/Failed/Cancelled，非法迁移抛错 |
| 取消 / 重试 / 清理 / 暂停调度 / 并发 1–4 | ✅ | 取消走进程树终止（Windows Job Object / POSIX 进程组） |
| 四屏大画幅独占调度（≥1280×720） | ✅ | 独占任务等待其他任务结束，其余任务不再并行 |
| 任务快照只读 | ✅ | UI 读取到不可变快照，避免渲染线程改写 |
| 进度节流（≥1% 或 ≥500ms） | ✅ | 队列层节流，避免 UI 洪泛 |
| 失败任务日志归档 | ✅ | `<输出目录>/.jingxu-logs/<任务ID>/`（render.log / filter.filter / ffmpeg-stderr.log），7 天与 64 MiB 保留策略，当前任务保留 |

**混剪编排**

| 能力 | 状态 | 说明 |
|------|------|------|
| 素材导入与文件名序号 | ✅ | 最后一个数字段为序号；纯 16 位以上十六进制哈希名不取号；重复序号在列表与预览中提示 |
| 随机批量 / 自定义序号 | ✅ | SplitMix64 确定性随机（与 .NET 同算法）、排列去重、批量差异化 |
| 自定义序号多任务 | ✅ | 换行/分号分隔多条表达式，各自产出一条成片；允许重复序号 |
| 序号命名模板 | ✅ | `sequence-templates.json`，保存/应用/重命名/删除 |
| 编排预览 | ✅ | 计划卡（序号链 + 时长、转场扣减）与入队前校验 |
| 输出质量档 | ✅ | 无损/高(CRF18+AAC192)/平衡(22/160)/小体积(27/128)/快速(26/128) |
| 输出目录与命名 | ✅ | 单源 `<源目录>\分镜输出`；多来源数据目录；前缀清洗、三位序号、999 上限、避开在途路径 |
| 导出兼容性 | ✅ | 分辨率按短边缩放（原画/1080/720/480，偶数对齐）、帧率（原帧率/24/25/30/50/60） |
| 处理器与硬件编码 | ✅ | 自动/CPU/GPU；NVENC/QSV/AMF/VideoToolbox/MF 真实探测；`-hwaccel auto` 硬解 + 失败回退软件解码 |
| 统一比例 | ✅ | 启用开关 + 继承首段/9:16/16:9/1:1/3:4/自定义；拼接适配 居中裁切/黑边/拉伸/模糊背景；蒙版适配 4 种（3:4 自动推荐先裁成画幅再覆盖）；实时描述 |
| 蒙版覆盖 | ✅ | 启用开关、图层计数、每条成片随机替换 1 个库蒙版（从**蒙版素材库**按固定种子+全局序号确定性抽取，只换素材不动画法）、打开蒙版模块 |
| 效果预览 | ✅ | 混剪页按当前画幅与已启用图层，用真实滤镜链渲染一张叠层静帧（对齐 .NET 同名区块，不用缩略图冒充合成结果） |
| 效果模板 | ✅ | 保存/应用/重命名/删除 |
| 效果与音频 | ✅ | 差异化（镜像±、旋转 ±15°、轻裁切、调色、降噪、强度 1–200%）/ 左右双屏 / 上下双屏 / 四屏（独立起点、随机文件夹、羽化 0–256）/ 原声音量 |
| 拼接主素材增强 | ✅ | 音量/缩放 100%–110%，固定或随机区间，音量先 loudnorm 再增益 |
| 音频库与 BGM | ✅ | 音频库随机抽取（确定性随机袋+跳过失效文件）、固定/随机音量；单文件 BGM 优先 |
| 封面 | ✅ | 首段首帧 / 成片尾帧 / 指定时间点，失败清理半成品 |
| 交叉转场 | ➕ | xfade/acrossfade 与时长校验（.NET 仅计划层字段） |
| 项目保存/打开（`.jxproj`） | ➕ | 版本化 JSON、原子写入、高版本只读、标题栏脏标记 |

**渲染管线**

| 能力 | 状态 | 说明 |
|------|------|------|
| 滤镜图（画幅、分屏、图层、音频、concat） | ✅ | 每个视频输入 `-threads 2`；滤镜脚本走 sidecar 文件避免命令行超限 |
| 双屏/四屏滤镜（.NET 语义） | ✅ | 内联灰度渐变蒙版 + `alphamerge=eof_action=repeat`，同源同尺寸只缩放一次 |
| 图层叠加 | ✅ | 适配 4 种、上向淡入、底边羽化（gblur ≤8）、源裁剪（自动/手选）、**尺寸缩放（1%–400%，对齐 .NET `Scale`）**、旋转、黑底抠除、自叠影、Z 序、音轨混入 |
| 音频 | ✅ | `aformat`+`aresample`、逐片段 `atrim`、loudnorm、BGM `aloop=-1`+淡出 |
| 字幕烧录 / 硬字幕去除 | ✅ | ASS 走 `ass=`；去除支持 模糊(gblur=12)/去标(delogo)/遮盖/裁切重构（须贴顶或贴底） |
| 磁盘预算 | ✅ | 渲染前按输出卷检查（含跨进程预留与 25% 余量），不足时先回收缓存再复查 |
| 失败诊断 | ✅ | 见上「失败任务日志归档」 |

**其它模块**

| 模块 | 状态 | 说明 |
|------|------|------|
| 蒙版模板 | ✅ | 透明度语义对齐 .NET（0=不透明）/上向淡入/羽化/分割位置/来源裁剪/适配选择/起始片段/画中画与横幅预设/统一尺寸与起点；预览区对齐 .NET「蒙版区域预览」：左为成片画面示意（216×384，暗红框＝默认上半叠区 `ImportedMaskBounds(0.05,0.05,0.90,0.42)`，蓝框＝输出位置与尺寸，可拖中心平移、拖边角改大小），右为独立的「源素材取景」白框画布（同样可拖拽）；导入默认值对齐 .NET 叠影预设（28% 不透明 + 中间→上渐变 + 羽化 28%） |
| 贴纸轨道 | ✅ | 同一套叠加引擎；旋转、拖拽、滚轮缩放 |
| 字幕实验室 | ✅ | SRT/ASS 导入导出、时间轴校验（重叠/空文本/倒序）、OCR 复核门禁（确认全部区域）、Whisper/OCR 离线识别 |
| 音频库 | ✅ | 导入/移除/清空/持久化 |
| 批量下载 | ✅ | yt-dlp 引擎、进度/取消/发送到素材、文件名行内编辑、续传与分片并发 |
| 选品爬虫 | 🟡 | 内嵌爬虫组件可用；结果表对齐 .NET 八列（含「对标账号明细」与「示例视频链接」），并支持勾选后一键送入下载 |

## 随包 FFmpeg 的选择（体积相关）

随包使用 gyan.dev 的 **essentials** 构建而非 full：

| | 二进制合计 | 说明 |
|---|---|---|
| full_build | 433.6 MB | 额外含 bluray / libsrt / libzmq / avisynth / libcaca / frei0r / vmaf / libplacebo / opencl / libjxl 等 |
| **essentials_build** | **194.2 MB** | 本产品用到的全部滤镜、编码器与解复用器都在 |

切换前逐项核验过 essentials 不缺口：

* 滤镜 51 个全在（`ass`/`subtitles`/`delogo`/`boxblur`/`gblur`/`cropdetect`/`xstack`/
  `xfade`/`acrossfade`/`colorkey`/`blend`/`loudnorm` 等，含字幕烧录依赖的
  libass + freetype + fribidi + harfbuzz）；
* 编码器全在（`libx264`、`aac`、`nvenc`/`qsv`/`amf` 的 h264 与 hevc）；
* 解复用器全在（mp4/mov、matroska、avi、flv、mpegts、hls、image2、mp3、wav）；
* 旧构建含而 essentials 不含的 `libdvdread`/`libdvdnav`/`libzvbi` 本产品不使用。

切换后 15 项真机集成测试全部通过（同一批断言，含字幕烧录、硬字幕去除、
四屏羽化、蒙版合成）。

维护工具：`tools/verify_runtime_manifest.py` 核对清单哈希与实际文件是否一致，
`tools/update_runtime_manifest.py` 在替换二进制后同步哈希与来源地址。

| 设置 | ✅ | 运行时清单逐组件诊断表、编码器状态、并发、维护清理（保护运行中任务与字幕/缩略图）、关于 |
| 启动维护 | ✅ | 后台孤儿清理（临时目录、过期半成品、下载残片）；崩溃日志写入 `<数据目录>/logs/crash-YYYYMMDD.log` |

**已知差异（相对 .NET）**

- 蒙版形状/PNG 遮罩：领域、滤镜、持久化与校验已与 .NET 对齐（含椭圆/圆角矩形/PNG 三档遮罩模式）；尚无形状编辑 UI，与 .NET「二期」定位一致。
- 圆角矩形几何未沿用 .NET 字面实现：.NET 的 `min(X,r)+min(W-X,r)-r` 写法在距边 r 的整条边带内恒为 r，会整体擦除四条边带、角部反而保留，几何上不是圆角。本版改用标准的「到圆角矩形边界距离」写法；若需与 .NET 逐像素一致需改为字面移植。
- 椭圆按 .NET 语义实现为**边界框内切圆**（半径 `min(W,H)/2`），非方框时只覆盖中间一块，不是真椭圆。
- 路径别名（staging 短路径）：Python 不复制/别名素材。量化依据——滤镜图已外置为 `concat.filter` sidecar，命令行只承载参数本身；实测 80 个「10 层中文目录 + 长文件名」素材的命令行约 4.8K 字符，远低于 Windows 32767 上限，因此不引入别名化的同步与清理风险。改为在超限前给出中文建议（上限 30000，对齐 .NET `RenderPreflight.MaxCommandLineLength`）。
- GPU 缩放（scale_qsv/scale_cuda）：已实现并与 .NET 语义对齐（白名单、Auto/GPU 双门槛、设备参数、hwdownload 回传、AwayFromZero 舍入、三级回退），循环输入一律不用硬解。
- 贴纸独立画幅与固定比例：已实现（预览画幅模式 + 宽高比锁定联动），与 .NET `StickerAspectMode` / `FixedAspectRatio` 对齐。
- 音频库音量单位：已对齐 .NET（−100..+100，0 = 默认 BGM 音量 0.18）；旧项目/模板中的音量按增益反算迁移，听感不变。

## 目录结构

```text
src/JingXu.Workbench.Py/
├── pyproject.toml
├── jingxu/
│   ├── domain/           # 素材、编排、确定性随机、效果计划、渲染/画幅/质量模型、图层、字幕
│   ├── application/      # 编排服务（批量/多任务/物化）、无损直拷判定、冒烟命令
│   ├── infrastructure/   # FFmpeg 渲染、滤镜图、进程树守卫、队列、诊断归档、磁盘预算、
│   │                     # 运行时清单、清理、下载、音频库、图层/字幕/模板/项目存储
│   └── ui/               # 主题、控件、壳层、编排页、图层页、字幕页、队列页、设置页
└── tests/                # ~360 项单元测试 + 真机渲染集成测试
```
