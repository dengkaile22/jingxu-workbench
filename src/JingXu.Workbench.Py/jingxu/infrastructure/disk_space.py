"""磁盘空间预算：渲染前的输出卷容量检查与预留登记。

对齐 .NET ``RenderDiskSpaceReservations`` 的语义：按卷登记跨进程预留，
预留量含 25% 余量；空间不足时给出明确的中文错误，触发上层回收缓存后重试。
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from jingxu.infrastructure.paths import data_directory

RESERVATION_DIR = "disk-reservations"
BUDGET_MARGIN = 1.25
STALE_SECONDS = 24 * 3600


class DiskSpaceError(RuntimeError):
    """磁盘空间不足。"""


@dataclass(frozen=True, slots=True)
class Reservation:
    """一条按卷登记的预留记录。"""

    token: str
    path: Path


def volume_key(path: Path) -> str:
    """返回路径所在卷的稳定标识（Windows 盘符或根路径）。"""
    resolved = Path(path).expanduser()
    try:
        anchor = resolved.resolve().anchor
    except OSError:
        anchor = resolved.anchor
    return anchor or str(resolved.drive) or "/"


def estimate_output_bytes(duration_seconds: float, *, bytes_per_second: float = 1_500_000.0) -> int:
    """按成片时长估算输出体积（默认约 12 Mbps 上限，含余量）。"""
    return max(64 * 1024 * 1024, int(max(duration_seconds, 0.0) * bytes_per_second))


def ensure_space(destination: Path, required_bytes: int) -> None:
    """检查目标卷剩余空间（含预留与 25% 余量），不足时抛出 :class:`DiskSpaceError`。"""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    required = int(required_bytes * BUDGET_MARGIN) + _reserved_bytes(destination)
    free = _free_bytes(destination)
    if free < required:
        raise DiskSpaceError(
            f"目标磁盘空间不足：需要约 {_human(required)}，剩余 {_human(free)}。"
            "请清理磁盘或更换输出目录后重试。"
        )


def reserve(destination: Path, required_bytes: int) -> Reservation:
    """登记一条预留（跨进程可见），失败时返回未登记的令牌。"""
    token = uuid.uuid4().hex
    registry = _registry_directory()
    record = {
        "token": token,
        "volume": volume_key(destination),
        "bytes": int(required_bytes),
        "pid": os.getpid(),
        "created": time.time(),
    }
    try:
        registry.mkdir(parents=True, exist_ok=True)
        (registry / f"{token}.json").write_text(json.dumps(record), encoding="utf-8")
    except OSError:
        pass
    return Reservation(token=token, path=registry / f"{token}.json")


def release(reservation: Reservation) -> None:
    """释放预留记录（幂等）。"""
    try:
        reservation.path.unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_stale_reservations() -> int:
    """清理超过 24 小时或属主进程已退出的预留记录。"""
    registry = _registry_directory()
    if not registry.is_dir():
        return 0

    removed = 0
    now = time.time()
    for record_path in registry.glob("*.json"):
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _remove(record_path)
            removed += 1
            continue

        created = float(payload.get("created") or 0.0)
        pid = int(payload.get("pid") or 0)
        if now - created > STALE_SECONDS or not _process_alive(pid):
            _remove(record_path)
            removed += 1
    return removed


# ────────────────────────────── 内部 ──────────────────────────────


def _registry_directory() -> Path:
    return data_directory() / RESERVATION_DIR


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _iter_records() -> list[dict]:
    registry = _registry_directory()
    if not registry.is_dir():
        return []
    records: list[dict] = []
    for record_path in registry.glob("*.json"):
        try:
            records.append(json.loads(record_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def _reserved_bytes(destination: Path) -> int:
    key = volume_key(destination)
    own = os.getpid()
    total = 0
    for record in _iter_records():
        if record.get("volume") != key:
            continue
        if int(record.get("pid") or 0) == own:
            continue
        total += int(record.get("bytes") or 0)
    return total


def _free_bytes(destination: Path) -> int:
    try:
        return shutil.disk_usage(_existing_parent(Path(destination))).free
    except OSError:
        return 1 << 62


def _existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _human(value: int) -> str:
    size = float(max(value, 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
