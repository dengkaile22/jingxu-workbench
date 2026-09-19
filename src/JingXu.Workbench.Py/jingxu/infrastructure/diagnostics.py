"""运行时诊断与临时文件清理（设置页数据源）。"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jingxu.domain.render import ProcessingMode
from jingxu.infrastructure.encoders import EncoderRegistry
from jingxu.infrastructure.ffmpeg_runner import PART_SUFFIX
from jingxu.infrastructure.paths import data_directory, temp_directory

TEMP_PREFIX = "jingxu-py-"
OCR_SESSION_PREFIX = "jingxu-ocr-"
FEATHER_PREFIX = "jingxu-feather-"
FEATHER_SUFFIX = ".png"
KNOWN_TEMP_DIRECTORIES = (
    "jingxu-whisper",
    "jingxu-ocr",
    "jingxu-subtitle-burn",
    "jingxu-gate-preview",
    "jingxu-download",
)
MIN_OPTIONAL_TOOL_BYTES = 64 * 1024
LOG_DIRECTORY_NAME = "logs"
THUMBNAIL_DIRECTORY_NAME = "overlay-thumbs"
DOWNLOAD_PART_SECONDS = 3600.0

_crash_log_lock = threading.Lock()


def runtime_tesseract() -> Path | None:
    """定位真实的 Tesseract（忽略发布流水线的占位文件）。"""
    import jingxu.infrastructure.runtime as runtime_module

    executable = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    for root in runtime_module._search_roots():  # noqa: SLF001
        candidate = root / "runtime" / "tesseract" / executable
        try:
            if candidate.is_file() and candidate.stat().st_size >= MIN_OPTIONAL_TOOL_BYTES:
                return candidate
        except OSError:
            continue

    on_path = shutil.which("tesseract")
    return Path(on_path) if on_path else None


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    ffmpeg_path: str
    ffmpeg_version: str
    ffprobe_path: str
    ffprobe_version: str
    available_encoders: list[str] = field(default_factory=list)
    resolved_encoders: dict[str, str] = field(default_factory=dict)
    python_version: str = ""
    platform_text: str = ""
    data_directory: str = ""


def _tool_version(executable: Path) -> str:
    try:
        completed = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "未知"
    first_line = (completed.stdout or completed.stderr or "").strip().splitlines()
    return first_line[0] if first_line else "未知"


def collect_runtime_info(ffmpeg: Path, ffprobe: Path, registry: EncoderRegistry) -> RuntimeInfo:
    """收集 FFmpeg/编码器/平台信息（编码器探针首次调用会真实试编码）。"""
    resolved: dict[str, str] = {}
    for mode in (ProcessingMode.AUTO, ProcessingMode.CPU, ProcessingMode.GPU):
        choice = registry.resolve(mode)
        resolved[mode.display_text] = f"{choice.label}（{registry.note(mode)}）"

    return RuntimeInfo(
        ffmpeg_path=str(ffmpeg),
        ffmpeg_version=_tool_version(ffmpeg),
        ffprobe_path=str(ffprobe),
        ffprobe_version=_tool_version(ffprobe),
        available_encoders=registry.available_names(),
        resolved_encoders=resolved,
        python_version=f"{sys.version.split()[0]}（{platform.machine()}）",
        platform_text=f"{platform.system()} {platform.release()}",
        data_directory=str(data_directory()),
    )


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """工作区清理结果：删除数量、释放字节数、因保护跳过数量。"""

    deleted: int
    freed_bytes: int
    skipped: int


def _resolve_path_set(paths: Sequence[Path]) -> set[str]:
    """把保护路径解析为规范化绝对字符串集合（大小写不敏感）。"""
    resolved: set[str] = set()
    for path in paths:
        try:
            resolved.add(os.path.normcase(str(Path(path).resolve())))
        except OSError:
            continue
    return resolved


def _is_protected(path: Path, protected: set[str]) -> bool:
    """待删项自身或其父目录在保护集内时返回 True。"""
    if not protected:
        return False
    try:
        resolved = path.resolve()
    except OSError:
        return True
    return (
        os.path.normcase(str(resolved)) in protected
        or os.path.normcase(str(resolved.parent)) in protected
    )


def _is_temp_candidate(entry: Path) -> bool:
    """只认本软件可验证的顶层临时项，绝不扫描整个 Temp 的任意 jingxu-*。"""
    name = entry.name
    if name.startswith(TEMP_PREFIX):
        return True
    if name.startswith(OCR_SESSION_PREFIX):
        return True
    if name.startswith(FEATHER_PREFIX) and name.endswith(FEATHER_SUFFIX):
        return True
    return name in KNOWN_TEMP_DIRECTORIES


def _entry_size(entry: Path) -> int:
    try:
        if entry.is_dir():
            return sum(file.stat().st_size for file in entry.rglob("*") if file.is_file())
        return entry.stat().st_size
    except OSError:
        return 0


def _cleanup_temp_entries(
    root: Path,
    protected: set[str],
    min_age_seconds: float = 0.0,
) -> tuple[int, int, int]:
    """删除已知前缀的顶层项，返回（删除数量，释放字节数，保护跳过数量）。

    ``min_age_seconds`` 用于启动清理：跳过刚创建的活动临时目录，
    避免误删并存实例正在使用的文件。
    """
    deleted = 0
    freed = 0
    skipped = 0
    if not root.is_dir():
        return deleted, freed, skipped
    try:
        entries = list(root.iterdir())
    except OSError:
        return deleted, freed, skipped

    now = time.time()
    for entry in entries:
        if not _is_temp_candidate(entry):
            continue
        if _is_protected(entry, protected):
            skipped += 1
            continue
        if min_age_seconds > 0:
            try:
                if now - entry.stat().st_mtime < min_age_seconds:
                    skipped += 1
                    continue
            except OSError:
                continue
        try:
            if entry.is_dir():
                freed += _entry_size(entry)
                shutil.rmtree(entry, ignore_errors=True)
            else:
                freed += entry.stat().st_size
                entry.unlink(missing_ok=True)
            deleted += 1
        except OSError:
            continue
    return deleted, freed, skipped


def cleanup_temp_files(
    temp_directory: Path | None = None,
    *,
    protected_paths: Sequence[Path] = (),
) -> tuple[int, int]:
    """清理本软件产生的临时目录/文件，返回（删除数量，释放字节数）。"""
    root = Path(temp_directory) if temp_directory else Path(tempfile.gettempdir())
    protected = _resolve_path_set(protected_paths)
    deleted, freed, _ = _cleanup_temp_entries(root, protected)
    return deleted, freed


def cleanup_workspace(
    *,
    temp_directory: Path | None = None,
    protected_paths: Sequence[Path] = (),
    output_directories: Sequence[Path] = (),
    download_directories: Sequence[Path] = (),
    stale_part_seconds: float = 3600.0,
) -> CleanupReport:
    """清理临时目录、输出与下载目录中的过期半成品，保护运行中任务的产物。"""
    protected = _resolve_path_set(protected_paths)
    root = Path(temp_directory) if temp_directory else Path(tempfile.gettempdir())
    deleted, freed, skipped = _cleanup_temp_entries(root, protected)

    part_report = _cleanup_stale_parts_report(output_directories, protected, stale_part_seconds)
    deleted += part_report[0]
    freed += part_report[1]
    skipped += part_report[2]

    download_report = _cleanup_download_parts(download_directories, protected, DOWNLOAD_PART_SECONDS)
    deleted += download_report[0]
    freed += download_report[1]
    skipped += download_report[2]

    return CleanupReport(deleted=deleted, freed_bytes=freed, skipped=skipped)


def cleanup_startup_orphans(
    *,
    protected_paths: Sequence[Path] = (),
    output_directories: Sequence[Path] = (),
    download_directories: Sequence[Path] = (),
    active_seconds: float = 600.0,
) -> CleanupReport:
    """启动时的孤儿清理：临时目录、过期半成品与下载残片。

    不触碰缩略图缓存（用户可见的预览资源）；最近 ``active_seconds`` 内
    修改过的临时项视为活动内容并跳过，避免误删并存实例的文件。
    """
    protected = _resolve_path_set(protected_paths)
    root = temp_directory()
    deleted, freed, skipped = _cleanup_temp_entries(root, protected, min_age_seconds=active_seconds)

    part_report = _cleanup_stale_parts_report(output_directories, protected, 3600.0)
    deleted += part_report[0]
    freed += part_report[1]
    skipped += part_report[2]

    download_report = _cleanup_download_parts(download_directories, protected, DOWNLOAD_PART_SECONDS)
    deleted += download_report[0]
    freed += download_report[1]
    skipped += download_report[2]

    return CleanupReport(deleted=deleted, freed_bytes=freed, skipped=skipped)


def _cleanup_stale_parts_report(
    output_directories: Sequence[Path],
    protected: set[str],
    stale_seconds: float,
) -> tuple[int, int, int]:
    """删除输出目录中过期（默认 1 小时）的 ``.part.mp4`` 半成品。"""
    deleted = 0
    freed = 0
    skipped = 0
    now = time.time()
    seen: set[str] = set()
    for directory in output_directories:
        output_directory = Path(directory)
        try:
            key = os.path.normcase(str(output_directory.resolve()))
        except OSError:
            continue
        if key in seen or not output_directory.is_dir():
            continue
        seen.add(key)

        try:
            entries = list(output_directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.name.endswith(PART_SUFFIX):
                continue
            if _is_protected(entry, protected):
                skipped += 1
                continue
            try:
                if not entry.is_file():
                    continue
                if entry.stat().st_mtime >= now - stale_seconds:
                    continue
                freed += entry.stat().st_size
                entry.unlink(missing_ok=True)
                deleted += 1
            except OSError:
                continue
    return deleted, freed, skipped


def _cleanup_download_parts(
    download_directories: Sequence[Path],
    protected: set[str],
    stale_seconds: float,
) -> tuple[int, int, int]:
    """删除下载目录中过期的 ``.part`` 残片（取消/失败遗留）。"""
    deleted = 0
    freed = 0
    skipped = 0
    now = time.time()
    for directory in download_directories:
        download_directory = Path(directory)
        if not download_directory.is_dir():
            continue
        try:
            entries = list(download_directory.rglob("*.part"))
        except OSError:
            continue
        for entry in entries:
            if _is_protected(entry, protected):
                skipped += 1
                continue
            try:
                if not entry.is_file():
                    continue
                if entry.stat().st_mtime >= now - stale_seconds:
                    continue
                freed += entry.stat().st_size
                entry.unlink(missing_ok=True)
                deleted += 1
            except OSError:
                continue
    return deleted, freed, skipped


def overlay_thumbnails_directory() -> Path:
    """蒙版/贴纸缩略图缓存目录（数据目录下，不随临时目录清理）。"""
    return data_directory() / THUMBNAIL_DIRECTORY_NAME


def logs_directory() -> Path:
    return data_directory() / LOG_DIRECTORY_NAME


def crash_log_path(moment: datetime | None = None) -> Path:
    stamp = (moment or datetime.now()).strftime("%Y%m%d")
    return logs_directory() / f"crash-{stamp}.log"


def install_crash_logging() -> Path:
    """安装全局异常钩子：把未捕获异常写入 ``logs/crash-YYYYMMDD.log``。"""

    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log_exception(exc_value if exc_value is not None else exc_type("未知异常"), traceback_text="".join(traceback.format_exception(exc_type, exc_value, exc_tb)))

    def _thread_excepthook(args) -> None:  # noqa: ANN001 - threading.ExceptHookArgs
        if issubclass(args.exc_type, SystemExit):
            return
        log_exception(
            args.exc_value if args.exc_value is not None else args.exc_type("线程异常"),
            traceback_text="".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
            context=f"线程 {getattr(args.thread, 'name', '?')}",
        )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    return logs_directory()


def log_exception(exc: BaseException, *, traceback_text: str = "", context: str = "") -> Path | None:
    """追加一条崩溃记录；返回日志文件路径（写入失败返回 None）。"""
    try:
        target = crash_log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[{stamp}] {context} {type(exc).__name__}: {exc}"]
        detail = traceback_text or "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        lines.append(detail.rstrip())
        lines.append("")
        with _crash_log_lock:
            with target.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        return target
    except OSError:
        return None
