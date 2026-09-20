"""贴纸素材库：登记、持久化与「随机贴纸库」选择。

对齐 .NET ``StickerEditorViewModel`` 的素材库语义：

* 素材库（``LibraryEntries``）是**导入贴纸的落点**，与「贴纸轨道」分离；
  轨道由用户在素材库里点「添加」生成，而不是每条轨道各自选一次文件。
  Python 版此前没有这一层，导致贴纸页只能在「导入素材」时直接建轨道，
  用起来像蒙版页的简化版。
* 「随机贴纸库」（``UseRandomStickerLibrary``）：渲染时把轨道素材替换为素材库中
  随机一款。随机不是任意取，而是用 ``select_index_with_reshuffled_cycles``
  做**确定性洗牌**——同一成片序号必得同一结果，批次内不重复，跨批次重新洗牌。
  这样批量出片既有变化又可复现，与该项目的随机种子约定一致。

素材库与轨道的关系：库只负责「有哪些贴纸」，画法（位置/尺寸/透明度/旋转）
仍由轨道决定；开启随机替换时只换素材，不动画法。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from jingxu.domain.deterministic import select_index_with_reshuffled_cycles
from jingxu.infrastructure.paths import data_directory

LIBRARY_FILE_NAME = "sticker-library.json"
CURRENT_SCHEMA_VERSION = 1

# 可导入的贴纸格式（与 .NET 文件过滤器一致）
STICKER_SUFFIXES = (".png", ".webp", ".gif", ".jpg", ".jpeg", ".bmp", ".mp4", ".mov", ".webm", ".mkv")
# 静态图片允许透明通道，视频贴纸会循环播放
IMAGE_SUFFIXES = (".png", ".webp", ".gif", ".jpg", ".jpeg", ".bmp")

# 随机替换时的分支号：与其它随机维度（转场/素材顺序）隔离，避免同源相关
RANDOM_STICKER_BRANCH = 1


@dataclass(frozen=True, slots=True)
class StickerEntry:
    """素材库中的一条贴纸。"""

    path: Path
    display_name: str = ""
    added_at: float = 0.0
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", uuid.uuid4().hex[:12])
        if not self.display_name:
            object.__setattr__(self, "display_name", self.path.stem or self.path.name)

    @property
    def is_video(self) -> bool:
        return self.path.suffix.lower() not in IMAGE_SUFFIXES

    @property
    def kind_text(self) -> str:
        return "视频" if self.is_video else "图片"

    def exists(self) -> bool:
        return self.path.is_file()


def _path_key(path: Path) -> str:
    """路径比较键：Windows 下不区分大小写。"""
    try:
        return str(Path(path).resolve()).casefold()
    except OSError:
        return str(path).casefold()


def filter_sticker_paths(candidates: list[Path]) -> list[Path]:
    """筛出可作为贴纸的文件（去重、保序）。"""
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates or []:
        path = Path(candidate)
        if path.suffix.lower() not in STICKER_SUFFIXES:
            continue
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


@dataclass(slots=True)
class StickerLibrary:
    """贴纸素材库：登记、移除、清空与原子持久化。"""

    store_path: Path | None = None
    _entries: list[StickerEntry] = field(default_factory=list, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.store_path = (
            Path(self.store_path) if self.store_path else data_directory() / LIBRARY_FILE_NAME
        )
        self._load()

    @property
    def entries(self) -> list[StickerEntry]:
        with self._lock:
            return list(self._entries)

    @property
    def sources(self) -> list[Path]:
        """随机替换用的素材路径（去重，保序）。"""
        seen: set[str] = set()
        result: list[Path] = []
        for entry in self.entries:
            key = _path_key(entry.path)
            if key in seen:
                continue
            seen.add(key)
            result.append(entry.path)
        return result

    def add(self, paths: list[Path]) -> int:
        """登记贴纸；重复路径只刷新时间、保留原 ID，返回新增条数。"""
        cleaned = filter_sticker_paths(list(paths or []))
        if not cleaned:
            return 0
        with self._lock:
            known = {_path_key(entry.path): index for index, entry in enumerate(self._entries)}
            added = 0
            for path in cleaned:
                key = _path_key(path)
                index = known.get(key)
                if index is None:
                    self._entries.insert(
                        0,
                        StickerEntry(path=path, added_at=time.time()),
                    )
                    known[key] = 0
                    # 插入到最前会让既有索引整体后移，重建映射避免错位
                    known = {
                        _path_key(entry.path): position
                        for position, entry in enumerate(self._entries)
                    }
                    added += 1
                    continue
                existing = self._entries[index]
                self._entries[index] = replace(existing, added_at=time.time())
            self.save()
            return added

    def remove(self, entry_id: str) -> bool:
        with self._lock:
            before = len(self._entries)
            self._entries = [entry for entry in self._entries if entry.id != entry_id]
            if len(self._entries) != before:
                self.save()
                return True
            return False

    def clear(self) -> int:
        """清空素材库（不删除磁盘文件），返回移除条数。"""
        with self._lock:
            removed = len(self._entries)
            self._entries = []
            if removed:
                self.save()
            return removed

    def find(self, entry_id: str) -> StickerEntry | None:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def prune_missing(self) -> int:
        """移除磁盘上已不存在的条目，返回移除条数。"""
        with self._lock:
            before = len(self._entries)
            self._entries = [entry for entry in self._entries if entry.exists()]
            removed = before - len(self._entries)
            if removed:
                self.save()
            return removed

    def save(self) -> None:
        with self._lock:
            payload = {
                "schemaVersion": CURRENT_SCHEMA_VERSION,
                "entries": [
                    {
                        "id": entry.id,
                        "filePath": str(entry.path),
                        "displayName": entry.display_name,
                        "addedAt": entry.added_at,
                    }
                    for entry in self._entries
                ],
            }
            assert self.store_path is not None
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temp_path.replace(self.store_path)

    def _load(self) -> None:
        assert self.store_path is not None
        if not self.store_path.is_file():
            return
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return
        entries = payload.get("entries") if isinstance(payload, dict) else None
        for item in entries or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("filePath") or item.get("path")
            if not raw:
                continue
            self._entries.append(
                StickerEntry(
                    path=Path(str(raw)),
                    display_name=str(item.get("displayName") or ""),
                    added_at=float(item.get("addedAt") or 0.0),
                    id=str(item.get("id") or ""),
                )
            )


def select_random_sticker(
    sources: list[Path],
    *,
    seed: int,
    plan_ordinal: int,
    track_index: int,
    track_count: int,
) -> Path | None:
    """为某个成片里的某条轨道选出替换用的贴纸。

    选择序号 = ``成片序号 × 轨道数 + 轨道位置``，因此：

    * 同一成片序号 + 同一轨道必得同一结果（可复现）；
    * 一个成片内的多条轨道取到不同素材（同轮次内不重复）；
    * 下一个成片序号进入下一轮洗牌，顺序重排。

    素材库为空时返回 ``None``，由调用方给出可读错误。
    """
    if not sources:
        return None
    if plan_ordinal < 0:
        raise ValueError("成片序号不能为负。")
    count = max(1, track_count)
    ordinal = plan_ordinal * count + track_index
    index = select_index_with_reshuffled_cycles(
        len(sources), seed, ordinal, branch_index=RANDOM_STICKER_BRANCH
    )
    return sources[index % len(sources)]
