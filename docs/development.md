# 开发指南

## 文档目的

给出可复现的本地开发方式。**本仓库技术栈为 Python（PySide6 + FFmpeg）**；
原 .NET/WPF 实现与相关脚本已于 2026-09-23 移除（git 标签 `last-dotnet-reference`）。

## 环境要求

- Windows 10/11 x64（主交付平台；代码结构兼容 macOS/Linux，打包脚本仅 Windows）
- Python 3.12+（源码运行）；目标机器无需安装 Python（自包含发布）
- FFmpeg/FFprobe（`PATH` 或 `runtime/ffmpeg/`）用于媒体集成测试
- 可选：Whisper.cpp、Tesseract（字幕实验室）

## 常用命令

验证缓存清理和素材库操作时，先为当前 PowerShell 会话配置独立目录，避免测试访问日常数据：

```powershell
$env:JINGXU_DATA_DIRECTORY = Join-Path $PWD 'artifacts\test-data'
$env:JINGXU_TEMP_DIRECTORY = Join-Path $PWD 'artifacts\test-temp'
$env:PATH = "$PWD\runtime\ffmpeg;$env:PATH"
```

未设置这些变量时，应用仍使用 `%LOCALAPPDATA%\JingXu` 与系统临时目录。

```powershell
cd src/JingXu.Workbench.Py

# 单元测试（默认；真机集成用 -m integration）
python -m pytest

# 启动界面（开发）
python -m jingxu

# 无界面自检 / 冒烟（进程结束后退出）
python -m jingxu --self-test
python -m jingxu --import-smoke
python -m jingxu --overlay-smoke

# 代码检查
python -m ruff check .
```

入口代码：`src/JingXu.Workbench.Py/jingxu/__main__.py`（壳层 `ui/shell_window.py`）。

## 编码标准

- 分层与 .NET 时期一致：领域规则进 `domain/`，编排进 `application/`，外部进程与文件进 `infrastructure/`，界面进 `ui/`
- 长操作不得阻塞 UI 线程；外部进程用参数列表传递，不拼接 shell 字符串
- 新行为先写失败测试，再实现（红—绿—重构）
- 以验收标准为检查表；界面开关必须有消费点与自动化断言（不留「能点但不变」的控件）

## 运行时开发

1. 将第三方二进制放入 `runtime/`（不提交 Git，见 `runtime/README.md`）
2. `scripts/Resolve-Runtimes.ps1 -CacheDirectory runtime -PrintHashes` 生成 SHA-256
3. 更新 `build/runtime-manifest.json` 后随打包脚本暂存
4. 选品爬虫内置运行时：`scripts/Resolve-SpiderRuntime.ps1`（下载嵌入式 Python + `src/JingXu.Workbench.Py/JingXu.Spider/requirements.txt` 依赖到 `runtime/python`）。国内网络可加 `-PipIndexUrl https://pypi.tuna.tsinghua.edu.cn/simple`；重建用 `-Force`。

## 项目结构（实际）

```text
src/
  JingXu.Workbench.Py/            # 主实现（PySide6 + FFmpeg）
    jingxu/
      ui/                         # 各功能页面、预览画布、主题与品牌资源
      application/                # 编排服务、渲染队列、下载
      domain/                     # 纯领域：图层、渲染计划、字幕、确定性随机
      infrastructure/             # FFmpeg 命令编译/执行、探测、持久化、诊断
    JingXu.Spider/                # 选品爬虫（主程序内嵌引擎，CLI 子进程驱动）
    tests/                        # pytest 单元 + 真机集成（-m integration）
scripts/                          # 构建与发布（PowerShell）
build/                            # runtime-manifest、WiX（Installer-Py）
docs/                             # 设计 + 现状索引见 docs/README.md
```

## 待对齐项

- 更细的功能完成度见 [docs/README.md](README.md) 中「开发现状与对齐」。

