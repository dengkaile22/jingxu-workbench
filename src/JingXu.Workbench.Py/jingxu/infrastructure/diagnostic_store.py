"""失败任务诊断归档：``.jingxu-logs/<任务ID>/`` 与保留策略。

失败任务保留完整日志（渲染输出、滤镜文本、concat 列表），
并按「7 天 + 64 MiB」策略回收旧任务，当前任务始终保留。
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

LOG_FOLDER = ".jingxu-logs"
RETENTION_BYTES = 64 * 1024 * 1024
RETENTION_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True, slots=True)
class DiagnosticArchive:
    """一条已归档的失败任务日志。"""

    job_id: str
    directory: Path


def archive_failure(
    output_directory: Path,
    job_id: str,
    *,
    log_text: str,
    filter_text: str | None = None,
    concat_text: str | None = None,
    stderr_text: str | None = None,
) -> DiagnosticArchive:
    """把失败任务日志写入输出目录下的 ``.jingxu-logs/<任务ID>/``。"""
    directory = Path(output_directory) / LOG_FOLDER / job_id
    directory.mkdir(parents=True, exist_ok=True)

    (directory / "render.log").write_text(log_text or "", encoding="utf-8")
    if filter_text is not None:
        (directory / "filter.filter").write_text(filter_text, encoding="utf-8")
    if concat_text is not None:
        (directory / "concat.txt").write_text(concat_text, encoding="utf-8")
    if stderr_text:
        (directory / "ffmpeg-stderr.log").write_text(stderr_text, encoding="utf-8")

    return DiagnosticArchive(job_id=job_id, directory=directory)


def trim_old_diagnostics(output_directory: Path, *, current_job_id: str | None = None) -> int:
    """按 7 天与 64 MiB 策略回收旧任务日志；返回删除的任务数。

    当前任务（``current_job_id``）保留完整记录，不参与回收。
    """
    root = Path(output_directory) / LOG_FOLDER
    if not root.is_dir():
        return 0

    entries: list[tuple[Path, float, int]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if current_job_id is not None and child.name == current_job_id:
            continue
        size = _directory_size(child)
        try:
            modified = child.stat().st_mtime
        except OSError:
            modified = 0.0
        entries.append((child, modified, size))

    removed = 0
    now = time.time()

    # 先按时间回收（超龄）。
    fresh: list[tuple[Path, float, int]] = []
    for child, modified, size in entries:
        if now - modified > RETENTION_SECONDS:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        else:
            fresh.append((child, modified, size))

    # 再按总量回收（从最旧开始，至少保留最新一条）。
    total = sum(size for _, _, size in fresh)
    ordered = sorted(fresh, key=lambda item: item[1])
    for child, _, size in ordered[: max(0, len(ordered) - 1)]:
        if total <= RETENTION_BYTES:
            break
        shutil.rmtree(child, ignore_errors=True)
        total -= size
        removed += 1

    return removed


def _directory_size(directory: Path) -> int:
    total = 0
    try:
        for file in directory.rglob("*"):
            if file.is_file():
                total += file.stat().st_size
    except OSError:
        return total
    return total


def latest_diagnostics(output_directory: Path, *, limit: int = 20) -> list[Path]:
    """列出最近的失败任务日志目录（按修改时间倒序）。"""
    root = Path(output_directory) / LOG_FOLDER
    if not root.is_dir():
        return []
    children = [child for child in root.iterdir() if child.is_dir()]
    children.sort(key=lambda child: child.stat().st_mtime if child.exists() else 0.0, reverse=True)
    return children[:limit]
