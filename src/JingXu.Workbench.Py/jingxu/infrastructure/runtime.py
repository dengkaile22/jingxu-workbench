"""FFmpeg / FFprobe 定位：环境变量 → 应用目录 runtime/ffmpeg → 系统 PATH。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

RUNTIME_ENV = "JINGXU_RUNTIME_DIR"
_SEARCH_DEPTH = 8


class ToolNotFoundError(FileNotFoundError):
    """未找到运行时工具。"""


def _executable_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _search_roots() -> list[Path]:
    """按包位置向上查找的候选根目录（可被测试替换）。"""
    here = Path(__file__).resolve()
    return list(here.parents)[:_SEARCH_DEPTH]


def _runtime_candidates(name: str) -> list[Path]:
    executable = _executable_name(name)
    candidates: list[Path] = []

    configured = os.environ.get(RUNTIME_ENV, "").strip()
    if configured:
        root = Path(configured).expanduser()
        candidates.extend([root / "ffmpeg" / executable, root / executable])

    for parent in _search_roots():
        candidates.append(parent / "runtime" / "ffmpeg" / executable)

    return candidates


def find_tool(name: str) -> Path | None:
    """返回工具绝对路径；找不到时返回 ``None``。"""
    for candidate in _runtime_candidates(name):
        if candidate.is_file():
            return candidate

    on_path = shutil.which(name)
    return Path(on_path) if on_path else None


def require_tool(name: str) -> Path:
    """定位工具，缺失时抛出带中文提示的异常。"""
    tool = find_tool(name)
    if tool is None:
        raise ToolNotFoundError(
            f"未找到 {name}。请将 FFmpeg 放入应用目录 runtime/ffmpeg/，"
            f"设置环境变量 {RUNTIME_ENV}，或加入系统 PATH。"
        )
    return tool
