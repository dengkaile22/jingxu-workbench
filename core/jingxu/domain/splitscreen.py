"""分屏模型：双屏 / 四屏（可从中途片段生效，带中缝羽化）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SplitMode(str, Enum):
    DOUBLE_H = "double_h"
    DOUBLE_V = "double_v"
    FOUR = "four"

    @property
    def display_text(self) -> str:
        return {"double_h": "双屏（左右）", "double_v": "双屏（上下）", "four": "四屏（2×2）"}[self.value]

    @property
    def cell_count(self) -> int:
        return 2 if self is not SplitMode.FOUR else 4


@dataclass(frozen=True, slots=True)
class SplitScreenSpec:
    """分屏参数。

    - ``same_source``：所有格子使用同一素材（同源多格）；
    - 否则按顺序循环使用 ``aux_paths`` 作为辅助画面（每格一个素材）；
    - ``start_index``：从第几个片段起生效（0 基，之前的片段保持普通画面）。
    """

    mode: SplitMode = SplitMode.FOUR
    same_source: bool = False
    aux_paths: tuple[Path, ...] = ()
    start_index: int = 0
    feather: bool = True
    feather_px: int = 24
    # 草稿保留随机意图；入队时按实际片段顺序物化，并冻结抽取结果。
    random_from_source_folder: bool = False
    aux_indices_by_clip: tuple[tuple[int, ...], ...] = ()

    @property
    def cell_count(self) -> int:
        return self.mode.cell_count

    def uses_aux(self) -> bool:
        return not self.same_source and len(self.aux_paths) > 0

    def aux_index_for(self, clip_index: int, cell_index: int) -> int:
        """查找指定片段的辅助格；旧的固定分屏继续按格循环使用素材。"""
        if self.aux_indices_by_clip:
            return self.aux_indices_by_clip[clip_index][cell_index - 1]
        return (cell_index - 1) % len(self.aux_paths)
