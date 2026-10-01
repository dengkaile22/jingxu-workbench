"""应用路径解析：区分源码运行与 PyInstaller 冻结运行。

打包后 ``__file__`` 指向 PyInstaller 的解包目录（``sys._MEIPASS``），而随包
的 ``runtime/``（FFmpeg/Whisper/Tesseract/爬虫）放在**可执行文件同级**目录，
因此必须按「可执行文件所在目录」优先解析，否则冻结后会找不到任何运行时。

解析顺序（对齐 .NET 的「应用目录 runtime/ → 用户目录 → PATH」第一层）：

1. 冻结运行时：``sys.executable`` 所在目录（含其向上若干级，便于开发布局）；
2. 源码运行时：包目录向上若干级（覆盖 ``core/`` 与仓库根）；
3. PyInstaller 解包目录（``sys._MEIPASS``）——仅用于随包内置的清单等少量资源。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 向上查找层数：覆盖「便携包根/runtime」与「仓库根/runtime」两种布局。
SEARCH_DEPTH = 8
# 实测索引（jingxu/infrastructure/app_paths.py 的 parents）：
#   [0] infrastructure  [1] jingxu  [2] core  [3] 仓库根（含 pyproject.toml）
_PACKAGE_TO_ROOT = 3
_PROJECT_PARENT_INDEX = 3


def is_frozen() -> bool:
    """是否运行在 PyInstaller 等冻结环境中。"""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """应用根目录：冻结时为可执行文件所在目录，否则为仓库根目录。

    ``runtime/`` 在两种情况下都位于本函数返回目录的下一级（开发机为
    ``<repo>/runtime``），因此运行时解析逻辑无需区分模式。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[_PACKAGE_TO_ROOT]


def package_root() -> Path:
    """Python 项目目录（含 ``pyproject.toml``）；冻结时等同于 :func:`app_root`。"""
    if is_frozen():
        return app_root()
    return Path(__file__).resolve().parents[_PROJECT_PARENT_INDEX]


def search_roots() -> list[Path]:
    """返回按优先级去重后的候选根目录列表。

    **冻结运行时只使用可执行文件所在目录（及其上一级）与解包目录**，不再上溯
    到源码布局的父目录——否则打包机上的仓库 ``runtime/`` 会被误命中，
    造成「便携包缺组件却显示就绪」以及依赖打包机路径的假象。

    源码运行时才向上扫描包目录的各级父目录，以覆盖
    ``core/`` 与仓库根两种布局。
    """
    roots: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            roots.append(path)

    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        _add(exe_dir)
        # 允许「<包根>/app/xxx.exe」这种把 exe 放进子目录的便携布局。
        if exe_dir.parent != exe_dir:
            _add(exe_dir.parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            _add(Path(meipass))
        return roots

    for parent in list(Path(__file__).resolve().parents)[:SEARCH_DEPTH]:
        _add(parent)

    return roots
