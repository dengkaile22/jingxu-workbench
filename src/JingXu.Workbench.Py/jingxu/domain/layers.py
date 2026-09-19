"""图层模型：蒙版覆盖与贴纸（共用一套叠加参数）。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from uuid import uuid4


class LayerKind(str, Enum):
    OVERLAY = "overlay"
    STICKER = "sticker"


@dataclass(frozen=True, slots=True)
class LayerSpec:
    """一条叠加图层：素材 + 时间窗口 + 位置 / 尺寸 / 透明度 / 边缘处理。"""

    kind: LayerKind
    source: Path
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    x_percent: float = 50.0
    y_percent: float = 50.0
    width_percent: float = 30.0
    height_percent: float = 0.0
    opacity: float = 1.0
    remove_black: bool = False
    rotation_degrees: float = 0.0
    feather: float = 0.0
    top_fade: float = 0.0
    source_crop_canvas: bool = False
    source_crop_y: float = 0.0
    source_crop_bounds: tuple[float, float, float, float] | None = None
    fit: str = "fill_crop"
    scale_percent: float = 100.0
    start_clip_index: int = 1
    audio_mode: str = "discard"
    z_index: int = 0
    enabled: bool = True
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", uuid4().hex[:10])

    @property
    def display_name(self) -> str:
        return self.source.name

    @property
    def is_image(self) -> bool:
        return self.source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

    @property
    def window_text(self) -> str:
        end = f"{self.end_seconds:.1f}s" if self.end_seconds > 0 else "片尾"
        return f"{self.start_seconds:.1f}s → {end}"

    def with_changes(self, **changes: object) -> "LayerSpec":
        return replace(self, **changes)
