"""Bounded Chromium cache maintenance that preserves all login storage."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

# Deliberately exclude Cookies, Network, Local/Session Storage, IndexedDB,
# Service Worker, Preferences and Local State: sites can store login state there.
CACHE_DIRECTORIES = frozenset(
    {
        "Cache",
        "Code Cache",
        "GPUCache",
        "Media Cache",
        "ShaderCache",
        "GrShaderCache",
        "DawnCache",
        "DawnGraphiteCache",
        "DawnWebGPUCache",
    }
)
AUTH_NAMES = frozenset(
    {
        "network",
        "local storage",
        "session storage",
        "indexeddb",
        "service worker",
        "preferences",
        "local state",
        "login data",
    }
)


@dataclass(frozen=True)
class CacheCleanupResult:
    files_removed: int = 0
    bytes_removed: int = 0
    skipped: bool = False
    reason: str = ""


class ProfileSessionLock:
    """OS lock shared by login, SDK and CLI; a crashed process releases it."""

    def __init__(self, directory: str | os.PathLike):
        self.directory = Path(directory).resolve()
        self._file = None

    def acquire(self) -> bool:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / ".jingxu-browser-session.lock"
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            return False
        handle = path.open("a+b")
        try:
            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            return False
        self._file = handle
        return True

    def close(self):
        handle, self._file = self._file, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _linked(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return path.is_symlink() or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    except OSError:
        return True


def cleanup_profile_cache(
    directory, *, session_lock=None, probe=None
) -> CacheCleanupResult:
    """Clean only a closed, exclusively owned profile's HTTP/code/GPU caches.

    Each deletion is checked against its resolved absolute cache root. Symlinks,
    junctions, protected names and unknown profile holders are skipped.
    """
    from core.profile_lock import profile_holder_state

    raw_root = Path(directory)
    if not raw_root.is_dir() or _linked(raw_root):
        return CacheCleanupResult(skipped=True, reason="档案不存在或为链接目录")
    root = raw_root.resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        return CacheCleanupResult(
            skipped=True, reason="拒绝把磁盘根目录或用户主目录当作浏览器档案清理"
        )
    protected = set()
    configured_cookies = os.environ.get("JINGXU_SPIDER_COOKIES", "").strip()
    if configured_cookies:
        protected.add(Path(configured_cookies).expanduser().resolve())
    own_lock = session_lock is None
    lock = session_lock or ProfileSessionLock(root)
    if own_lock and not lock.acquire():
        return CacheCleanupResult(skipped=True, reason="另一登录或抓取会话正在使用档案")
    try:
        holders = (probe or profile_holder_state)(root)
        if holders is None or holders:
            return CacheCleanupResult(
                skipped=True, reason="浏览器仍在使用档案或无法确认占用情况"
            )
        roots = [root]
        for child in root.iterdir():
            if (
                child.is_dir()
                and not _linked(child)
                and (
                    child.name == "Default" or re.fullmatch(r"Profile \d+", child.name)
                )
            ):
                roots.append(child)
        files = bytes_removed = 0
        for profile in roots:
            for name in sorted(CACHE_DIRECTORIES):
                target = profile / name
                if not target.is_dir() or _linked(target):
                    continue
                cache_root = target.resolve()
                if not cache_root.is_relative_to(root):
                    continue
                stack = [(target, False)]
                while stack:
                    path, visited = stack.pop()
                    if _linked(path) or not path.resolve().is_relative_to(cache_root):
                        continue
                    lowered = path.name.casefold()
                    if (
                        "cookie" in lowered
                        or lowered in AUTH_NAMES
                        or path.resolve() in protected
                    ):
                        continue
                    try:
                        if path.is_dir():
                            if visited:
                                path.rmdir()
                            else:
                                stack.append((path, True))
                                stack.extend((child, False) for child in path.iterdir())
                        elif path.is_file():
                            size = path.stat().st_size
                            path.unlink()
                            files += 1
                            bytes_removed += size
                    except OSError:
                        # Locked/read-only cache entries do not block crawling.
                        continue
        return CacheCleanupResult(files_removed=files, bytes_removed=bytes_removed)
    finally:
        if own_lock:
            lock.close()
