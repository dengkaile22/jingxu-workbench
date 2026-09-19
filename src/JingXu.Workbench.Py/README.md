# 炳恒快速混剪 · Python 版（JingXu.Workbench.Py）

Windows / macOS / Linux 桌面版：PySide6 + 系统 FFmpeg。本目录是整个应用的
**唯一实现**（.NET 版源码保留在 `src/JingXu.Workbench.*` 仅作迁移参照）。

## 运行

```bash
cd src/JingXu.Workbench.Py
python -m pip install -e ".[download]"   # 安装依赖（PySide6 + yt-dlp 下载引擎）
python -m jingxu                         # 启动图形界面
python -m jingxu --self-test             # 无界面自检（JSON 报告，退出码 0/1）
python -m jingxu --import-smoke a.mp4    # 探测素材并输出 JSON 报告
python -m jingxu --overlay-smoke mask.mp4 --overlay-preset free   # 蒙版合成静帧冒烟
```

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
| 蒙版覆盖 | ✅ | 启用开关、图层计数、每条成片随机替换 1 个库蒙版（预留）、打开蒙版模块 |
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
| 图层叠加 | ✅ | 适配 4 种、上向淡入、底边羽化（gblur ≤8）、源裁剪（自动/手选）、旋转、黑底抠除、自叠影、Z 序、音轨混入 |
| 音频 | ✅ | `aformat`+`aresample`、逐片段 `atrim`、loudnorm、BGM `aloop=-1`+淡出 |
| 字幕烧录 / 硬字幕去除 | ✅ | ASS 走 `ass=`；去除支持 模糊(gblur=12)/去标(delogo)/遮盖/裁切重构（须贴顶或贴底） |
| 磁盘预算 | ✅ | 渲染前按输出卷检查（含跨进程预留与 25% 余量），不足时先回收缓存再复查 |
| 失败诊断 | ✅ | 见上「失败任务日志归档」 |

**其它模块**

| 模块 | 状态 | 说明 |
|------|------|------|
| 蒙版模板 | ✅ | 透明度语义对齐 .NET（0=不透明）/上向淡入/羽化/分割位置/来源裁剪/适配选择/起始片段/画中画与横幅预设/统一尺寸与起点 |
| 贴纸轨道 | ✅ | 同一套叠加引擎；旋转、拖拽、滚轮缩放 |
| 字幕实验室 | ✅ | SRT/ASS 导入导出、时间轴校验（重叠/空文本/倒序）、OCR 复核门禁（确认全部区域）、Whisper/OCR 离线识别 |
| 音频库 | ✅ | 导入/移除/清空/持久化 |
| 批量下载 | ✅ | yt-dlp 引擎、进度/取消/发送到素材、文件名行内编辑、续传与分片并发 |
| 选品爬虫 | 🟡 | 内嵌爬虫组件可用；结果一键送入下载/混剪尚未接线 |
| 设置 | ✅ | 运行时清单逐组件诊断表、编码器状态、并发、维护清理（保护运行中任务与字幕/缩略图）、关于 |
| 启动维护 | ✅ | 后台孤儿清理（临时目录、过期半成品、下载残片）；崩溃日志写入 `<数据目录>/logs/crash-YYYYMMDD.log` |

**已知差异（相对 .NET）**

- 蒙版形状/PNG 遮罩：.NET 仅领域与渲染保留、无编辑 UI；Python 暂未实现该路径。
- 路径别名（staging 短路径）：Python 直接把绝对路径交给 FFmpeg；滤镜文本走 sidecar 文件，实测未触及 Windows 命令行长度上限。
- GPU 缩放（scale_cuda/scale_qsv）：Python 使用 `-hwaccel auto` 硬件解码，缩放仍在软件侧完成（蒙版/合成同样在 CPU）。
- 贴纸独立画幅选择器与固定比例：Python 使用全局成片画幅。
- 音频库音量单位：Python 用 0–200%（.NET 为 −100..+100 的增益映射）。
- 队列持久化：跨重启的任务历史沿用项目文档 `recent_jobs`（.NET 队列为纯内存，无持久化）。

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
