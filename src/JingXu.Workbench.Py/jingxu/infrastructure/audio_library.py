"""音频库：BGM 素材登记、元数据缓存与最近使用。

文档格式（对齐 .NET ``AudioLibraryService``）：
``{"schemaVersion": 1, "entries": [{"id", "filePath", "duration", "displayName", "lastUsedAt", ...}]}``
兼容旧版 ``{"tracks": [...]}`` 文档。
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from jingxu.domain.render import BgmSettings
from jingxu.infrastructure.paths import data_directory

LIBRARY_FILE_NAME = "audio-library.json"
CURRENT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AudioTrack:
    path: Path
    duration: float
    sample_rate: int
    channels: int
    codec: str
    id: str = ""
    display_name: str = ""
    last_used_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", uuid.uuid4().hex)
        if not self.display_name:
            object.__setattr__(self, "display_name", self.path.name)

    @property
    def duration_text(self) -> str:
        total = max(0, int(round(self.duration)))
        minutes, seconds = divmod(total, 60)
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def last_used_text(self) -> str:
        if self.last_used_at <= 0:
            return "未使用"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.last_used_at))


class AudioProbeError(RuntimeError):
    """音频探测失败。"""


def probe_audio(path: Path, ffprobe_path: Path, *, timeout: float = 30.0) -> AudioTrack:
    """探测音频流基础信息；时长必须大于零（对齐 .NET 的导入校验）。"""
    path = Path(path)
    if not path.is_file():
        raise AudioProbeError(f"音频文件不存在：{path}")

    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AudioProbeError(f"音频探测失败：{error}") from error

    if completed.returncode != 0:
        raise AudioProbeError(f"音频探测失败：{path.name}")

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise AudioProbeError(f"音频探测输出无法解析：{path.name}") from error

    return parse_audio_payload(payload, path)


def parse_audio_payload(payload: dict, path: Path) -> AudioTrack:
    streams = payload.get("streams") or []
    stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if stream is None:
        raise AudioProbeError(f"文件不含音频流：{path.name}")

    duration = 0.0
    for source in (payload.get("format") or {}, stream):
        try:
            duration = float(source.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            break

    if duration <= 0:
        raise AudioProbeError(f"音频时长无效（必须大于零）：{path.name}")

    return AudioTrack(
        path=path,
        duration=duration,
        sample_rate=int(stream.get("sample_rate") or 0),
        channels=int(stream.get("channels") or 0),
        codec=str(stream.get("codec_name") or ""),
    )


class AudioLibrary:
    """音频库：登记、移除、最近使用与原子持久化（存于数据目录的 JSON）。"""

    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = Path(store_path) if store_path else data_directory() / LIBRARY_FILE_NAME
        self._tracks: list[AudioTrack] = []
        self._lock = threading.RLock()
        self._load()

    @property
    def store_path(self) -> Path:
        return self._store_path

    @property
    def tracks(self) -> list[AudioTrack]:
        with self._lock:
            return list(self._tracks)

    @property
    def recent_tracks(self) -> list[AudioTrack]:
        """按最近使用倒序（对齐 .NET 列表排序）。"""
        return sorted(self.tracks, key=lambda track: track.last_used_at, reverse=True)

    def add(self, tracks: list[AudioTrack]) -> int:
        """登记曲目；重复路径刷新元数据与最近使用时间并保留原 ID。"""
        with self._lock:
            known = {_path_key(track.path): index for index, track in enumerate(self._tracks)}
            added = 0
            for track in tracks:
                key = _path_key(track.path)
                index = known.get(key)
                if index is None:
                    self._tracks.append(replace(track, last_used_at=track.last_used_at or time.time()))
                    known[key] = len(self._tracks) - 1
                    added += 1
                    continue
                existing = self._tracks[index]
                self._tracks[index] = replace(
                    track,
                    id=existing.id,
                    last_used_at=time.time(),
                )
            if added or tracks:
                self.save()
            return added

    def remove(self, path: Path) -> bool:
        with self._lock:
            before = len(self._tracks)
            key = _path_key(Path(path))
            self._tracks = [track for track in self._tracks if _path_key(track.path) != key]
            if len(self._tracks) != before:
                self.save()
                return True
            return False

    def clear(self) -> int:
        """清空音频库（不删除磁盘文件），返回移除条数。"""
        with self._lock:
            removed = len(self._tracks)
            if removed:
                self._tracks = []
                self.save()
            return removed

    def find(self, path: Path | None) -> AudioTrack | None:
        if path is None:
            return None
        key = _path_key(Path(path))
        return next((track for track in self._tracks if _path_key(track.path) == key), None)

    def touch(self, path: Path) -> bool:
        """记录一次使用，用于「最近使用」排序。"""
        with self._lock:
            key = _path_key(Path(path))
            for index, track in enumerate(self._tracks):
                if _path_key(track.path) == key:
                    self._tracks[index] = replace(track, last_used_at=time.time())
                    self.save()
                    return True
            return False

    def prune_missing(self) -> int:
        """移除磁盘上已不存在的条目（对齐 .NET PruneMissingAsync）。"""
        with self._lock:
            before = len(self._tracks)
            self._tracks = [track for track in self._tracks if track.path.is_file()]
            removed = before - len(self._tracks)
            if removed:
                self.save()
            return removed

    def save(self) -> None:
        with self._lock:
            payload = {
                "schemaVersion": CURRENT_SCHEMA_VERSION,
                "entries": [
                    {
                        "id": track.id,
                        "filePath": str(track.path),
                        "duration": track.duration,
                        "displayName": track.display_name,
                        "lastUsedAt": track.last_used_at,
                        "sampleRate": track.sample_rate,
                        "channels": track.channels,
                        "codec": track.codec,
                    }
                    for track in self._tracks
                ],
            }
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._store_path.with_suffix(self._store_path.suffix + ".tmp")
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(self._store_path)

    def _load(self) -> None:
        if not self._store_path.is_file():
            return
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return

        entries = payload.get("entries")
        if entries is None:
            # 兼容旧版 {"tracks": [...]} 文档。
            entries = [
                {
                    "filePath": item.get("path"),
                    "duration": item.get("duration"),
                    "sampleRate": item.get("sample_rate"),
                    "channels": item.get("channels"),
                    "codec": item.get("codec"),
                }
                for item in (payload.get("tracks") or [])
            ]

        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            raw_path = entry.get("filePath") or entry.get("path")
            if not raw_path:
                continue
            path = Path(str(raw_path))
            if not path.is_file():
                continue
            try:
                self._tracks.append(
                    AudioTrack(
                        path=path,
                        duration=float(entry.get("duration") or 0.0),
                        sample_rate=int(entry.get("sampleRate") or entry.get("sample_rate") or 0),
                        channels=int(entry.get("channels") or 0),
                        codec=str(entry.get("codec") or ""),
                        id=str(entry.get("id") or ""),
                        display_name=str(entry.get("displayName") or ""),
                        last_used_at=float(entry.get("lastUsedAt") or 0.0),
                    )
                )
            except (TypeError, ValueError):
                continue


def _path_key(path: Path) -> str:
    """路径去重键：解析为绝对路径并忽略大小写（对齐 .NET OrdinalIgnoreCase）。"""
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()


def build_bgm(track: AudioTrack, *, volume_percent: int, fade_out_seconds: float, loop: bool) -> BgmSettings:
    return BgmSettings(
        path=track.path,
        volume_percent=max(0, min(volume_percent, 200)),
        fade_out_seconds=max(0.0, fade_out_seconds),
        loop=loop,
    )
