"""数据目录与输出命名规则。"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from jingxu.domain.media import MediaAsset

DATA_ENV = "JINGXU_DATA_DIRECTORY"
TEMP_ENV = "JINGXU_TEMP_DIRECTORY"
OUTPUT_FOLDER_NAME = "分镜输出"
DEFAULT_PREFIX = "混剪成片"
_MAX_INDEX = 999
_BATCH_SUFFIX = re.compile(r"_\d{3}$")
_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def data_directory() -> Path:
    """应用数据目录（配置/日志），不写入安装目录。"""
    configured = os.environ.get(DATA_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")

    return base / "JingXu"


def temp_directory() -> Path:
    """工作临时目录；可用 JINGXU_TEMP_DIRECTORY 覆盖。"""
    configured = os.environ.get(TEMP_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    import tempfile

    return Path(tempfile.gettempdir())


def default_output_directory(assets: Sequence[MediaAsset]) -> Path:
    """单一源文件夹输出到源目录下的「分镜输出」；多来源输出到项目数据目录。"""
    parents: dict[str, Path] = {}
    for asset in assets:
        parent = asset.path.parent
        if not parent:
            continue
        try:
            key = str(parent.resolve()).casefold()
        except OSError:
            key = str(parent).casefold()
        parents.setdefault(key, parent)

    if len(parents) == 1:
        return next(iter(parents.values())) / OUTPUT_FOLDER_NAME

    return data_directory() / OUTPUT_FOLDER_NAME


def sanitize_file_name_prefix(name: str) -> str:
    """清理文件名前缀：非法字符替换为下划线，空值回退默认名。"""
    cleaned = _INVALID_NAME_CHARS.sub("_", name or "")
    cleaned = cleaned.strip().strip(".")
    return cleaned or DEFAULT_PREFIX


def allocate_unique_path(
    directory: Path,
    base_file_name: str,
    *,
    reserved_paths: Iterable[Path] = (),
) -> Path:
    """为输出文件分配不冲突的路径，避开已存在文件与预约路径（队列在途任务）。

    同名文件自动追加三位序号（001–999），超过上限抛出异常。
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    reserved = set()
    for item in reserved_paths:
        try:
            reserved.add(str(Path(item).resolve()).casefold())
        except OSError:
            reserved.add(str(item).casefold())

    def _available(candidate: Path) -> bool:
        if candidate.exists():
            return False
        try:
            key = str(candidate.resolve()).casefold()
        except OSError:
            key = str(candidate).casefold()
        return key not in reserved

    candidate = directory / base_file_name
    if _available(candidate):
        return candidate

    stem = Path(base_file_name).stem
    suffix = Path(base_file_name).suffix
    base_stem = _BATCH_SUFFIX.sub("", stem)
    for index in range(1, _MAX_INDEX + 1):
        candidate = directory / f"{base_stem}_{index:03d}{suffix}"
        if _available(candidate):
            return candidate

    raise FileExistsError(f"无法在目录 {directory} 中为 {base_file_name} 分配唯一文件名。")


def unique_output_path(
    directory: Path,
    stem: str,
    suffix: str = ".mp4",
    *,
    reserved_paths: Iterable[Path] = (),
) -> Path:
    """同名文件自动追加三位序号，不静默覆盖。"""
    return allocate_unique_path(
        directory,
        f"{sanitize_file_name_prefix(stem)}{suffix}",
        reserved_paths=reserved_paths,
    )


def default_output_stem(now: datetime | None = None) -> str:
    moment = now or datetime.now()
    return f"混剪_{moment.strftime('%Y%m%d_%H%M%S')}"
